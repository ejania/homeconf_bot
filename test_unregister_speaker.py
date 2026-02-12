import unittest
import sqlite3
import os
from unittest.mock import MagicMock, AsyncMock, patch
from bot import unregister
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

class TestUnregisterSpeaker(unittest.IsolatedAsyncioTestCase):
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS speakers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                username TEXT,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_speaker_cannot_unregister(self):
        # Setup event with speaker group
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, speakers_group_id) VALUES ('OPEN', 'group_123')")
        self.real_conn.commit()

        # Mock update
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 999
        update.effective_user.username = "speaker_user"
        update.message.reply_text = AsyncMock()

        # Mock context and chat member check
        context = MagicMock()
        member = MagicMock()
        member.status = "member"
        context.bot.get_chat_member = AsyncMock(return_value=member)

        # Call unregister
        await unregister(update, context)

        # Verify response
        update.message.reply_text.assert_called_with(messages.SPEAKER_UNREGISTER_ERROR)

    async def test_manual_speaker_cannot_unregister(self):
        # Setup event and manual speaker
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('OPEN')")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker_manual"))
        self.real_conn.commit()

        # Mock update
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 888
        update.effective_user.username = "speaker_manual"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        
        # Call unregister
        await unregister(update, context)

        # Verify response
        update.message.reply_text.assert_called_with(messages.SPEAKER_UNREGISTER_ERROR)

if __name__ == '__main__':
    unittest.main()
