import unittest
import sqlite3
import random
from unittest.mock import patch, AsyncMock, MagicMock
from models import init_db
from bot import close_registration_job

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

class TestLotteryRandomness(unittest.IsolatedAsyncioTestCase):
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

    async def test_lottery_randomness(self):
        # We will create two separate events with the exact same 10 users registering.
        # We expect the 'ACCEPTED' users to be different in random draws.
        # Since it's random, there's a small chance they are identical, but with 2 spots out of 100 users,
        # or 5 out of 100, the chance is miniscule. Let's use a large pool (50 users) and 10 spots.
        
        # We need to mock application.bot to avoid exceptions during send_message
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.get_me = AsyncMock()
            mock_app.bot.get_chat_member_count = AsyncMock(return_value=1) # Just the bot
            
            # Run simulation 5 times to surely capture different results
            all_winners_sets = []
            
            for sim in range(5):
                cursor = self.real_conn.cursor()
                cursor.execute(
                    "INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 10)"
                )
                event_id = cursor.lastrowid
                
                # Add 50 users
                for i in range(50):
                    cursor.execute(
                        "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                        (event_id, 1000 + i, 'REGISTERED')
                    )
                self.real_conn.commit()
                
                await close_registration_job(event_id, 123)
                
                cursor.execute(
                    "SELECT user_id FROM registrations WHERE event_id = ? AND status = 'ACCEPTED'",
                    (event_id,)
                )
                winners = set(row['user_id'] for row in cursor.fetchall())
                all_winners_sets.append(winners)
            
            # Check that not all sets of winners are exactly identical
            unique_sets_count = len(set(frozenset(s) for s in all_winners_sets))
            self.assertGreater(unique_sets_count, 1, "The lottery did not produce any random variations in 5 draws.")

if __name__ == '__main__':
    unittest.main()
