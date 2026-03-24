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
        cursor.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, status TEXT, total_places INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE speakers (id INTEGER PRIMARY KEY, event_id INTEGER, username TEXT, first_name TEXT)")
        cursor.execute("CREATE TABLE registrations (id INTEGER PRIMARY KEY, event_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT, status TEXT, guest_of_user_id INTEGER, signup_time DATETIME, priority INTEGER)")
        cursor.execute("CREATE TABLE action_logs (id INTEGER PRIMARY KEY, event_id INTEGER, timestamp DATETIME, username TEXT, first_name TEXT, user_id INTEGER, action TEXT, details TEXT)")
        
        # Insert test data
        cursor.execute("INSERT INTO events (status, total_places, created_at) VALUES ('OPEN', 10, CURRENT_TIMESTAMP)")
        event_id = cursor.lastrowid
        
        # Insert > 150 logs to verify pagination removal
        for i in range(200):
            cursor.execute("INSERT INTO action_logs (event_id, action, details) VALUES (?, ?, ?)", (event_id, f"ACTION_{i}", f"Details {i}"))
            
        self.conn.commit()

    def tearDown(self):
        self.patcher.stop()
        self.conn.close()

    def test_user_formatting_on_dashboard(self):
        cursor = self.conn.cursor()
        # 1. User with username
        cursor.execute("INSERT INTO registrations (event_id, username, first_name, status) VALUES (1, 'user_with_at', 'Alice', 'ACCEPTED')")
        # 2. User without username (first_name only)
        cursor.execute("INSERT INTO registrations (event_id, username, first_name, status) VALUES (1, NULL, 'Bob', 'ACCEPTED')")
        # 3. User with numeric username (should be treated as ID)
        cursor.execute("INSERT INTO registrations (event_id, username, first_name, status) VALUES (1, '12345', 'Charlie', 'ACCEPTED')")
        # 4. Speaker without username
        cursor.execute("INSERT INTO speakers (event_id, username, first_name) VALUES (1, '99999', 'SpeakerDave')")
        
        self.conn.commit()
        
        response = self.client.get('/')
        html = response.data.decode()
        
        self.assertIn("@user_with_at", html)
        self.assertIn("Bob", html)
        self.assertIn("Charlie", html)
        self.assertIn("SpeakerDave", html)

    def test_scroll_persistence_script_present(self):
        response = self.client.get('/')
        html = response.data.decode()
        self.assertIn("localStorage.setItem('scrollPosition', window.scrollY)", html)
        self.assertIn("window.scrollTo(0, parseInt(scrollPos))", html)
        self.assertIn('body onload="restoreScroll()"', html)

    def test_dashboard_shows_recent_logs(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        
        # Check title update
        self.assertIn("<h2>Real-time Action Logs (Zurich)</h2>", html)
        self.assertNotIn("(Latest 150)", html)
        
        # Check that we do NOT see log 0, but DO see log 199 (due to LIMIT 100)
        self.assertNotIn("ACTION_0", html)
        self.assertIn("ACTION_199", html)
        
        # Simple count check - "ACTION_" appears 100 times in the logs
        self.assertEqual(html.count("ACTION_"), 100)

    def test_dashboard_cancelled_hides_participants(self):
        # Update event to CANCELLED
        cursor = self.conn.cursor()
        cursor.execute("UPDATE events SET status = 'CANCELLED' WHERE id = 1")
        # Add a speaker and registration
        cursor.execute("INSERT INTO speakers (event_id, username) VALUES (1, 'test_speaker')")
        cursor.execute("INSERT INTO registrations (event_id, username, status) VALUES (1, 'test_user', 'ACCEPTED')")
        self.conn.commit()
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        
        # Should show "No active event found"
        self.assertIn("No active event found.", html)
        # Should NOT show the participant tables or names
        self.assertNotIn("@test_speaker", html)
        self.assertNotIn("@test_user", html)
        # Should STILL show logs
        self.assertIn("Real-time Action Logs (Zurich)", html)
        self.assertEqual(html.count("ACTION_"), 100)

    def test_timestamp_formatting_zurich(self):
        cursor = self.conn.cursor()
        # Insert a registration with UTC time
        # UTC 11:00:00 -> Zurich 12:00:00 (assuming CET/CEST conversion)
        # In March 2024 (before last Sunday), it's CET (+01:00)
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, signup_time) VALUES (1, 'zurich_test_user', 'REGISTERED', ?)", 
            ("2024-03-09 11:00:00+00:00",)
        )
        self.conn.commit()
        
        response = self.client.get('/')
        html = response.data.decode()
        
        # Check that it is converted to Zurich time (CET in March is +1)
        self.assertIn("2024-03-09 12:00:00", html)
        self.assertNotIn("2024-03-09 11:00:00", html)

    def test_timestamp_formatting_naive(self):
        cursor = self.conn.cursor()
        # Insert a log with naive time (should be treated as UTC and converted to Zurich)
        cursor.execute(
            "INSERT INTO action_logs (event_id, action, timestamp) VALUES (1, 'NAIVE_LOG', ?)", 
            ("2024-03-09 10:00:00",)
        )
        self.conn.commit()
        
        response = self.client.get('/')
        html = response.data.decode()
        
        # 10:00 UTC -> 11:00 Zurich
        self.assertIn("2024-03-09 11:00:00", html)

if __name__ == '__main__':
    unittest.main()
