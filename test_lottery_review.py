import unittest
import sqlite3
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import bot
from bot import close_registration_job, send_invites, status, register, list_participants
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

class TestLotteryReview(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Setup in-memory DB
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.conn = MockConnection(self.real_conn)
        
        # Patch the get_db in bot.py
        self.db_patcher = patch('bot.get_db')
        self.mock_get_db = self.db_patcher.start()
        self.mock_get_db.return_value = self.conn
        
        # Patch the application in bot.py
        self.app_patcher = patch('bot.application')
        self.mock_app = self.app_patcher.start()
        self.mock_app.bot.send_message = AsyncMock()
        
        # Initialize schema
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, status TEXT, total_places INTEGER, speakers_group_id TEXT, waitlist_timeout_hours INTEGER, end_time DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE registrations (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, chat_id INTEGER, username TEXT, first_name TEXT, status TEXT, signup_time DATETIME, priority INTEGER, notified_at DATETIME, expires_at DATETIME, guest_of_user_id INTEGER)")
        cursor.execute("CREATE TABLE speakers (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, username TEXT)")
        cursor.execute("CREATE TABLE action_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, username TEXT, action TEXT, details TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        self.conn.commit()

        # Admin IDs patch
        self.admin_patcher = patch('bot.ADMIN_IDS', {123})
        self.admin_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()
        self.app_patcher.stop()
        self.admin_patcher.stop()
        self.real_conn.close()

    async def test_full_review_flow(self):
        cursor = self.conn.cursor()
        # 1. Create event
        cursor.execute("INSERT INTO events (status, total_places, chat_id) VALUES ('OPEN', 2, 999)")
        event_id = cursor.lastrowid
        self.conn.commit()

        # 2. Register 3 users (only 2 spots available)
        for i in range(1, 4):
            cursor.execute("INSERT INTO registrations (event_id, user_id, username, status, signup_time) VALUES (?, ?, ?, 'REGISTERED', ?)",
                           (event_id, 100+i, f"user{i}", datetime.now()))
        self.conn.commit()

        # 3. Close registration (trigger lottery)
        await close_registration_job(event_id, 999)

        # 4. Verify Event Status is REVIEW
        cursor.execute("SELECT status FROM events WHERE id = ?", (event_id,))
        self.assertEqual(cursor.fetchone()['status'], 'REVIEW')

        # 5. Verify 2 winners, 1 loser, and NO notifications yet (other than admin summary)
        cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'ACCEPTED'", (event_id,))
        self.assertEqual(cursor.fetchone()['count'], 2)
        cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'WAITLIST'", (event_id,))
        self.assertEqual(cursor.fetchone()['count'], 1)
        
        # Check that ONLY the admin/chat summary messages were sent
        # bot.py sends: 1. CLOSED_SUMMARY, 2. READY_FOR_REVIEW
        self.assertEqual(self.mock_app.bot.send_message.call_count, 2)
        
        # 6. Verify /status still shows REGISTERED for a winner
        cursor.execute("SELECT user_id FROM registrations WHERE event_id = ? AND status = 'ACCEPTED' LIMIT 1", (event_id,))
        winner_id = cursor.fetchone()['user_id']
        
        update = MagicMock()
        update.effective_user.id = winner_id
        update.effective_user.username = f"user_winner"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        
        # We need to mock ensure_private to return True
        with patch('bot.ensure_private', return_value=True):
            await status(update, context)
        
        # Should show REGISTERED status
        update.message.reply_text.assert_called_with(messages.STATUS_MSG.format(status=messages.STATUS_REGISTERED))

        # 7. Run /send_invites as admin
        admin_update = MagicMock()
        admin_update.effective_user.id = 123
        admin_update.message.reply_text = AsyncMock()
        admin_context = MagicMock()
        admin_context.bot = self.mock_app.bot
        
        await send_invites(admin_update, admin_context)

        # 8. Verify Event Status is now CLOSED
        cursor.execute("SELECT status FROM events WHERE id = ?", (event_id,))
        self.assertEqual(cursor.fetchone()['status'], 'CLOSED')

        # 9. Verify notifications were sent
        # Previous 2 calls + 2 winners + 1 waitlist = 5 calls total
        self.assertEqual(self.mock_app.bot.send_message.call_count, 5)
        
        # 10. Verify /status now shows ACCEPTED for the winner
        update.message.reply_text.reset_mock()
        with patch('bot.ensure_private', return_value=True):
            await status(update, context)
        update.message.reply_text.assert_called_with(messages.STATUS_MSG.format(status=messages.STATUS_ACCEPTED))

if __name__ == '__main__':
    unittest.main()
