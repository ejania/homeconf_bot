import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
from bot import create_event, open_event_command, invite_guest, register
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

class TestPreOpen(unittest.IsolatedAsyncioTestCase):
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
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_create_and_open_flow(self):
        # 1. Admin creates event
        update = MagicMock()
        update.effective_chat.id = 123
        update.effective_chat.type = "private"
        update.effective_user.id = 999
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["2", "10", "group_speakers"] # 2 hours, 10 places
        
        # Mock admin check
        with patch('bot.is_admin', return_value=True):
            # Mock validation of group
            chat_mock = MagicMock()
            chat_mock.id = 888
            chat_mock.title = "Speakers Group"
            context.bot.get_chat = AsyncMock(return_value=chat_mock)
            
            await create_event(update, context)
            
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT * FROM events WHERE status = 'PRE_OPEN'")
        event = cursor.fetchone()
        self.assertIsNotNone(event)
        self.assertEqual(event['registration_duration_hours'], 2)
        self.assertEqual(event['total_places'], 10)
        
        event_id = event['id']

        # 2. Speaker invites guest during PRE_OPEN
        update_sp = MagicMock()
        update_sp.effective_chat.type = "private"
        update_sp.effective_user.id = 555 # Speaker
        update_sp.effective_user.username = "speaker_alice"
        update_sp.message.reply_text = AsyncMock()
        
        context_sp = MagicMock()
        context_sp.args = ["guest_bob"]
        
        # Mock speaker check (manual list for simplicity)
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker_alice"))
        self.real_conn.commit()
        
        await invite_guest(update_sp, context_sp)
        
        cursor.execute("SELECT * FROM registrations WHERE username = 'guest_bob'")
        guest = cursor.fetchone()
        self.assertIsNotNone(guest, "Guest should be invited in PRE_OPEN")
        self.assertEqual(guest['status'], 'ACCEPTED')

        # 3. Admin opens registration
        update_open = MagicMock()
        update_open.effective_chat.id = 123
        update_open.effective_user.id = 999
        update_open.message.reply_text = AsyncMock()
        context_open = MagicMock()
        
        with patch('bot.is_admin', return_value=True):
            with patch('bot.scheduler') as mock_scheduler:
                await open_event_command(update_open, context_open)
                
                # Verify status change
                cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
                event = cursor.fetchone()
                self.assertEqual(event['status'], 'OPEN')
                self.assertIsNotNone(event['end_time'])
                
                # Verify job scheduled
                mock_scheduler.add_job.assert_called()

        # 4. Speaker tries to invite guest in OPEN -> Should FAIL
        update_sp.message.reply_text.reset_mock()
        context_sp.args = ["guest_charlie"]
        
        await invite_guest(update_sp, context_sp)
        
        update_sp.message.reply_text.assert_called_with(messages.INVITE_ONLY_PRE_OPEN)
        cursor.execute("SELECT * FROM registrations WHERE username = 'guest_charlie'")
        self.assertIsNone(cursor.fetchone(), "Guest invite should fail in OPEN state")

if __name__ == '__main__':
    unittest.main()
