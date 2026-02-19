import unittest
import sqlite3
import os

# Set environment before importing web
TEST_DB_PATH = "test_web_data.db"
os.environ["DB_PATH"] = TEST_DB_PATH

from web import app

class TestWebDashboard(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

        # Init test db
        conn = sqlite3.connect(TEST_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, status TEXT, total_places INTEGER)")
        cursor.execute("CREATE TABLE IF NOT EXISTS registrations (id INTEGER PRIMARY KEY, event_id INTEGER, first_name TEXT, username TEXT, status TEXT, priority INTEGER, signup_time DATETIME, guest_of_user_id INTEGER)")
        cursor.execute("CREATE TABLE IF NOT EXISTS speakers (id INTEGER PRIMARY KEY, event_id INTEGER, username TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS action_logs (id INTEGER PRIMARY KEY, event_id INTEGER, user_id INTEGER, username TEXT, action TEXT, details TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        
        cursor.execute("INSERT INTO events (id, status, total_places) VALUES (1, 'OPEN', 10)")
        cursor.execute("INSERT INTO registrations (event_id, first_name, username, status, priority, signup_time, guest_of_user_id) VALUES (1, 'John', 'john123', 'REGISTERED', NULL, '2023-01-01', NULL)")
        cursor.execute("INSERT INTO action_logs (event_id, username, action, details, timestamp) VALUES (1, 'john123', 'REGISTER', 'Test log', '2023-01-01')")
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    def test_dashboard_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        
        # Verify event loaded
        self.assertIn("OPEN", content)
        
        # Verify user loaded
        self.assertIn("John", content)
        self.assertIn("john123", content)
        
        # Verify log loaded
        self.assertIn("Test log", content)

if __name__ == '__main__':
    unittest.main()
