import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "bot_data.db")

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
            registration_duration_hours INTEGER,
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
            status TEXT, -- 'REGISTERED', 'INVITED', 'ACCEPTED', 'UNREGISTERED', 'EXPIRED'
            signup_time DATETIME,
            priority INTEGER, -- Used for sorting waitlist
            notified_at DATETIME,
            expires_at DATETIME,
            guest_of_user_id INTEGER, -- ID of the speaker who invited this user
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    ''')
    
    # Simple migration for existing DBs
    try:
        cursor.execute("ALTER TABLE registrations ADD COLUMN guest_of_user_id INTEGER")
    except sqlite3.OperationalError:
        pass # Column likely already exists

    try:
        cursor.execute("ALTER TABLE events ADD COLUMN registration_duration_hours INTEGER")
    except sqlite3.OperationalError:
        pass

    # Speakers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            username TEXT, -- lowercased for matching
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    ''')
    
    # Action Logs table for persistent state-change logging
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            details TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
