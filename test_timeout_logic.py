import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot import calculate_expiration_with_night_pause

class TestTimeoutLogic(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("Europe/Zurich")

    def test_24h_timeout_no_pause(self):
        # 24 hour timeout should not be affected by night hours
        now_utc = datetime(2026, 3, 23, 12, 0, tzinfo=ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 24)
        expected = now_utc + timedelta(hours=24)
        self.assertEqual(res, expected)

    def test_12h_timeout_no_pause(self):
        # 12 hour timeout should not be affected by night hours
        now_utc = datetime(2026, 3, 23, 12, 0, tzinfo=ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 12)
        expected = now_utc + timedelta(hours=12)
        self.assertEqual(res, expected)

    def test_short_timeout_daytime(self):
        # 1 hour timeout entirely during the day
        now_zurich = datetime(2026, 3, 23, 14, 0, tzinfo=self.tz)
        now_utc = now_zurich.astimezone(ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 1)
        expected = now_utc + timedelta(hours=1)
        self.assertEqual(res, expected)

    def test_short_timeout_crossing_into_night(self):
        # 2 hour timeout starting at 23:00 Zurich time.
        # Should consume 1 hour until 00:00, then pause until 10:00, then consume remaining 1 hour -> 11:00 next day.
        now_zurich = datetime(2026, 3, 23, 23, 0, tzinfo=self.tz)
        now_utc = now_zurich.astimezone(ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 2)
        expected_zurich = datetime(2026, 3, 24, 11, 0, tzinfo=self.tz)
        self.assertEqual(res, expected_zurich.astimezone(ZoneInfo("UTC")))

    def test_short_timeout_starting_in_night(self):
        # 1 hour timeout starting at 02:00 Zurich time.
        # Should be paused until 10:00, then consume 1 hour -> 11:00.
        now_zurich = datetime(2026, 3, 23, 2, 0, tzinfo=self.tz)
        now_utc = now_zurich.astimezone(ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 1)
        expected_zurich = datetime(2026, 3, 23, 11, 0, tzinfo=self.tz)
        self.assertEqual(res, expected_zurich.astimezone(ZoneInfo("UTC")))

    def test_short_timeout_starting_at_night_end(self):
        # 1 hour timeout starting exactly at 10:00 Zurich time.
        now_zurich = datetime(2026, 3, 23, 10, 0, tzinfo=self.tz)
        now_utc = now_zurich.astimezone(ZoneInfo("UTC"))
        res = calculate_expiration_with_night_pause(now_utc, 1)
        expected_zurich = datetime(2026, 3, 23, 11, 0, tzinfo=self.tz)
        self.assertEqual(res, expected_zurich.astimezone(ZoneInfo("UTC")))

if __name__ == '__main__':
    unittest.main()
