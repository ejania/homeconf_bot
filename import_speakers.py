import os
import sqlite3
import argparse
import asyncio
from telethon import TelegramClient

API_ID = int(os.getenv('TELEGRAM_API_ID', 0))
API_HASH = os.getenv('TELEGRAM_API_HASH', '')

async def main():
    parser = argparse.ArgumentParser(description="Extract users from a telegram group and add them to the speakers table.")
    parser.add_argument('group_id', type=str, help="The Telegram Group ID or Username (e.g. -1001234567890)")
    parser.add_argument('--db', type=str, default='/app/data/bot_data.db', help="Path to the bot database")
    args = parser.parse_args()

    print(f"Connecting to database: {args.db}")
    conn = sqlite3.connect(args.db)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        print("Error: No events found in the database. Run /create first.")
        conn.close()
        return
        
    event_id = event[0]
    print(f"Target Event ID: {event_id}")

    # Log in and fetch members
    print("Initialize Telethon login...")
    # Use persistent path for session file
    session_file = '/app/data/userbot_session'
    client = TelegramClient(session_file, API_ID, API_HASH)
    
    await client.start()
    
    try:
        # Resolve peer correctly based on input type
        group_peer = int(args.group_id) if args.group_id.lstrip('-').isdigit() else args.group_id
        
        print(f"Fetching members from chat: {group_peer}...")
        participants = await client.get_participants(group_peer)
        
        print(f"Found {len(participants)} members.")
        
        inserted = 0
        skipped = 0
        
        for user in participants:
            if user.bot:
                continue # Skip bots
                
            username = user.username.lower() if user.username else None
            
            # If no username, use ID as string for speakers table (which usually expects username)
            # though our logic currently matches lowercase usernames. We should probably only add users 
            # with names, but let's just insert what we have.
            identifier = username if username else str(user.id)
            
            # Check if already exists to prevent duplicates
            cursor.execute("SELECT id FROM speakers WHERE event_id = ? AND username = ?", (event_id, identifier))
            if cursor.fetchone():
                skipped += 1
                continue
                
            cursor.execute("INSERT INTO speakers (event_id, username) VALUES (?, ?)", (event_id, identifier))
            inserted += 1
            
        conn.commit()
        print(f"Successfully added {inserted} speakers. (Skipped {skipped} duplicates/bots).")
        
    except Exception as e:
        print(f"Error fetching members: {e}")
        
    finally:
        conn.close()
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
