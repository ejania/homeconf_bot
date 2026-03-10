import sqlite3
import sys

def clean_database(db_path="bot_data.db"):
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, username FROM registrations WHERE username LIKE '%<%' OR username LIKE '%>%' OR username LIKE '@%'")
    rows = cursor.fetchall()
    
    updated_count = 0
    for row in rows:
        old_username = row['username']
        new_username = old_username.replace('<', '').replace('>', '').lstrip('@')
        
        if new_username != old_username:
            cursor.execute("UPDATE registrations SET username = ? WHERE id = ?", (new_username, row['id']))
            print(f"Updated id {row['id']}: '{old_username}' -> '{new_username}'")
            updated_count += 1
            
    conn.commit()
    conn.close()
    print(f"Total updated records: {updated_count}")

if __name__ == '__main__':
    db_file = sys.argv[1] if len(sys.argv) > 1 else "bot_data.db"
    clean_database(db_file)
