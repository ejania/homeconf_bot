import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from models import init_db
from bot import open_event_command, create_event, reset_event, invite_guest, unregister

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

class TestStateLogging(unittest.IsolatedAsyncioTestCase):
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
                registration_duration_hours INTEGER,
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

        # Add admin
        patch_admin = patch('bot.ADMIN_IDS', {111})
        self.mock_admin = patch_admin.start()
        self.addCleanup(patch_admin.stop)

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_logs_created_on_state_change(self):
        update = MagicMock()
        update.effective_user.id = 111
        update.effective_user.username = "admin_user"
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["1", "10", "@speakers"]
        context.bot.get_chat = AsyncMock()
        context.bot.get_chat.return_value.id = 999
        context.bot.get_chat.return_value.title = "Speakers"

        # 1. Test create_event logs
        await create_event(update, context)
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT * FROM action_logs WHERE action = 'CREATE_EVENT'")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['username'], "admin_user")
        self.assertEqual(logs[0]['action'], "CREATE_EVENT")

        # 2. Test open_event logs
        # Need to mock scheduler
        with patch('bot.scheduler') as mock_scheduler:
            await open_event_command(update, context)
            
        cursor.execute("SELECT * FROM action_logs WHERE action = 'OPEN_EVENT'")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['action'], "OPEN_EVENT")

        # 3. Test reset_event logs
        context.args = ["confirm"]
        with patch('bot.scheduler') as mock_scheduler:
            await reset_event(update, context)
        
        cursor.execute("SELECT * FROM action_logs WHERE action = 'RESET_EVENT'")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['action'], "RESET_EVENT")

    async def test_invite_guest_logs(self):
        # Setup: Create event and speaker
        cursor = self.real_conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS speakers (id INTEGER PRIMARY KEY, event_id INTEGER, username TEXT, FOREIGN KEY (event_id) REFERENCES events (id))''') # Ensure table exists
        cursor.execute("INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, 'group')")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, "speaker"))
        self.real_conn.commit()

        update = MagicMock()
        update.effective_user.id = 888
        update.effective_user.username = "speaker"
        update.effective_chat.type = "private"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["guest_user"]
        context.bot.get_chat_member = AsyncMock() 

        # Ensure ensure_private returns True (it's called in invite_guest)
        # but mock only works if we patch it or pass context
        # Actually invite_guest checks update.effective_chat.type which we set to 'private'
        
        # Test invite_guest
        await invite_guest(update, context)
        
        cursor.execute("SELECT * FROM action_logs WHERE action = 'INVITE_GUEST'")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['details'], "Guest: guest_user")

    async def test_unregister_logs(self):
         # Setup: Create event and registration
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, 'REGISTERED')", (event_id, 777))
        reg_id = cursor.lastrowid
        self.real_conn.commit()
        
        update = MagicMock()
        update.effective_user.id = 777
        update.effective_user.username = "user777"
        update.effective_chat.type = "private"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        # Mock get_chat_member to avoid error
        context.bot.get_chat_member = AsyncMock()

        await unregister(update, context)
        
        cursor.execute("SELECT * FROM action_logs WHERE action = 'UNREGISTER'")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        # Note: unregister creates a log, and details might contain "Old status: ..." if checking old_status
        # In current unregister impl: log_action(..., 'UNREGISTER', f'Old status: {old_status}')
        self.assertIn("Old status: REGISTERED", logs[0]['details'])

if __name__ == '__main__':
    unittest.main()
