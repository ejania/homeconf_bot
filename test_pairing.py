import unittest
import sqlite3
import random
from unittest.mock import patch, MagicMock, AsyncMock
from bot import pair_command, callback_handler, close_registration_job, invite_next, unregister
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


def _setup_schema(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            status TEXT,
            total_places INTEGER,
            speakers_group_id TEXT,
            waitlist_timeout_hours INTEGER,
            end_time DATETIME,
            event_start_time DATETIME,
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
            partner_reg_id INTEGER,
            invite_token TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            username TEXT,
            first_name TEXT
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
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()


class _BaseCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()

        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_conn = MockConnection(self.real_conn)
        self.mock_get_db.return_value = self.mock_conn

        _setup_schema(self.real_conn)

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    def _add_event(self, status='OPEN', total_places=10, speakers_group_id=None):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, speakers_group_id) VALUES (?, ?, ?)",
            (status, total_places, speakers_group_id)
        )
        self.real_conn.commit()
        return cursor.lastrowid

    def _add_reg(self, event_id, user_id, username, status='REGISTERED', partner_reg_id=None, guest_of=None):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, first_name, status, partner_reg_id, guest_of_user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, user_id, username, username, status, partner_reg_id, guest_of)
        )
        self.real_conn.commit()
        return cursor.lastrowid


class TestPairCommand(_BaseCase):
    async def _call_pair(self, requester_id, requester_username, target_arg):
        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = requester_id
        update.effective_user.username = requester_username
        update.effective_user.first_name = requester_username
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = [target_arg]
        context.bot.send_message = AsyncMock()
        context.bot.get_chat_member = AsyncMock(side_effect=Exception("no group"))
        await pair_command(update, context)
        return update, context

    async def test_pair_happy_path(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        a_reg = self._add_reg(event_id, 111, 'alice_user')
        b_reg = self._add_reg(event_id, 222, 'bob_user')

        await self._call_pair(111, 'alice_user', '@bob_user')

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (a_reg,))
        self.assertIsNone(cursor.fetchone()['partner_reg_id'])  # not yet — needs confirm

        # Now bob confirms
        update = MagicMock()
        update.effective_user.id = 222
        update.effective_user.username = 'bob_user'
        update.callback_query = MagicMock()
        update.callback_query.data = f"pyes_{a_reg}_{b_reg}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        await callback_handler(update, context)

        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (a_reg,))
        self.assertEqual(cursor.fetchone()['partner_reg_id'], b_reg)
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (b_reg,))
        self.assertEqual(cursor.fetchone()['partner_reg_id'], a_reg)

    async def test_pair_decline_does_not_link(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        a_reg = self._add_reg(event_id, 111, 'alice_user')
        b_reg = self._add_reg(event_id, 222, 'bob_user')

        update = MagicMock()
        update.effective_user.id = 222
        update.callback_query = MagicMock()
        update.callback_query.data = f"pno_{a_reg}_{b_reg}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        await callback_handler(update, context)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT partner_reg_id FROM registrations WHERE id = ?", (a_reg,))
        self.assertIsNone(cursor.fetchone()['partner_reg_id'])

    async def test_pair_self(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        update, context = await self._call_pair(111, 'alice_user', '@alice_user')
        update.message.reply_text.assert_called_with(messages.PAIR_SELF)

    async def test_pair_target_not_registered(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        update, context = await self._call_pair(111, 'alice_user', '@ghost')
        update.message.reply_text.assert_called_with(messages.PAIR_PARTNER_NOT_FOUND.format(username='ghost'))

    async def test_pair_requester_not_registered(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 222, 'bob_user')
        update, context = await self._call_pair(111, 'alice_user', '@bob_user')
        update.message.reply_text.assert_called_with(messages.PAIR_NOT_REGISTERED)

    async def test_pair_already_paired(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        a_reg = self._add_reg(event_id, 111, 'alice_user')
        b_reg = self._add_reg(event_id, 222, 'bob_user', partner_reg_id=a_reg)
        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_reg, a_reg))
        self.real_conn.commit()

        self._add_reg(event_id, 333, 'carol_user')
        update, context = await self._call_pair(111, 'alice_user', '@carol_user')
        # Alice is already paired with bob
        called = update.message.reply_text.call_args[0][0]
        self.assertIn('bob_user', called)

    async def test_pair_target_already_paired(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        b_reg = self._add_reg(event_id, 222, 'bob_user')
        c_reg = self._add_reg(event_id, 333, 'carol_user', partner_reg_id=b_reg)
        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (c_reg, b_reg))
        self.real_conn.commit()

        update, context = await self._call_pair(111, 'alice_user', '@bob_user')
        update.message.reply_text.assert_called_with(messages.PAIR_PARTNER_ALREADY_PAIRED.format(username='bob_user'))

    async def test_pair_target_is_guest(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        # bob is a guest (guest_of_user_id set)
        self._add_reg(event_id, 222, 'bob_user', status='REGISTERED', guest_of=999)

        update, context = await self._call_pair(111, 'alice_user', '@bob_user')
        update.message.reply_text.assert_called_with(messages.PAIR_PARTNER_IS_GUEST.format(username='bob_user'))

    async def test_pair_when_closed(self):
        event_id = self._add_event(status='CLOSED', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        self._add_reg(event_id, 222, 'bob_user')
        update, context = await self._call_pair(111, 'alice_user', '@bob_user')
        update.message.reply_text.assert_called_with(messages.PAIR_NOT_OPEN)

    async def test_pair_invalid_username(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        self._add_reg(event_id, 111, 'alice_user')
        update, context = await self._call_pair(111, 'alice_user', '!!!')
        update.message.reply_text.assert_called_with(messages.PAIR_INVALID_USERNAME)

    async def test_pair_when_requester_is_speaker(self):
        """A speaker cannot initiate a pair request."""
        event_id = self._add_event(status='OPEN', total_places=10, speakers_group_id='grp_123')
        self._add_reg(event_id, 111, 'alice_speaker')
        self._add_reg(event_id, 222, 'bob_user')

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.effective_user.username = "alice_speaker"
        update.effective_user.first_name = "Alice"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ['@bob_user']
        context.bot.send_message = AsyncMock()

        async def mock_get_chat_member(chat_id, user_id):
            member = MagicMock()
            member.status = "member" if user_id == 111 else "left"
            return member

        context.bot.get_chat_member = AsyncMock(side_effect=mock_get_chat_member)

        await pair_command(update, context)

        update.message.reply_text.assert_called_with(messages.ALREADY_SPEAKER)

    async def test_pair_target_is_speaker(self):
        """A user cannot pair with a speaker (they have a guaranteed spot)."""
        event_id = self._add_event(status='OPEN', total_places=10, speakers_group_id='grp_123')
        self._add_reg(event_id, 111, 'alice_user')
        self._add_reg(event_id, 222, 'bob_speaker')

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.effective_user.username = "alice_user"
        update.effective_user.first_name = "Alice"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ['@bob_speaker']
        context.bot.send_message = AsyncMock()

        async def mock_get_chat_member(chat_id, user_id):
            member = MagicMock()
            member.status = "member" if user_id == 222 else "left"
            return member

        context.bot.get_chat_member = AsyncMock(side_effect=mock_get_chat_member)

        await pair_command(update, context)

        update.message.reply_text.assert_called_with(
            messages.PAIR_PARTNER_IS_SPEAKER.format(username='bob_speaker')
        )


class TestLotteryWithPairs(_BaseCase):
    async def test_pair_atomic_outcome(self):
        """Pair members are always both winners or both losers."""
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()

            for trial in range(20):
                cursor = self.real_conn.cursor()
                cursor.execute("DELETE FROM events")
                cursor.execute("DELETE FROM registrations")
                cursor.execute("DELETE FROM action_logs")
                self.real_conn.commit()

                event_id = self._add_event(status='OPEN', total_places=4)
                # 1 pair + 4 singles → 6 people, 4 seats
                a = self._add_reg(event_id, 1, 'a')
                b = self._add_reg(event_id, 2, 'b')
                cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b, a))
                cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a, b))
                for i in range(3, 7):
                    self._add_reg(event_id, i, f'u{i}')
                self.real_conn.commit()

                await close_registration_job(event_id, 999)

                cursor.execute("SELECT status FROM registrations WHERE id = ?", (a,))
                a_status = cursor.fetchone()['status']
                cursor.execute("SELECT status FROM registrations WHERE id = ?", (b,))
                b_status = cursor.fetchone()['status']
                self.assertEqual(a_status, b_status, f"Trial {trial}: pair split! a={a_status}, b={b_status}")

    async def test_pair_shared_waitlist_priority(self):
        """A waitlisted pair has the same priority on both members."""
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()

            event_id = self._add_event(status='OPEN', total_places=2)
            cursor = self.real_conn.cursor()
            # 1 pair + 4 singles → 6 people, 2 seats; pair will sometimes lose.
            # Force RNG so pair loses.
            a = self._add_reg(event_id, 1, 'a')
            b = self._add_reg(event_id, 2, 'b')
            cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b, a))
            cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a, b))
            for i in range(3, 7):
                self._add_reg(event_id, i, f'u{i}')
            self.real_conn.commit()

            # Try several seeds; at least one should put the pair on waitlist
            found = False
            for seed in range(50):
                cursor.execute("UPDATE registrations SET status = 'REGISTERED', priority = NULL")
                cursor.execute("UPDATE events SET status = 'OPEN' WHERE id = ?", (event_id,))
                self.real_conn.commit()
                random.seed(seed)
                await close_registration_job(event_id, 999)
                cursor.execute("SELECT status, priority FROM registrations WHERE id = ?", (a,))
                ar = cursor.fetchone()
                cursor.execute("SELECT status, priority FROM registrations WHERE id = ?", (b,))
                br = cursor.fetchone()
                if ar['status'] == 'WAITLIST' and br['status'] == 'WAITLIST':
                    self.assertEqual(ar['priority'], br['priority'])
                    found = True
                    break
            self.assertTrue(found, "Could not find a seed where the pair landed on waitlist")

    async def test_lottery_fairness_single_pair(self):
        """Monte Carlo: each individual P(win) ≈ M/N regardless of pairing."""
        with patch('bot.application') as mock_app:
            mock_app.bot.send_message = AsyncMock()

            # 1 pair + 8 singles, 5 seats out of 10 → fair P = 0.5 for everyone
            trials = 600
            wins = {i: 0 for i in range(1, 11)}

            for _ in range(trials):
                cursor = self.real_conn.cursor()
                cursor.execute("DELETE FROM events")
                cursor.execute("DELETE FROM registrations")
                cursor.execute("DELETE FROM action_logs")
                self.real_conn.commit()

                event_id = self._add_event(status='OPEN', total_places=5)
                a = self._add_reg(event_id, 1, 'a')
                b = self._add_reg(event_id, 2, 'b')
                cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b, a))
                cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a, b))
                for i in range(3, 11):
                    self._add_reg(event_id, i, f'u{i}')
                self.real_conn.commit()

                await close_registration_job(event_id, 999)

                cursor.execute("SELECT user_id FROM registrations WHERE event_id = ? AND status = 'ACCEPTED'", (event_id,))
                for row in cursor.fetchall():
                    wins[row['user_id']] += 1

            # Each individual should have win rate ≈ 0.5. With 600 trials, 99% of the
            # time the empirical rate falls in [0.44, 0.56] for true p=0.5.
            for user_id, count in wins.items():
                rate = count / trials
                self.assertGreater(rate, 0.4, f"user {user_id} win rate {rate} too low")
                self.assertLess(rate, 0.6, f"user {user_id} win rate {rate} too high")


class TestWaitlistPairAtomicity(_BaseCase):
    async def test_pair_at_head_holds_seat_when_only_one_open(self):
        """If a pair is at the front of the waitlist and only 1 seat is open,
        nobody gets promoted — the seat is held until a second seat opens."""
        with patch('bot.application') as mock_app, patch('bot.scheduler') as mock_sched:
            mock_app.bot.send_message = AsyncMock()
            mock_sched.add_job = MagicMock()

            event_id = self._add_event(status='CLOSED', total_places=3)
            cursor = self.real_conn.cursor()
            # 2 ACCEPTED → 1 free seat. Waitlist head is a pair, then a single.
            self._add_reg(event_id, 10, 'x_user', status='ACCEPTED')
            self._add_reg(event_id, 11, 'y_user', status='ACCEPTED')
            a = self._add_reg(event_id, 1, 'a_user', status='WAITLIST')
            b = self._add_reg(event_id, 2, 'b_user', status='WAITLIST')
            cursor.execute("UPDATE registrations SET partner_reg_id = ?, priority = 1 WHERE id = ?", (b, a))
            cursor.execute("UPDATE registrations SET partner_reg_id = ?, priority = 1 WHERE id = ?", (a, b))
            single = self._add_reg(event_id, 3, 'c_user', status='WAITLIST')
            cursor.execute("UPDATE registrations SET priority = 2 WHERE id = ?", (single,))
            self.real_conn.commit()

            await invite_next(event_id)

            # Pair stays on waitlist
            cursor.execute("SELECT status FROM registrations WHERE id = ?", (a,))
            self.assertEqual(cursor.fetchone()['status'], 'WAITLIST')
            cursor.execute("SELECT status FROM registrations WHERE id = ?", (b,))
            self.assertEqual(cursor.fetchone()['status'], 'WAITLIST')
            # Single behind the pair does NOT jump them — seat held.
            cursor.execute("SELECT status FROM registrations WHERE id = ?", (single,))
            self.assertEqual(cursor.fetchone()['status'], 'WAITLIST')

    async def test_pair_at_head_promotes_when_two_seats_open(self):
        """Once a second seat opens, the held pair is invited together."""
        with patch('bot.application') as mock_app, patch('bot.scheduler') as mock_sched:
            mock_app.bot.send_message = AsyncMock()
            mock_sched.add_job = MagicMock()

            event_id = self._add_event(status='CLOSED', total_places=4)
            cursor = self.real_conn.cursor()
            # 2 ACCEPTED → 2 free seats. Waitlist head is a pair.
            self._add_reg(event_id, 10, 'x_user', status='ACCEPTED')
            self._add_reg(event_id, 11, 'y_user', status='ACCEPTED')
            a = self._add_reg(event_id, 1, 'a_user', status='WAITLIST')
            b = self._add_reg(event_id, 2, 'b_user', status='WAITLIST')
            cursor.execute("UPDATE registrations SET partner_reg_id = ?, priority = 1 WHERE id = ?", (b, a))
            cursor.execute("UPDATE registrations SET partner_reg_id = ?, priority = 1 WHERE id = ?", (a, b))
            single = self._add_reg(event_id, 3, 'c_user', status='WAITLIST')
            cursor.execute("UPDATE registrations SET priority = 2 WHERE id = ?", (single,))
            self.real_conn.commit()

            await invite_next(event_id)

            cursor.execute("SELECT status FROM registrations WHERE id = ?", (a,))
            self.assertEqual(cursor.fetchone()['status'], 'INVITED')
            cursor.execute("SELECT status FROM registrations WHERE id = ?", (b,))
            self.assertEqual(cursor.fetchone()['status'], 'INVITED')
            cursor.execute("SELECT status FROM registrations WHERE id = ?", (single,))
            self.assertEqual(cursor.fetchone()['status'], 'WAITLIST')


class TestPairUnregister(_BaseCase):
    async def test_unregister_unlinks_partner(self):
        event_id = self._add_event(status='OPEN', total_places=10)
        a = self._add_reg(event_id, 111, 'alice_user')
        b = self._add_reg(event_id, 222, 'bob_user')
        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b, a))
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (a, b))
        self.real_conn.commit()

        update = MagicMock()
        update.effective_chat.type = "private"
        update.effective_user.id = 111
        update.effective_user.username = "alice"
        update.effective_user.first_name = "alice"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.get_chat_member = AsyncMock(side_effect=Exception("no group"))

        await unregister(update, context)

        cursor.execute("SELECT status, partner_reg_id FROM registrations WHERE id = ?", (a,))
        a_row = cursor.fetchone()
        self.assertEqual(a_row['status'], 'UNREGISTERED')
        self.assertIsNone(a_row['partner_reg_id'])

        cursor.execute("SELECT status, partner_reg_id FROM registrations WHERE id = ?", (b,))
        b_row = cursor.fetchone()
        # Partner stays in their state (REGISTERED) but is unlinked
        self.assertEqual(b_row['status'], 'REGISTERED')
        self.assertIsNone(b_row['partner_reg_id'])

        # Partner gets a DM
        context.bot.send_message.assert_called()


if __name__ == '__main__':
    unittest.main()
