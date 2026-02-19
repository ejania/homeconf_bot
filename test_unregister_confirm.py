import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import unregister, callback_handler
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

class TestUnregisterConfirm(unittest.IsolatedAsyncioTestCase):
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
                registration_duration_hours INTEGER,
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
        cursor.execute("CREATE TABLE IF NOT EXISTS action_logs (id INTEGER PRIMARY KEY, event_id INTEGER, user_id INTEGER, username TEXT, action TEXT, details TEXT)")
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    async def test_unregister_closed_requires_confirm(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 10)")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)", (event_id, 111, 'ACCEPTED'))
        reg_id = cursor.lastrowid
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.effective_user.username = "testuser"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await unregister(update, context)

        # Check that status is STILL ACCEPTED
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')

        # Check that reply_text was called with confirmation
        update.message.reply_text.assert_called_with(
            messages.UNREGISTER_CONFIRM,
            reply_markup=unittest.mock.ANY
        )

    async def test_callback_uyes_unregisters(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('CLOSED', 10)")
        event_id = cursor.lastrowid
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, ?, ?)", (event_id, 222, 'ACCEPTED'))
        reg_id = cursor.lastrowid
        self.real_conn.commit()

        update = MagicMock()
        update.effective_user.id = 222
        update.callback_query = MagicMock()
        update.callback_query.data = f"uyes_{reg_id}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        
        with patch('bot.scheduler') as mock_sched:
            await callback_handler(update, context)

        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'UNREGISTERED')

if __name__ == '__main__':
    unittest.main()
