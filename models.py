import sqlite3
from datetime import datetime

DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Event table: only one active event at a time for simplicity
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            status TEXT, -- 'OPEN', 'CLOSED'
            total_places INTEGER,
            speakers_group_id TEXT,
            waitlist_timeout_hours INTEGER,
            end_time DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Registrations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            first_name TEXT,
            status TEXT, -- 'REGISTERED', 'INVITED', 'ACCEPTED', 'CANCELLED', 'EXPIRED'
            signup_time DATETIME,
            priority INTEGER, -- Used for sorting waitlist
            notified_at DATETIME,
            expires_at DATETIME,
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    ''')
    
    # Speakers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            username TEXT, -- lowercased for matching
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
