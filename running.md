# AI Employee Vault — Running Guide

> Complete operational reference: dry-run testing, live production, and full pipeline verification.
> **Current phase: Silver Tier** (Gmail + WhatsApp + FileSystem watchers + email-triage skill)

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [DRY RUN Mode — Safe Testing](#3-dry-run-mode--safe-testing)
4. [Production (Live) Mode](#4-production-live-mode)
5. [Email Triage Skill](#5-email-triage-skill)
6. [Complete Pipeline Flow](#6-complete-pipeline-flow)
7. [Watcher Runner Commands](#7-watcher-runner-commands)
8. [PM2 — Production Deployment](#8-pm2--production-deployment)
9. [Verification Checklist](#9-verification-checklist)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

### Install dependencies
```bash
cd AI_Employee_Vault
uv sync
```

### Install Playwright browsers (WhatsApp watcher only)
```bash
uv run playwright install chromium
```

### Verify Python version (3.13+ required)
```bash
uv run python --version
# Python 3.13.x
```

---

## 2. Environment Setup

Copy the example and fill in your values:
```bash
cp .env.example .env
```

### Minimum required for each watcher

| Watcher | Required for DRY_RUN | Required for Live |
|---|---|---|
| filesystem | nothing | nothing |
| gmail | nothing | `GMAIL_CREDENTIALS_PATH` |
| whatsapp | nothing | `WHATSAPP_SESSION_PATH` (after QR setup) |

### Full `.env` reference

```env
# ─── Global ───────────────────────────────────────────
VAULT_PATH=.                        # Path to vault root (. = current dir)
DRY_RUN=true                        # true = safe test mode, false = real APIs
LOG_LEVEL=INFO                      # DEBUG | INFO | WARNING | ERROR
MAX_ACTIONS_PER_HOUR=20             # Safety cap
CHECK_INTERVAL_SECONDS=120          # Default polling interval

# ─── Gmail (Bronze) ───────────────────────────────────
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
GMAIL_PRIORITY_KEYWORDS=urgent,asap,emergency,critical

# ─── WhatsApp (Silver) ────────────────────────────────
WHATSAPP_SESSION_PATH=./sessions/whatsapp
WHATSAPP_KEYWORDS=urgent,asap,invoice,payment,help,pricing,quote,deadline
WHATSAPP_VIP_CHATS=John Client,Alice CEO       # Optional: these get priority +1

# ─── FileSystem (Silver) ──────────────────────────────
# No required vars — works out of the box
FILESYSTEM_WATCH_EXTENSIONS=.pdf,.csv,.xlsx,.txt,.md,.doc,.docx,.png,.jpg,.json
FILESYSTEM_IGNORE_PATTERNS=*.tmp,*.bak,.DS_Store,Thumbs.db
```

### Gmail — First-time setup (Live only)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project → Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop app) → Download as `credentials.json`
4. Place `credentials.json` in vault root
5. First live run opens a browser for Google sign-in → saves `token.json` automatically

### WhatsApp — First-time setup (Live only)

Run once to authenticate and save the session:
```bash
PYTHONPATH=. uv run python scripts/setup_whatsapp_session.py
```

Steps in the browser window:
1. Wait for WhatsApp Web QR code to appear
2. On your phone: WhatsApp → three dots (⋮) → **Linked Devices** → **Link a Device** → scan QR
3. Wait until your chats appear in the browser
4. Come back to the terminal → press **Enter**

Session saved to `./sessions/whatsapp/`. No QR scan needed again (valid ~14 days).

---

## 3. DRY RUN Mode — Safe Testing

> **DRY_RUN=true** (the default). No real APIs called. Synthetic test data generated.
> All files, logs, and Dashboard updates work exactly as in production.

### Run all 3 watchers once (dry run)

```bash
# FileSystem watcher — generates 3 synthetic files
PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/filesystem_watcher.py --once

# WhatsApp watcher — generates 3 synthetic messages (no browser)
PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/whatsapp_watcher.py --once

# Gmail watcher — generates 3 synthetic emails (no OAuth)
PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once
```

### What each watcher generates in DRY_RUN

**Gmail** → 3 emails in `Needs_Action/email/`:
- `CRITICAL`: "URGENT: Overdue Invoice #2024-001" (client)
- `HIGH`: "Q1 Strategy Meeting — Can you attend Thursday?"
- `LOW`: "50% off all products this weekend only!" (newsletter)

**WhatsApp** → 3 messages in `Needs_Action/whatsapp/`:
- `CRITICAL`: "URGENT: I need the payment processed asap! Invoice #INV-2026-001 was due yesterday" (John Client)
- `HIGH`: "Can someone send me the pricing for the enterprise plan?" (Team Chat)
- `MEDIUM`: "Hey, can we reschedule our meeting to Thursday?" (Sarah Colleague)

**FileSystem** → 3 files in `Needs_Action/file/`:
- `HIGH`: Invoice_January_2026.pdf (245 KB)
- `MEDIUM`: Q1_Sales_Report_2026.csv (4 KB)
- `MEDIUM`: screenshot_dashboard_2026-01.png (512 KB)

### Verify output after dry run

```bash
# Check queue counts across all domains
PYTHONPATH=. uv run python -m scripts.utils.vault_processor counts

# List pending items (all domains)
PYTHONPATH=. uv run python -m scripts.utils.vault_processor list-pending

# List email domain only
PYTHONPATH=. uv run python -m scripts.utils.vault_processor list-pending --subdomain email
```

### Check watcher status
```bash
PYTHONPATH=. uv run python scripts/watchers/runner.py status
```

Expected output:
```
Watcher     │ Status      │ PID   │ Uptime  │ Processed │ Prerequisites
────────────┼─────────────┼───────┼─────────┼───────────┼──────────────
gmail      │ 🔴 Stopped   │ —     │ —       │ 3         │ ✅ Ready
whatsapp   │ 🔴 Stopped   │ —     │ —       │ 3         │ ⚠️  Missing: WHATSAPP_SESSION_PATH
filesystem │ 🔴 Stopped   │ —     │ —       │ 3         │ ✅ Ready
```

> WhatsApp shows "Missing" for live mode — still fully works in DRY_RUN.

### Run full test suite
```bash
uv run pytest tests/ -v
# Expected: 319 passed
```

---

## 4. Production (Live) Mode

> Set `DRY_RUN=false` in `.env`. Real APIs. Real browser. Real emails.
> Complete prerequisites in Section 2 first.

### Pre-flight check
```bash
PYTHONPATH=. uv run python scripts/watchers/runner.py check all
```

All 3 should show `✅ Ready` before switching to live mode.

### Run watchers once in live mode (manual test)

```bash
# FileSystem — watches /Drop/ folder, scans for new files
PYTHONPATH=. DRY_RUN=false uv run python scripts/watchers/filesystem_watcher.py --once

# WhatsApp — opens headless browser, reads unread messages matching keywords
PYTHONPATH=. DRY_RUN=false uv run python scripts/watchers/whatsapp_watcher.py --once

# Gmail — polls Gmail API for unread important emails
PYTHONPATH=. DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once
```

### Test the FileSystem watcher (live)

Drop a real file into the `/Drop/` folder and run once:
```bash
cp some_invoice.pdf Drop/
PYTHONPATH=. DRY_RUN=false uv run python scripts/watchers/filesystem_watcher.py --once
# Check: Needs_Action/file/FILE_some_invoice_*.md should appear
```

### Run watchers as continuous daemons (dev mode, no PM2)

```bash
# Start all watchers as background subprocesses
PYTHONPATH=. uv run python scripts/watchers/runner.py start all

# Start with dry run
PYTHONPATH=. uv run python scripts/watchers/runner.py start all --dry-run

# Start a single watcher
PYTHONPATH=. uv run python scripts/watchers/runner.py start gmail

# Check what's running
PYTHONPATH=. uv run python scripts/watchers/runner.py status

# Stop everything
PYTHONPATH=. uv run python scripts/watchers/runner.py stop all
```

Watcher logs go to: `Logs/watcher_{name}.log`

### Polling intervals (live)

| Watcher | Default interval | Configurable via |
|---|---|---|
| filesystem | 30 seconds | `--interval 30` |
| whatsapp | 60 seconds | `--interval 60` |
| gmail | 120 seconds | `--interval 120` |

---

## 5. Email Triage Skill

> Reads emails from `Needs_Action/email/`, classifies them, generates Plans, moves to Done.
> Invoked via Claude Code — not a watcher daemon.

### How to trigger

In Claude Code:
```
/email-triage
```

### What it does (7 steps)

1. **Reads** all `.md` files in `Needs_Action/email/`
2. **Classifies** each email into one of 7 categories:
   - `REPLY_NEEDED` — sender expects a response
   - `INVOICE_ACTION` — financial document to process
   - `MEETING_REQUEST` — calendar / scheduling
   - `TASK_REQUEST` — action requested
   - `FYI_ONLY` — informational only
   - `ESCALATION` — complaint, legal keywords, unknown sender
   - `SPAM` — irrelevant or unsolicited
3. **Checks** Company_Handbook.md for contact tier and approval rules
4. **Writes** a Plan file: `Plans/PLAN_email_{CATEGORY}_{sender}_{timestamp}.md`
5. **Drafts** a response (for REPLY_NEEDED) — saved in Plan, never sent automatically
6. **Moves** processed email to `Done/`
7. **Updates** Dashboard.md (queue counts + activity log)

### Approval rules (from Company_Handbook.md)

| Action | Auto or Requires Approval |
|---|---|
| Triage / classify | Auto |
| Create Plan file | Auto |
| Draft a response | Auto (draft saved, not sent) |
| Send any email | **Requires approval** |
| Any financial action | **Requires approval** |
| Contact unknown person | **Requires approval** |
| Legal / contract keywords | **Requires approval** (escalated to CRITICAL) |

### Output files

- Plan: `Plans/PLAN_email_REPLY_NEEDED_john-doe_2026-02-27T09-00-00.md`
- Processed email moved to: `Done/EMAIL_john-doe_2026-02-27T08-58-21.md`

---

## 6. Complete Pipeline Flow

```
External World
     │
     ▼
┌────────────────────────────────────────┐
│  WATCHERS (perceive)                   │
│                                        │
│  Gmail → poll every 120s               │
│  WhatsApp → poll every 60s             │
│  FileSystem → watch /Drop/ every 30s  │
└────────────────┬───────────────────────┘
                 │ writes .md files
                 ▼
┌────────────────────────────────────────┐
│  Needs_Action/                         │
│   ├── email/     EMAIL_*.md            │
│   ├── whatsapp/  WHATSAPP_*.md         │
│   └── file/      FILE_*.md             │
└────────────────┬───────────────────────┘
                 │ /email-triage skill reads
                 ▼
┌────────────────────────────────────────┐
│  REASON (Claude Code skills)           │
│                                        │
│  /email-triage → classifies, plans,    │
│  drafts responses                      │
└────────────────┬───────────────────────┘
                 │ writes Plan files
                 ▼
┌────────────────────────────────────────┐
│  Plans/                                │
│   PLAN_email_REPLY_NEEDED_*.md         │
│   PLAN_email_ESCALATION_*.md           │
└────────────────┬───────────────────────┘
                 │
           ┌─────┴──────┐
           │             │
    No approval      Needs approval
    needed           (requires_approval: true)
           │             │
           ▼             ▼
        Done/      Pending_Approval/
                         │
                   Human reviews
                         │
               ┌─────────┴──────────┐
               │                    │
           Approved/            Rejected/
               │
         Execute via MCP
               │
            Done/
```

### Per-item lifecycle example (email)

```
1. Gmail watcher polls → finds "URGENT: Invoice" email
2. Creates: Needs_Action/email/EMAIL_client_2026-02-27T09-00-00.md
3. Logs to: Logs/2026-02-27.json
4. /email-triage runs → classifies as INVOICE_ACTION
5. Creates: Plans/PLAN_email_INVOICE_ACTION_client_2026-02-27T09-01-00.md
6. Moves email to: Done/EMAIL_client_2026-02-27T09-00-00.md
7. Updates: Dashboard.md (queue counts, activity log)
8. Human reviews Plan → decides to approve → moves to Approved/
9. MCP server executes → sends reply → item moved to Done/
```

---

## 7. Watcher Runner Commands

All commands require `PYTHONPATH=.` prefix:

```bash
# Show all registered watchers
PYTHONPATH=. uv run python scripts/watchers/runner.py list

# Check prerequisites (are all env vars set?)
PYTHONPATH=. uv run python scripts/watchers/runner.py check all
PYTHONPATH=. uv run python scripts/watchers/runner.py check gmail

# Status table (all watchers)
PYTHONPATH=. uv run python scripts/watchers/runner.py status
PYTHONPATH=. uv run python scripts/watchers/runner.py status --format json
PYTHONPATH=. uv run python scripts/watchers/runner.py status --format brief

# Start (background subprocesses)
PYTHONPATH=. uv run python scripts/watchers/runner.py start all
PYTHONPATH=. uv run python scripts/watchers/runner.py start all --dry-run
PYTHONPATH=. uv run python scripts/watchers/runner.py start gmail

# Stop
PYTHONPATH=. uv run python scripts/watchers/runner.py stop all
PYTHONPATH=. uv run python scripts/watchers/runner.py stop whatsapp

# Restart
PYTHONPATH=. uv run python scripts/watchers/runner.py restart gmail

# Generate PM2 config
PYTHONPATH=. uv run python scripts/watchers/runner.py generate-pm2
PYTHONPATH=. uv run python scripts/watchers/runner.py generate-pm2 --output ./ecosystem.config.js
```

---

## 8. PM2 — Production Deployment

> For long-running production: use PM2 instead of the runner.
> PM2 handles auto-restart, memory limits, log rotation, and boot persistence.

### Install PM2
```bash
npm install -g pm2
```

### Generate config from current settings
```bash
PYTHONPATH=. uv run python scripts/watchers/runner.py generate-pm2
# Creates: ecosystem.config.js
```

### PM2 commands

```bash
# Start all watchers
pm2 start ecosystem.config.js

# Check status
pm2 status
pm2 monit              # Real-time resource monitor

# View logs
pm2 logs                              # All watchers
pm2 logs aiemp-gmail-watcher         # Single watcher
pm2 logs aiemp-whatsapp-watcher --lines 50

# Restart / stop
pm2 restart aiemp-gmail-watcher
pm2 stop all
pm2 delete all

# Persist across reboots (run once)
pm2 save
pm2 startup            # Follow the printed instructions

# Reload without downtime
pm2 reload ecosystem.config.js
```

### Resource limits (auto-configured per watcher)

| Watcher | Memory limit | Max restarts | Restart delay |
|---|---|---|---|
| gmail | 200 MB | 10 | 5s |
| whatsapp | 500 MB | 5 | 10s |
| filesystem | 100 MB | 10 | 3s |

Logs written to: `Logs/pm2/{name}-watcher-{out,error}.log`

---

## 9. Verification Checklist

Run this sequence to confirm everything is working end-to-end.

### Step 1 — Install and sync
```bash
uv sync
uv run playwright install chromium
```

### Step 2 — Test suite (all 319 tests must pass)
```bash
uv run pytest tests/ -v --tb=short
# Expected: 319 passed
```

### Step 3 — DRY_RUN all 3 watchers
```bash
PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/filesystem_watcher.py --once
# Expected: "Processed 3 files"

PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/whatsapp_watcher.py --once
# Expected: "Processed 3 messages"

PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once
# Expected: "[DRY RUN] Skipping Gmail authentication" + "Processed 3 items"
```

### Step 4 — Check queue counts
```bash
PYTHONPATH=. uv run python -m scripts.utils.vault_processor counts
# Expected: Needs_Action: 9 | Plans: 2 | Pending_Approval: 0
```

### Step 5 — Runner status
```bash
PYTHONPATH=. uv run python scripts/watchers/runner.py status
# Expected: 3 rows, gmail + filesystem = ✅ Ready, whatsapp = ⚠️ Missing WHATSAPP_SESSION_PATH (expected in DRY_RUN)
```

### Step 6 — Email triage skill
In Claude Code:
```
/email-triage
```
Expected:
- Reads `Needs_Action/email/*.md`
- Creates `Plans/PLAN_email_*.md` for each non-spam email
- Moves processed emails to `Done/`
- Dashboard updated

### Step 7 — Check audit log
```bash
# View today's log entries (last 5)
PYTHONPATH=. python -c "
import json, pathlib
log = pathlib.Path('Logs/2026-02-27.json')
entries = json.loads(log.read_text())
for e in entries[-5:]:
    print(e['timestamp'], e['action_type'], e['result'])
"
```

### Step 8 — Lint (zero errors)
```bash
uv run ruff check scripts/
# Expected: All checks passed.
```

---

## 10. Troubleshooting

### `ModuleNotFoundError: No module named 'scripts'`
**Cause:** Python path not set.
**Fix:** Always prefix commands with `PYTHONPATH=.`

```bash
# Wrong
uv run python scripts/watchers/gmail_watcher.py --once

# Correct
PYTHONPATH=. uv run python scripts/watchers/gmail_watcher.py --once
```

### `UnicodeEncodeError` in runner.py status (Windows)
**Cause:** Windows cp1252 terminal can't render box-drawing characters.
**Fix:** Already patched — `sys.stdout.reconfigure(encoding='utf-8')` added to `__main__`.
If still happening: `PYTHONUTF8=1 PYTHONPATH=. uv run python scripts/watchers/runner.py status`

### WhatsApp: `TimeoutError` on `wait_for_selector`
**Cause:** WhatsApp Web didn't load QR/chats within timeout.
**Most common reason:** Browser opened, user scanned QR, but the 60-second timer expired before scanning completed.
**Fix:** Use `setup_whatsapp_session.py` (waits for Enter key, no timer):
```bash
PYTHONPATH=. uv run python scripts/setup_whatsapp_session.py
```

### WhatsApp: `Missing: WHATSAPP_SESSION_PATH` in runner status
**Cause:** `WHATSAPP_SESSION_PATH` not set in `.env`.
**Fix:** Set it (the path doesn't need to exist yet — it's created automatically):
```
WHATSAPP_SESSION_PATH=./sessions/whatsapp
```
Then run `setup_whatsapp_session.py` once to create the session.

### Gmail: `FileNotFoundError: credentials.json`
**Cause:** OAuth credentials not downloaded.
**Fix:** Follow Gmail setup in Section 2. Place `credentials.json` in vault root.

### Gmail: `token.json` expired / `RefreshError`
**Cause:** OAuth token expired and can't refresh.
**Fix:** Delete `token.json` and re-run the watcher in live mode — it will re-open the browser OAuth flow.
```bash
rm token.json
PYTHONPATH=. DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once
```

### Duplicate items created
**Cause:** Dedup state file corrupted or missing.
**Fix:** Check `.state/` folder. Each watcher maintains its own:
- `.state/gmail_processed.json`
- `.state/whatsapp_processed.json`
- `.state/filesystem_processed.json`

These are auto-created. Do not delete unless you want to reprocess everything.

### Dashboard.md looks broken
**Cause:** A section header or table structure was accidentally modified.
**Fix:** The dashboard_updater parses by `## ` headings — do not rename or reorder sections. Check git diff:
```bash
git diff Dashboard.md
```

---

*Last updated: 2026-02-27 | Phase: Silver Tier*
*Watchers implemented: Gmail (Bronze) + WhatsApp + FileSystem (Silver)*
*Skills implemented: email-triage (Bronze)*
