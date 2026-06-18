# Deferred Human-Factor Issues

UX/logic issues that don't cause software crashes but can cause conference problems. Deferred for future conference cycle.

---

**1. Unclaimed phone-number guest permanently blocks a seat**

Speaker invites +phone → total_places increments, status is ACCEPTED with user_id=NULL. If the friend never claims the link, the seat is locked forever. No warning, no expiry, no auto-reclaim when registration opens. The speaker would need to proactively replace the guest using /invite again.

Possible fix: when /open is called (or N hours before close), warn any speaker whose phone-invited guest has user_id=NULL.

---

**2. No "registration closes in X hours" alert**

The auto-close fires silently. No broadcast to people who started the bot but haven't registered. Someone who planned to "register tonight" just misses the lottery with no second chance. The 5-day/2-day reminders only go to people who already have a confirmed spot.

Possible fix: scheduled broadcast to all users who've ever done /start for this bot, N hours before close.

---

**3. Pair request silently rejected when target pairs with someone else**

Alice sends /pair @bob. Bob accepts Carol's request instead. Alice is never notified. She sees "request sent" in chat history, but /status shows her as solo in the pool. She might not realize her pair never formed until after the lottery.

Possible fix: when a user who has a pending pair request aimed at them pairs with someone else, notify the requester.

---

**5. Post-lottery waitlist pairing is unavailable**

Two friends both lose the lottery and end up on the waitlist as singles. They'd prefer to link their fates (both get a spot or neither does). But /pair only works during OPEN. They're stuck attending separately or one misses out if only 1 seat opens.

Possible fix: allow /pair between WAITLIST registrations during REVIEW/CLOSED, with atomic promotion logic applied (both promoted together or neither).

---

**8. Waitlist users get no reminder they're still in line**

The 5-day and 2-day reminders go only to ACCEPTED/INVITED users. A waitlist user at position #5 might have completely forgotten they're waiting, especially weeks after registration. They might miss the 1-hour INVITED window simply because they stopped watching the bot.

Possible fix: include WAITLIST users in the 2-day reminder with a different message: "You're still on the waitlist at position #X. Spots may still open up!"

---

**9. No event details in the waitlist invite message**

"A spot opened! Will you come? (You have 24h to decide)" — if weeks passed since registration, a user might not remember what event this is or when it is. They're committing within 24h to something they can't immediately recall the date of.

Possible fix: include the event date/time in the SPOT_OPENED_INVITE and SPOT_OPENED_PAIR_INVITE messages.
