import unittest
import sqlite3
import os
from unittest.mock import MagicMock, AsyncMock, patch
from bot import list_participants
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

class TestList(unittest.IsolatedAsyncioTestCase):
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

    async def test_list_visibility(self):
        # Setup event: 10 total places
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places, speakers_group_id) VALUES ('OPEN', 10, 'group_123')")
        event_id = cursor.lastrowid
        
        # 2 manual speakers
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, 's1')", (event_id,))
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, 's2')", (event_id,))
        
        # 1 guest
        cursor.execute("INSERT INTO registrations (event_id, user_id, status, guest_of_user_id) VALUES (?, 101, 'ACCEPTED', 999)", (event_id,))
        
        # 2 general accepted
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 201, 'ACCEPTED')", (event_id,))
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 202, 'ACCEPTED')", (event_id,))
        
        # 3 lottery pool
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 301, 'REGISTERED')", (event_id,))
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 302, 'REGISTERED')", (event_id,))
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 303, 'REGISTERED')", (event_id,))
        
        self.real_conn.commit()

        # Mock update
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        # Mock context and chat member count
        context = MagicMock()
        # Mock get_chat_member_count to return 3 (e.g. bot, admin, 1 speaker in group)
        context.bot.get_chat_member_count = AsyncMock(return_value=3)

        # Call list_participants
        await list_participants(update, context)

        # Verify response
        # Total speakers = 3 (from group) + 2 (manual) = 5
        # Total guests = 1
        # VIP taken = 5 + 1 = 6
        # General total = 10 - 6 = 4
        # General taken = 2
        # Lottery count = 3
        
        expected_msg = messages.EVENT_STATUS_HEADER.format(
            status="OPEN",
            vip_taken=6,
            general_taken=2,
            general_total=4
        )
        expected_msg += messages.EVENT_STATUS_OPEN.format(count=3)
        
        update.message.reply_text.assert_called_once()
        actual_msg = update.message.reply_text.call_args[0][0]
        self.assertEqual(actual_msg, expected_msg)

if __name__ == '__main__':
    unittest.main()
