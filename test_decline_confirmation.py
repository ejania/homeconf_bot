"""
Tests for the waitlist invite decline confirmation flow (fix #4 and #6).

Fix 4: clicking Decline on a waitlist invite shows a confirmation step
       rather than immediately unregistering the user.
Fix 6: when a paired user declines (confirmed), the partner receives a
       distinct message identifying who declined, not the generic "we declined".
"""
import unittest
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from bot import callback_handler
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
    cursor.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER, status TEXT, total_places INTEGER,
        speakers_group_id TEXT, waitlist_timeout_hours INTEGER,
        end_time DATETIME, event_start_time DATETIME,
        registration_duration_hours INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, chat_id INTEGER,
        username TEXT, first_name TEXT, status TEXT,
        signup_time DATETIME, priority INTEGER, notified_at DATETIME,
        expires_at DATETIME, guest_of_user_id INTEGER,
        partner_reg_id INTEGER, invite_token TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS speakers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, username TEXT, first_name TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, user_id INTEGER, username TEXT,
        first_name TEXT, action TEXT, details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()


class TestDeclineConfirmation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch('bot.get_db')
        self.mock_get_db = self.patcher.start()
        self.real_conn = sqlite3.connect(TEST_DB_PATH)
        self.real_conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = MockConnection(self.real_conn)
        _setup_schema(self.real_conn)

    def tearDown(self):
        self.real_conn.close()
        self.patcher.stop()

    def _add_event(self, status='CLOSED'):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO events (status, total_places, event_start_time) VALUES (?, 5, '2026-10-10 12:00:00')",
            (status,)
        )
        self.real_conn.commit()
        return cursor.lastrowid

    def _add_invited_reg(self, event_id, user_id, username, partner_reg_id=None):
        cursor = self.real_conn.cursor()
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, username, first_name, status, partner_reg_id) "
            "VALUES (?, ?, ?, ?, 'INVITED', ?)",
            (event_id, user_id, username, username, partner_reg_id)
        )
        self.real_conn.commit()
        return cursor.lastrowid

    def _make_callback(self, action_data, user_id):
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query = MagicMock()
        update.callback_query.data = action_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        return update, context

    # --- Fix 4: decline shows confirmation, not immediate unregister ---

    async def test_decline_shows_confirmation_not_immediate(self):
        """Clicking Decline on a waitlist invite shows confirmation — status stays INVITED."""
        event_id = self._add_event()
        reg_id = self._add_invited_reg(event_id, 111, 'alice')

        update, context = self._make_callback(f"dec_{reg_id}", user_id=111)
        await callback_handler(update, context)

        # Still INVITED — not removed yet
        cursor = self.real_conn.cursor()
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'INVITED')

        # Confirmation message shown with two buttons
        call_args = update.callback_query.edit_message_text.call_args
        self.assertEqual(call_args[0][0], messages.INVITATION_DECLINE_CONFIRM)
        markup = call_args[1]['reply_markup']
        button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn(f"decyes_{reg_id}", button_data)
        self.assertIn(f"decno_{reg_id}", button_data)

    async def test_decyes_actually_unregisters(self):
        """Confirming decline (decyes) unregisters the user."""
        event_id = self._add_event()
        reg_id = self._add_invited_reg(event_id, 111, 'alice')

        with patch('bot.application') as mock_app, patch('bot.scheduler'):
            mock_app.bot.send_message = AsyncMock()
            update, context = self._make_callback(f"decyes_{reg_id}", user_id=111)
            await callback_handler(update, context)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'UNREGISTERED')
        update.callback_query.edit_message_text.assert_called_with(messages.INVITATION_DECLINED)

    async def test_decno_keeps_spot_and_restores_accept_button(self):
        """Clicking 'No, I'll stay' keeps INVITED status and shows an Accept button."""
        event_id = self._add_event()
        reg_id = self._add_invited_reg(event_id, 111, 'alice')

        update, context = self._make_callback(f"decno_{reg_id}", user_id=111)
        await callback_handler(update, context)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'INVITED')

        call_args = update.callback_query.edit_message_text.call_args
        self.assertEqual(call_args[0][0], messages.INVITATION_DECLINE_ABORTED)
        markup = call_args[1]['reply_markup']
        button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn(f"acc_{reg_id}", button_data)

    async def test_decno_then_accept_works(self):
        """User clicks Decline → No I'll stay → Accept: should end up ACCEPTED."""
        event_id = self._add_event()
        reg_id = self._add_invited_reg(event_id, 111, 'alice')

        # Step 1: Decline → confirmation shown
        update, _ = self._make_callback(f"dec_{reg_id}", user_id=111)
        await callback_handler(update, MagicMock())

        # Step 2: "No I'll stay" → spot restored
        update, _ = self._make_callback(f"decno_{reg_id}", user_id=111)
        await callback_handler(update, MagicMock())

        # Step 3: Accept
        update, context = self._make_callback(f"acc_{reg_id}", user_id=111)
        context.bot.send_message = AsyncMock()
        await callback_handler(update, context)

        cursor = self.real_conn.cursor()
        cursor.execute("SELECT status FROM registrations WHERE id = ?", (reg_id,))
        self.assertEqual(cursor.fetchone()['status'], 'ACCEPTED')

    # --- Fix 6: partner receives a distinct "your partner declined" message ---

    async def test_paired_decline_shows_pair_confirmation(self):
        """For a pair, the decline confirmation message mentions the partner."""
        event_id = self._add_event()
        a_id = self._add_invited_reg(event_id, 111, 'alice')
        b_id = self._add_invited_reg(event_id, 222, 'bob', partner_reg_id=a_id)
        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_id, a_id))
        self.real_conn.commit()

        update, context = self._make_callback(f"dec_{a_id}", user_id=111)
        await callback_handler(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        confirm_text = call_args[0][0]
        # Should use the pair-specific confirmation mentioning the partner
        self.assertIn('bob', confirm_text)
        self.assertNotEqual(confirm_text, messages.INVITATION_DECLINE_CONFIRM)

    async def test_paired_decyes_notifies_partner_with_specific_message(self):
        """When Alice confirms decline, Bob gets a message naming Alice — not the generic declined text."""
        event_id = self._add_event()
        a_id = self._add_invited_reg(event_id, 111, 'alice')
        b_id = self._add_invited_reg(event_id, 222, 'bob', partner_reg_id=a_id)
        cursor = self.real_conn.cursor()
        cursor.execute("UPDATE registrations SET partner_reg_id = ? WHERE id = ?", (b_id, a_id))
        self.real_conn.commit()

        with patch('bot.application') as mock_app, patch('bot.scheduler'):
            mock_app.bot.send_message = AsyncMock()
            update, context = self._make_callback(f"decyes_{a_id}", user_id=111)
            await callback_handler(update, context)

        # Alice's view: generic "we declined"
        update.callback_query.edit_message_text.assert_called_with(messages.INVITATION_DECLINED)

        # Bob's DM: specific message naming Alice
        bob_calls = [c for c in context.bot.send_message.call_args_list if c[0][0] == 222]
        self.assertEqual(len(bob_calls), 1)
        bob_msg = bob_calls[0][0][1]
        self.assertNotEqual(bob_msg, messages.INVITATION_DECLINED)
        self.assertIn('alice', bob_msg)

    async def test_solo_decyes_sends_declined_not_partner_message(self):
        """A solo (unpaired) confirmed decline still sends INVITATION_DECLINED, not partner message."""
        event_id = self._add_event()
        reg_id = self._add_invited_reg(event_id, 111, 'alice')

        with patch('bot.application') as mock_app, patch('bot.scheduler'):
            mock_app.bot.send_message = AsyncMock()
            update, context = self._make_callback(f"decyes_{reg_id}", user_id=111)
            await callback_handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(messages.INVITATION_DECLINED)
        # No DM to a partner (there is none)
        context.bot.send_message.assert_not_called()


if __name__ == '__main__':
    unittest.main()
