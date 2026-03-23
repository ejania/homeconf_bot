import unittest
from unittest.mock import AsyncMock, patch
import sqlite3
import os

os.environ["DB_PATH"] = ":memory:"

from bot import invite_next, get_now
import messages

class TestStrictCapacity(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self):
        self.real_conn.close()

    async def test_strict_capacity_prevents_promotion(self):
        cursor = self.real_conn.cursor()
        # Create event with 3 total places
        cursor.execute("INSERT INTO events (status, total_places, event_start_time) VALUES ('CLOSED', 3, '2026-10-10 10:00:00')")
        event_id = cursor.lastrowid
        
        # Add 1 speaker
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, 'speaker1'))
        
        # Add 1 ACCEPTED user
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, 'ACCEPTED')", (event_id, 101))
        
        # Add 1 INVITED user
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, 'INVITED')", (event_id, 102))
        
        # Add 1 WAITLIST user
        cursor.execute("INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, ?, 'WAITLIST', 1)", (event_id, 103))
        
        self.real_conn.commit()
        
        # Total occupied = 1 (speaker) + 1 (ACCEPTED) + 1 (INVITED) = 3. 
        # Total places = 3. 
        # invite_next should NOT promote the WAITLIST user.
        
        await invite_next(event_id)
        
        cursor.execute("SELECT status FROM registrations WHERE user_id = 103")
        waitlist_user = cursor.fetchone()
        
        self.assertEqual(waitlist_user['status'], 'WAITLIST')

    async def test_strict_capacity_allows_promotion_if_space(self):
        cursor = self.real_conn.cursor()
        # Create event with 3 total places
        cursor.execute("INSERT INTO events (status, total_places, event_start_time) VALUES ('CLOSED', 3, '2026-10-10 10:00:00')")
        event_id = cursor.lastrowid
        
        # Add 1 speaker
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, 'speaker1'))
        
        # Add 1 ACCEPTED user
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, 'ACCEPTED')", (event_id, 101))
        
        # Add 1 WAITLIST user
        cursor.execute("INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, ?, 'WAITLIST', 1)", (event_id, 103))
        
        self.real_conn.commit()
        
        # Total occupied = 1 (speaker) + 1 (ACCEPTED) = 2. 
        # Total places = 3. 
        # invite_next SHOULD promote the WAITLIST user.
        
        with patch('bot.application') as mock_app, patch('bot.scheduler') as mock_sched:
            mock_app.bot.send_message = AsyncMock()
            await invite_next(event_id)
            
        cursor.execute("SELECT status FROM registrations WHERE user_id = 103")
        waitlist_user = cursor.fetchone()
        
        self.assertEqual(waitlist_user['status'], 'INVITED')

if __name__ == '__main__':
    unittest.main()
