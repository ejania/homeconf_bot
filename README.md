# Event Registration & Lottery Bot

A Telegram bot designed to handle event registrations with a fair lottery system and an automated waitlist.

## Features

- **Lottery System:** When registration closes, participants are randomly selected for available spots.
- **Automated Waitlist:** Users not selected in the lottery are placed on a waitlist. If a winner unregisters, the next person on the waitlist is automatically invited.
- **Guest Invitations:** Speakers can invite one guest each. These guests bypass the lottery and are guaranteed a spot (which is deducted from the general pool).
- **Private Chat Only:** All registration commands are restricted to private chats to reduce spam in group channels.
- **Speaker Protection:** Users in a specific "Speakers Group" are automatically recognized and prevented from taking up general registration spots.
- **Configurable Timeouts:** Admin-configurable invitation windows (default 24h) for waitlist users to accept their spots.
- **Persistence:** Uses SQLite to ensure registration data and active timers survive bot restarts.

## Commands

### User Commands
*All user commands (except `/start`) must be used in a private chat with the bot.*

- `/start` - Displays the welcome message and available commands.
- `/register` - Sign up for the currently open event.
- `/invite <username>` - (Speakers only) Invite a guest. The guest gets a guaranteed spot.
- `/status` - Check your current registration status (Registered, Accepted, Waitlist, etc.) and your position on the waitlist.
- `/unregister` - Unregister from the event or spot. If you were already accepted, this triggers an invitation for the next person on the waitlist.
- `/list` - Shows a summary of the current event's participation (spots filled, waitlist size).

### Admin Commands
- `/create <hours> <places> <speakers_group_id> [timeout_hours]` - Initialize a new event.
    - `hours`: Duration of registration in hours (once opened).
    - `places`: Total number of spots available.
    - `speakers_group_id`: The ID or @username of the speakers group.
    - Sets the status to `PRE_OPEN`. Speakers can invite guests.
- `/open` - Switch event from `PRE_OPEN` to `OPEN`.
    - Starts the countdown timer.
    - Opens general registration `/register`.
    - Speakers can no longer invite guests.
- `/close` - Manually close registration (triggers the lottery immediately).

## How it Works

1. **Pre-Open Phase:** Admin creates an event using `/create`. Status becomes `PRE_OPEN`. Speakers can use `/invite` to add their guests. General public cannot register yet.
2. **Registration Phase:** Admin runs `/open`. Status becomes `OPEN`. Speakers can no longer invite guests. Public can `/register`.
3. **The Lottery:** Once the timer expires (or `/close` is called), the bot shuffles the pool of registrants. Spots occupied by speaker guests are deducted from the total. The first `N` users (where `N` is available places) are marked as `ACCEPTED` and notified. All others are moved to the `WAITLIST`.
3. **The Waitlist:** If an accepted user unregisters, the bot finds the next person on the waitlist and sends them an invitation with "Accept" and "Decline" buttons.
4. **Invitation Timeout:** If an invited user doesn't respond within the `timeout_hours` window, their invitation expires, and the bot automatically invites the next person in line.

## Setup

1. **Environment:**
   - Python 3.10+
   - Create a `.env` file with your `BOT_TOKEN`.
2. **Installation:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install python-telegram-bot python-dotenv apscheduler
   ```
3. **Run:**
   ```bash
   python3 bot.py
   ```

The database (`bot_data.db`) will be initialized automatically on the first run.
