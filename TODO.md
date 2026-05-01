# TODO

- [x] **Rename `/cancel` to `/unregister`**: Update the command name and all internal references to improve clarity.
- [x] **Add Guest Support for Speakers**: Implement a feature allowing users in the speakers group to add guests to the event registration.
- [x] **Restrict Commands to Private Chat**: Prohibit user commands in group chats to avoid spam; ensure the bot only responds to registration-related commands in DMs.
- [x] **Polished User Messages**: Rewrite all user-facing bot responses to be more welcoming, polite, and professionally phrased.
- [x] **Speaker Count Logic**: Speakers should count towards the total number of places. Currently, if there are 3 speakers and 5 total places, only 2 regular users should be able to win the lottery (or register). Ensure speakers reduce the available pool size for the lottery.
- [x] **Immediate Waitlist Promotion**: After the lottery runs, if there are still free spots (e.g. total places > winners + speakers), users from the waitlist should be immediately promoted to fill those spots. Promotion must happen **in order of registration priority** and stop exactly when the total places are filled.
- [x] **Blocking Group Access Error**: If the bot fails to access the speakers group during `/create`, the registration should NOT proceed.
- [x] **Pre-Opening State Refactor**: 
    - Rename current `/open` to `/create`. This command initializes the event (sets spots, time in **hours**, speaker group) but keeps registration **closed** for the public.
    - During this "Pre-Open" state, speakers can invite guests.
    - Add a new `/open` command (no args) that transitions the event from "Pre-Open" to "Open", starting the timer and allowing public `/register`.
- [x] **Guest Spot Deduction**: When a speaker invites a guest, the number of *general* spots available for the lottery must decrease.
- [x] **Hardcode Admin IDs**: Moved to environment variable `ADMIN_IDS`.
- [x] **Guest Username Validation**: When a speaker invites a guest, check that the guest's username is not already a speaker or another speaker's guest.
- [x] **Status Visibility**: The `/list` command clearly distinguishes between VIP/Guest and General spots.
- [x] **Reset Command**: Initial implementation of the reset command.
- [x] **Closing Time Logic Validation**: Verified `apscheduler` handling.
- [x] **Cleanup**: All tests passing.

## Pending Tasks
- [x] **Handle Users Without Usernames**: Implement a strategy for users who don't have a Telegram username (e.g., use their first name + user ID for identification in lists and web dashboard).
- [x] **Logging Fixes**: Logging is still not working! (User reported missing logs for guest invites). Needs investigation.
- [x] **Lottery Randomness Test**: Add a test that checks that the lottery is random (two different draws should give different results).
- [x] **State-Change Logging**: Log all state-changing events (new user registration, opening registration, invites, etc.). Logs should be persistent and not deleted during reset.
- [x] **Improved Reset Logic**: The `/reset` command should delete the current event state entirely to allow for a fresh `/create` with new parameters, rather than just resetting the status.
- [x] **Unregister Confirmation**: When a user unregisters after the lottery has ended, if there are no free spots, ask for additional confirmation since they won't be able to re-register easily.
- [x] **Lottery Review Step**: Introduced a `REVIEW` state after the lottery runs. Admin can check results via `/list` or web dashboard before sending actual invites with `/send_invites`.
- [x] **Admin Dashboard (Logs)**: Create a simple web-based admin page to watch logs from the latest registration in real time.
- [x] **Admin Dashboard (Status)**: Add registration status, user lists, and waitlist visibility to the admin page.
- [x] **Invite by Phone Number**: Allow speakers to invite guests using their phone number if they don't have a Telegram username.
- [x] **Web Interface Scroll Persistence**: Fix the issue where the dashboard scrolls to the top on every refresh, making it difficult to read long lists.
- [x] **Rewrite Waitlist Promotion**: Rewrite waitlist promotion logic so that people don't have to respond at night to secure their place.
- [x] **Waitlist Timeout Re-registration**: If a person missed their waitlist response time and the waitlist invite timed out, they should be able to register again and get added to the end of the waitlist.
- [x] **Auto-update Total Places**: Automatically increase the total places for the event when guests are added, so that they don't consume general registration spots.
- [x] **Strict Capacity Check for Waitlist**: Count the total number of everyone (guests, speakers, lottery winners, etc.) before promoting from the waitlist to ensure we never overstep the total expected capacity.
- [x] **Database Cleanup & Event Renumbering**: Delete all old test events from the database and renumber the current event (#26) to be #8. 
- [x] **Test Event Flag**: Add a flag for `/create` to mark an event as "test-only". Test-only events should be automatically deleted from the database as soon as a new, real event is created.
- [x] **Polished Copywriting**: Review and edit all bot messages to sound even nicer, more welcoming, and more human.
- [x] **Dashboard Auth**: Require HTTP basic auth on the web dashboard (was open on the public IP and getting scanned). User: `admin`, password in `WEB_PASSWORD` env.
- [x] **Server & Repo Cleanup**: Delete one-off scripts and stale test fixtures from local repo and prod server; add `.DS_Store` and `data/` to `.gitignore`.
- [x] **Public Attendee List (`/who`)**: DM-only command listing event attendees in three sections — Орги (hardcoded: @ejania, @crassirostris, @awarehouse), Докладчики (from speakers table, excl. orgs), Слушатели (registrations.status=ACCEPTED, excl. orgs). Available only after `/send_invites` (status=CLOSED). Privacy notice appended to register/guest-invite/guest-accept/waitlist-accept messages.

## Pending — Future Features
- [ ] **Couples in the Lottery**: Allow two registered users to pair up so they win or lose the lottery together — never split.
    - Both must already be registered. Either runs `/pair @partner`; bot DMs partner with confirm flow. Pair locks only when both confirm.
    - In the lottery: pair = single ticket worth 2 seats. Atomic outcome (both ACCEPTED or both WAITLIST). Waitlist promotion only when ≥2 contiguous slots are available.
    - Pair priority = the *later* of the two confirmations (no late-pair queue jumping).
    - If either partner unregisters, the other auto-vacates.
    - Speakers excluded from pairing (already guaranteed; use existing `/invite` for their guest).
    - Open questions to settle before coding: max 1 partner per person? what if pair loses lottery and 1 spot opens later — strict "both or neither" forever, or offer split? cutoff to form pairs (until `/close`? until `/open`?). All discussed in conversation 2026-05-01.

## Notes for Next Session
- **Current State**: The bot is deployed on `104.248.28.207`. The current active flow uses `/create` -> `/open` -> `/close`.
- **Environment**: `ADMIN_IDS` is now in `.env`.
- **Testing**: Full test suite passes. Ensure to run `python3 -m unittest discover` before any deploy.
