import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import os

os.environ["DB_PATH"] = ":memory:"

from bot import invite_guest, get_db
import messages

class TestAutoUpdateTotalPlaces(unittest.IsolatedAsyncioTestCase):
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

        self.update = MagicMock()
        self.context = MagicMock()
        self.update.effective_user.id = 100
        self.update.effective_user.username = "speaker_x"
        self.update.effective_user.first_name = "SpeakerX"
        self.update.effective_chat.id = 100
        self.update.message.reply_text = AsyncMock()

        self.context.bot.get_chat_member = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        self.context.bot.get_chat_member.return_value = member_mock

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
        
        patcher_ep = patch('bot.ensure_private', return_value=True)
        self.mock_ensure_private = patcher_ep.start()
        self.addCleanup(patcher_ep.stop)

    def tearDown(self):
        self.real_conn.close()

    async def create_event(self, initial_places=10):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES (?, ?, ?)",
            ('PRE_OPEN', initial_places, 'group_id')
        )
        self.real_conn.commit()
        return cursor.lastrowid

    async def test_invite_new_guest_increases_total_places(self):
        event_id = await self.create_event(initial_places=50)
        
        self.context.args = ["new_guest"]
        await invite_guest(self.update, self.context)
        
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT total_places FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        
        self.assertEqual(event['total_places'], 51)

    async def test_upgrade_existing_user_increases_total_places(self):
        event_id = await self.create_event(initial_places=50)
        
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, ?, ?, 'REGISTERED')",
            (event_id, 200, 'existing_user')
        )
        self.real_conn.commit()
        
        self.context.args = ["existing_user"]
        await invite_guest(self.update, self.context)
        
        cursor.execute("SELECT total_places FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        
        self.assertEqual(event['total_places'], 51)

    async def test_replacing_guest_does_not_increase_total_places(self):
        event_id = await self.create_event(initial_places=50)
        
        # Insert a guest of someone else
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, 'ACCEPTED', ?)",
            (event_id, 'another_guest', 999) # 999 is different from self.update.effective_user.id (100)
        )
        # This speaker already invited someone
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id) VALUES (?, ?, 'ACCEPTED', ?)",
            (event_id, 'old_guest', 100) 
        )
        # We manually update total places to reflect past insertions
        cursor.execute("UPDATE events SET total_places = 52 WHERE id = ?", (event_id,))
        self.real_conn.commit()
        
        self.context.args = ["brand_new_guest"]
        await invite_guest(self.update, self.context)
        
        cursor.execute("SELECT total_places FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        
        # Since speaker 100 already had a guest, they replace 'old_guest' with 'brand_new_guest'. 
        # Total places shouldn't increase because the spot was already accounted for.
        self.assertEqual(event['total_places'], 52)


if __name__ == '__main__':
    unittest.main()
