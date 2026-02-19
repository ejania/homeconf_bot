import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from bot import create_event
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

class TestGroupAccess(unittest.IsolatedAsyncioTestCase):
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

    async def test_create_aborts_on_group_access_error(self):
        update = MagicMock()
        update.effective_chat.id = 123
        update.effective_user.id = 999
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["2", "10", "invalid_group"]
        
        # Mock admin check
        with patch('bot.is_admin', return_value=True):
            # Mock get_chat raising an exception
            context.bot.get_chat.side_effect = Exception("Chat not found")
            
            await create_event(update, context)
            
            # Verify error message sent
            update.message.reply_text.assert_called_with(messages.ERROR_ACCESS_GROUP)
            
            # Verify NO event was created
            cursor = self.real_conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM events")
            self.assertEqual(cursor.fetchone()['cnt'], 0, "Event should not be created if group access fails")

    async def test_create_success_on_valid_group(self):
        update = MagicMock()
        update.effective_chat.id = 123
        update.effective_user.id = 999
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["2", "10", "valid_group"]
        
        with patch('bot.is_admin', return_value=True):
            # Mock success
            chat_mock = MagicMock()
            chat_mock.id = 888
            chat_mock.title = "Valid Group"
            context.bot.get_chat = AsyncMock(return_value=chat_mock)
            
            # Mock subprocess for import_speakers.py
            with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as mock_exec:
                mock_proc = MagicMock()
                mock_proc.communicate = AsyncMock(return_value=(b'Imported 10 speakers', b''))
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc
                
                await create_event(update, context)
            
            # Verify success message was sent at some point
            # Since multiple messages are sent, use assert_any_call or check call_args_list
            update.message.reply_text.assert_any_call(messages.EVENT_CREATED)
            
            # Verify event created
            cursor = self.real_conn.cursor()
            cursor.execute("SELECT * FROM events")
            event = cursor.fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(event['speakers_group_id'], "888")

if __name__ == '__main__':
    unittest.main()
