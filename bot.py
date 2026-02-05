import logging
import random
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from models import init_db, get_db

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

# Global scheduler and application
scheduler = None
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Event Registration Bot!\n\n"
        "Commands:\n"
        "/register - Register for the event\n"
        "/status - Check your status\n"
        "/cancel - Cancel your registration\n"
        "/list - Show current registration summary\n\n"
        "Admin commands:\n"
        "/open <minutes> <places> - Open registration\n"
        "/close - Close current registration early"
    )

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return True # For testing
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return member.status in ["creator", "administrator"]

async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can open registration.")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM events WHERE status = 'OPEN'")
    if cursor.fetchone():
        await update.message.reply_text("❌ There is already an open registration. Close it first with /close.")
        conn.close()
        return

    try:
        minutes = int(context.args[0])
        places = int(context.args[1])
        speakers_group_id = context.args[2]
        # Optional 4th arg for timeout, default 24
        timeout_hours = int(context.args[3]) if len(context.args) > 3 else 24
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /open <minutes> <places> <speakers_group>")
        conn.close()
        return

    # Validate that we can access the speakers group
    try:
        chat = await context.bot.get_chat(speakers_group_id)
        logging.info(f"Verified speakers group: {chat.title} ({chat.id})")
        actual_group_id = chat.id
    except Exception as e:
        await update.message.reply_text(f"❌ Error: Could not access the specified group. Make sure the bot is a member and the ID/username is correct.")
        logging.error(f"Failed to access group {speakers_group_id}: {e}")
        conn.close()
        return

    end_time = datetime.now() + timedelta(minutes=minutes)
    cursor.execute(
        "INSERT INTO events (chat_id, status, total_places, speakers_group_id, waitlist_timeout_hours, end_time) VALUES (?, ?, ?, ?, ?, ?)",
        (update.effective_chat.id, 'OPEN', places, str(actual_group_id), timeout_hours, end_time)
    )
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()

    scheduler.add_job(
        close_registration_job,
        'date',
        run_date=end_time,
        args=[event_id, update.effective_chat.id],
        id=f"close_{event_id}",
        replace_existing=True
    )

    await update.message.reply_text(
        f"✅ Registration opened for {places} places!\n"
        f"Closing at: {end_time.strftime('%H:%M:%S')}.",
        parse_mode='Markdown'
    )

async def close_registration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can close registration.")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id FROM events WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text("No open registration found.")
        conn.close()
        return

    # Cancel scheduled job and run it now
    job_id = f"close_{event['id']}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    conn.close()
    await close_registration_job(event['id'], event['chat_id'])
    await update.message.reply_text("Registration closed manually.")

async def close_registration_job(event_id, chat_id):
    logging.info(f"Closing registration for event {event_id}")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT total_places FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    if not event:
        conn.close()
        return
    
    total_places = event['total_places']
    cursor.execute("UPDATE events SET status = 'CLOSED' WHERE id = ?", (event_id,))
    
    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND status = 'REGISTERED'",
        (event_id,)
    )
    regs = [dict(row) for row in cursor.fetchall()]
    
    if not regs:
        await application.bot.send_message(chat_id, "Registration closed. No one registered.")
        conn.commit()
        conn.close()
        return

    random.shuffle(regs)
    winners = regs[:total_places]
    waitlist = regs[total_places:]
    
    for reg in winners:
        cursor.execute("UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", (reg['id'],))
        try:
            await application.bot.send_message(
                reg['user_id'], 
                "Congratulations! You've won a place in the event!"
            )
        except Exception as e:
            logging.error(f"Failed to notify winner {reg['user_id']}: {e}")

    for i, reg in enumerate(waitlist):
        cursor.execute(
            "UPDATE registrations SET status = 'WAITLIST', priority = ? WHERE id = ?",
            (i, reg['id'])
        )
        try:
            await application.bot.send_message(
                reg['user_id'], 
                f"You are on the waitlist. Your number is {i+1}."
            )
        except Exception as e:
            logging.error(f"Failed to notify waitlist user {reg['user_id']}: {e}")

    conn.commit()
    conn.close()
    await application.bot.send_message(chat_id, f"Registration closed! {len(winners)} people got places. {len(waitlist)} are on the waitlist.")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text("No event found.")
        conn.close()
        return

    # Check if user is in the speakers group
    if event['speakers_group_id']:
        try:
            member = await context.bot.get_chat_member(event['speakers_group_id'], update.effective_user.id)
            if member.status in ["member", "administrator", "creator"]:
                await update.message.reply_text("You are already a speaker!")
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
            await update.message.reply_text("You are already a speaker!")
            conn.close()
            return

    cursor.execute(
        "SELECT * FROM registrations WHERE event_id = ? AND user_id = ? AND status != 'CANCELLED'",
        (event['id'], update.effective_user.id)
    )
    if cursor.fetchone():
        await update.message.reply_text("You are already registered or on the waitlist.")
        conn.close()
        return

    if event['status'] == 'OPEN':
        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'REGISTERED', datetime.now())
        )
        try:
            await context.bot.send_message(update.effective_user.id, "You have been registered for the event! I will notify you here after the lottery.")
            if update.effective_chat.type != "private":
                await update.message.reply_text(f"@{update.effective_user.username} registered!")
        except Exception:
            await update.message.reply_text("Please start me in private chat first so I can notify you!")
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
        try:
            await context.bot.send_message(update.effective_user.id, f"You've been added to the waitlist at position {max_p + 2}.")
            if update.effective_chat.type != "private":
                await update.message.reply_text(f"@{update.effective_user.username} added to waitlist.")
        except Exception:
            await update.message.reply_text("Please start me in private chat first so I can notify you!")
            cursor.execute("DELETE FROM registrations WHERE id = ?", (cursor.lastrowid,))
            conn.commit()
            conn.close()
            return
    
    conn.commit()
    conn.close()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM registrations WHERE user_id = ? AND status IN ('ACCEPTED', 'INVITED', 'WAITLIST', 'REGISTERED') ORDER BY id DESC LIMIT 1",
        (update.effective_user.id,)
    )
    reg = cursor.fetchone()
    
    if not reg:
        await update.message.reply_text("No active registration found.")
        conn.close()
        return

    old_status = reg['status']
    cursor.execute("UPDATE registrations SET status = 'CANCELLED' WHERE id = ?", (reg['id'],))
    conn.commit()
    await update.message.reply_text("Cancelled.")
    
    if old_status in ('ACCEPTED', 'INVITED'):
        await invite_next(reg['event_id'])

    conn.close()

async def invite_next(event_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT waitlist_timeout_hours FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    timeout_hours = event['waitlist_timeout_hours'] if event else 24

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
        
        keyboard = [[InlineKeyboardButton("Accept", callback_data=f"acc_{next_reg['id']}"),
                     InlineKeyboardButton("Decline", callback_data=f"dec_{next_reg['id']}")]]
        
        await application.bot.send_message(
            next_reg['user_id'],
            f"A place has opened up! Do you accept? (Expires in {timeout_hours}h)",
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
        try:
            await application.bot.send_message(reg['user_id'], "Invitation expired.")
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
    
    if not reg or reg['status'] != 'INVITED' or reg['user_id'] != update.effective_user.id:
        await query.edit_message_text("Invalid or expired invitation.")
        conn.close()
        return
            
    if action == "acc":
        cursor.execute("UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", (reg_id,))
        await query.edit_message_text("Accepted!")
    else:
        cursor.execute("UPDATE registrations SET status = 'CANCELLED' WHERE id = ?", (reg_id,))
        await query.edit_message_text("Declined.")
        await invite_next(reg['event_id'])
            
    conn.commit()
    conn.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT r.*, e.status as event_status FROM registrations r JOIN events e ON r.event_id = e.id WHERE r.user_id = ? ORDER BY r.id DESC LIMIT 1",
        (update.effective_user.id,)
    )
    reg = cursor.fetchone()
    
    if not reg:
        await update.message.reply_text("Not registered.")
    else:
        msg = f"Status: {reg['status']}"
        if reg['status'] == 'WAITLIST':
            cursor.execute("SELECT COUNT(*) as pos FROM registrations WHERE event_id = ? AND status = 'WAITLIST' AND priority < ?", (reg['event_id'], reg['priority']))
            msg += f"\nWaitlist position: {cursor.fetchone()['pos'] + 1}"
        await update.message.reply_text(msg)
    conn.close()

async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    if not event:
        await update.message.reply_text("No events found.")
        conn.close()
        return

    cursor.execute("SELECT status, COUNT(*) as count FROM registrations WHERE event_id = ? GROUP BY status", (event['id'],))
    rows = cursor.fetchall()
    counts = {row['status']: row['count'] for row in rows}
    
    accepted = counts.get('ACCEPTED', 0)
    invited = counts.get('INVITED', 0)
    waitlist = counts.get('WAITLIST', 0)
    registered = counts.get('REGISTERED', 0)
    
    total_places = event['total_places']
    status_str = "OPEN" if event['status'] == 'OPEN' else "CLOSED"
    
    msg = (
        f"📊 *Event Status: {status_str}*\n"
        f"Places filled: {accepted + invited}/{total_places}\n"
    )
    
    if event['status'] == 'OPEN':
        msg += f"People currently in lottery pool: {registered}\n"
        msg += "\nLottery will run when registration closes."
    else:
        msg += f"People on waitlist: {waitlist}\n"
        if invited > 0:
            msg += f"Pending invitations: {invited}\n"

    await update.message.reply_text(msg, parse_mode='Markdown')
    conn.close()

async def post_init(app):
    global scheduler
    scheduler = AsyncIOScheduler()
    scheduler.start()
    logging.info("Scheduler started in post_init")
    
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
            
    conn.close()

def main():
    global application
    init_db()
    
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("open", open_registration))
    application.add_handler(CommandHandler("close", close_registration_command))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("list", list_participants))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logging.info("Bot starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
