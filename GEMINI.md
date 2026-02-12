# Deployment Information

This project is deployed on a DigitalOcean droplet.

## Server Details
- **IP Address:** 104.248.28.207
- **SSH User:** root
- **Remote Directory:** `~/homeconf_bot`
- **Deployment Method:** Docker Compose

## Local Configuration
- **SSH Key:** `~/.ssh/id_ed25519_gemini`

## Redeployment Procedure
To deploy new changes:
1. Sync files:
   ```bash
   rsync -avz -e "ssh -i ~/.ssh/id_ed25519_gemini" --exclude 'venv' --exclude '__pycache__' --exclude '.git' --exclude '.DS_Store' --exclude 'bot.log' --exclude 'bot_data.db' ./ root@104.248.28.207:~/homeconf_bot/
   ```
2. Restart container:
   ```bash
   ssh -i ~/.ssh/id_ed25519_gemini root@104.248.28.207 "cd ~/homeconf_bot && docker compose up -d --build"
   ```

## Logs and Maintenance
- **View logs:** `ssh -i ~/.ssh/id_ed25519_gemini root@104.248.28.207 "docker logs -f homeconf_bot"`
- **Stop bot:** `ssh -i ~/.ssh/id_ed25519_gemini root@104.248.28.207 "cd ~/homeconf_bot && docker compose down"`
- **Database Location:** `~/homeconf_bot/data/bot_data.db` (on server)

## Pending Tasks & Bugs
- **Check `TODO.md`**: This file contains the prioritized list of bugs and feature requests reported by the user. Always check this file first when starting a new session.

## Development Requirements
- **Testing:**
  - All new features must be accompanied by comprehensive tests.
  - **MANDATORY:** Always execute the full test suite (`python3 -m unittest discover`) before requesting a deploy or considering a feature complete. Do not rely solely on targeted tests.
- **Language & Style:**
  - All user-facing messages must be in **Russian**.
  - Tone should be **friendly and informal** (not too official).
