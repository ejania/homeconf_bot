import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from bot import close_registration_job
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
        pass

class TestGuestDeduction(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_conn = MockConnection(self.real_conn)
        self.mock_get_db.return_value = self.mock_conn
        
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
                registration_duration_hours INTEGER
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

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_guest_deduces_spot(self):
        # 5 Places Total
        # 1 Speaker (mocked in group)
        # 1 Guest Invited (ACCEPTED)
        # Expectation: 5 - 1 (Speaker) - 1 (Guest) = 3 Spots for Lottery
        
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, speakers_group_id) VALUES (123, 'OPEN', 5, 'group_sp')")
        event_id = cursor.lastrowid
        
        # 1 Guest Invited by Speaker (ID 999)
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, "guest_user", "ACCEPTED", 999)
        )
        
        # 5 Registered Users (Candidates)
        for i in range(5):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                (event_id, i+10, 'REGISTERED')
            )
        self.real_conn.commit()
        
        # Insert 1 Speaker into DB
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker_1"))
        self.real_conn.commit()

        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            
            with patch('bot.invite_next'): # Prevent external calls
                await close_registration_job(event_id, 123)
            
            # Verify Results
            # Guest should remain ACCEPTED
            cursor.execute("SELECT status FROM registrations WHERE username = 'guest_user'")
            self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')
            
            # Lottery Winners should be 3
            cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'ACCEPTED' AND guest_of_user_id IS NULL")
            winners = cursor.fetchone()['cnt']
            self.assertEqual(winners, 3, f"Expected 3 winners (5 total - 1 speaker - 1 guest), got {winners}")
            
            # Waitlist should be 2
            cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'WAITLIST'")
            waitlist = cursor.fetchone()['cnt']
            self.assertEqual(waitlist, 2)

if __name__ == '__main__':
    unittest.main()
