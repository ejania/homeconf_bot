import logging
import random
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from models import init_db, get_db
import messages

load_dotenv()

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

# Global scheduler and application
scheduler = None
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


def log_action(event_id, user_id, username, action, details=""):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO action_logs (event_id, user_id, username, action, details) VALUES (?, ?, ?, ?, ?)",
            (event_id, user_id, username, action, details)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Failed to log action {action}: {e}")

async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_OPEN)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM events WHERE status IN ('OPEN', 'PRE_OPEN')")
    if cursor.fetchone():
        await update.message.reply_text(messages.REGISTRATION_ALREADY_OPEN)
        conn.close()
        return

    try:
        hours = int(context.args[0])
        places = int(context.args[1])
        speakers_group_id = context.args[2]
        # Optional 4th arg for timeout, default 24
        timeout_hours = int(context.args[3]) if len(context.args) > 3 else 24
    except (IndexError, ValueError):
        await update.message.reply_text(messages.USAGE_CREATE)
        conn.close()
        return

    # Validate that we can access the speakers group
    try:
        chat = await context.bot.get_chat(speakers_group_id)
        logging.info(f"Verified speakers group: {chat.title} ({chat.id})")
        actual_group_id = chat.id
    except Exception as e:
        await update.message.reply_text(messages.ERROR_ACCESS_GROUP)
        logging.error(f"Failed to access group {speakers_group_id}: {e}")
        conn.close()
        return

    cursor.execute(
        "INSERT INTO events (chat_id, status, total_places, speakers_group_id, waitlist_timeout_hours, registration_duration_hours) VALUES (?, ?, ?, ?, ?, ?)",
        (update.effective_chat.id, 'PRE_OPEN', places, str(actual_group_id), timeout_hours, hours)
    )
    conn.commit()
    event_id = cursor.lastrowid
    log_action(event_id, update.effective_user.id, update.effective_user.username, 'CREATE_EVENT', f'places={places}, hours={hours}')
    conn.close()

    await update.message.reply_text(messages.EVENT_CREATED)
    
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
            logging.info(f"Imported speakers: {stdout.decode()}")
            await update.message.reply_text(f"✅ Speakers automatically imported!")
        else:
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
    cursor.execute("SELECT * FROM events WHERE status = 'PRE_OPEN' ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_PRE_OPEN_EVENT)
        conn.close()
        return

    duration_hours = event['registration_duration_hours']
    end_time = datetime.now() + timedelta(hours=duration_hours)
    
    cursor.execute("UPDATE events SET status = 'OPEN', end_time = ? WHERE id = ?", (end_time, event['id']))
    conn.commit()
    log_action(event['id'], update.effective_user.id, update.effective_user.username, 'OPEN_EVENT', f'end_time={end_time}')
    conn.close()

    scheduler.add_job(
        close_registration_job,
        'date',
        run_date=end_time,
        args=[event['id'], update.effective_chat.id],
        id=f"close_{event['id']}",
        replace_existing=True
    )

    await update.message.reply_text(
        messages.REGISTRATION_OPENED.format(places=event['total_places'], end_time=end_time.strftime('%H:%M:%S')),
        parse_mode='Markdown'
    )

async def close_registration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_CLOSE)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id FROM events WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1")
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

async def reset_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text(messages.ONLY_ADMIN_RESET)
        return

    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text(messages.RESET_CONFIRMATION)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1")
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
    log_action(event_id, update.effective_user.id, update.effective_user.username, 'RESET_EVENT', '')
    conn.close()
    
    await update.message.reply_text(messages.RESET_SUCCESS)

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
    cursor.execute("UPDATE events SET status = 'CLOSED' WHERE id = ?", (event_id,))
    log_action(event_id, None, None, 'CLOSE_REGISTRATION', 'Lottery started')
    
    # Count already accepted (e.g. guests)
    cursor.execute("SELECT COUNT(*) as count FROM registrations WHERE event_id = ? AND status = 'ACCEPTED'", (event_id,))
    accepted_count = cursor.fetchone()['count']
    
    # Count speakers
    speakers_count = 0
    if event['speakers_group_id']:
        try:
            group_count = await application.bot.get_chat_member_count(event['speakers_group_id'])
            # Only subtract the bot if it is actually in the group
            try:
                bot_user = await application.bot.get_me()
                member = await application.bot.get_chat_member(event['speakers_group_id'], bot_user.id)
                if member.status not in ["left", "kicked"]:
                    group_count -= 1
            except Exception:
                pass 
            speakers_count += max(0, group_count)
        except Exception as e:
            logging.error(f"Failed to count speakers in group {event['speakers_group_id']}: {e}")

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
                 member = await application.bot.get_chat_member(event['speakers_group_id'], reg['user_id'])
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
        try:
            await application.bot.send_message(
                reg['user_id'], 
                messages.LOTTERY_WINNER
            )
        except Exception as e:
            logging.error(f"Failed to notify winner {reg['user_id']}: {e}")

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
        try:
            await application.bot.send_message(
                reg['user_id'], 
                messages.WAITLIST_NOTIFICATION.format(position=i+1)
            )
        except Exception as e:
            logging.error(f"Failed to notify waitlist user {reg['user_id']}: {e}")

    conn.commit()

    # Immediate Promotion if spots available
    spots_remaining = places_available - len(winners)
    if spots_remaining > 0:
        logging.info(f"Promoting {spots_remaining} users from waitlist...")
        # We need to loop because invite_next only invites one person.
        # Note: invite_next logic relies on 'WAITLIST' status.
        # Ensure we call it enough times.
        for _ in range(spots_remaining):
            await invite_next(event_id)

    conn.close()
    await application.bot.send_message(chat_id, messages.REGISTRATION_CLOSED_SUMMARY.format(winners=len(winners), waitlist=len(lottery_losers)))

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_EVENT_FOUND)
        conn.close()
        return

    # Check if user is in the speakers group
    if event['speakers_group_id']:
        try:
            member = await context.bot.get_chat_member(event['speakers_group_id'], update.effective_user.id)
            if member.status in ["member", "administrator", "creator"]:
                await update.message.reply_text(messages.ALREADY_SPEAKER)
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
                (update.effective_user.id, update.effective_chat.id, update.effective_user.first_name, datetime.now(), pending_invite['id'])
            )
            conn.commit()
            log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER_GUEST', 'Claimed guest spot')
            await update.message.reply_text(messages.GUEST_IDENTIFIED)
            conn.close()
            return

    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND user_id = ? AND status != 'UNREGISTERED'",
        (event['id'], update.effective_user.id)
    )
    existing_reg = cursor.fetchone()
    if existing_reg:
        if existing_reg['guest_of_user_id']:
             await update.message.reply_text(messages.ALREADY_INVITED_HAS_PLACE)
        else:
             await update.message.reply_text(messages.ALREADY_REGISTERED)
        conn.close()
        return

    if event['status'] == 'PRE_OPEN':
        await update.message.reply_text(messages.NO_OPEN_REGISTRATION)
        conn.close()
        return

    if event['status'] == 'OPEN':
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'REGISTERED', datetime.now())
        )
        log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER', 'Status: REGISTERED')
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
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'WAITLIST', datetime.now(), max_p + 1)
        )
        log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER', 'Status: WAITLIST')
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
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
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
            member = await context.bot.get_chat_member(event['speakers_group_id'], update.effective_user.id)
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
        conn.close()
        return

    # Check if speaker already invited someone
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND guest_of_user_id = ? AND status != 'UNREGISTERED'",
        (event['id'], update.effective_user.id)
    )
    if cursor.fetchone():
        await update.message.reply_text(messages.ALREADY_INVITED_GUEST)
        conn.close()
        return

    if not context.args:
        await update.message.reply_text(messages.USAGE_INVITE)
        conn.close()
        return
        
    guest_username = context.args[0].lstrip('@')
    
    # Check if speaker tries to invite themselves
    if update.effective_user.username and guest_username.lower() == update.effective_user.username.lower():
        await update.message.reply_text(messages.ALREADY_SPEAKER)
        conn.close()
        return

    # Check if guest is a speaker (manual list)
    cursor.execute(
        "SELECT id FROM speakers WHERE event_id = ? AND LOWER(username) = ?",
        (event['id'], guest_username.lower())
    )
    if cursor.fetchone():
        await update.message.reply_text(messages.GUEST_IS_SPEAKER.format(username=guest_username))
        conn.close()
        return

    # Check if guest is already registered (case insensitive)
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND LOWER(username) = ? AND status != 'UNREGISTERED'",
        (event['id'], guest_username.lower())
    )
    existing_reg = cursor.fetchone()
    
    if existing_reg:
        # If they are already REGISTERED (lottery pool) or WAITLIST, upgrade them
        if existing_reg['status'] in ['REGISTERED', 'WAITLIST']:
            cursor.execute(
                "UPDATE registrations SET status = 'ACCEPTED', guest_of_user_id = ? WHERE id = ?",
                (update.effective_user.id, existing_reg['id'])
            )
            log_action(event['id'], update.effective_user.id, update.effective_user.username, 'INVITE_GUEST', f'Upgraded Guest: {guest_username}')
            await update.message.reply_text(messages.GUEST_UPGRADED.format(username=guest_username))
            try:
                if existing_reg['user_id']:
                    await context.bot.send_message(existing_reg['user_id'], messages.GUEST_INVITED_NOTIFY.format(speaker=update.effective_user.first_name))
            except: pass
        elif existing_reg['status'] == 'ACCEPTED':
             # Already accepted (maybe via lottery or another invite?)
             if existing_reg['guest_of_user_id']:
                 await update.message.reply_text(messages.GUEST_ALREADY_GUEST.format(username=guest_username))
             else:
                 await update.message.reply_text(messages.GUEST_ALREADY_HAS_SPOT.format(username=guest_username))
        else:
             await update.message.reply_text(f"@{guest_username} has status {existing_reg['status']}.")
    else:
        # Create new registration for guest
        # We don't have user_id yet, so we insert username and status ACCEPTED
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id, signup_time) VALUES (?, ?, ?, ?, ?)",
            (event['id'], guest_username, 'ACCEPTED', update.effective_user.id, datetime.now())
        )
        log_action(event['id'], update.effective_user.id, update.effective_user.username, 'INVITE_GUEST', f'Guest: {guest_username}')
        await update.message.reply_text(messages.GUEST_INVITED_NEW.format(username=guest_username))

    conn.commit()
    conn.close()

async def unregister(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()

    # Check if user is a speaker
    if event:
        is_speaker = False
        if event['speakers_group_id']:
            try:
                member = await context.bot.get_chat_member(event['speakers_group_id'], update.effective_user.id)
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
            conn.close()
            return

    cursor.execute(
        "SELECT * FROM registrations WHERE user_id = ? AND status IN ('ACCEPTED', 'INVITED', 'WAITLIST', 'REGISTERED') ORDER BY id DESC LIMIT 1",
        (update.effective_user.id,)
    )
    reg = cursor.fetchone()
    
    if not reg:
        await update.message.reply_text(messages.NO_ACTIVE_REGISTRATION)
        conn.close()
        return

    old_status = reg['status']
    
    if event['status'] == 'CLOSED' and old_status in ('ACCEPTED', 'INVITED'):
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

    cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg['id'],))
    conn.commit()
    log_action(event['id'], update.effective_user.id, update.effective_user.username, 'UNREGISTER', f'Old status: {old_status}')
    await update.message.reply_text(messages.UNREGISTERED_SUCCESS)
    
    if old_status in ('ACCEPTED', 'INVITED'):
        await invite_next(reg['event_id'])

    conn.close()

async def invite_next(event_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT waitlist_timeout_hours FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    timeout_hours = event['waitlist_timeout_hours'] if event and event['waitlist_timeout_hours'] is not None else 24

    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND status = 'WAITLIST' ORDER BY priority ASC LIMIT 1",
        (event_id,)
    )
    next_reg = cursor.fetchone()
    
    if next_reg:
        expires_at = datetime.now() + timedelta(hours=timeout_hours)
        cursor.execute(
            "UPDATE registrations SET status = 'INVITED', notified_at = ?, expires_at = ? WHERE id = ?",
            (datetime.now(), expires_at, next_reg['id'])
        )
        conn.commit()
        log_action(event_id, next_reg['user_id'], next_reg['username'], 'INVITE_NEXT', 'Waitlist invited')
        
        keyboard = [[InlineKeyboardButton("Accept", callback_data=f"acc_{next_reg['id']}"),
                     InlineKeyboardButton("Decline", callback_data=f"dec_{next_reg['id']}")]]
        
        await application.bot.send_message(
            next_reg['user_id'],
            messages.SPOT_OPENED_INVITE.format(hours=timeout_hours),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
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
        log_action(reg['event_id'], reg['user_id'], reg['username'], 'EXPIRE_INVITE', 'Waitlist invite expired')
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
            cursor.execute("UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", (reg_id,))
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, 'CALLBACK_ACCEPT', '')
            await query.edit_message_text(messages.INVITATION_ACCEPTED)
        else:
            cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg_id,))
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, 'CALLBACK_DECLINE', '')
            await query.edit_message_text(messages.INVITATION_DECLINED)
            await invite_next(reg['event_id'])
            
    elif action == "uyes":
        if reg['status'] == 'UNREGISTERED':
            await query.edit_message_text(messages.UNREGISTERED_SUCCESS)
        else:
            old_status = reg['status']
            cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg_id,))
            log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, 'UNREGISTER', f'Confirmed unregister: {old_status}')
            await query.edit_message_text(messages.UNREGISTERED_SUCCESS)
            if old_status in ('ACCEPTED', 'INVITED'):
                await invite_next(reg['event_id'])
                
    elif action == "uno":
        await query.edit_message_text("Отлично, ждём тебя на конфе! 🎉")
            
    conn.commit()
    conn.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update, context):
        return

    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user is a speaker first
    is_speaker = False
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if event:
        if event['speakers_group_id']:
            try:
                member = await context.bot.get_chat_member(event['speakers_group_id'], update.effective_user.id)
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

    cursor.execute(
        "SELECT r.*, e.status as event_status FROM registrations r JOIN events e ON r.event_id = e.id WHERE r.user_id = ? ORDER BY r.id DESC LIMIT 1",
        (update.effective_user.id,)
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
    elif not reg:
        await update.message.reply_text(messages.NOT_REGISTERED)
        conn.close()
        return
    else:
        display_status = status_map.get(reg['status'], reg['status'])
        msg = messages.STATUS_MSG.format(status=display_status)
        if reg['status'] == 'WAITLIST':
            cursor.execute("SELECT COUNT(*) as pos FROM registrations WHERE event_id = ? AND status = 'WAITLIST' AND priority < ?", (reg['event_id'], reg['priority']))
            msg += messages.WAITLIST_POSITION.format(position=cursor.fetchone()['pos'] + 1)
    
    await update.message.reply_text(msg)
    conn.close()

async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text(messages.NO_EVENTS_FOUND)
        conn.close()
        return

    # Count speakers
    speakers_count = 0
    if event['speakers_group_id']:
        try:
            group_count = await context.bot.get_chat_member_count(event['speakers_group_id'])
            # Only subtract the bot if it is actually in the group
            try:
                bot_user = await context.bot.get_me()
                member = await context.bot.get_chat_member(event['speakers_group_id'], bot_user.id)
                if member.status not in ["left", "kicked"]:
                    group_count -= 1
            except Exception:
                pass
            speakers_count = max(0, group_count)
        except Exception as e:
            logging.error(f"Failed to count speakers in group {event['speakers_group_id']}: {e}")

    cursor.execute("SELECT COUNT(*) as count FROM speakers WHERE event_id = ?", (event['id'],))
    speakers_count += cursor.fetchone()['count']

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
    general_total = max(0, total_places - vip_total)
    
    status_str = "OPEN" if event['status'] == 'OPEN' else "CLOSED"
    if event['status'] == 'PRE_OPEN':
        status_str = "PRE_OPEN"

    msg = messages.EVENT_STATUS_HEADER.format(
        status=status_str, 
        vip_taken=vip_total,
        general_taken=general_taken,
        general_total=general_total
    )
    
    if event['status'] == 'OPEN':
        msg += messages.EVENT_STATUS_OPEN.format(count=lottery_count)
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
    commands = [
        BotCommand("start", messages.DESC_START),
        BotCommand("register", messages.DESC_REGISTER),
        BotCommand("status", messages.DESC_STATUS),
        BotCommand("unregister", messages.DESC_UNREGISTER),
        BotCommand("list", messages.DESC_LIST),
        BotCommand("invite", messages.DESC_INVITE),
        BotCommand("create", messages.DESC_CREATE),
        BotCommand("open", messages.DESC_OPEN),
        BotCommand("close", messages.DESC_CLOSE),
        BotCommand("reset", messages.DESC_RESET),
    ]
    await app.bot.set_my_commands(commands)
    logging.info("Bot commands menu set")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, end_time FROM events WHERE status = 'OPEN'")
    open_events = cursor.fetchall()
    
    for event in open_events:
        try:
            end_time = datetime.fromisoformat(event['end_time'])
            if end_time <= datetime.now():
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
            if expires_at <= datetime.now():
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
            
    conn.close()

def main():
    global application
    init_db()
    
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create", create_event))
    application.add_handler(CommandHandler("open", open_event_command))
    application.add_handler(CommandHandler("close", close_registration_command))
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
