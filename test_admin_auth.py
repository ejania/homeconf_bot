import unittest
import os
from unittest.mock import MagicMock, AsyncMock, patch
from bot import is_admin, create_event, close_registration_command
from models import init_db, get_db
import messages

# Use an in-memory database for testing
TEST_DB_PATH = ":memory:"

class TestAdminAuth(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # We need to mock ADMIN_IDS inside bot.py for each test, 
        # or globally set it before importing. Since bot.py is already imported, 
        # we can patch bot.ADMIN_IDS.
        pass

    async def test_is_admin_check(self):
        # Patch ADMIN_IDS for this test
        with patch('bot.ADMIN_IDS', {123456789}):
            # Test with an admin ID
            update = MagicMock()
            update.effective_user.id = 123456789
            context = MagicMock()
            
            result = await is_admin(update, context)
            self.assertTrue(result, "User 123456789 should be admin")
                
            # Test with a non-admin ID
            update = MagicMock()
            update.effective_user.id = 99999
            context = MagicMock()
            
            result = await is_admin(update, context)
            self.assertFalse(result, "User 99999 should not be admin")

    async def test_create_event_denied(self):
        # Ensure create_event denies non-admins
        update = MagicMock()
        update.effective_user.id = 99999
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        
        await create_event(update, context)
        
        update.message.reply_text.assert_called_with(messages.ONLY_ADMIN_OPEN)

    async def test_close_registration_denied(self):
        # Ensure close_registration denies non-admins
        update = MagicMock()
        update.effective_user.id = 99999
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        
        await close_registration_command(update, context)
        
        update.message.reply_text.assert_called_with(messages.ONLY_ADMIN_CLOSE)

if __name__ == '__main__':
    unittest.main()
