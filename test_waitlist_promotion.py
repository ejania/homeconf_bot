import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from bot import close_registration_job, invite_next
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

class TestWaitlistPromotion(unittest.IsolatedAsyncioTestCase):
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
                end_time DATETIME
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

    async def test_promote_waitlist_when_spots_available(self):
        # 5 Places total
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 5)")
        event_id = cursor.lastrowid
        
        # 2 Registered (Lottery candidates)
        for i in range(2):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                (event_id, i+10, 'REGISTERED')
            )
            
        # 2 Waitlist (Existing/Late) with priority 0 and 1
        for i in range(2):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, ?, ?, ?)",
                (event_id, i+20, 'WAITLIST', i)
            )
        self.real_conn.commit()
        
        # Mock application.bot.send_message
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            # Also mock scheduler for invite_next
            with patch('bot.scheduler'):
                await close_registration_job(event_id, 123)
        
        # Expectation:
        # 2 Registered -> ACCEPTED
        # 2 Waitlist -> INVITED (Promoted)
        # Total filled/invited = 4. 1 Spot remains free.
        
        cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'ACCEPTED'")
        self.assertEqual(cursor.fetchone()['cnt'], 2, "Registered users should be accepted")
        
        cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'INVITED'")
        self.assertEqual(cursor.fetchone()['cnt'], 2, "Waitlist users should be invited")
        
        cursor.execute("SELECT user_id FROM registrations WHERE status = 'INVITED'")
        invited_ids = [row['user_id'] for row in cursor.fetchall()]
        self.assertIn(20, invited_ids)
        self.assertIn(21, invited_ids)

        # Verify messages sent
        # We expect 2 WINNER messages (for 10, 11) and 2 INVITE messages (for 20, 21)
        calls = mock_app.bot.send_message.call_args_list
        
        # Check invites
        invite_calls = [c for c in calls if c[0][0] in (20, 21)]
        self.assertEqual(len(invite_calls), 2)
        for call in invite_calls:
            self.assertIn("Освободилось место!", call[0][1])
            self.assertIn("24 ч.", call[0][1]) # Default timeout

    async def test_lottery_losers_priority_over_waitlist(self):
        # 2 Places total
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 2)")
        event_id = cursor.lastrowid
        
        # 3 Registered (Lottery candidates) -> 2 Winners, 1 Loser
        for i in range(3):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                (event_id, i+10, 'REGISTERED')
            )
            
        # 1 Waitlist (Existing) - Priority 0
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, ?, ?, ?)",
            (event_id, 99, 'WAITLIST', 0)
        )
        self.real_conn.commit()
        
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            await close_registration_job(event_id, 123)
            
        # Expectation:
        # 2 Winners (ACCEPTED)
        # 1 Loser (WAITLIST) -> Should be Priority 0
        # 1 Old Waitlist (WAITLIST) -> Should be Priority 1
        
        cursor.execute("SELECT status, priority FROM registrations WHERE user_id = 99") # Old waitlist
        row = cursor.fetchone()
        self.assertEqual(row['status'], 'WAITLIST')
        self.assertEqual(row['priority'], 1, "Old waitlist should be shifted down")
        
        # Check loser
        cursor.execute("SELECT status, priority FROM registrations WHERE user_id IN (10, 11, 12) AND status = 'WAITLIST'")
        loser = cursor.fetchone()
        self.assertIsNotNone(loser)
        self.assertEqual(loser['priority'], 0, "Lottery loser should get top priority")

if __name__ == '__main__':
    unittest.main()
