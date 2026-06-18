"""
Stale pair callback scenarios — when the state changes between sending a pair
request and the target clicking accept/decline.

Real-conference risk: Telegram queues old messages. If Alice unregisters after
sending a request to Bob, or if the event closes in the interim, clicking
"accept" on a stale notification must not corrupt the pairing data.
"""
import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import callback_handler
import messages

TEST_DB_PATH = ":memory:"


class MockConnection:
    def __init__(self, real_conn):
        self.real_conn = real_conn

    def cursor(self):
        return self.real_conn.cursor()

    def commit(self):
        self.real_conn.commit()

    def close(self):
        pass


def _setup_schema(conn):
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER, status TEXT, total_places INTEGER,
        speakers_group_id TEXT, waitlist_timeout_hours INTEGER,
        end_time DATETIME, event_start_time DATETIME,
        registration_duration_hours INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, chat_id INTEGER,
        username TEXT, first_name TEXT, status TEXT,
        signup_time DATETIME, priority INTEGER, notified_at DATETIME,
        expires_at DATETIME, guest_of_user_id INTEGER,
        partner_reg_id INTEGER, invite_token TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS speakers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, username TEXT, first_name TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, username TEXT,
        first_name TEXT, action TEXT, details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()


class TestStalePairCallbacks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = MockConnection(self.real_conn)
        _setup_schema(self.real_conn)

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    def _add_event(self, status='OPEN'):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES (?, 10)", (status,))
        self.real_conn.commit()
        return cursor.lastrowid

    def _add_reg(self, event_id, user_id, username, status='REGISTERED', partner_reg_id=None):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, first_name, status, partner_reg_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, user_id, username, username, status, partner_reg_id)
        )
        self.real_conn.commit()
        return cursor.lastrowid

    def _make_pair_callback(self, action, requester_reg_id, target_reg_id, sender_user_id):
        update = MagicMock()
        update.effective_user.id = sender_user_id
        update.callback_query = MagicMock()
        update.callback_query.data = f"{action}_{requester_reg_id}_{target_reg_id}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        return update, context

    async def test_accept_after_requester_unregistered(self):
        """Bob accepts after Alice already unregistered — must show stale notice, no pairing created."""
        event_id = self._add_event(status='OPEN')
        a_reg = self._add_reg(event_id, 111, 'alice', status='UNREGISTERED')
        b_reg = self._add_reg(event_id, 222, 'bob', status='REGISTERED')

        update, context = self._make_pair_callback('pyes', a_reg, b_reg, sender_user_id=222)
        await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.PAIR_INVITE_STALE)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (b_reg,))
        self.assertIsNone(cursor.fetchone()['partner_reg_id'])

    async def test_accept_after_event_closed(self):
        """Bob accepts after the event moved to CLOSED — must show stale notice."""
        event_id = self._add_event(status='CLOSED')
        a_reg = self._add_reg(event_id, 111, 'alice', status='REGISTERED')
        b_reg = self._add_reg(event_id, 222, 'bob', status='REGISTERED')

        update, context = self._make_pair_callback('pyes', a_reg, b_reg, sender_user_id=222)
        await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.PAIR_INVITE_STALE)

    async def test_accept_from_wrong_user(self):
        """Carol (not Bob) clicks Bob's accept button — must show stale notice."""
        event_id = self._add_event(status='OPEN')
        a_reg = self._add_reg(event_id, 111, 'alice', status='REGISTERED')
        b_reg = self._add_reg(event_id, 222, 'bob', status='REGISTERED')

        # user_id=333 (Carol) sends the callback meant for Bob (user_id=222)
        update, context = self._make_pair_callback('pyes', a_reg, b_reg, sender_user_id=333)
        await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.PAIR_INVITE_STALE)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (b_reg,))
        self.assertIsNone(cursor.fetchone()['partner_reg_id'])

    async def test_accept_after_target_already_paired(self):
        """Bob accepts Alice's old request but he's already paired with Carol — must show stale."""
        event_id = self._add_event(status='OPEN')
        a_reg = self._add_reg(event_id, 111, 'alice', status='REGISTERED')
        c_reg = self._add_reg(event_id, 333, 'carol', status='REGISTERED')
        b_reg = self._add_reg(event_id, 222, 'bob', status='REGISTERED')

        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (c_reg, b_reg))
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_reg, c_reg))
        self.real_conn.commit()

        update, context = self._make_pair_callback('pyes', a_reg, b_reg, sender_user_id=222)
        await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.PAIR_INVITE_STALE)

        # Bob is still paired with Carol
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (b_reg,))
        self.assertEqual(cursor.fetchone()['partner_reg_id'], c_reg)

    async def test_decline_stale_is_safe(self):
        """Declining a stale request (requester unregistered) shows stale notice, no crash."""
        event_id = self._add_event(status='OPEN')
        a_reg = self._add_reg(event_id, 111, 'alice', status='UNREGISTERED')
        b_reg = self._add_reg(event_id, 222, 'bob', status='REGISTERED')

        update, context = self._make_pair_callback('pno', a_reg, b_reg, sender_user_id=222)
        await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.PAIR_INVITE_STALE)


if __name__ == '__main__':
    unittest.main()
