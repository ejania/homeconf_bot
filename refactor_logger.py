import re

with open("bot.py", "r") as f:
    content = f.read()

helper = """
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

"""

# Insert helper
content = content.replace("async def create_event", helper + "async def create_event")

def inject_log(search, log_stmt):
    global content
    content = content.replace(search, search + "\n    " + log_stmt)

# 1. create_event
search_create = """
    cursor.execute(
        "INSERT INTO events (chat_id, status, total_places, speakers_group_id, waitlist_timeout_hours, registration_duration_hours) VALUES (?, ?, ?, ?, ?, ?)",
        (update.effective_chat.id, 'PRE_OPEN', places, str(actual_group_id), timeout_hours, hours)
    )
    conn.commit()
"""
log_create = "event_id = cursor.lastrowid\n    log_action(event_id, update.effective_user.id, update.effective_user.username, 'CREATE_EVENT', f'places={places}, hours={hours}')"
content = content.replace(search_create, search_create + "    " + log_create + "\n")

# 2. open_event_command
search_open = """    cursor.execute("UPDATE events SET status = 'OPEN', end_time = ? WHERE id = ?", (end_time, event['id']))
    conn.commit()"""
log_open = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'OPEN_EVENT', f'end_time={end_time}')"
content = content.replace(search_open, search_open + "\n    " + log_open)

# 3. reset_event
search_reset = """    # Reset event status to PRE_OPEN
    cursor.execute("UPDATE events SET status = 'PRE_OPEN', end_time = NULL WHERE id = ?", (event_id,))
    
    conn.commit()"""
log_reset = "log_action(event_id, update.effective_user.id, update.effective_user.username, 'RESET_EVENT', '')"
content = content.replace(search_reset, search_reset + "\n    " + log_reset)

# 4. register (OPEN loop)
search_reg = """        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'REGISTERED', datetime.now())
        )"""
log_reg = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER', 'Status: REGISTERED')"
content = content.replace(search_reg, search_reg + "\n        " + log_reg)

# 5. register (WAITLIST loop)
search_wait = """        cursor.execute(
            "INSERT INTO registrations (event_id, user_id, chat_id, username, first_name, status, signup_time, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event['id'], update.effective_user.id, update.effective_chat.id, update.effective_user.username, update.effective_user.first_name, 'WAITLIST', datetime.now(), max_p + 1)
        )"""
log_wait = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER', 'Status: WAITLIST')"
content = content.replace(search_wait, search_wait + "\n        " + log_wait)

# 6. register (Identified Guest)
search_ident = """            cursor.execute(
                "UPDATE registrations SET user_id = ?, chat_id = ?, first_name = ?, signup_time = ? WHERE id = ?",
                (update.effective_user.id, update.effective_chat.id, update.effective_user.first_name, datetime.now(), pending_invite['id'])
            )
            conn.commit()"""
log_ident = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'REGISTER_GUEST', 'Claimed guest spot')"
content = content.replace(search_ident, search_ident + "\n            " + log_ident)

# 7. invite_guest (new guest)
search_guest_new = """        # Create new registration for guest
        # We don't have user_id yet, so we insert username and status ACCEPTED
        cursor.execute(
            "INSERT INTO registrations (event_id, username, status, guest_of_user_id, signup_time) VALUES (?, ?, ?, ?, ?)",
            (event['id'], guest_username, 'ACCEPTED', update.effective_user.id, datetime.now())
        )"""
log_guest_new = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'INVITE_GUEST', f'Guest: {guest_username}')"
content = content.replace(search_guest_new, search_guest_new + "\n        " + log_guest_new)

# 8. invite_guest (upgrade guest)
search_guest_upg = """            cursor.execute(
                "UPDATE registrations SET status = 'ACCEPTED', guest_of_user_id = ? WHERE id = ?",
                (update.effective_user.id, existing_reg['id'])
            )"""
log_guest_upg = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'INVITE_GUEST', f'Upgraded Guest: {guest_username}')"
content = content.replace(search_guest_upg, search_guest_upg + "\n            " + log_guest_upg)

# 9. unregister
search_unreg = """    old_status = reg['status']
    cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg['id'],))
    conn.commit()"""
log_unreg = "log_action(event['id'], update.effective_user.id, update.effective_user.username, 'UNREGISTER', f'Old status: {old_status}')"
content = content.replace(search_unreg, search_unreg + "\n    " + log_unreg)

# 10. close_registration_job (lottery ran)
search_close = """    cursor.execute("UPDATE events SET status = 'CLOSED' WHERE id = ?", (event_id,))"""
log_close = "log_action(event_id, None, None, 'CLOSE_REGISTRATION', 'Lottery started')"
content = content.replace(search_close, search_close + "\n    " + log_close)

# 11. invite_next
search_inv = """        cursor.execute(
            "UPDATE registrations SET status = 'INVITED', notified_at = ?, expires_at = ? WHERE id = ?",
            (datetime.now(), expires_at, next_reg['id'])
        )
        conn.commit()"""
log_inv = "log_action(event_id, next_reg['user_id'], next_reg['username'], 'INVITE_NEXT', 'Waitlist invited')"
content = content.replace(search_inv, search_inv + "\n        " + log_inv)

# 12. check_timeout_job
search_to = """    if reg and reg['status'] == 'INVITED':
        cursor.execute("UPDATE registrations SET status = 'EXPIRED' WHERE id = ?", (reg_id,))
        conn.commit()"""
log_to = "log_action(reg['event_id'], reg['user_id'], reg['username'], 'EXPIRE_INVITE', 'Waitlist invite expired')"
content = content.replace(search_to, search_to + "\n        " + log_to)

# 13. callback_handler
search_cb_acc = """    if action == "acc":
        cursor.execute("UPDATE registrations SET status = 'ACCEPTED' WHERE id = ?", (reg_id,))"""
log_cb_acc = "log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, 'CALLBACK_ACCEPT', '')"
content = content.replace(search_cb_acc, search_cb_acc + "\n        " + log_cb_acc)

search_cb_dec = """    else:
        cursor.execute("UPDATE registrations SET status = 'UNREGISTERED' WHERE id = ?", (reg_id,))"""
log_cb_dec = "log_action(reg['event_id'], update.effective_user.id, update.effective_user.username, 'CALLBACK_DECLINE', '')"
content = content.replace(search_cb_dec, search_cb_dec + "\n        " + log_cb_dec)

with open("bot.py", "w") as f:
    f.write(content)
