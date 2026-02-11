import unittest
import sqlite3
import os
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from bot import unregister, invite_next, invite_guest, register, close_registration_job, status
from models import init_db, get_db
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

class TestBot(unittest.IsolatedAsyncioTestCase):
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
                username TEXT, -- lowercased for matching
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        ''')
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_unregister_registered_user(self):
        # Setup event and registration
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 10)")
        event_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
            (event_id, 456, 'REGISTERED')
        )
        self.real_conn.commit()

        # Mock Update and Context
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 456
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()

        # Call unregister
        await unregister(update, context)

        # Verify status update
        cursor.execute("SELECT status FROM registrations WHERE user_id = 456")
        status = cursor.fetchone()['status']
        self.assertEqual(status, 'UNREGISTERED')
        
        # Verify response
        update.message.reply_text.assert_called_with(messages.UNREGISTERED_SUCCESS)

    async def test_unregister_accepted_user_triggers_invite(self):
        # Setup event and registrations
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, waitlist_timeout_hours) VALUES (123, 'CLOSED', 1, 24)")
        event_id = cursor.lastrowid
        
        # Accepted user
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
            (event_id, 111, 'ACCEPTED')
        )
        # Waitlist user
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status, priority) VALUES (?, ?, ?, ?)",
            (event_id, 222, 'WAITLIST', 1)
        )
        self.real_conn.commit()

        # Mock Update and Context for unregister
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # Patch invite_next to verify it's called (or let it run if we want full integration)
        # We'll let it run but we need to mock scheduler in invite_next or just check DB changes
        
        # We need to mock scheduler.add_job in bot.py since invite_next uses it
        with patch('bot.scheduler') as mock_scheduler:
            # Also patch application.bot.send_message used in invite_next
            with patch('bot.application') as mock_app:
                mock_app.bot.send_message = AsyncMock()
                
                await unregister(update, context)

                # Verify accepted user is unregistered
                cursor.execute("SELECT status FROM registrations WHERE user_id = 111")
                self.assertEqual(cursor.fetchone()['status'], 'UNREGISTERED')
                
                # Verify waitlist user is invited
                cursor.execute("SELECT status FROM registrations WHERE user_id = 222")
                self.assertEqual(cursor.fetchone()['status'], 'INVITED')

    async def test_invite_guest_success(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, speakers_group_id) VALUES (123, 'OPEN', 10, 'group_id')")
        event_id = cursor.lastrowid
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 999 # Speaker
        update.effective_user.username = "speaker_user"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["guest_user"]
        
        # Mock speaker check
        member = MagicMock()
        member.status = "member"
        context.bot.get_chat_member = AsyncMock(return_value=member)

        await invite_guest(update, context)
        
        cursor.execute("SELECT * FROM registrations WHERE username = 'guest_user'")
        reg = cursor.fetchone()
        self.assertIsNotNone(reg)
        self.assertEqual(reg['status'], 'ACCEPTED')
        self.assertEqual(reg['guest_of_user_id'], 999)
        self.assertIsNone(reg['user_id'])
        
        update.message.reply_text.assert_called_with(messages.GUEST_INVITED_NEW.format(username="guest_user"))

    async def test_invite_guest_not_speaker(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, speakers_group_id) VALUES (123, 'OPEN', 10, 'group_id')")
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 888 # Not Speaker
        update.effective_user.username = "not_speaker"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["guest_user"]
        
        # Mock speaker check fail
        member = MagicMock()
        member.status = "left"
        context.bot.get_chat_member = AsyncMock(return_value=member)

        await invite_guest(update, context)
        
        update.message.reply_text.assert_called_with(messages.ONLY_SPEAKERS_INVITE)

    async def test_register_claims_guest_spot(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 10)")
        event_id = cursor.lastrowid
        # Pre-seed invite
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, 'guest_user', 'ACCEPTED', 999)
        )
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 777
        update.effective_user.username = "guest_user"
        update.effective_user.first_name = "Guest"
        update.effective_chat.id = 1000
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()

        await register(update, context)
        
        cursor.execute("SELECT * FROM registrations WHERE username = 'guest_user'")
        reg = cursor.fetchone()
        self.assertEqual(reg['user_id'], 777)
        self.assertEqual(reg['chat_id'], 1000)
        
        update.message.reply_text.assert_called_with(messages.GUEST_IDENTIFIED)

    async def test_lottery_respects_guests(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 3)")
        event_id = cursor.lastrowid
        
        # 1 Guest (ACCEPTED)
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, 'guest', 'ACCEPTED', 999)
        )
        # 3 Registered users (for 2 remaining spots)
        for i in range(3):
            cursor.execute(
                "INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)",
                (event_id, i+10, 'REGISTERED')
            )
        self.real_conn.commit()
        
        # We need to mock application.bot.send_message
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()
            
            await close_registration_job(event_id, 123)
            
            # Check results
            cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'ACCEPTED' AND guest_of_user_id IS NULL")
            # Should be 2 winners from lottery
            self.assertEqual(cursor.fetchone()['cnt'], 2)
            
            cursor.execute("SELECT COUNT(*) as cnt FROM registrations WHERE status = 'WAITLIST'")
            # Should be 1 waitlisted
            self.assertEqual(cursor.fetchone()['cnt'], 1)

    async def test_invite_guest_already_invited(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places, speakers_group_id) VALUES (123, 'OPEN', 10, 'group_id')")
        event_id = cursor.lastrowid
        
        # Speaker already invited someone
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, 'first_guest', 'ACCEPTED', 999)
        )
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 999 # Speaker
        update.effective_user.username = "speaker_user"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["second_guest"]
        
        # Mock speaker check
        member = MagicMock()
        member.status = "member"
        context.bot.get_chat_member = AsyncMock(return_value=member)

        await invite_guest(update, context)
        
        update.message.reply_text.assert_called_with(messages.ALREADY_INVITED_GUEST)

    async def test_guest_try_register_again(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (chat_id, status, total_places) VALUES (123, 'OPEN', 10)")
        event_id = cursor.lastrowid
        # Guest already claimed spot
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, 777, 'ACCEPTED', 999)
        )
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 777
        update.effective_user.username = "guest_user"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()

        await register(update, context)
        
        update.message.reply_text.assert_called_with(messages.ALREADY_INVITED_HAS_PLACE)

    async def test_commands_restricted_to_private(self):
        # Mock group chat update
        update = MagicMock()
        update.effective_chat.type = "group"
        update.effective_user.id = 123
        
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        
        # Test register
        await register(update, context)
        context.bot.send_message.assert_called() # Should try to DM
        # Ensure DB interaction didn't happen (mocking get_db to fail or checking call count)
        # We can just check that no registration was created if we had a DB.
        # But here we are using the real DB in memory.
        
        # Let's verify ensuring private prevents execution
        # We can check if get_db was called?
        # In this test setup, get_db returns a mock connection.
        # If ensure_private returns false, get_db is not called in the handler.
        
        # Reset mocks
        self.mock_get_db.reset_mock()
        context.bot.send_message.reset_mock()
        
        await register(update, context)
        self.mock_get_db.assert_not_called()
        context.bot.send_message.assert_called()

        self.mock_get_db.reset_mock()
        await unregister(update, context)
        self.mock_get_db.assert_not_called()

        self.mock_get_db.reset_mock()
        await status(update, context)
        self.mock_get_db.assert_not_called()
        
        self.mock_get_db.reset_mock()
        await invite_guest(update, context)
        self.mock_get_db.assert_not_called()

if __name__ == '__main__':
    unittest.main()
