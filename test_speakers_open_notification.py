"""
Test for fix #7: when /open is called, the speakers group gets a message
warning that the guest-invite window is now closed.
"""
import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import open_event_command
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
    cursor.execute('''CREATE TABLE IF NOT EXISTS speakers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, username TEXT, first_name TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, chat_id INTEGER,
        username TEXT, first_name TEXT, status TEXT,
        signup_time DATETIME, priority INTEGER, notified_at DATETIME,
        expires_at DATETIME, guest_of_user_id INTEGER,
        partner_reg_id INTEGER, invite_token TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, username TEXT,
        first_name TEXT, action TEXT, details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()


class TestSpeakersOpenNotification(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = MockConnection(self.real_conn)
        _setup_schema(self.real_conn)

        self.admin_patcher = patch('bot.is_admin', return_value=True)
        self.mock_is_admin = self.admin_patcher.start()

        self.scheduler_patcher = patch('bot.scheduler')
        self.mock_scheduler = self.scheduler_patcher.start()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()
        self.admin_patcher.stop()
        self.scheduler_patcher.stop()

    def _make_open_update(self, hours=24, places=20, date='2026-10-10', time='18:00'):
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_user.username = 'admin'
        update.effective_user.first_name = 'Admin'
        update.effective_chat.id = 100
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = [str(hours), str(places), date, time]
        context.bot.send_message = AsyncMock()
        return update, context

    async def test_speakers_group_notified_on_open(self):
        """When /open is called with a speakers group set, the group receives the window-closed message."""
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, '-100987654321')"
        )
        self.real_conn.commit()

        update, context = self._make_open_update()
        await open_event_command(update, context)

        # Check that the speakers group received a message
        group_calls = [
            c for c in context.bot.send_message.call_args_list
            if c[0][0] == -100987654321
        ]
        self.assertEqual(len(group_calls), 1)
        self.assertEqual(group_calls[0][0][1], messages.SPEAKERS_INVITE_WINDOW_CLOSED)

    async def test_no_speakers_group_no_extra_message(self):
        """When speakers_group_id is not set, no extra message is sent."""
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, NULL)"
        )
        self.real_conn.commit()

        update, context = self._make_open_update()
        await open_event_command(update, context)

        context.bot.send_message.assert_not_called()

    async def test_speakers_group_notification_failure_does_not_break_open(self):
        """If the DM to the speakers group fails, /open still succeeds."""
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, '-100987654321')"
        )
        self.real_conn.commit()

        update, context = self._make_open_update()
        context.bot.send_message = AsyncMock(side_effect=Exception("Forbidden"))

        await open_event_command(update, context)

        # Event is still set to OPEN despite the notification failure
        cursor.execute("SELECT status FROM events")
        self.assertEqual(cursor.fetchone()['status'], 'OPEN')
        update.message.reply_text.assert_called()


if __name__ == '__main__':
    unittest.main()
