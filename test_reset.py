import unittest
import sqlite3
import os
from unittest.mock import MagicMock, AsyncMock, patch
from bot import reset_event
import messages

# Use an in-memory database for testing
TEST_DB_PATH = ":memory:"

class MockConnection:
    def __init__(self, real_conn):
        self.real_conn = real_conn
    
    def cursor(self):
        return self.real_conn.cursor()
    
    def commit(self):
        self.real_conn.commit()
        
    def close(self):
        pass # Do nothing

class TestReset(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Redirect the database path to memory
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        
        # Setup in-memory DB
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        
        # Use wrapper
        self.mock_conn = MockConnection(self.real_conn)
        self.mock_get_db.return_value = self.mock_conn
        
        # Initialize schema
        cursor = self.real_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                status TEXT,
                total_places INTEGER,
                speakers_group_id TEXT,
                waitlist_timeout_hours INTEGER,
                end_time DATETIME,
                registration_duration_hours INTEGER,
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
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        """)

        self.real_conn.commit()

        # Mock ADMIN_IDS
        self.admin_patcher = patch('bot.ADMIN_IDS', {123})
        self.admin_patcher.start()
        
        # Mock scheduler
        self.sched_patcher = patch('bot.scheduler')
        self.mock_scheduler = self.sched_patcher.start()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()
        self.admin_patcher.stop()
        self.sched_patcher.stop()

    async def test_reset_unauthorized(self):
        update = MagicMock()
        update.effective_user.id = 456 # Not an admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await reset_event(update, context)
        update.message.reply_text.assert_called_with(messages.ONLY_ADMIN_RESET)

    async def test_reset_no_confirm(self):
        update = MagicMock()
        update.effective_user.id = 123 # Admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        await reset_event(update, context)
        update.message.reply_text.assert_called_with(messages.RESET_CONFIRMATION)

    async def test_reset_success(self):
        # Setup event and registrations
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 1, 'ACCEPTED')", (event_id, ))
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 2, 'WAITLIST')", (event_id, ))
        self.real_conn.commit()

        update = MagicMock()
        update.effective_user.id = 123 # Admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["confirm"]

        # Mock scheduler job existence
        self.mock_scheduler.get_job.return_value = MagicMock()

        await reset_event(update, context)

        # Verify response
        update.message.reply_text.assert_called_with(messages.RESET_SUCCESS)
        
        # Verify DB state
        cursor.execute("SELECT status FROM events WHERE id = ?", (event_id,))
        self.assertEqual(cursor.fetchone()['status'], 'CANCELLED')
        
        cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ?", (event_id,))
        self.assertEqual(cursor.fetchone()['count'], 2)
        
        # Verify scheduler called
        self.mock_scheduler.remove_job.assert_called_once_with(f"close_{event_id}")

if __name__ == '__main__':
    unittest.main()
