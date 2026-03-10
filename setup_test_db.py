import sqlite3
import os

os.environ["DB_PATH"] = "test_data.db"

# Create necessary tables manually for test
conn = sqlite3.connect("test_data.db")
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT,
        total_places INTEGER
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        user_id INTEGER,
        username TEXT,
        status TEXT
    )
""")

# Insert a dummy event
cursor.execute("INSERT INTO events (status, total_places) VALUES ('PRE_OPEN', 10)")
event_id = cursor.lastrowid

# Insert good user
cursor.execute("INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, ?, ?, ?)", (event_id, 1, 'good_user', 'ACCEPTED'))

# Insert users with brackets/at symbols
cursor.execute("INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, ?, ?, ?)", (event_id, 2, '<bad_user1>', 'ACCEPTED'))
cursor.execute("INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, ?, ?, ?)", (event_id, 3, '@bad_user2', 'ACCEPTED'))
cursor.execute("INSERT INTO registrations (event_id, user_id, username, status) VALUES (?, ?, ?, ?)", (event_id, 4, '<@bad_user3>', 'ACCEPTED'))

conn.commit()
conn.close()
print("Test database populated.")
