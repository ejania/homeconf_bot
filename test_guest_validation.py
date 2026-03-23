import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import sqlite3
import os

from bot import invite_guest, get_db
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
        pass # Do nothing

class TestGuestValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Use an in-memory database for isolation
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_conn = MockConnection(self.real_conn)
        
        # Patch get_db to return our test connection
        patcher_db = patch('bot.get_db', return_value=self.mock_conn)
        self.mock_get_db = patcher_db.start()
        self.addCleanup(patcher_db.stop)
        
        # Patch models.get_db just in case
        patcher_models_db = patch('models.get_db', return_value=self.mock_conn)
        self.mock_models_get_db = patcher_models_db.start()
        self.addCleanup(patcher_models_db.stop)

        # Initialize the database schema on the in-memory db
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
        
        # Setup common mocks
        self.update = MagicMock()
        self.context = MagicMock()
        self.update.effective_user.id = 123
        self.update.effective_user.username = "speaker_alice"
        self.update.effective_user.first_name = "Alice"
        self.update.effective_chat.id = 123
        self.update.message.reply_text = AsyncMock()
        
        # Mock ensure_private
        patcher = patch('bot.ensure_private', return_value=True)
        self.mock_ensure_private = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.real_conn.close()

    async def create_event(self):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES (?, ?, ?)",
            ('PRE_OPEN', 10, 'group_123')
        )
        event_id = cursor.lastrowid
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                username TEXT, first_name TEXT, action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        """)

        self.real_conn.commit()
        return event_id

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_self(self, mock_context):
        await self.create_event()
        
        self.context.args = ["speaker_alice"]
        self.update.effective_user.id = 101
        self.update.effective_user.username = "speaker_alice"
        
        # Mock group check - speaker is in group
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        await invite_guest(self.update, self.context)
        
        self.update.message.reply_text.assert_called_with(messages.ALREADY_SPEAKER)

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_other_speaker(self, mock_context):
        event_id = await self.create_event()
        
        # Add another speaker manually
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker_bob"))
        self.real_conn.commit()
        
        self.context.args = ["speaker_bob"]
        self.update.effective_user.id = 101
        self.update.effective_user.username = "speaker_alice"
        
        # Mock group check
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        await invite_guest(self.update, self.context)
        
        self.update.message.reply_text.assert_called_with(messages.GUEST_IS_SPEAKER.format(username="speaker_bob"))

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_already_guest(self, mock_context):
        event_id = await self.create_event()
        
        # Add a guest for Alice
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, "guest_charlie", "ACCEPTED", 101)
        )
        self.real_conn.commit()
        
        # Bob tries to invite Charlie
        self.context.args = ["guest_charlie"]
        self.update.effective_user.id = 102
        self.update.effective_user.username = "speaker_bob"
        self.update.effective_user.first_name = "speaker_bob_name"
        
        # Mock group check
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        await invite_guest(self.update, self.context)
        
        self.update.message.reply_text.assert_called_with(messages.GUEST_ALREADY_GUEST.format(username="guest_charlie"))

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_sanitizes_input(self, mock_context):
        event_id = await self.create_event()
        
        # Mock group check
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        # Test input with brackets and @
        self.context.args = ["<@guest_dan>"]
        self.update.effective_user.id = 103
        self.update.effective_user.username = "speaker_diana"
        self.update.effective_user.first_name = "speaker_diana_name"
        
        await invite_guest(self.update, self.context)
        
        # Check database
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT username FROM registrations WHERE event_id = ? AND guest_of_user_id = ?", (event_id, 103))
        reg = cursor.fetchone()
        
        
        self.assertIsNotNone(reg)
        self.assertEqual(reg['username'], "guest_dan")

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_accepts_with_and_without_at(self, mock_context):
        event_id = await self.create_event()
        
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock

        # Test with @
        self.context.args = ["@guest_with_at"]
        self.update.effective_user.id = 201
        self.update.effective_user.username = "speaker_201"
        await invite_guest(self.update, self.context)

        # Test without @
        self.context.args = ["guest_without_at"]
        self.update.effective_user.id = 202
        self.update.effective_user.username = "speaker_202"
        await invite_guest(self.update, self.context)
        
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT username FROM registrations WHERE event_id = ? AND guest_of_user_id = ?", (event_id, 201))
        reg1 = cursor.fetchone()
        cursor.execute("SELECT username FROM registrations WHERE event_id = ? AND guest_of_user_id = ?", (event_id, 202))
        reg2 = cursor.fetchone()
        
        
        self.assertIsNotNone(reg1)
        self.assertEqual(reg1['username'], "guest_with_at")
        self.assertIsNotNone(reg2)
        self.assertEqual(reg2['username'], "guest_without_at")

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_sanitizes_brackets_only(self, mock_context):
        event_id = await self.create_event()
        
        # Test input with brackets only
        self.context.args = ["<guest_eve>"]
        self.update.effective_user.id = 104
        self.update.effective_user.username = "speaker_edward"
        self.update.effective_user.first_name = "speaker_edward_name"
        
        # Mock group check
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        await invite_guest(self.update, self.context)
        
        # Check database
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT username FROM registrations WHERE event_id = ? AND guest_of_user_id = ?", (event_id, 104))
        reg = cursor.fetchone()
        
        
        self.assertIsNotNone(reg)
        self.assertEqual(reg['username'], "guest_eve")

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_invalid_format(self, mock_context):
        event_id = await self.create_event()
        
        # Test invalid inputs
        invalid_inputs = [
            ["some name"],
            ["my-guest"],
            ["$$$invalid"],
            ["only 123 letters"]
        ]
        
        self.update.effective_user.id = 105
        self.update.effective_user.username = "speaker_test"
        
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock

        for args in invalid_inputs:
            self.context.args = args
            await invite_guest(self.update, self.context)
            self.update.message.reply_text.assert_called_with(messages.INVALID_INVITE_FORMAT)

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_invite_phone_formats(self, mock_context):
        event_id = await self.create_event()
        
        # Test valid phone inputs
        valid_phones = [
            (["+1234567890"], "+1234567890"),
            (["+1", "(234)", "567-891"], "+1234567891"),
            (["8", "900", "123", "45", "67"], "89001234567"),
            (["00123456789"], "00123456789")
        ]
        
        self.update.effective_user.username = "speaker_phone"
        
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock

        user_id = 200
        for args, expected_db_val in valid_phones:
            self.update.effective_user.id = user_id
            self.context.args = args
            await invite_guest(self.update, self.context)
            
            # Should have generated a link
            args_called = self.update.message.reply_text.call_args[0][0]
            self.assertIn("https://t.me/", args_called)

            
            cursor = self.real_conn.cursor()
            cursor.execute("SELECT username FROM registrations WHERE event_id = ? AND guest_of_user_id = ?", (event_id, user_id))
            reg = cursor.fetchone()
            
            
            self.assertIsNotNone(reg)
            self.assertEqual(reg['username'], expected_db_val)
            user_id += 1

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_start_with_invite_token(self, mock_context):
        event_id = await self.create_event()
        
        
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id, invite_token) VALUES (?, ?, ?, ?, ?)",
            (event_id, "+1234567890", "ACCEPTED", 101, "my_secret_token")
        )
        self.real_conn.commit()
        

        from bot import start
        self.context.args = ["my_secret_token"]
        self.update.effective_user.id = 500
        self.update.effective_user.first_name = "Guest User"
        self.update.effective_user.username = "guest_username"
        self.update.effective_chat.id = 500

        await start(self.update, self.context)

        self.update.message.reply_text.assert_called_with(f"{messages.GUEST_IDENTIFIED}\n\n{messages.WELCOME_MESSAGE}")

        conn = get_db()
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT * FROM registrations WHERE invite_token = ?", ("my_secret_token",))
        reg = cursor.fetchone()
        

        self.assertEqual(reg['user_id'], 500)
        self.assertEqual(reg['username'], "guest_username")

    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_start_token_already_used(self, mock_context):
        event_id = await self.create_event()
        
        
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id, invite_token, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, "+1234567890", "ACCEPTED", 101, "used_token", 500)
        )
        self.real_conn.commit()
        

        from bot import start
        self.context.args = ["used_token"]
        self.update.effective_user.id = 600

        await start(self.update, self.context)

        self.update.message.reply_text.assert_called_with(messages.GUEST_LINK_USED)

if __name__ == '__main__':
    unittest.main()
