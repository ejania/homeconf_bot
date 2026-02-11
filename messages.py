# User-facing messages

WELCOME_MESSAGE = (
    "Welcome to the Event Registration Bot!\n\n"
    "Commands:\n"
    "/register - Register for the event\n"
    "/status - Check your status\n"
    "/unregister - Unregister from the event\n"
    "/list - Show current registration summary\n\n"
    "Admin commands:\n"
    "/open <minutes> <places> - Open registration\n"
    "/close - Close current registration early"
)

# Errors & Warnings
ONLY_ADMIN_OPEN = "Only admins can open registration."
ONLY_ADMIN_CLOSE = "Only admins can close registration."
REGISTRATION_ALREADY_OPEN = "❌ There is already an open registration. Close it first with /close."
USAGE_OPEN = "Usage: /open <minutes> <places> <speakers_group>"
ERROR_ACCESS_GROUP = "❌ Error: Could not access the specified group. Make sure the bot is a member and the ID/username is correct."
NO_OPEN_REGISTRATION = "No open registration found."
NO_EVENT_FOUND = "No event found."
ALREADY_SPEAKER = "You are already a speaker!"
ALREADY_REGISTERED = "You are already registered or on the waitlist."
ALREADY_INVITED_HAS_PLACE = "You have already been invited by a speaker and have a place."
START_IN_PRIVATE = "Please start me in private chat first so I can notify you!"
ONLY_SPEAKERS_INVITE = "Only speakers can invite guests."
ALREADY_INVITED_GUEST = "You have already invited a guest. You cannot change your guest."
USAGE_INVITE = "Usage: /invite <username>"
GUEST_ALREADY_GUEST = "@{username} is already a guest of another speaker."
GUEST_ALREADY_HAS_SPOT = "@{username} already has a spot."
NO_ACTIVE_REGISTRATION = "No active registration found."
INVALID_INVITATION = "Invalid or expired invitation."
NOT_REGISTERED = "Not registered."
NO_EVENTS_FOUND = "No events found."
PRIVATE_CHAT_ONLY = "Please use the command /{command} in this private chat."

# Success Messages
REGISTRATION_OPENED = (
    "✅ Registration opened for {places} places!\n"
    "Closing at: {end_time}."
)
REGISTRATION_CLOSED_MANUAL = "Registration closed manually."
REGISTRATION_CLOSED_NO_REG = "Registration closed. No one registered."
REGISTRATION_CLOSED_SUMMARY = "Registration closed! {winners} people got places. {waitlist} are on the waitlist."

REGISTER_SUCCESS_LOTTERY = "You have been registered for the event! I will notify you here after the lottery."
REGISTER_SUCCESS_PUBLIC = "@{username} registered!"
REGISTER_WAITLIST = "You've been added to the waitlist at position {position}."
REGISTER_WAITLIST_PUBLIC = "@{username} added to waitlist."

GUEST_IDENTIFIED = "You have been identified as a guest! Your spot is confirmed."
GUEST_UPGRADED = "@{username} has been upgraded to a guest spot!"
GUEST_INVITED_NOTIFY = "You have been invited as a guest by {speaker}! You now have a guaranteed spot."
GUEST_INVITED_NEW = "@{username} invited! They should run /register to confirm their details."

UNREGISTERED_SUCCESS = "Unregistered."
INVITATION_ACCEPTED = "Accepted!"
INVITATION_DECLINED = "Declined."

# Notifications
LOTTERY_WINNER = "Congratulations! You've won a place in the event!"
WAITLIST_NOTIFICATION = "You are on the waitlist. Your number is {position}."
INVITATION_EXPIRED = "Invitation expired."
SPOT_OPENED_INVITE = "A place has opened up! Do you accept? (Expires in {hours}h)"

# Status & List
STATUS_MSG = "Status: {status}"
WAITLIST_POSITION = "\nWaitlist position: {position}"
EVENT_STATUS_HEADER = "📊 *Event Status: {status}*\nPlaces filled: {filled}/{total}\n"
EVENT_STATUS_OPEN = "People currently in lottery pool: {count}\n\nLottery will run when registration closes."
EVENT_STATUS_CLOSED = "People on waitlist: {waitlist}\n"
EVENT_STATUS_PENDING = "Pending invitations: {invited}\n"
