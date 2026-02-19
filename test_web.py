import unittest
import sqlite3
import os
from unittest.mock import patch, MagicMock
from web import app, get_db

TEST_DB_PATH = ":memory:"

class TestWebDashboard(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        
        # Setup DB
        self.patcher = patch('web.get_db')
        self.mock_get_db = self.patcher.start()
        
        self.conn = sqlite3.connect(TEST_DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.mock_get_db.return_value = self.conn
        
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, status TEXT, total_places INTEGER)")
        cursor.execute("CREATE TABLE speakers (id INTEGER PRIMARY KEY, event_id INTEGER, username TEXT)")
        cursor.execute("CREATE TABLE registrations (id INTEGER PRIMARY KEY, event_id INTEGER, username TEXT, first_name TEXT, status TEXT, guest_of_user_id INTEGER, signup_time DATETIME, priority INTEGER)")
        cursor.execute("CREATE TABLE action_logs (id INTEGER PRIMARY KEY, event_id INTEGER, timestamp DATETIME, username TEXT, user_id INTEGER, action TEXT, details TEXT)")
        
        # Insert test data
        cursor.execute("INSERT INTO events (status, total_places) VALUES ('OPEN', 10)")
        event_id = cursor.lastrowid
        
        # Insert > 150 logs to verify pagination removal
        for i in range(200):
            cursor.execute("INSERT INTO action_logs (event_id, action, details) VALUES (?, ?, ?)", (event_id, f"ACTION_{i}", f"Details {i}"))
            
        self.conn.commit()

    def tearDown(self):
        self.patcher.stop()
        self.conn.close()

    def test_dashboard_shows_all_logs(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        
        # Check title update
        self.assertIn("<h2>Real-time Action Logs</h2>", html)
        self.assertNotIn("(Latest 150)", html)
        
        # Check that we see logs beyond 150
        # Specifically, "ACTION_0" (the first inserted) should be visible if we show ALL (DESC order means it's last)
        # "ACTION_199" (latest) should be at top.
        self.assertIn("ACTION_0", html)
        self.assertIn("ACTION_199", html)
        
        # Simple count check - "ACTION_" appears 200 times in the logs
        self.assertEqual(html.count("ACTION_"), 200)

if __name__ == '__main__':
    unittest.main()
