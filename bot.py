import logging
import random
import os
import asyncio
import secrets
import string
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from models import init_db, get_db
import messages

load_dotenv()

def _get_group_id(gid):
    if not gid:
        return None
    try:
        return int(gid)
    except ValueError:
        return gid

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

ADMIN_IDS = {int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip()}

# Timezone configuration
TZ = ZoneInfo("Europe/Berlin")

def get_now():
    return datetime.now(TZ)

def calculate_expiration_with_night_pause(now_utc: datetime, timeout_hours: int) -> datetime:
    # Only pause during the night if the timeout is short (e.g. 1h or similar).
    # If the timeout is 12h or 24h, there's naturally plenty of daytime included, so no need to pause.
    if timeout_hours >= 12:
        return now_utc + timedelta(hours=timeout_hours)

    tz = ZoneInfo("Europe/Zurich")
    now_local = now_utc.astimezone(tz)
    
    # We allocate time chunk by chunk
    remaining_hours = timeout_hours
    current = now_local
    
    while remaining_hours > 0:
        # Check if current time is inside night window (00:00 to 10:00)
        # Night ends at 10:00 today. If current is < 10:00, move it to 10:00.
        if 0 <= current.hour < 10:
            current = current.replace(hour=10, minute=0, second=0, microsecond=0)
        
        # Next night starts at 00:00 tomorrow
        next_night_start = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Available hours until next night
        available_hours = (next_night_start - current).total_seconds() / 3600.0
        
        if remaining_hours <= available_hours:
            current += timedelta(hours=remaining_hours)
            remaining_hours = 0
        else:
            current = next_night_start
            remaining_hours -= available_hours
            
    return current.astimezone(ZoneInfo("UTC"))

# Global scheduler and application
scheduler = None
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        token = context.args[0]
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM registrations WHERE invite_token = ?", (token,))
        invite = cursor.fetchone()
        if invite:
            if invite['user_id']:
                if invite['user_id'] == update.effective_user.id:
                    await update.message.reply_text(messages.GUEST_LINK_ALREADY)
                else:
                    await update.message.reply_text(messages.GUEST_LINK_USED)
            else:
                # check if user is already registered in this event
                cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND user_id = ? AND status != 'UNREGISTERED'", (invite['event_id'], update.effective_user.id))
                existing = cursor.fetchone()
                if existing:
                    if existing['status'] in ['REGISTERED', 'WAITLIST']:
                        cursor.execute("DELETE FROM registrations WHERE id = ?", (invite['id'],))
                        cursor.execute("UPDATE registrations SET status = 'ACCEPTED', guest_of_user_id = ? WHERE id = ?", (invite['guest_of_user_id'], existing['id']))
                        await update.message.reply_text(f"{messages.GUEST_IDENTIFIED}\n\n{messages.WELCOME_MESSAGE}")
                    else:
                        await update.message.reply_text(messages.ALREADY_REGISTERED)
                else:
                    cursor.execute("UPDATE registrations SET user_id = ?, chat_id = ?, first_name = ?, username = ?, signup_time = ? WHERE id = ?", 
                                   (update.effective_user.id, update.effective_chat.id, update.effective_user.first_name, update.effective_user.username, get_now(), invite['id']))
                    await update.message.reply_text(f"{messages.GUEST_IDENTIFIED}\n\n{messages.WELCOME_MESSAGE}")
            conn.commit()
            conn.close()
            return
        conn.close()

    await update.message.reply_text(messages.WELCOME_MESSAGE)

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return update.effective_user.id in ADMIN_IDS

async def ensure_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return True
    
    # It's a group, try to DM the user
    try:
        await context.bot.send_message(
            update.effective_user.id, 
            messages.PRIVATE_CHAT_ONLY.format(command=context.args[0] if context.args else 'command')
        )
    except Exception:
        # User hasn't started the bot, so we can't DM. 
        # We might silently fail or send a temporary message in group.
        # "avoid spam" -> prefer silence or very minimal feedback.
        pass
    return False


def reoder_waitlist(event_id, cursor):
    cursor.execute("SELECT id FROM registrations WHERE event_id = ? AND status = 'WAITLIST' ORDER BY priority ASC", (event_id,))
    rows = cursor.fetchall()
    for i, r in enumerate(rows, 1):
        cursor.execute("UPDATE registrations SET priority = ? WHERE id = ?", (i, r['id']))

def log_action(event_id, user_id, username, first_name, action, details=""):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO action_logs (event_id, user_id, username, first_name, action, details) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, user_id, username, first_name, action, details)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Failed to log action {action}: {e}")

async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_OPEN)
        return

    is_test = False
    args = list(context.args)
    if args and args[0].lower() == 'test':
        is_test = True
        args = args[1:]

    conn = get_db()
    cursor = conn.cursor()
    
    # Check if a real event is already active. Test events don't block each other.
    if not is_test:
        cursor.execute("SELECT id FROM events WHERE id > 0 AND status IN ('OPEN', 'PRE_OPEN')")
        if cursor.fetchone():
            await update.message.reply_text(messages.REGISTRATION_ALREADY_OPEN)
            conn.close()
            return
    
    try:
        speakers_group_id = args[0]
        try:
            speakers_group_id = int(speakers_group_id)
        except ValueError:
            pass
    except IndexError:
        await update.message.reply_text(messages.USAGE_CREATE)
        conn.close()
        return

    # Validate that we can access the speakers group
    try:
        chat = await context.bot.get_chat(speakers_group_id)
        logging.info(f"Verified speakers group: {chat.title} ({chat.id})")
        actual_group_id = chat.id
    except Exception as e:
        # Fallback: Telegram clients often strip the -100 prefix for supergroups.
        if isinstance(speakers_group_id, int) and speakers_group_id < 0 and not str(speakers_group_id).startswith("-100"):
            try:
                speakers_group_id = int(f"-100{abs(speakers_group_id)}")
                chat = await context.bot.get_chat(speakers_group_id)
                logging.info(f"Verified speakers group (with -100 prefix): {chat.title} ({chat.id})")
                actual_group_id = chat.id
            except Exception as e2:
                await update.message.reply_text(messages.ERROR_ACCESS_GROUP)
                logging.error(f"Failed to access group {speakers_group_id}: {e2}")
                conn.close()
                return
        else:
            await update.message.reply_text(messages.ERROR_ACCESS_GROUP)
            logging.error(f"Failed to access group {speakers_group_id}: {e}")
            conn.close()
            return

    if not is_test:
        # Clean up all test events and their related data
        cursor.execute("SELECT id FROM events WHERE id < 0")
        test_event_ids = [row['id'] for row in cursor.fetchall()]
        for te_id in test_event_ids:
            cursor.execute("DELETE FROM registrations WHERE event_id = ?", (te_id,))
            cursor.execute("DELETE FROM speakers WHERE event_id = ?", (te_id,))
            cursor.execute("DELETE FROM action_logs WHERE event_id = ?", (te_id,))
            cursor.execute("DELETE FROM events WHERE id = ?", (te_id,))
        
        cursor.execute(
            "INSERT INTO events (chat_id, status, speakers_group_id) VALUES (?, ?, ?)",
            (update.effective_chat.id, 'PRE_OPEN', str(actual_group_id))
        )
        event_id = cursor.lastrowid
    else:
        # Find next negative ID
        cursor.execute("SELECT MIN(id) as min_id FROM events WHERE id < 0")
        row = cursor.fetchone()
        next_test_id = (row['min_id'] - 1) if (row and row['min_id'] is not None) else -1
        
        cursor.execute(
            "INSERT INTO events (id, chat_id, status, speakers_group_id) VALUES (?, ?, ?, ?)",
            (next_test_id, update.effective_chat.id, 'PRE_OPEN', str(actual_group_id))
        )
        event_id = next_test_id

    conn.commit()
    log_action(event_id, update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'CREATE_EVENT', f'group={actual_group_id}{" (TEST)" if is_test else ""}')
    conn.close()

    await update.message.reply_text(f"Событие создано! (ID: {event_id}) {'[ТЕСТ]' if is_test else ''}")
    
    # Run userbot script to import speakers
    # We do this asynchronously so we don't block the bot
    await update.message.reply_text("Fetching speakers from group... This might take a few seconds.")
    try:
        import asyncio
        import subprocess
        # Execute it via CLI because Telethon runs its own asyncio loop 
        # which can conflict with the main bot application loop if run in the same process
        process = await asyncio.create_subprocess_exec(
            'python', 'import_speakers.py', str(actual_group_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            count = len(stdout.decode().splitlines()) # Estimate count or parse output
            log_action(event_id, None, "System", None, "SPEAKERS_IMPORTED", f"Result: {stdout.decode().strip()}")
            logging.info(f"Imported speakers: {stdout.decode()}")
            await update.message.reply_text(f"✅ Speakers automatically imported!")
        else:
            log_action(event_id, None, "System", None, "SPEAKERS_IMPORT_FAIL", f"Error: {stderr.decode().strip()}")
            logging.error(f"Error importing speakers: {stderr.decode()}")
            await update.message.reply_text("⚠️ There was an issue importing speakers. Are you sure you logged in to the userbot via SSH?")
    except Exception as e:
        logging.error(f"Exception running import_speakers.py: {e}")
        await update.message.reply_text("⚠️ Could not run the speaker import script.")

async def open_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_OPEN)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events WHERE status = 'PRE_OPEN' ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_PRE_OPEN_EVENT)
        conn.close()
        return

    try:
        hours = int(context.args[0])
        places = int(context.args[1])
        # Parse event datetime (can be "YYYY-MM-DD HH:MM")
        event_dt_str = f"{context.args[2]} {context.args[3]}"
        event_start_time = datetime.strptime(event_dt_str, '%Y-%m-%d %H:%M')
        # If no timezone info, assume UTC or local - but let's be consistent with get_now()
        # get_now() is datetime.now(ZoneInfo("UTC"))
        event_start_time = event_start_time.replace(tzinfo=ZoneInfo("UTC"))
        
        timeout_hours = 24
    except (IndexError, ValueError):
        await update.message.reply_text(messages.USAGE_OPEN)
        conn.close()
        return

    end_time = get_now() + timedelta(hours=hours)
    
    cursor.execute(
        "UPDATE events SET status = 'OPEN', end_time = ?, total_places = ?, waitlist_timeout_hours = ?, registration_duration_hours = ?, event_start_time = ? WHERE id = ?", 
        (end_time, places, timeout_hours, hours, event_start_time, event['id'])
    )
    conn.commit()
    log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'OPEN_EVENT', f'places={places}, end_time={end_time}')
    conn.close()

    scheduler.add_job(
        close_registration_job,
        'date',
        run_date=end_time,
        args=[event['id'], update.effective_chat.id],
        id=f"close_{event['id']}",
        replace_existing=True
    )

    schedule_reminders(event['id'], event_start_time)

    await update.message.reply_text(
        messages.REGISTRATION_OPENED.format(places=places, end_time=end_time.strftime('%H:%M:%S')),
        parse_mode='Markdown'
    )

async def close_registration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_CLOSE)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id FROM events WHERE status = 'OPEN' ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_OPEN_REGISTRATION)
        conn.close()
        return

    # Cancel scheduled job and run it now
    job_id = f"close_{event['id']}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    conn.close()
    await close_registration_job(event['id'], event['chat_id'])
    await update.message.reply_text(messages.REGISTRATION_CLOSED_MANUAL)

async def send_invites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_SEND_INVITES)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, total_places FROM events WHERE status = 'REVIEW' ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_REVIEW_EVENT)
        conn.close()
        return

    event_id = event['id']
    total_places = event['total_places']

    # Notify winners
    cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'ACCEPTED' AND notified_at IS NULL", (event_id,))
    winners = cursor.fetchall()
    for reg in winners:
        try:
            if reg['user_id']:
                await context.bot.send_message(reg['user_id'], messages.LOTTERY_WINNER)
                cursor.execute("UPDATE registrations SET notified_at = ? WHERE id = ?", (get_now(), reg['id']))
        except Exception as e:
            logging.error(f"Failed to notify winner {reg['user_id']}: {e}")

    # Notify waitlist
    cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'WAITLIST' AND notified_at IS NULL", (event_id,))
    losers = cursor.fetchall()
    for reg in losers:
        try:
            if reg['user_id']:
                # We need to find their actual position in the waitlist
                cursor.execute("SELECT COUNT(*) as pos FROM registrations WHERE event_id = ? AND status = 'WAITLIST' AND priority < ?", (event_id, reg['priority']))
                pos = cursor.fetchone()['pos']
                await context.bot.send_message(reg['user_id'], messages.WAITLIST_NOTIFICATION.format(position=pos + 1))
                cursor.execute("UPDATE registrations SET notified_at = ? WHERE id = ?", (get_now(), reg['id']))
        except Exception as e:
            logging.error(f"Failed to notify waitlist user {reg['user_id']}: {e}")

    cursor.execute("UPDATE events SET status = 'CLOSED' WHERE id = ?", (event_id,))
    conn.commit()

    # After notifications, check if there are still free spots (e.g. if someone unregistered during review)
    cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED')", (event_id,))
    accepted_count = cursor.fetchone()['count']
    
    # We also need to count speakers
    cursor.execute("SELECT COUNT(*) as count FROM speakers WHERE event_id = ?", (event_id,))
    speakers_count = cursor.fetchone()['count']
    
    spots_remaining = total_places - accepted_count - speakers_count
    if spots_remaining > 0:
        logging.info(f"Promoting {spots_remaining} users from waitlist after review...")
        for _ in range(spots_remaining):
            await invite_next(event_id)

    conn.close()
    await update.message.reply_text(messages.SEND_INVITES_SUCCESS)

async def reset_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_RESET)
        return

    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text(messages.RESET_CONFIRMATION)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_EVENT_FOUND)
        conn.close()
        return

    event_id = event['id']
    
    # Cancel any scheduled jobs
    job_id = f"close_{event_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # We no longer clear registrations, to keep logs and history intact
    
    # Retire the event by setting it to CANCELLED instead of PRE_OPEN
    cursor.execute("UPDATE events SET status = 'CANCELLED', end_time = NULL WHERE id = ?", (event_id,))
    
    conn.commit()
    log_action(event_id, update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'RESET_EVENT', '')
    conn.close()
    
    await update.message.reply_text(messages.RESET_SUCCESS)

async def send_reminder_job(event_id, days_left):
    logging.info(f"Sending {days_left}-day reminder for event {event_id}")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM registrations WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED') AND user_id IS NOT NULL", (event_id,))
    users = cursor.fetchall()
    conn.close()
    
    msg = messages.REMINDER_5_DAYS if days_left == 5 else messages.REMINDER_2_DAYS
    
    for row in users:
        try:
            await application.bot.send_message(row['user_id'], msg)
        except Exception as e:
            logging.error(f"Failed to send {days_left}-day reminder to user {row['user_id']}: {e}")

def schedule_reminders(event_id, event_start_time):
    if not event_start_time:
        return

    if isinstance(event_start_time, str):
        event_start_time = datetime.fromisoformat(event_start_time)
    if event_start_time.tzinfo is None:
        event_start_time = event_start_time.replace(tzinfo=ZoneInfo("UTC"))
        
    now = get_now()
    
    reminder_5_time = event_start_time - timedelta(days=5)
    if reminder_5_time > now:
        job_id = f"remind_5_{event_id}"
        scheduler.add_job(
            send_reminder_job,
            'date',
            run_date=reminder_5_time,
            args=[event_id, 5],
            id=job_id,
            replace_existing=True
        )
        logging.info(f"Scheduled 5-day reminder for event {event_id} at {reminder_5_time}")
        
    reminder_2_time = event_start_time - timedelta(days=2)
    if reminder_2_time > now:
        job_id = f"remind_2_{event_id}"
        scheduler.add_job(
            send_reminder_job,
            'date',
            run_date=reminder_2_time,
            args=[event_id, 2],
            id=job_id,
            replace_existing=True
        )
        logging.info(f"Scheduled 2-day reminder for event {event_id} at {reminder_2_time}")

async def close_registration_job(event_id, chat_id):
    logging.info(f"Closing registration for event {event_id}")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT total_places, speakers_group_id FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    if not event:
        conn.close()
        return
    
    total_places = event['total_places']
    cursor.execute("UPDATE events SET status = 'REVIEW' WHERE id = ?", (event_id,))
    log_action(event_id, None, None, None, 'CLOSE_REGISTRATION', 'Lottery started, awaiting review')
    
    # Count already accepted (e.g. guests)
    cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'ACCEPTED'", (event_id,))
    accepted_count = cursor.fetchone()['count']
    
    # Count speakers
    # We now rely exclusively on the speakers table which is auto-populated/manual
    speakers_count = 0

    # Add manual speakers
    cursor.execute("SELECT COUNT(*) as count FROM speakers WHERE event_id = ?", (event_id,))
    speakers_count += cursor.fetchone()['count']
    
    places_available = max(0, total_places - accepted_count - speakers_count)
    logging.info(f"Lottery: {total_places} total, {accepted_count} taken, {speakers_count} speakers, {places_available} available.")

    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND status = 'REGISTERED'",
        (event_id,)
    )
    regs = [dict(row) for row in cursor.fetchall()]
    
    if not regs:
        await application.bot.send_message(chat_id, messages.REGISTRATION_CLOSED_NO_REG)
        conn.commit()
        conn.close()
        return

    # Filter out speakers from the lottery pool to prevent double-dipping
    valid_regs = []
    for reg in regs:
        is_speaker = False
        # Check manual list
        if reg['username']:
            cursor.execute("SELECT id FROM speakers WHERE event_id = ? AND username = ?", (event_id, reg['username'].lower()))
            if cursor.fetchone():
                is_speaker = True
            
        # Check group membership
        if not is_speaker and event['speakers_group_id']:
             try:
                 member = await application.bot.get_chat_member(_get_group_id(event['speakers_group_id']), reg['user_id'])
                 if member.status in ["member", "administrator", "creator"]:
                     is_speaker = True
             except Exception:
                 pass
        
        if is_speaker:
             logging.info(f"User {reg['user_id']} is a speaker, skipping lottery.")
             # We mark them as accepted (or just leave them as registered but ignored? 
             # If we leave them as REGISTERED, they might get confused. 
             # Let's just ignore them for the lottery. They are speakers.)
        else:
             valid_regs.append(reg)
    
    regs = valid_regs

    random.shuffle(regs)
    winners = regs[:places_available]
    lottery_losers = regs[places_available:]
    
    for reg in winners:
        cursor.execute("UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", (reg['id'],))
        # Notifications skipped for review

    # Handle Waitlist Priorities
    # Shift existing waitlist users down by len(lottery_losers)
    if lottery_losers:
        cursor.execute(
            "UPDATE registrations SET priority = priority + ? WHERE event_id = ? AND status = 'WAITLIST'",
            (len(lottery_losers), event_id)
        )
        
    for i, reg in enumerate(lottery_losers):
        cursor.execute(
            "UPDATE registrations SET status = 'WAITLIST', priority = ? WHERE id = ?",
            (i, reg['id'])
        )
        # Notifications skipped for review

    conn.commit()

    # Immediate Promotion skipped during review - it will happen during send_invites if needed

    conn.close()
    log_action(event_id, None, "System", None, "LOTTERY_COMPLETE", f"Winners: {len(winners)}, Waitlist: {len(lottery_losers)}")
    await application.bot.send_message(chat_id, messages.REGISTRATION_CLOSED_SUMMARY.format(winners=len(winners), waitlist=len(lottery_losers)))
    await application.bot.send_message(chat_id, messages.LOTTERY_READY_FOR_REVIEW)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event or event['status'] == 'CANCELLED':
        await update.message.reply_text(messages.NO_EVENT_FOUND)
        conn.close()
        return

    # Check if user is in the speakers group
    if event['speakers_group_id']:
        try:
            member = await context.bot.get_chat_member(_get_group_id(event['speakers_group_id']), update.effective_user.id)
            if member.status in ["member", "administrator", "creator"]:
                await update.message.reply_text(messages.ALREADY_SPEAKER)
                log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_FAIL', 'User is in speakers group')
                conn.close()
                return
        except Exception as e:
            logging.error(f"Error checking speaker group membership: {e}")

    # Check if user is a speaker (manual list)
    if update.effective_user.username:
        cursor.execute(
            "SELECT id FROM speakers WHERE event_id = ? AND username = ?",
            (event['id'], update.effective_user.username.lower())
        )
        if cursor.fetchone():
            await update.message.reply_text(messages.ALREADY_SPEAKER)
            log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_FAIL', 'User is in manual speakers list')
            conn.close()
            return

    # Check if there is a pending invite by username (without user_id)
    if update.effective_user.username:
        cursor.execute(
            "SELECT * FROM registrations WHERE event_id = ? AND username = ? AND guest_of_user_id IS NOT NULL AND user_id IS NULL",
            (event['id'], update.effective_user.username)
        )
        pending_invite = cursor.fetchone()
        if pending_invite:
            cursor.execute(
                "UPDATE registrations SET user_id = ?, chat_id = ?, first_name = ?, signup_time = ? WHERE id = ?",
                (update.effective_user.id, update.effective_chat.id, update.effective_user.first_name, get_now(), pending_invite['id'])
            )
            conn.commit()
            log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_GUEST', 'Claimed guest spot')
            await update.message.reply_text(f"{messages.GUEST_IDENTIFIED}\n\n{messages.WELCOME_MESSAGE}")
            conn.close()
            return

    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND user_id = ? AND status != 'UNREGISTERED' AND status != 'EXPIRED'",
        (event['id'], update.effective_user.id)
    )
    existing_reg = cursor.fetchone()
    if existing_reg:
        if existing_reg['guest_of_user_id']:
             await update.message.reply_text(messages.ALREADY_INVITED_HAS_PLACE)
             log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_FAIL', 'Already has guest spot')
        else:
             await update.message.reply_text(messages.ALREADY_REGISTERED)
             log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_FAIL', 'Already registered')
        conn.close()
        return

    if event['status'] == 'PRE_OPEN':
        await update.message.reply_text(messages.NO_OPEN_REGISTRATION)
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER_FAIL', 'Event is PRE_OPEN')
        conn.close()
        return

    if event['status'] == 'OPEN':
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'REGISTERED', get_now())
        )
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER', 'Status: REGISTERED')
        try:
            await context.bot.send_message(update.effective_user.id, messages.REGISTER_SUCCESS_LOTTERY)
            if update.effective_chat.type != "private":
                await update.message.reply_text(messages.REGISTER_SUCCESS_PUBLIC.format(username=update.effective_user.username))
        except Exception:
            await update.message.reply_text(messages.START_IN_PRIVATE)
            cursor.execute("DELETE FROM registrations WHERE event_id = ? AND user_id = ?", (event['id'], update.effective_user.id))
            conn.commit()
            conn.close()
            return
    else:
        cursor.execute("SELECT MAX(priority) as max_p FROM registrations WHERE event_id = ? AND status = 'WAITLIST'", (event['id'],))
        row = cursor.fetchone()
        max_p = row['max_p'] if row['max_p'] is not None else -1
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'WAITLIST', get_now(), max_p + 1)
        )
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'REGISTER', 'Status: WAITLIST')
        try:
            await context.bot.send_message(update.effective_user.id, messages.REGISTER_WAITLIST.format(position=max_p + 2))
            if update.effective_chat.type != "private":
                await update.message.reply_text(messages.REGISTER_WAITLIST_PUBLIC.format(username=update.effective_user.username))
        except Exception:
            await update.message.reply_text(messages.START_IN_PRIVATE)
            cursor.execute("DELETE FROM registrations WHERE id = ?", (cursor.lastrowid,))
            conn.commit()
            conn.close()
            return
    
    conn.commit()
    conn.close()

async def invite_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event or event['status'] == 'CANCELLED':
        await update.message.reply_text(messages.NO_EVENT_FOUND)
        conn.close()
        return

    # Check state - only allow in PRE_OPEN
    if event['status'] != 'PRE_OPEN':
        await update.message.reply_text(messages.INVITE_ONLY_PRE_OPEN)
        conn.close()
        return

    # Check if sender is a speaker
    is_speaker = False
    if event['speakers_group_id']:
        try:
            member = await context.bot.get_chat_member(_get_group_id(event['speakers_group_id']), update.effective_user.id)
            if member.status in ["member", "administrator", "creator"]:
                is_speaker = True
        except Exception as e:
            logging.error(f"Error checking speaker group: {e}")

    if not is_speaker and update.effective_user.username:
        cursor.execute(
            "SELECT id FROM speakers WHERE event_id = ? AND username = ?",
            (event['id'], update.effective_user.username.lower())
        )
        if cursor.fetchone():
            is_speaker = True
            
    if not is_speaker:
        await update.message.reply_text(messages.ONLY_SPEAKERS_INVITE)
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', 'User is not a speaker')
        conn.close()
        return

    if not context.args:
        await update.message.reply_text(messages.USAGE_INVITE)
        conn.close()
        return

    guest_input = ' '.join(context.args).replace('<', '').replace('>', '').lstrip('@')
    is_tg_username = bool(re.match(r'^[a-zA-Z0-9_]{5,32}$', guest_input)) and not guest_input.isdigit()
    
    cleaned_phone = re.sub(r'[\s\-\(\)]', '', guest_input)
    is_phone = bool(re.match(r'^\+?\d{7,15}$', cleaned_phone))

    if not is_tg_username and not is_phone:
        await update.message.reply_text(messages.INVALID_INVITE_FORMAT)
        conn.close()
        return

    guest_username = cleaned_phone if is_phone else guest_input

    # Check if speaker tries to invite themselves
    if update.effective_user.username and guest_username.lower() == update.effective_user.username.lower():
        await update.message.reply_text(messages.ALREADY_SPEAKER)
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', 'Tried to invite self')
        conn.close()
        return

    # Check if speaker already invited someone
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND guest_of_user_id = ? AND status != 'UNREGISTERED'",
        (event['id'], update.effective_user.id)
    )
    existing_invite = cursor.fetchone()
    invite_to_delete_id = None
    old_guest_message = ""
    if existing_invite:
        if existing_invite['user_id'] is not None:
            await update.message.reply_text(messages.ALREADY_INVITED_GUEST)
            log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', 'Already invited a guest who is registered')
            conn.close()
            return
        elif existing_invite['username'].lower() != guest_username.lower():
            invite_to_delete_id = existing_invite['id']
            old_guest_message = messages.GUEST_REPLACED.format(old_username=existing_invite['username']) + "\n\n"

    # Check if guest is a speaker (manual list)
    cursor.execute(
        "SELECT id FROM speakers WHERE event_id = ? AND LOWER(username) = ?",
        (event['id'], guest_username.lower())
    )
    if cursor.fetchone():
        await update.message.reply_text(messages.GUEST_IS_SPEAKER.format(username=guest_username))
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', f'Guest {guest_username} is a speaker')
        conn.close()
        return

    # Check if guest is already registered (case insensitive)
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND LOWER(username) = ? AND status != 'UNREGISTERED'",
        (event['id'], guest_username.lower())
    )
    existing_reg = cursor.fetchone()
    
    log_details = None

    if existing_reg:
        # If they are already REGISTERED (lottery pool) or WAITLIST, upgrade them
        if existing_reg['status'] in ['REGISTERED', 'WAITLIST']:
            if invite_to_delete_id:
                cursor.execute("DELETE FROM registrations WHERE id = ?", (invite_to_delete_id,))
            else:
                # Upgrading from general pool, increase total_places so they don't consume a general spot
                cursor.execute("UPDATE events SET total_places = total_places + 1 WHERE id = ?", (event['id'],))
                
            cursor.execute(
                "UPDATE registrations SET status = 'ACCEPTED', guest_of_user_id = ? WHERE id = ?",
                (update.effective_user.id, existing_reg['id'])
            )
            log_details = f'Upgraded Guest: {guest_username}'
            await update.message.reply_text(old_guest_message + messages.GUEST_UPGRADED.format(username=guest_username))
            try:
                if existing_reg['user_id']:
                    await context.bot.send_message(existing_reg['user_id'], messages.GUEST_INVITED_NOTIFY.format(speaker=update.effective_user.first_name))
            except: pass
        elif existing_reg['status'] == 'ACCEPTED':
             # Already accepted (maybe via lottery or another invite?)
             if existing_reg['guest_of_user_id']:
                 await update.message.reply_text(messages.GUEST_ALREADY_GUEST.format(username=guest_username))
                 log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', f'Guest {guest_username} is already invited by someone else')
             else:
                 await update.message.reply_text(messages.GUEST_ALREADY_HAS_SPOT.format(username=guest_username))
                 log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_FAIL', f'Guest {guest_username} already has a spot')
        else:
             await update.message.reply_text(f"@{guest_username} has status {existing_reg['status']}.")
    else:
        if invite_to_delete_id:
            cursor.execute("DELETE FROM registrations WHERE id = ?", (invite_to_delete_id,))
        else:
            # Completely new guest, increase total_places so they don't consume a general spot
            cursor.execute("UPDATE events SET total_places = total_places + 1 WHERE id = ?", (event['id'],))
            
        # Create new registration for guest
        invite_token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id, signup_time, invite_token) VALUES (?, ?, ?, ?, ?, ?)",
            (event['id'], guest_username, 'ACCEPTED', update.effective_user.id, get_now(), invite_token)
        )
        log_details = f'Guest: {guest_username}'
        
        # Decide which message to show based on whether it was a phone number
        if is_phone:
            bot_username = context.bot.username
            link = f"https://t.me/{bot_username}?start={invite_token}"
            await update.message.reply_text(old_guest_message + messages.GUEST_INVITED_LINK.format(link=link))
        else:
            await update.message.reply_text(old_guest_message + messages.GUEST_INVITED_NEW.format(username=guest_username))
 
    conn.commit()
    conn.close()
    
    # Log after commit to avoid DB lock
    if log_details:
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'INVITE_GUEST', log_details)

async def unregister(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()

    if not event or event['status'] == 'CANCELLED':
        await update.message.reply_text(messages.NO_ACTIVE_REGISTRATION)
        conn.close()
        return

    # Check if user is a speaker
    is_speaker = False
    if event['speakers_group_id']:
        try:
            member = await context.bot.get_chat_member(_get_group_id(event['speakers_group_id']), update.effective_user.id)
            if member.status in ["member", "administrator", "creator"]:
                is_speaker = True
        except Exception as e:
            logging.error(f"Error checking speaker group membership: {e}")

    if not is_speaker and update.effective_user.username:
        cursor.execute(
            "SELECT id FROM speakers WHERE event_id = ? AND username = ?",
            (event['id'], update.effective_user.username.lower())
        )
        if cursor.fetchone():
            is_speaker = True
    
    if is_speaker:
        await update.message.reply_text(messages.SPEAKER_UNREGISTER_ERROR)
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'UNREGISTER_FAIL', 'Speaker cannot unregister')
        conn.close()
        return

    username = update.effective_user.username.lower() if update.effective_user.username else ""
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND (user_id = ? OR (LOWER(username) = ? AND user_id IS NULL)) AND status IN ('ACCEPTED', 'INVITED', 'WAITLIST', 'REGISTERED') ORDER BY id DESC LIMIT 1",
        (event['id'], update.effective_user.id, username)
    )
    reg = cursor.fetchone()
    
    if not reg:
        await update.message.reply_text(messages.NO_ACTIVE_REGISTRATION)
        log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'UNREGISTER_FAIL', 'No active registration')
        conn.close()
        return

    old_status = reg['status']
    
    if event['status'] in ('CLOSED', 'REVIEW') and old_status in ('ACCEPTED', 'INVITED'):
        keyboard = [
            [InlineKeyboardButton("Да, я не приду", callback_data=f"uyes_{reg['id']}"),
             InlineKeyboardButton("Нет, я приду!", callback_data=f"uno_{reg['id']}")]
        ]
        await update.message.reply_text(
            messages.UNREGISTER_CONFIRM,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        conn.close()
        return

    cursor.execute("UPDATE registrations SET status = 'UNREGISTERED', user_id = ? WHERE id = ?", (update.effective_user.id, reg['id']))
    conn.commit()
    log_action(event['id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'UNREGISTER', f'Old status: {old_status}')
    await update.message.reply_text(messages.UNREGISTERED_SUCCESS)
    
    if old_status in ('ACCEPTED', 'INVITED'):
        await invite_next(reg['event_id'])

    conn.close()

async def invite_next(event_id):
    if str(event_id) == '26':
        logging.info("Waitlist promotion stopped for event 26.")
        return

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status, event_start_time, total_places FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    if not event:
        conn.close()
        return

    # --- Strict Capacity Check ---
    cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED')", (event_id,))
    occupied_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM speakers WHERE event_id = ?", (event_id,))
    speakers_count = cursor.fetchone()['count']
    
    total_occupied = occupied_count + speakers_count
    
    if event['total_places'] is not None and total_occupied >= event['total_places']:
        logging.info(f"Strict Capacity Check: Event {event_id} is full (Total: {event['total_places']}, Occupied: {total_occupied}). Stopping waitlist promotion.")
        conn.close()
        return
    # -----------------------------

    # If in REVIEW, we promote to ACCEPTED silently
    # They will be notified later when admin runs /send_invites
    if event['status'] == 'REVIEW':
        cursor.execute(
            "SELECT * FROM registrations WHERE event_id = ? AND status = 'WAITLIST' ORDER BY priority ASC LIMIT 1",
            (event_id,)
        )
        next_reg = cursor.fetchone()
        if next_reg:
            # We do NOT set notified_at here, so /send_invites picks them up
            cursor.execute(
                "UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", 
                (next_reg['id'],)
            )
            conn.commit()
            log_action(event_id, next_reg['user_id'], next_reg['username'], next_reg['first_name'], 'PROMOTE_REVIEW', 'Waitlist promoted silently during review')
        conn.close()
        return
        
    # Default timeout is 24h
    default_timeout = 24
    
    # Calculate dynamic timeout based on distance to event
    now = get_now()
    timeout_hours = default_timeout
    
    if event['event_start_time']:
        # Ensure event_start_time has tzinfo for comparison
        event_start = event['event_start_time']
        if isinstance(event_start, str):
            event_start = datetime.fromisoformat(event_start)
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=ZoneInfo("UTC"))
            
        time_to_event = event_start - now
        
        # Stop promotions 2 hours before the event
        if time_to_event < timedelta(hours=2):
            logging.info(f"Event {event_id} starts in {time_to_event}, stopping waitlist promotions.")
            conn.close()
            return

        if time_to_event < timedelta(hours=24):
            timeout_hours = 1
        elif time_to_event < timedelta(hours=48):
            timeout_hours = 12
        else:
            timeout_hours = default_timeout
            
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND status = 'WAITLIST' ORDER BY priority ASC LIMIT 1",
        (event_id,)
    )
    next_reg = cursor.fetchone()
    
    if next_reg:
        expires_at = calculate_expiration_with_night_pause(get_now(), timeout_hours)
        cursor.execute(
            "UPDATE registrations SET status = 'INVITED', notified_at = ?, expires_at = ?, priority = 0 WHERE id = ?",
            (get_now(), expires_at, next_reg['id'])
        )
        reoder_waitlist(event_id, cursor)
        conn.commit()
        log_action(event_id, next_reg['user_id'], next_reg['username'], next_reg['first_name'], 'INVITE_NEXT', 'Waitlist invited')
        
        keyboard = [[InlineKeyboardButton("Accept", callback_data=f"acc_{next_reg['id']}"),
                     InlineKeyboardButton("Decline", callback_data=f"dec_{next_reg['id']}")]]
        
        try:
            await application.bot.send_message(
                next_reg['user_id'],
                messages.SPOT_OPENED_INVITE.format(hours=timeout_hours),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"Failed to notify waitlist user {next_reg['user_id']}: {e}")
            # Even if message fails, we keep them as INVITED for now
            # They will eventually EXPIRE if they don't see it
        
        scheduler.add_job(
            check_timeout_job, 
            'date', 
            run_date=expires_at, 
            args=[next_reg['id']],
            id=f"timeout_{next_reg['id']}",
            replace_existing=True
        )
    
    conn.close()

async def check_timeout_job(reg_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,))
    reg = cursor.fetchone()
    
    if reg and reg['status'] == 'INVITED':
        cursor.execute("UPDATE registrations SET status = 'EXPIRED' WHERE id = ?", (reg_id,))
        conn.commit()
        log_action(reg['event_id'], reg['user_id'], reg['username'], reg['first_name'], 'EXPIRE_INVITE', 'Waitlist invite expired')
        try:
            await application.bot.send_message(reg['user_id'], messages.INVITATION_EXPIRED)
        except: pass
        await invite_next(reg['event_id'])
    conn.close()

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, reg_id = query.data.split("_")
    reg_id = int(reg_id)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,))
    reg = cursor.fetchone()
    
    if not reg or reg['user_id'] != update.effective_user.id:
        await query.edit_message_text(messages.INVALID_INVITATION)
        conn.close()
        return
            
    if action in ("acc", "dec"):
        if reg['status'] != 'INVITED':
            await query.edit_message_text(messages.INVALID_INVITATION)
            conn.close()
            return
            
        if action == "acc":
            cursor.execute("UPDATE registrations SET status = 'ACCEPTED', priority = NULL WHERE id = ?", (reg_id,))
            reoder_waitlist(reg['event_id'], cursor)
            conn.commit()
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'CALLBACK_ACCEPT', '')
            await query.edit_message_text(messages.INVITATION_ACCEPTED)
        else:
            cursor.execute("UPDATE registrations SET status = 'UNREGISTERED', priority = NULL WHERE id = ?", (reg_id,))
            conn.commit() # Commit BEFORE invite_next
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'CALLBACK_DECLINE', '')
            await query.edit_message_text(messages.INVITATION_DECLINED)
            await invite_next(reg['event_id'])
            
    elif action == "uyes":
        if reg['status'] == 'UNREGISTERED':
            await query.edit_message_text(messages.UNREGISTERED_SUCCESS)
        else:
            old_status = reg['status']
            cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg_id,))
            conn.commit() # Commit BEFORE invite_next
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, update.effective_user.first_name, 'UNREGISTER', f'Confirmed unregister: {old_status}')
            await query.edit_message_text(messages.UNREGISTERED_SUCCESS)
            if old_status in ('ACCEPTED', 'INVITED'):
                await invite_next(reg['event_id'])
                
    elif action == "uno":
        await query.edit_message_text("Отлично, ждём тебя на конфе! 🎉")
            
    # Final commit just in case (e.g. for "acc" action which doesn't call invite_next)
    conn.commit()
    conn.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user is a speaker first
    is_speaker = False
    cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if event and event['status'] != 'CANCELLED':
        if event['speakers_group_id']:
            try:
                member = await context.bot.get_chat_member(_get_group_id(event['speakers_group_id']), update.effective_user.id)
                if member.status in ["member", "administrator", "creator"]:
                    is_speaker = True
            except Exception as e:
                logging.error(f"Error checking speaker group: {e}")

        if not is_speaker and update.effective_user.username:
            cursor.execute(
                "SELECT id FROM speakers WHERE event_id = ? AND username = ?",
                (event['id'], update.effective_user.username.lower())
            )
            if cursor.fetchone():
                is_speaker = True

    username = update.effective_user.username.lower() if update.effective_user.username else ""
    event_id = event['id'] if event else 0
    cursor.execute(
        "SELECT r.*, e.status as event_status FROM registrations r JOIN events e ON r.event_id = e.id WHERE e.id = ? AND (r.user_id = ? OR (LOWER(r.username) = ? AND r.user_id IS NULL)) ORDER BY r.id DESC LIMIT 1",
        (event_id, update.effective_user.id, username)
    )
    reg = cursor.fetchone()
    
    status_map = {
        'REGISTERED': messages.STATUS_REGISTERED,
        'INVITED': messages.STATUS_INVITED,
        'ACCEPTED': messages.STATUS_ACCEPTED,
        'WAITLIST': messages.STATUS_WAITLIST,
        'UNREGISTERED': messages.STATUS_UNREGISTERED,
        'EXPIRED': messages.STATUS_EXPIRED
    }

    if is_speaker:
        display_status = messages.STATUS_SPEAKER
        msg = messages.STATUS_MSG.format(status=display_status)
    elif not reg or reg['event_status'] == 'CANCELLED':
        await update.message.reply_text(messages.NOT_REGISTERED)
        conn.close()
        return
    else:
        # If the event is in REVIEW status, we should still show REGISTERED status to the user
        # unless they were already ACCEPTED before the lottery (e.g. as a guest)
        if reg['event_status'] == 'REVIEW' and reg['status'] in ('ACCEPTED', 'WAITLIST') and reg['guest_of_user_id'] is None:
            display_status = messages.STATUS_REGISTERED
        else:
            display_status = status_map.get(reg['status'], reg['status'])
            
        msg = messages.STATUS_MSG.format(status=display_status)
        if reg['status'] == 'WAITLIST' and (reg['event_status'] != 'REVIEW' or reg['guest_of_user_id'] is not None):
            cursor.execute("SELECT COUNT(*) as pos FROM registrations WHERE event_id = ? AND status = 'WAITLIST' AND priority < ?", (reg['event_id'], reg['priority']))
            msg += messages.WAITLIST_POSITION.format(position=cursor.fetchone()['pos'] + 1)
    
    await update.message.reply_text(msg)
    conn.close()

async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_EVENTS_FOUND)
        conn.close()
        return

    if event['status'] == 'CANCELLED':
        await update.message.reply_text(messages.EVENT_NOT_STARTED)
        conn.close()
        return

    # Count speakers
    # We now rely exclusively on the speakers table which is auto-populated/manual
    cursor.execute("SELECT COUNT(*) as count FROM speakers WHERE event_id = ?", (event['id'],))
    speakers_count = cursor.fetchone()['count']

    # Count guests
    cursor.execute(
        "SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED') AND guest_of_user_id IS NOT NULL",
        (event['id'],)
    )
    guests_count = cursor.fetchone()['count']

    # Count general accepted
    cursor.execute(
        "SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED') AND guest_of_user_id IS NULL",
        (event['id'],)
    )
    general_taken = cursor.fetchone()['count']

    # Count lottery pool
    cursor.execute(
        "SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'REGISTERED'",
        (event['id'],)
    )
    lottery_count = cursor.fetchone()['count']

    # Count waitlist
    cursor.execute(
        "SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'WAITLIST'",
        (event['id'],)
    )
    waitlist_count = cursor.fetchone()['count']

    # Count pending confirmations (already included in general_taken if guest_of_user_id is NULL)
    cursor.execute(
        "SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'INVITED'",
        (event['id'],)
    )
    invited_count = cursor.fetchone()['count']
    
    total_places = event['total_places']
    vip_total = speakers_count + guests_count
    
    if event['status'] == 'PRE_OPEN':
        msg = messages.EVENT_STATUS_HEADER_PRE_OPEN.format(
            status="PRE_OPEN",
            vip_taken=vip_total
        )
        msg += messages.EVENT_STATUS_PRE_OPEN
    elif event['status'] == 'REVIEW':
        general_total = max(0, total_places - vip_total) if total_places is not None else 0
        msg = messages.EVENT_STATUS_HEADER.format(
            status="REVIEW", 
            vip_taken=vip_total,
            general_taken=general_taken,
            general_total=general_total
        )
        msg += messages.EVENT_STATUS_REVIEW
        msg += messages.EVENT_STATUS_CLOSED.format(waitlist=waitlist_count)
    else:
        general_total = max(0, total_places - vip_total) if total_places is not None else 0
        status_str = "OPEN" if event['status'] == 'OPEN' else "CLOSED"
        msg = messages.EVENT_STATUS_HEADER.format(
            status=status_str, 
            vip_taken=vip_total,
            general_taken=general_taken,
            general_total=general_total
        )
        
        if event['status'] == 'OPEN':
            msg += messages.EVENT_STATUS_OPEN.format(count=lottery_count)
            if event['end_time']:
                try:
                    et = datetime.fromisoformat(event['end_time'])
                    # If it's naive, assume UTC as it was stored before
                    if et.tzinfo is None:
                        et = et.replace(tzinfo=ZoneInfo("UTC"))
                    # Convert to our local timezone
                    et_local = et.astimezone(TZ)
                    msg += messages.EVENT_REGISTRATION_ENDS.format(end_time=et_local.strftime("%Y-%m-%d %H:%M"))
                except Exception as e:
                    logging.error(f"Error formatting end_time in /list: {e}")
        elif event['status'] == 'CLOSED':
            msg += messages.EVENT_STATUS_CLOSED.format(waitlist=waitlist_count)
            if invited_count > 0:
                msg += messages.EVENT_STATUS_PENDING.format(invited=invited_count)

    await update.message.reply_text(msg, parse_mode='Markdown')
    conn.close()

async def post_init(app):
    global scheduler
    scheduler = AsyncIOScheduler()
    scheduler.start()
    logging.info("Scheduler started in post_init")

    # Set bot commands menu
    user_commands = [
        BotCommand("start", messages.DESC_START),
        BotCommand("register", messages.DESC_REGISTER),
        BotCommand("status", messages.DESC_STATUS),
        BotCommand("unregister", messages.DESC_UNREGISTER),
        BotCommand("list", messages.DESC_LIST),
        BotCommand("invite", messages.DESC_INVITE),
    ]
    
    admin_commands = user_commands + [
        BotCommand("create", messages.DESC_CREATE),
        BotCommand("open", messages.DESC_OPEN),
        BotCommand("close", messages.DESC_CLOSE),
        BotCommand("send_invites", messages.DESC_SEND_INVITES),
        BotCommand("reset", messages.DESC_RESET),
    ]
    
    # Default scope for everyone
    await app.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    
    # Specific scope for admins
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logging.error(f"Failed to set admin commands for {admin_id}: {e}")
            
    logging.info("Bot commands menu set with scoping")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, end_time FROM events WHERE status = 'OPEN'")
    open_events = cursor.fetchall()
    
    for event in open_events:
        try:
            end_time = datetime.fromisoformat(event['end_time'])
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=ZoneInfo("UTC"))
            
            if end_time <= get_now():
                # Already expired, run close logic now
                logging.info(f"Event {event['id']} expired while bot was down, closing now.")
                await close_registration_job(event['id'], event['chat_id'])
            else:
                logging.info(f"Rescheduling closure for event {event['id']} at {end_time}")
                scheduler.add_job(
                    close_registration_job,
                    'date',
                    run_date=end_time,
                    args=[event['id'], event['chat_id']],
                    id=f"close_{event['id']}",
                    replace_existing=True
                )
        except Exception as e:
            logging.error(f"Failed to resume job for event {event['id']}: {e}")

    # Reschedule timeout jobs for INVITED registrations
    cursor.execute("SELECT id, expires_at FROM registrations WHERE status = 'INVITED'")
    invited_regs = cursor.fetchall()
    for reg in invited_regs:
        try:
            expires_at = datetime.fromisoformat(reg['expires_at'])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=ZoneInfo("UTC"))

            if expires_at <= get_now():
                logging.info(f"Invitation {reg['id']} expired while bot was down, checking timeout now.")
                await check_timeout_job(reg['id'])
            else:
                logging.info(f"Rescheduling timeout for invitation {reg['id']} at {expires_at}")
                scheduler.add_job(
                    check_timeout_job,
                    'date',
                    run_date=expires_at,
                    args=[reg['id']],
                    id=f"timeout_{reg['id']}",
                    replace_existing=True
                )
        except Exception as e:
            logging.error(f"Failed to resume timeout job for registration {reg['id']}: {e}")

    # Reschedule reminders
    cursor.execute("SELECT id, event_start_time FROM events WHERE status != 'CANCELLED' AND event_start_time IS NOT NULL")
    active_events = cursor.fetchall()
    for event in active_events:
        try:
            schedule_reminders(event['id'], event['event_start_time'])
        except Exception as e:
            logging.error(f"Failed to reschedule reminders for event {event['id']}: {e}")
            
    conn.close()

def main():
    global application
    init_db()
    
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create", create_event))
    application.add_handler(CommandHandler("open", open_event_command))
    application.add_handler(CommandHandler("close", close_registration_command))
    application.add_handler(CommandHandler("send_invites", send_invites))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("invite", invite_guest))
    application.add_handler(CommandHandler("unregister", unregister))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("list", list_participants))
    application.add_handler(CommandHandler("reset", reset_event))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logging.info("Bot starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
