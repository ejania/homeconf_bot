"""Tests for ensure_private: correct command name in the DM sent to the user."""
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from bot import ensure_private
import messages


def _make_update(chat_type, text):
    update = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_user.id = 42
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


class TestEnsurePrivate(unittest.IsolatedAsyncioTestCase):

    async def test_private_chat_returns_true(self):
        update = _make_update("private", "/register")
        context = MagicMock()
        result = await ensure_private(update, context)
        self.assertTrue(result)
        context.bot.send_message.assert_not_called()

    async def test_group_sends_dm_with_correct_command(self):
        update = _make_update("group", "/register")
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        result = await ensure_private(update, context)

        self.assertFalse(result)
        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args[0][1]
        self.assertIn("/register", sent_text)
        self.assertNotIn("/command", sent_text)
        self.assertFalse(sent_text.startswith("Эту"))

    async def test_command_with_bot_username_stripped(self):
        update = _make_update("group", "/register@zrh_homeconf_bot")
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await ensure_private(update, context)

        sent_text = context.bot.send_message.call_args[0][1]
        self.assertIn("/register", sent_text)
        self.assertNotIn("@zrh_homeconf_bot", sent_text)
        self.assertNotIn("/command", sent_text)

    async def test_unregister_command_shown_correctly(self):
        update = _make_update("supergroup", "/unregister")
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await ensure_private(update, context)

        sent_text = context.bot.send_message.call_args[0][1]
        self.assertIn("/unregister", sent_text)

    async def test_dm_fails_gracefully(self):
        """If the user hasn't started the bot, send_message raises — ensure_private still returns False."""
        update = _make_update("group", "/stats")
        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=Exception("Forbidden"))

        result = await ensure_private(update, context)
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
