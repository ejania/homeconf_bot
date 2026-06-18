"""
Registration failure modes:
- DM failure during OPEN registration rolls back the DB entry (no phantom seats consumed)
- DM failure during waitlist (REVIEW/CLOSED) rolls back the entry
- PRE_OPEN registration attempt is rejected cleanly
- WAITLIST unregister from CLOSED needs no confirmation and never triggers invite_next
- ACCEPTED user in REVIEW state requires the same confirmation dialog as CLOSED

Real-conference risk:
  A silent rollback failure leaves a ghost REGISTERED entry in the pool, consuming
  a lottery seat for someone who can never receive the invitation.  The PRE_OPEN
  and REVIEW-confirm cases protect against user confusion during the conference day.
"""
import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import register, unregister
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


class TestRegistrationFailureModes(unittest.IsolatedAsyncioTestCase):
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

    def _make_update(self, user_id=123, username='test_user'):
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = user_id
        update.effective_user.username = username
        update.effective_user.first_name = username
        update.effective_chat.id = user_id
        update.message.reply_text = AsyncMock()
        return update

    async def test_register_during_pre_open_is_rejected(self):
        """Attempting to register during PRE_OPEN returns NO_OPEN_REGISTRATION with no DB entry."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('PRE_OPEN', 10)")
        self.real_conn.commit()

        update = self._make_update()
        context = MagicMock()

        await register(update, context)

        update.message.reply_text.assert_called_with(messages.NO_OPEN_REGISTRATION)
        cursor.execute("SELECT COUNT(*) as cnt FROM registrations")
        self.assertEqual(cursor.fetchone()['cnt'], 0)

    async def test_register_dm_fail_during_open_rolls_back(self):
        """If the bot can't DM the user during OPEN registration, the DB entry is removed."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        self.real_conn.commit()

        update = self._make_update(user_id=999, username='dm_fail_user')
        context = MagicMock()
        context.bot.send_message = AsyncMock(
            side_effect=Exception("Forbidden: bot can't start conversations with this user")
        )

        await register(update, context)

        cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE user_id = 999")
        self.assertEqual(cursor.fetchone()['cnt'], 0, "Ghost registration must be deleted on DM failure")
        update.message.reply_text.assert_called_with(messages.START_IN_PRIVATE)

    async def test_register_dm_fail_during_waitlist_rolls_back(self):
        """If the bot can't DM the user when joining the waitlist, the DB entry is removed."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 2)")
        self.real_conn.commit()

        update = self._make_update(user_id=888, username='dm_fail_waitlist')
        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=Exception("Forbidden"))

        await register(update, context)

        cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE user_id = 888")
        self.assertEqual(cursor.fetchone()['cnt'], 0, "Ghost waitlist entry must be deleted on DM failure")
        update.message.reply_text.assert_called_with(messages.START_IN_PRIVATE)

    async def test_register_after_unregistered_creates_fresh_entry(self):
        """A user who previously unregistered can re-register during OPEN."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        event_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, 123, 'test_user', 'UNREGISTERED')",
            (event_id,)
        )
        self.real_conn.commit()

        update = self._make_update()
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await register(update, context)

        cursor.execute(
            "SELECT COUNT(*) as cnt FROM registrations WHERE user_id = 123 AND status = 'REGISTERED'"
        )
        self.assertEqual(cursor.fetchone()['cnt'], 1)


class TestUnregisterEdgeCases(unittest.IsolatedAsyncioTestCase):
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

    async def test_unregister_waitlist_requires_no_confirmation(self):
        """A WAITLIST user can unregister immediately — no confirmation dialog, no invite triggered."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 5)")
        event_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, 111, 'WAITLIST', 0)",
            (event_id,)
        )
        reg_id = cursor.lastrowid
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.effective_user.username = "waitlister"
        update.effective_user.first_name = "waitlister"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.get_chat_member = AsyncMock(side_effect=Exception("no group"))

        await unregister(update, context)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'UNREGISTERED')
        update.message.reply_text.assert_called_with(messages.UNREGISTERED_SUCCESS)
        # No InlineKeyboardMarkup call (which would be the confirm dialog)
        for call in update.message.reply_text.call_args_list:
            self.assertNotEqual(call[0][0], messages.UNREGISTER_CONFIRM)

    async def test_unregister_accepted_in_review_requires_confirmation(self):
        """An ACCEPTED user in REVIEW state must see the confirmation dialog, same as CLOSED."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('REVIEW', 5)")
        event_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status) VALUES (?, 222, 'ACCEPTED')",
            (event_id,)
        )
        reg_id = cursor.lastrowid
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 222
        update.effective_user.username = "lottery_winner"
        update.effective_user.first_name = "lottery_winner"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.get_chat_member = AsyncMock(side_effect=Exception("no group"))

        await unregister(update, context)

        # Status unchanged — user hasn't confirmed yet
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')
        update.message.reply_text.assert_called_with(
            messages.UNREGISTER_CONFIRM,
            reply_markup=unittest.mock.ANY
        )

    async def test_unregister_with_no_active_registration(self):
        """A user with no active registration gets NO_ACTIVE_REGISTRATION, no crash."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 777
        update.effective_user.username = "ghost"
        update.effective_user.first_name = "ghost"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.get_chat_member = AsyncMock(side_effect=Exception("no group"))

        await unregister(update, context)

        update.message.reply_text.assert_called_with(messages.NO_ACTIVE_REGISTRATION)


if __name__ == '__main__':
    unittest.main()
