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
- [x] **Lottery Randomness Test**: Add a test that checks that the lottery is random (two different draws should give different results).
- [x] **State-Change Logging**: Log all state-changing events (new user registration, opening registration, invites, etc.). Logs should be persistent and not deleted during reset.
- [x] **Improved Reset Logic**: The `/reset` command should delete the current event state entirely to allow for a fresh `/create` with new parameters, rather than just resetting the status.
- [x] **Unregister Confirmation**: When a user unregisters after the lottery has ended, if there are no free spots, ask for additional confirmation since they won't be able to re-register easily.
- [x] **Admin Dashboard (Logs)**: Create a simple web-based admin page to watch logs from the latest registration in real time.
- [x] **Admin Dashboard (Status)**: Add registration status, user lists, and waitlist visibility to the admin page.

## Notes for Next Session
- **Current State**: The bot is deployed on `104.248.28.207`. The current active flow uses `/create` -> `/open` -> `/close`.
- **Environment**: `ADMIN_IDS` is now in `.env`.
- **Testing**: Full test suite passes. Ensure to run `python3 -m unittest discover` before any deploy.
