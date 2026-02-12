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

class TestSpeakerCount(unittest.IsolatedAsyncioTestCase):
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
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_speakers_reduce_lottery_pool(self):
        # 5 Total Places
        # 3 Speakers in Group (mocked)
        # 0 Guests
        # Expectation: 5 - 3 = 2 spots for lottery.
        
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, speakers_group_id) VALUES (123, 'OPEN', 5, 'group_speakers')")
        event_id = cursor.lastrowid
        
        # 5 Registered Users (Candidates)
        for i in range(5):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                (event_id, i+10, 'REGISTERED')
            )
        self.real_conn.commit()
        
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            
            # Mock get_chat_member_count
            # We need to mock calls made inside close_registration_job.
            # close_registration_job uses `application.bot` if available or we might need to patch where it gets the bot.
            # The current implementation of `close_registration_job` uses `application.bot`.
            mock_app.bot.get_chat_member_count = AsyncMock(return_value=3) 
            
            # Since `close_registration_job` might not use `application.bot` to get the count yet (we haven't implemented it),
            # this test is predicting the implementation.
            # However, to fail first, I'll run it.
            
            await close_registration_job(event_id, 123)
            
            # Check results
            cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'ACCEPTED'")
            accepted_count = cursor.fetchone()['cnt']
            
            # Without the fix, it ignores speakers, so 5 spots total -> 5 winners (since 5 registered)
            # With the fix, it should be 2 winners.
            
            # This assertion validates if the logic is present.
            # Currently it should fail (expecting 5, or maybe fewer if I asserted 2).
            # I will assert 2 to confirm failure.
            self.assertEqual(accepted_count, 2, f"Expected 2 winners, got {accepted_count}")

if __name__ == '__main__':
    unittest.main()
