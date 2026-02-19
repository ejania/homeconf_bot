import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import sqlite3
import os

# Set dummy DB path for tests
os.environ["DB_PATH"] = "test_bot.db"
from bot import invite_guest, get_db
import messages

class TestGuestValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Clear DB before each test
        if os.path.exists("test_bot.db"):
            os.remove("test_bot.db")
        
        from models import init_db
        init_db()
        
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

    async def create_event(self):
        conn = get_db()
        cursor = conn.cursor()
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
                username TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        """)

        conn.commit()
        conn.close()
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
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker_bob"))
        conn.commit()
        conn.close()
        
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
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, ?, ?)",
            (event_id, "guest_charlie", "ACCEPTED", 101)
        )
        conn.commit()
        conn.close()
        
        # Bob tries to invite Charlie
        self.context.args = ["guest_charlie"]
        self.update.effective_user.id = 102
        self.update.effective_user.username = "speaker_bob"
        
        # Mock group check
        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock
        
        await invite_guest(self.update, self.context)
        
        self.update.message.reply_text.assert_called_with(messages.GUEST_ALREADY_GUEST.format(username="guest_charlie"))

if __name__ == '__main__':
    unittest.main()
