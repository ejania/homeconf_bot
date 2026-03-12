import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3

import bot
import messages
from models import init_db

class MockConnection:
    def __init__(self, real_conn):
        self.real_conn = real_conn
    
    def cursor(self):
        return self.real_conn.cursor()
    
    def commit(self):
        self.real_conn.commit()
        
    def close(self):
        pass # Do nothing

class TestReminders(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Override get_db to use an in-memory database for testing
        self.db_patcher = patch('bot.get_db')
        self.mock_get_db = self.db_patcher.start()
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.mock_conn = MockConnection(self.conn)
        self.mock_get_db.return_value = self.mock_conn
        
        # Initialize the schema
        with patch('models.sqlite3.connect', return_value=self.mock_conn):
            init_db()
        
        # Mock scheduler
        self.sched_patcher = patch('bot.scheduler')
        self.mock_scheduler = self.sched_patcher.start()
        
        # Mock application.bot
        self.app_patcher = patch('bot.application')
        self.mock_application = self.app_patcher.start()
        self.mock_application.bot.send_message = AsyncMock()
        
        # Mock get_now
        self.now = datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        self.now_patcher = patch('bot.get_now', return_value=self.now)
        self.mock_get_now = self.now_patcher.start()

    def tearDown(self):
        self.conn.close()
        patch.stopall()

    def test_schedule_reminders(self):
        # Event is 10 days in the future
        event_start_time = self.now + timedelta(days=10)
        bot.schedule_reminders(1, event_start_time)
        
        # Should schedule both 5-day and 2-day reminders
        self.assertEqual(self.mock_scheduler.add_job.call_count, 2)
        
        calls = self.mock_scheduler.add_job.call_args_list
        
        # 5-day reminder
        call_5 = calls[0]
        self.assertEqual(call_5[0][0], bot.send_reminder_job)
        self.assertEqual(call_5[1]['run_date'], event_start_time - timedelta(days=5))
        self.assertEqual(call_5[1]['args'], [1, 5])
        
        # 2-day reminder
        call_2 = calls[1]
        self.assertEqual(call_2[0][0], bot.send_reminder_job)
        self.assertEqual(call_2[1]['run_date'], event_start_time - timedelta(days=2))
        self.assertEqual(call_2[1]['args'], [1, 2])

    def test_schedule_reminders_partial(self):
        # Event is 3 days in the future
        event_start_time = self.now + timedelta(days=3)
        bot.schedule_reminders(1, event_start_time)
        
        # Should only schedule 2-day reminder
        self.assertEqual(self.mock_scheduler.add_job.call_count, 1)
        
        call = self.mock_scheduler.add_job.call_args_list[0]
        self.assertEqual(call[0][0], bot.send_reminder_job)
        self.assertEqual(call[1]['run_date'], event_start_time - timedelta(days=2))
        self.assertEqual(call[1]['args'], [1, 2])

    def test_schedule_reminders_past(self):
        # Event is 1 day in the future
        event_start_time = self.now + timedelta(days=1)
        bot.schedule_reminders(1, event_start_time)
        
        # Should schedule nothing
        self.assertEqual(self.mock_scheduler.add_job.call_count, 0)

    async def test_send_reminder_job(self):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO events (id, status, event_start_time) VALUES (1, 'CLOSED', ?)", (self.now + timedelta(days=5),))
        
        # Insert users
        # 1. Lottery winner
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (1, 101, 'ACCEPTED')")
        # 2. Speaker guest (accepted)
        cursor.execute("INSERT INTO registrations (event_id, user_id, status, guest_of_user_id) VALUES (1, 102, 'ACCEPTED', 999)")
        # 3. Speaker guest (invited but hasn't registered/confirmed yet)
        cursor.execute("INSERT INTO registrations (event_id, user_id, status, guest_of_user_id) VALUES (1, 103, 'INVITED', 999)")
        # 4. Waitlist person
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (1, 104, 'WAITLIST')")
        # 5. Unregistered person
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (1, 105, 'UNREGISTERED')")
        # 6. Speaker (in speakers table, maybe also in registrations as REGISTERED)
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (1, 'speaker1')")
        cursor.execute("INSERT INTO registrations (event_id, user_id, status) VALUES (1, 106, 'REGISTERED')")

        self.conn.commit()

        # Send 5-day reminder
        await bot.send_reminder_job(1, 5)
        
        # Should send to 101, 102, 103
        self.assertEqual(self.mock_application.bot.send_message.call_count, 3)
        calls = self.mock_application.bot.send_message.call_args_list
        user_ids = [c[0][0] for c in calls]
        
        self.assertIn(101, user_ids, "Lottery winner should receive reminder")
        self.assertIn(102, user_ids, "Accepted guest should receive reminder")
        self.assertIn(103, user_ids, "Invited guest should receive reminder")
        
        self.assertNotIn(104, user_ids, "Waitlist user should NOT receive reminder")
        self.assertNotIn(105, user_ids, "Unregistered user should NOT receive reminder")
        self.assertNotIn(106, user_ids, "Speaker should NOT receive reminder")
        
        # Verify message content
        self.assertEqual(calls[0][0][1], messages.REMINDER_5_DAYS)

        self.mock_application.bot.send_message.reset_mock()
        
        # Send 2-day reminder
        await bot.send_reminder_job(1, 2)
        
        # Should send to 101, 102, 103
        self.assertEqual(self.mock_application.bot.send_message.call_count, 3)
        calls = self.mock_application.bot.send_message.call_args_list
        self.assertEqual(calls[0][0][1], messages.REMINDER_2_DAYS)

if __name__ == '__main__':
    unittest.main()
