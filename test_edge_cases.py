import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from bot import close_registration_job, invite_guest, register
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

class TestEdgeCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_conn = MockConnection(self.real_conn)
        self.mock_get_db.return_value = self.mock_conn
        
        # Init Schema
        cursor = self.real_conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, status TEXT, 
            total_places INTEGER, speakers_group_id TEXT, waitlist_timeout_hours INTEGER, 
            end_time DATETIME, registration_duration_hours INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, 
            chat_id INTEGER, username TEXT, first_name TEXT, status TEXT, 
            signup_time DATETIME, priority INTEGER, notified_at DATETIME, 
            expires_at DATETIME, guest_of_user_id INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, username TEXT)''')
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
        
        # Common Mocks
        self.app_patcher = patch('bot.application')
        self.mock_app = self.app_patcher.start()
        self.mock_app.bot.send_message = AsyncMock()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()
        self.app_patcher.stop()

    async def test_double_dipping_speaker(self):
        """Ensure a speaker who is also in the lottery pool doesn't consume a lottery spot."""
        # 1. Setup Event: 2 places total.
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places, speakers_group_id) VALUES ('OPEN', 2, 'group_1')")
        event_id = cursor.lastrowid

        # 2. Setup Users
        # User 1: The Speaker (who also registered)
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 101, 'REGISTERED')", (event_id,))
        # User 2: Regular User
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (?, 102, 'REGISTERED')", (event_id,))
        self.real_conn.commit()

        # 3. Mock Speaker Group
        # The group has 2 members: Bot + User 101
        self.mock_app.bot.get_chat_member_count = AsyncMock(return_value=2)
        
        # Mock get_me (Bot ID 999)
        mock_bot_user = MagicMock()
        mock_bot_user.id = 999
        self.mock_app.bot.get_me = AsyncMock(return_value=mock_bot_user)

        # Mock membership checks
        async def mock_get_chat_member(chat_id, user_id):
            member = MagicMock()
            if user_id == 999: # Bot
                member.status = "administrator"
            elif user_id == 101: # The Speaker
                member.status = "member"
            else:
                member.status = "left"
            return member
        self.mock_app.bot.get_chat_member = AsyncMock(side_effect=mock_get_chat_member)

        # 4. Run Lottery
        # Logic expectation: 
        # Total Places = 2
        # Speakers = 1 (User 101)
        # Available for Lottery = 1
        # Pool = [User 101, User 102]
        # User 101 should be EXCLUDED from pool because they are a speaker.
        # User 102 should win the single spot.
        
        await close_registration_job(event_id, 12345)

        # 5. Verify Results
        cursor.execute("SELECT user_id, status FROM registrations")
        rows = {row['user_id']: row['status'] for row in cursor.fetchall()}
        
        # Check that User 102 won the lottery
        self.assertEqual(rows[102], 'ACCEPTED', "User 102 should have won the single available lottery spot")
        
        # Check that User 101 (Speaker) was NOT processed in the lottery or is handled correctly.
        # Current Implementation Bug Hypothesis: User 101 might win the lottery, meaning 2 spots taken (1 speaker + 1 lottery)
        # Ideally, we want User 101 to NOT use a lottery spot if they are a speaker.
        # If the bug exists, User 101 might be ACCEPTED and User 102 WAITLISTED/LOST (if shuffled that way).
        # We need to ensure logic handles this.
        
        # For this test to pass with strict logic, User 102 MUST be accepted. 
        # If User 101 is accepted via lottery, we have a double-dipping bug.

    async def test_reclaimed_invite(self):
        """Test that a speaker can invite a new guest if the previous one unregistered."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, 'group_1')")
        event_id = cursor.lastrowid
        
        # Speaker 555 invites Guest A (User 777) who then Unregisters
        cursor.execute("""
            INSERT INTO registrations (event_id, user_id, status, guest_of_user_id) 
            VALUES (?, 777, 'UNREGISTERED', 555)
        """, (event_id,))
        self.real_conn.commit()

        # Mock Update/Context for inviting Guest B
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 555
        update.effective_user.username = "SpeakerBob"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["@GuestB"]
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member")) # Speaker check

        # Execute Invite
        await invite_guest(update, context)

        # Verify Success
        update.message.reply_text.assert_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("GuestB", msg)
        self.assertNotIn("уже позвал", msg)

    async def test_case_insensitive_username(self):
        """Test that @Guest matches @guest."""
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status, total_places, speakers_group_id) VALUES ('PRE_OPEN', 10, 'group_1')")
        event_id = cursor.lastrowid
        
        # User registers with CamelCase
        cursor.execute("""
            INSERT INTO registrations (event_id, username, status) 
            VALUES (?, 'CamelCaseUser', 'REGISTERED')
        """, (event_id,))
        self.real_conn.commit()

        # Speaker invites lowercase
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 555
        update.effective_user.username = "Speaker"
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()
        context.args = ["@camelcaseuser"] # lowercase input
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        context.bot.send_message = AsyncMock()

        await invite_guest(update, context)

        # Verify the existing registration was updated (upgraded to ACCEPTED)
        cursor.execute("SELECT status, guest_of_user_id FROM registrations WHERE username = 'CamelCaseUser'")
        row = cursor.fetchone()
        self.assertEqual(row['status'], 'ACCEPTED')
        self.assertEqual(row['guest_of_user_id'], 555)

if __name__ == '__main__':
    unittest.main()
