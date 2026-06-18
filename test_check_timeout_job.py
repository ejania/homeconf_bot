"""
check_timeout_job: INVITED waitlist registrations that time out.

Real-conference risk: if the expiry job silently fails, an invited user who
never responds keeps their seat forever — nobody from the waitlist fills it.
Pair members must expire together so the pair doesn't get split.
"""
import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import check_timeout_job
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


class TestCheckTimeoutJob(unittest.IsolatedAsyncioTestCase):
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

    async def test_invited_user_expires_and_promotes_next_in_waitlist(self):
        """INVITED reg times out → EXPIRED; the next WAITLIST user gets promoted to INVITED."""
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, event_start_time) "
            "VALUES ('CLOSED', 3, '2026-10-10 12:00:00')"
        )
        event_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, first_name, status) "
            "VALUES (?, 101, 'invited_user', 'Invited', 'INVITED')",
            (event_id,)
        )
        timed_out_reg_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status, priority) "
            "VALUES (?, 202, 'waiter', 'WAITLIST', 0)",
            (event_id,)
        )
        self.real_conn.commit()

        with patch('bot.application') as mock_app, patch('bot.scheduler') as mock_sched:
            mock_app.bot.send_message = AsyncMock()
            mock_sched.add_job = MagicMock()
            await check_timeout_job(timed_out_reg_id)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (timed_out_reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'EXPIRED')

        cursor.execute("SELECT status FROM registrations WHERE user_id = 202")
        self.assertEqual(cursor.fetchone()['status'], 'INVITED')

        expiry_sent = any(
            messages.INVITATION_EXPIRED in (c[0][1] if c[0] else '')
            for c in mock_app.bot.send_message.call_args_list
        )
        self.assertTrue(expiry_sent, "Expired user must receive INVITATION_EXPIRED message")

    async def test_already_accepted_is_noop(self):
        """If the user already accepted before the timeout fires, nothing changes."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 3)")
        event_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) "
            "VALUES (?, 101, 'accepted_user', 'ACCEPTED')",
            (event_id,)
        )
        reg_id = cursor.lastrowid
        self.real_conn.commit()

        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            await check_timeout_job(reg_id)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')
        mock_app.bot.send_message.assert_not_called()

    async def test_invited_pair_both_expire_atomically(self):
        """When a paired INVITED unit times out, both members expire together."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 5)")
        event_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, 1, 'pair_a', 'INVITED')",
            (event_id,)
        )
        a_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, 2, 'pair_b', 'INVITED')",
            (event_id,)
        )
        b_id = cursor.lastrowid
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_id, a_id))
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a_id, b_id))
        self.real_conn.commit()

        with patch('bot.application') as mock_app, patch('bot.scheduler'):
            mock_app.bot.send_message = AsyncMock()
            await check_timeout_job(a_id)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (a_id,))
        self.assertEqual(cursor.fetchone()['status'], 'EXPIRED')
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (b_id,))
        self.assertEqual(cursor.fetchone()['status'], 'EXPIRED')

        # Both get the expiry DM
        notified_ids = {c[0][0] for c in mock_app.bot.send_message.call_args_list
                        if messages.INVITATION_EXPIRED in (c[0][1] if len(c[0]) > 1 else '')}
        self.assertIn(1, notified_ids)
        self.assertIn(2, notified_ids)

    async def test_invited_pair_with_unaccepted_partner_only_expires_invitee(self):
        """If pair partner is already ACCEPTED, only the INVITED member expires."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 5)")
        event_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, 1, 'pair_a', 'INVITED')",
            (event_id,)
        )
        a_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, 2, 'pair_b', 'ACCEPTED')",
            (event_id,)
        )
        b_id = cursor.lastrowid
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_id, a_id))
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a_id, b_id))
        self.real_conn.commit()

        with patch('bot.application') as mock_app, patch('bot.scheduler'):
            mock_app.bot.send_message = AsyncMock()
            await check_timeout_job(a_id)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (a_id,))
        self.assertEqual(cursor.fetchone()['status'], 'EXPIRED')
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (b_id,))
        self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')


if __name__ == '__main__':
    unittest.main()
