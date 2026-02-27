Here are all the commands, in order:

---

1. One-time setup

# Install dependencies

uv sync

# Create your .env (copy the example, then edit it)

Copy-Item .env.example .env

Open .env and set these two lines correctly:
VAULT_PATH=F:\PROJECTS\hackathon-0\AI_Employee_Vault
DRY_RUN=true

---

2. Run the tests (verify everything works)

uv run pytest tests/ -v

Expected: 91 passed

---

3. Run the Gmail watcher (dry run — no real Gmail needed)

uv run python scripts/watchers/gmail_watcher.py --once

This reads DRY_RUN=true from your .env automatically.

---

4. Check the output

After running --once, verify these appeared:

# See the 3 generated email files

ls Needs_Action\email\

# See the audit log

cat Logs\2026-02-26.json

---

5. Run the full polling loop (stays running, checks every 2 min)

uv run python scripts/watchers/gmail_watcher.py

Stop it with Ctrl+C — it shuts down cleanly.

---

Summary

┌──────────────┬────────────────────────────────────────────────────────┐
│ What │ Command │
├──────────────┼────────────────────────────────────────────────────────┤
│ Install deps │ uv sync │
├──────────────┼────────────────────────────────────────────────────────┤
│ Run tests │ uv run pytest tests/ -v │
├──────────────┼────────────────────────────────────────────────────────┤
│ Dry-run once │ uv run python scripts/watchers/gmail_watcher.py --once │
├──────────────┼────────────────────────────────────────────────────────┤
│ Full loop │ uv run python scripts/watchers/gmail_watcher.py │
├──────────────┼────────────────────────────────────────────────────────┤
│ Lint check │ uv run ruff check scripts/ │
└──────────────┴────────────────────────────────────────────────────────┘

Your Gmail inbox
↓
Watcher finds unread+important emails
↓
Creates .md files in Needs_Action/email/
↓
Logs every action to Logs/2026-02-26.json
↓
Claude reads those files and reasons/acts
