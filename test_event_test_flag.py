import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import os

os.environ["DB_PATH"] = ":memory:"

from bot import create_event, get_db
import messages

class TestEventTestFlag(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.real_conn = sqlite3.connect(":memory:")
        self.real_conn.row_factory = sqlite3.Row
        
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

        class MockConnection:
            def __init__(self, conn):
                self.conn = conn
            def cursor(self):
                return self.conn.cursor()
            def commit(self):
                self.conn.commit()
            def close(self):
                pass
        
        self.mock_conn = MockConnection(self.real_conn)
        
        patcher = patch('bot.get_db', return_value=self.mock_conn)
        self.mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)
        
        patcher_admin = patch('bot.is_admin', return_value=True)
        self.mock_is_admin = patcher_admin.start()
        self.addCleanup(patcher_admin.stop)

    def tearDown(self):
        self.real_conn.close()

    async def test_create_test_event_uses_negative_id(self):
        update = MagicMock()
        context = MagicMock()
        context.args = ["test", "888"]
        update.effective_chat.id = 100
        update.message.reply_text = AsyncMock()
        
        chat_mock = MagicMock()
        chat_mock.id = 888
        chat_mock.title = "Test Group"
        context.bot.get_chat = AsyncMock(return_value=chat_mock)
        
        with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b'', b''))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            await create_event(update, context)
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT id FROM events")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], -1)

    async def test_create_real_event_cleans_up_test_events(self):
        cursor = self.real_conn.cursor()
        # Pre-insert test event
        cursor.execute("INSERT INTO events (id, status) VALUES (-1, 'PRE_OPEN')")
        cursor.execute("INSERT INTO registrations (event_id, username) VALUES (-1, 'test_user')")
        self.real_conn.commit()
        
        update = MagicMock()
        context = MagicMock()
        context.args = ["888"] # Real event
        update.effective_chat.id = 100
        update.message.reply_text = AsyncMock()
        
        chat_mock = MagicMock()
        chat_mock.id = 888
        chat_mock.title = "Real Group"
        context.bot.get_chat = AsyncMock(return_value=chat_mock)
        
        with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b'', b''))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            await create_event(update, context)
            
        cursor = self.real_conn.cursor()
        # Verify test event is gone
        cursor.execute("SELECT COUNT(*) as count FROM events WHERE id < 0")
        self.assertEqual(cursor.fetchone()['count'], 0)
        # Verify real event is created
        cursor.execute("SELECT COUNT(*) as count FROM events WHERE id > 0")
        self.assertEqual(cursor.fetchone()['count'], 1)
        # Verify registrations for test event are gone
        cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = -1")
        self.assertEqual(cursor.fetchone()['count'], 0)

if __name__ == '__main__':
    unittest.main()
