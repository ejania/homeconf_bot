import unittest
import sqlite3
from unittest.mock import MagicMock, AsyncMock, patch
from bot import who
import messages


class MockConnection:
    def __init__(self, real_conn):
        self.real_conn = real_conn

    def cursor(self):
        return self.real_conn.cursor()

    def commit(self):
        self.real_conn.commit()

    def close(self):
        pass


class TestWhoCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()

        self.real_conn = sqlite3.connect(":memory:")
        self.real_conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = MockConnection(self.real_conn)

        cursor = self.real_conn.cursor()
        cursor.execute('''
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                status TEXT,
                total_places INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                status TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE speakers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                username TEXT,
                first_name TEXT
            )
        ''')
        self.real_conn.commit()

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    def _make_update(self):
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 1
        update.message.reply_text = AsyncMock()
        return update

    async def test_no_event_returns_no_event_message(self):
        update = self._make_update()
        await who(update, MagicMock())
        update.message.reply_text.assert_called_with(messages.WHO_NO_EVENT)

    async def test_cancelled_event_returns_no_event_message(self):
        self.real_conn.execute("INSERT INTO events (status) VALUES ('CANCELLED')")
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        update.message.reply_text.assert_called_with(messages.WHO_NO_EVENT)

    async def test_pre_open_returns_not_ready(self):
        self.real_conn.execute("INSERT INTO events (status) VALUES ('PRE_OPEN')")
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        update.message.reply_text.assert_called_with(messages.WHO_NOT_READY)

    async def test_open_returns_not_ready(self):
        self.real_conn.execute("INSERT INTO events (status) VALUES ('OPEN')")
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        update.message.reply_text.assert_called_with(messages.WHO_NOT_READY)

    async def test_review_returns_not_ready(self):
        self.real_conn.execute("INSERT INTO events (status) VALUES ('REVIEW')")
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        update.message.reply_text.assert_called_with(messages.WHO_NOT_READY)

    async def test_closed_event_lists_speakers_and_attendees(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        eid = cursor.lastrowid
        cursor.executemany(
            "INSERT INTO speakers (event_id, username, first_name) VALUES (?, ?, ?)",
            [(eid, 'zara_speaker', None), (eid, 'alice_speaker', None)],
        )
        cursor.executemany(
            "INSERT INTO registrations (event_id, username, first_name, status) VALUES (?, ?, ?, ?)",
            [
                (eid, 'frank', 'Frank', 'ACCEPTED'),
                (eid, None, 'Боб', 'ACCEPTED'),
                (eid, 'eve', None, 'ACCEPTED'),
                (eid, 'unreg', None, 'UNREGISTERED'),
                (eid, 'wait', None, 'WAITLIST'),
            ],
        )
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())

        call_args = update.message.reply_text.call_args
        msg = call_args[0][0]
        self.assertEqual(call_args[1].get('parse_mode'), 'HTML')
        self.assertIn(messages.WHO_HEADER, msg)
        self.assertIn("@alice_speaker", msg)
        self.assertIn("@zara_speaker", msg)
        self.assertLess(msg.index("@alice_speaker"), msg.index("@zara_speaker"))
        self.assertIn("@eve", msg)
        self.assertIn("@frank", msg)
        self.assertIn("Боб", msg)
        self.assertNotIn("unreg", msg)
        self.assertNotIn("wait", msg)
        self.assertLess(msg.index("Докладчики"), msg.index("Слушатели"))

    async def test_closed_event_no_attendees_shows_empty_message(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        eid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO speakers (event_id, username, first_name) VALUES (?, ?, ?)",
            (eid, 'lonely_speaker', None),
        )
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("@lonely_speaker", msg)
        self.assertIn(messages.WHO_EMPTY_ATTENDEES, msg)

    async def test_closed_event_no_speakers_skips_speaker_section(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        eid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status) VALUES (?, ?, ?)",
            (eid, 'lone_attendee', 'ACCEPTED'),
        )
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Докладчики", msg)
        self.assertIn("@lone_attendee", msg)

    async def test_organizers_appear_at_top_and_excluded_elsewhere(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        eid = cursor.lastrowid
        cursor.executemany(
            "INSERT INTO speakers (event_id, username, first_name) VALUES (?, ?, ?)",
            [
                (eid, 'ejania', 'Olya'),
                (eid, 'crassirostris', None),
                (eid, 'awarehouse', None),
                (eid, 'real_speaker', None),
            ],
        )
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status) VALUES (?, ?, ?)",
            (eid, 'ejania', 'ACCEPTED'),
        )
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status) VALUES (?, ?, ?)",
            (eid, 'real_attendee', 'ACCEPTED'),
        )
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        msg = update.message.reply_text.call_args[0][0]

        self.assertIn("Орги", msg)
        self.assertIn("@ejania", msg)
        self.assertIn("@crassirostris", msg)
        self.assertIn("@awarehouse", msg)
        # Each organizer username appears exactly once (only in Орги)
        self.assertEqual(msg.count("@ejania"), 1)
        self.assertEqual(msg.count("@crassirostris"), 1)
        self.assertEqual(msg.count("@awarehouse"), 1)
        # Real speaker and attendee still show
        self.assertIn("@real_speaker", msg)
        self.assertIn("@real_attendee", msg)
        # Order: Орги -> Докладчики -> Слушатели
        self.assertLess(msg.index("Орги"), msg.index("Докладчики"))
        self.assertLess(msg.index("Докладчики"), msg.index("Слушатели"))

    async def test_anonymous_fallback_when_no_username_or_first_name(self):
        cursor = self.real_conn.cursor()
        cursor.execute("INSERT INTO events (status) VALUES ('CLOSED')")
        eid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO registrations (event_id, username, first_name, status) VALUES (?, NULL, NULL, 'ACCEPTED')",
            (eid,),
        )
        self.real_conn.commit()

        update = self._make_update()
        await who(update, MagicMock())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("Аноним", msg)


if __name__ == '__main__':
    unittest.main()
