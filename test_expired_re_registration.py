import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import os

os.environ["DB_PATH"] = ":memory:"

from bot import register, get_now, get_db
import messages

class TestExpiredReRegistration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.real_conn = sqlite3.connect(":memory:")
        self.real_conn.row_factory = sqlite3.Row
        
        cursor = self.real_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                status TEXT,
                total_places INTEGER,
                speakers_group_id TEXT,
                waitlist_timeout_hours INTEGER,
                registration_duration_hours INTEGER,
                end_time DATETIME,
                event_start_time DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                chat_id INTEGER,
                username TEXT,
                first_name TEXT,
                status TEXT,
                signup_time DATETIME,
                priority INTEGER,
                notified_at DATETIME,
                expires_at DATETIME,
                guest_of_user_id INTEGER,
                invite_token TEXT,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS speakers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                username TEXT,
                first_name TEXT,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        self.real_conn.commit()

        self.update = MagicMock()
        self.context = MagicMock()
        self.update.effective_user.id = 123
        self.update.effective_user.username = "test_user"
        self.update.effective_user.first_name = "Test"
        self.update.effective_chat.id = 123
        self.update.message.reply_text = AsyncMock()

        class MockConnection:
            def __init__(self, conn):
                self.conn = conn
            def cursor(self):
                return self.conn.cursor()
            def commit(self):
                self.conn.commit()
            def close(self):
                pass
        
        self.mock_conn = MockConnection(self.real_conn)
        
        patcher = patch('bot.get_db', return_value=self.mock_conn)
        self.mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)
        
        patcher_ep = patch('bot.ensure_private', return_value=True)
        self.mock_ensure_private = patcher_ep.start()
        self.addCleanup(patcher_ep.stop)

    def tearDown(self):
        self.real_conn.close()

    async def test_re_register_after_expired(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        event_id = cursor.lastrowid
        
        # User is expired
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status, signup_time) VALUES (?, ?, ?, 'EXPIRED', ?)",
            (event_id, 123, 'test_user', get_now())
        )
        self.real_conn.commit()
        
        # Existing waitlist max priority is 5
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status, signup_time, priority) VALUES (?, ?, ?, 'WAITLIST', ?, ?)",
            (event_id, 456, 'other_user', get_now(), 5)
        )
        self.real_conn.commit()

        self.context.bot.send_message = AsyncMock()

        await register(self.update, self.context)

        self.context.bot.send_message.assert_called_with(123, messages.REGISTER_WAITLIST.format(position=7))

        # Verify db state
        cursor.execute("SELECT * FROM registrations WHERE user_id = 123 AND status = 'WAITLIST'")
        new_reg = cursor.fetchone()
        self.assertIsNotNone(new_reg)
        self.assertEqual(new_reg['priority'], 6)
if __name__ == '__main__':
    unittest.main()
