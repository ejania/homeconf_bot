import unittest
import sqlite3
from datetime import timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import bot
from bot import (
    start, raffle_command, raffle_open_command, raffle_draw_command,
    raffle_status_command, raffle_text_message, _seat_raffle_winners, get_now,
)
import messages

ADMIN_ID = 1
ATTENDEE_ID = 100
SPEAKER_ID = 200
STRANGER_ID = 300


class MockConnection:
    def __init__(self, real_conn):
        self.real_conn = real_conn

    def cursor(self):
        return self.real_conn.cursor()

    def commit(self):
        self.real_conn.commit()

    def close(self):
        pass


def make_update(user_id, username="user", chat_type="private"):
    update = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_chat.id = user_id
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.first_name = f"Name{user_id}"
    update.message.reply_text = AsyncMock()
    return update


def make_context(args=None):
    context = MagicMock()
    context.args = args or []
    context.bot.username = "testbot"
    context.bot.send_message = AsyncMock()
    # Nobody is in the speakers group unless a test says otherwise
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="left"))
    return context


class TestRaffle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        self.real_conn = sqlite3.connect(":memory:")
        self.real_conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = MockConnection(self.real_conn)

        self.admin_patcher = patch('bot.ADMIN_IDS', {ADMIN_ID})
        self.admin_patcher.start()

        cursor = self.real_conn.cursor()
        cursor.execute('''CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, status TEXT, total_places INTEGER,
            speakers_group_id TEXT, waitlist_timeout_hours INTEGER, end_time DATETIME, event_start_time DATETIME,
            registration_duration_hours INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            raffle_token TEXT, raffle_deadline DATETIME)''')
        cursor.execute('''CREATE TABLE registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, chat_id INTEGER,
            username TEXT, first_name TEXT, status TEXT, signup_time DATETIME, priority INTEGER,
            notified_at DATETIME, expires_at DATETIME, guest_of_user_id INTEGER, invite_token TEXT, partner_reg_id INTEGER)''')
        cursor.execute('''CREATE TABLE speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, username TEXT, first_name TEXT, user_id INTEGER)''')
        cursor.execute('''CREATE TABLE action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER, username TEXT, first_name TEXT, action TEXT, details TEXT)''')
        cursor.execute('''CREATE TABLE raffle_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE (event_id, user_id))''')
        cursor.execute('''CREATE TABLE raffle_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT,
            drawn_at DATETIME DEFAULT CURRENT_TIMESTAMP, claimed_event_id INTEGER, burned INTEGER DEFAULT 0)''')

        # A finished event with one attendee and one speaker, raffle already open
        self.deadline = (get_now() + timedelta(days=7)).isoformat()
        cursor.execute("INSERT INTO events (id, chat_id, status, speakers_group_id, raffle_token, raffle_deadline, created_at) VALUES (10, 1, 'CLOSED', '-100', 'tok10', ?, '2026-01-01')", (self.deadline,))
        cursor.execute("INSERT INTO registrations (event_id, user_id, username, status) VALUES (10, ?, 'attendee', 'ACCEPTED')", (ATTENDEE_ID,))
        cursor.execute("INSERT INTO speakers (event_id, username, user_id) VALUES (10, 'speaker', ?)", (SPEAKER_ID,))
        self.real_conn.commit()

    def tearDown(self):
        self.patcher.stop()
        self.admin_patcher.stop()
        self.real_conn.close()

    def entries(self):
        return [r['user_id'] for r in self.real_conn.execute("SELECT user_id FROM raffle_entries WHERE event_id = 10 ORDER BY id")]

    # --- joining ---

    async def test_attendee_joins_via_start_link(self):
        update = make_update(ATTENDEE_ID, "attendee")
        await start(update, make_context(["fb_tok10"]))
        self.assertEqual(self.entries(), [ATTENDEE_ID])
        self.assertIn("Ты в розыгрыше", update.message.reply_text.call_args[0][0])

    async def test_attendee_joins_via_prefilled_text(self):
        update = make_update(ATTENDEE_ID, "attendee")
        update.message.text = "Розыгрыш tok10"
        await raffle_text_message(update, make_context())
        self.assertEqual(self.entries(), [ATTENDEE_ID])

    async def test_unrelated_text_ignored(self):
        update = make_update(ATTENDEE_ID, "attendee")
        update.message.text = "привет, розыгрыш когда?"
        await raffle_text_message(update, make_context())
        self.assertEqual(self.entries(), [])
        update.message.reply_text.assert_not_called()

    async def test_speaker_joins_via_raffle_command(self):
        update = make_update(SPEAKER_ID, "speaker")
        await raffle_command(update, make_context(["tok10"]))
        self.assertEqual(self.entries(), [SPEAKER_ID])

    async def test_stranger_cannot_join(self):
        update = make_update(STRANGER_ID, "stranger")
        await raffle_command(update, make_context(["tok10"]))
        self.assertEqual(self.entries(), [])
        update.message.reply_text.assert_called_with(messages.RAFFLE_NOT_ATTENDEE)

    async def test_join_twice_keeps_one_entry(self):
        update = make_update(ATTENDEE_ID, "attendee")
        await raffle_command(update, make_context(["tok10"]))
        await raffle_command(update, make_context(["tok10"]))
        self.assertEqual(self.entries(), [ATTENDEE_ID])
        update.message.reply_text.assert_called_with(messages.RAFFLE_ALREADY_JOINED)

    async def test_bad_token_rejected(self):
        update = make_update(ATTENDEE_ID, "attendee")
        await raffle_command(update, make_context(["nope"]))
        self.assertEqual(self.entries(), [])
        update.message.reply_text.assert_called_with(messages.RAFFLE_BAD_TOKEN)

    async def test_join_after_deadline_rejected(self):
        past = (get_now() - timedelta(hours=1)).isoformat()
        self.real_conn.execute("UPDATE events SET raffle_deadline = ? WHERE id = 10", (past,))
        self.real_conn.commit()
        update = make_update(ATTENDEE_ID, "attendee")
        await raffle_command(update, make_context(["tok10"]))
        self.assertEqual(self.entries(), [])
        update.message.reply_text.assert_called_with(messages.RAFFLE_CLOSED)

    async def test_raffle_without_args_shows_user_status(self):
        update = make_update(ATTENDEE_ID, "attendee")
        await raffle_command(update, make_context())
        update.message.reply_text.assert_called_with(messages.RAFFLE_STATUS_USER_OUT)
        await raffle_command(update, make_context(["tok10"]))
        await raffle_command(update, make_context())
        self.assertIn("Ты в розыгрыше", update.message.reply_text.call_args[0][0])

    # --- admin: open ---

    async def test_raffle_open_creates_token_and_week_deadline(self):
        self.real_conn.execute("UPDATE events SET raffle_token = NULL, raffle_deadline = NULL WHERE id = 10")
        self.real_conn.commit()
        update = make_update(ADMIN_ID, "admin")
        await raffle_open_command(update, make_context())
        event = self.real_conn.execute("SELECT * FROM events WHERE id = 10").fetchone()
        self.assertEqual(len(event['raffle_token']), 8)
        deadline = bot.datetime.fromisoformat(event['raffle_deadline'])
        self.assertAlmostEqual((deadline - get_now()).total_seconds(), 7 * 86400, delta=60)
        self.assertIn("https://t.me/testbot?text=", update.message.reply_text.call_args[0][0])
        self.assertIn(f"/raffle {event['raffle_token']}", update.message.reply_text.call_args[0][0])

    async def test_raffle_open_again_keeps_token(self):
        update = make_update(ADMIN_ID, "admin")
        await raffle_open_command(update, make_context())
        event = self.real_conn.execute("SELECT raffle_token FROM events WHERE id = 10").fetchone()
        self.assertEqual(event['raffle_token'], 'tok10')

    async def test_raffle_open_requires_admin(self):
        update = make_update(ATTENDEE_ID, "attendee")
        await raffle_open_command(update, make_context())
        update.message.reply_text.assert_called_with(messages.ONLY_ADMIN_OPEN)

    # --- admin: draw ---

    async def _fill_entries(self, user_ids):
        for uid in user_ids:
            self.real_conn.execute("INSERT INTO raffle_entries (event_id, user_id, username, first_name) VALUES (10, ?, ?, ?)", (uid, f"u{uid}", f"N{uid}"))
        self.real_conn.commit()

    async def test_draw_picks_requested_number_and_notifies(self):
        await self._fill_entries([101, 102, 103, 104])
        context = make_context(["2"])
        with patch('bot._report_send_failures', new=AsyncMock()):
            await raffle_draw_command(make_update(ADMIN_ID, "admin"), context)
        winners = [r['user_id'] for r in self.real_conn.execute("SELECT user_id FROM raffle_winners WHERE event_id = 10")]
        self.assertEqual(len(winners), 2)
        self.assertTrue(set(winners) <= {101, 102, 103, 104})
        notified = sorted(c[0][0] for c in context.bot.send_message.call_args_list)
        self.assertEqual(notified, sorted(winners))

    async def test_second_draw_excludes_previous_winners(self):
        await self._fill_entries([101, 102, 103])
        with patch('bot._report_send_failures', new=AsyncMock()):
            await raffle_draw_command(make_update(ADMIN_ID, "admin"), make_context(["2"]))
            await raffle_draw_command(make_update(ADMIN_ID, "admin"), make_context(["5"]))
        winners = [r['user_id'] for r in self.real_conn.execute("SELECT user_id FROM raffle_winners WHERE event_id = 10")]
        self.assertEqual(sorted(winners), [101, 102, 103])

    async def test_draw_requires_count(self):
        update = make_update(ADMIN_ID, "admin")
        await raffle_draw_command(update, make_context())
        update.message.reply_text.assert_called_with(messages.RAFFLE_DRAW_USAGE)

    async def test_status_shows_entries_and_winners(self):
        await self._fill_entries([101, 102])
        self.real_conn.execute("INSERT INTO raffle_winners (event_id, user_id, username, first_name) VALUES (10, 101, 'u101', 'N101')")
        self.real_conn.commit()
        update = make_update(ADMIN_ID, "admin")
        await raffle_status_command(update, make_context())
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Билетов: 2", text)
        self.assertIn("@u101", text)

    # --- prize: seating at the next event ---

    async def test_winner_gets_guaranteed_spot_at_next_event(self):
        self.real_conn.execute("INSERT INTO raffle_winners (event_id, user_id, username, first_name) VALUES (10, 101, 'u101', 'N101')")
        self.real_conn.execute("INSERT INTO events (id, chat_id, status, speakers_group_id, created_at) VALUES (11, 1, 'PRE_OPEN', '-200', '2026-06-01')")
        self.real_conn.commit()
        context = make_context()
        lines = await _seat_raffle_winners(11, ADMIN_ID, context)
        reg = self.real_conn.execute("SELECT * FROM registrations WHERE event_id = 11 AND user_id = 101").fetchone()
        self.assertIsNotNone(reg)
        self.assertEqual(reg['status'], 'ACCEPTED')
        self.assertEqual(reg['guest_of_user_id'], ADMIN_ID)
        winner = self.real_conn.execute("SELECT * FROM raffle_winners WHERE user_id = 101").fetchone()
        self.assertEqual(winner['claimed_event_id'], 11)
        self.assertEqual(winner['burned'], 0)
        context.bot.send_message.assert_called_with(101, messages.RAFFLE_SEATED)
        self.assertEqual(lines, [messages.RAFFLE_SEATED_LINE_OK.format(name="@u101")])

    async def test_winner_who_speaks_next_time_loses_prize(self):
        self.real_conn.execute("INSERT INTO raffle_winners (event_id, user_id, username, first_name) VALUES (10, 101, 'u101', 'N101')")
        self.real_conn.execute("INSERT INTO events (id, chat_id, status, speakers_group_id, created_at) VALUES (11, 1, 'PRE_OPEN', '-200', '2026-06-01')")
        self.real_conn.execute("INSERT INTO speakers (event_id, username, user_id) VALUES (11, 'u101', 101)")
        self.real_conn.commit()
        context = make_context()
        lines = await _seat_raffle_winners(11, ADMIN_ID, context)
        self.assertIsNone(self.real_conn.execute("SELECT id FROM registrations WHERE event_id = 11 AND user_id = 101").fetchone())
        winner = self.real_conn.execute("SELECT * FROM raffle_winners WHERE user_id = 101").fetchone()
        self.assertEqual(winner['burned'], 1)
        self.assertEqual(winner['claimed_event_id'], 11)
        context.bot.send_message.assert_not_called()
        self.assertEqual(lines, [messages.RAFFLE_SEATED_LINE_SPEAKER.format(name="@u101")])

    async def test_claimed_winner_not_seated_twice(self):
        self.real_conn.execute("INSERT INTO raffle_winners (event_id, user_id, username, first_name, claimed_event_id) VALUES (10, 101, 'u101', 'N101', 11)")
        self.real_conn.execute("INSERT INTO events (id, chat_id, status, speakers_group_id, created_at) VALUES (12, 1, 'PRE_OPEN', '-300', '2026-09-01')")
        self.real_conn.commit()
        lines = await _seat_raffle_winners(12, ADMIN_ID, make_context())
        self.assertEqual(lines, [])
        self.assertIsNone(self.real_conn.execute("SELECT id FROM registrations WHERE event_id = 12").fetchone())


if __name__ == '__main__':
    unittest.main()
