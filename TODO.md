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

## Pending Tasks
- [x] **Status Visibility**: The `/list` command should clearly distinguish between **VIP/Guest spots** (Taken by speakers + guests) and **General spots** (Lottery winners + Open).
- [x] **Reset Command**: Add an admin-only command (e.g., `/reset`) to clear all registrations and the waitlist for the current event, allowing for a fresh start or a re-run.
- [x] **Closing Time Logic Validation**: Double-check that `apscheduler` handles the `hours` based duration correctly (especially across container restarts).
- [x] **Cleanup**: All tests passing. Consolidated test suite verified via `unittest discover`.

## Notes for Next Session
- **Current State**: The bot is deployed on `104.248.28.207`. The current active flow uses `/create` -> `/open` -> `/close`.
- **Environment**: `ADMIN_IDS` is now in `.env`.
- **Testing**: Full test suite passes. Ensure to run `python3 -m unittest discover` before any deploy.
