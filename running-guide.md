# AI Employee Vault — Running Guide

> Complete operational reference: dry-run testing, live production, and full pipeline verification.
> **Current phase: 🥈 Silver Tier** — 4 watchers · 4 skills · 2 MCP servers · HITL workflow · Orchestrator

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [DRY_RUN Mode — Safe Testing](#3-dry-run-mode--safe-testing)
4. [Production (Live) Mode](#4-production-live-mode)
5. [Skills — Claude Code Commands](#5-skills--claude-code-commands)
6. [HITL Workflow — Approve / Reject Actions](#6-hitl-workflow--approve--reject-actions)
7. [Orchestrator](#7-orchestrator)
8. [Scheduled Tasks](#8-scheduled-tasks)
9. [MCP Servers](#9-mcp-servers)
10. [Watcher Runner Reference](#10-watcher-runner-reference)
11. [PM2 — Production Deployment](#11-pm2--production-deployment)
12. [Complete Pipeline Flow](#12-complete-pipeline-flow)
13. [Verification Checklist](#13-verification-checklist)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Prerequisites

### Install Python dependencies
```bash
cd AI_Employee_Vault
uv sync
```

### Install Playwright browsers (WhatsApp watcher only)
```bash
uv run playwright install chromium
```

### Install Node.js dependencies for MCP servers
```bash
cd mcp-servers/email-mcp && npm install && npm run build && cd ../..
cd mcp-servers/linkedin-mcp && npm install && npm run build && cd ../..
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

### What each watcher needs

| Watcher | DRY_RUN | Live mode |
|---------|---------|-----------|
| `filesystem` | nothing | nothing |
| `gmail` | nothing | `credentials.json` + `token.json` |
| `whatsapp` | nothing | `WHATSAPP_SESSION_PATH` (after QR setup) |
| `approval` | nothing | nothing (relies on MCP servers) |

### Full `.env` reference

```env
# ─── Global ────────────────────────────────────────────────────
VAULT_PATH=.                        # Absolute path to vault root (. = cwd)
DRY_RUN=true                        # true = safe test mode, false = real APIs
LOG_LEVEL=INFO                      # DEBUG | INFO | WARNING | ERROR
MAX_ACTIONS_PER_HOUR=20             # Safety cap on AI actions
CHECK_INTERVAL_SECONDS=120          # Default watcher polling interval

# ─── Gmail (Bronze) ────────────────────────────────────────────
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
GMAIL_PRIORITY_KEYWORDS=urgent,asap,emergency,critical

# ─── WhatsApp (Silver) ─────────────────────────────────────────
WHATSAPP_SESSION_PATH=./sessions/whatsapp
WHATSAPP_KEYWORDS=urgent,asap,invoice,payment,help,pricing,quote,deadline
WHATSAPP_VIP_CHATS=John Client,Alice CEO    # Upgrade these contacts by 1 priority level
WHATSAPP_MAX_CHATS=10

# ─── FileSystem (Silver) ───────────────────────────────────────
FILESYSTEM_WATCH_EXTENSIONS=.pdf,.csv,.xlsx,.txt,.md,.doc,.docx,.png,.jpg,.json
FILESYSTEM_IGNORE_PATTERNS=*.tmp,*.bak,.DS_Store,Thumbs.db

# ─── LinkedIn MCP (Silver) ─────────────────────────────────────
LINKEDIN_SESSION_COOKIE=<your li_at cookie value>
LINKEDIN_DRY_RUN=true               # Override DRY_RUN for LinkedIn specifically
```

### Gmail — First-time setup (live only)

1. [Google Cloud Console](https://console.cloud.google.com) → Create project → Enable Gmail API
2. Create OAuth 2.0 credentials (Desktop app type) → Download as `credentials.json`
3. Place `credentials.json` in vault root
4. First live run opens browser for Google sign-in → saves `token.json` automatically:
   ```bash
   DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once
   ```

### WhatsApp — First-time session setup (live only)

```bash
uv run python scripts/setup_whatsapp_session.py
```

In the browser window:
1. Wait for WhatsApp Web QR code
2. Phone: WhatsApp → ⋮ → **Linked Devices** → **Link a Device** → scan QR
3. Wait until your chats load in the browser
4. Return to terminal → press **Enter**

Session saved to `./sessions/whatsapp/`. Valid ~14 days. No re-scan needed until it expires.

### LinkedIn — Get your session cookie (live only)

1. Log in to LinkedIn in Chrome/Edge
2. Open DevTools (F12) → **Application** tab → **Cookies** → `https://www.linkedin.com`
3. Find `li_at` → copy its value
4. Add to `.env`: `LINKEDIN_SESSION_COOKIE=<value>`

---

## 3. DRY_RUN Mode — Safe Testing

> **DRY_RUN=true is the default.** No real APIs called. All file writes, logs, and Dashboard updates work exactly as in production.

### Run all 4 watchers once (dry run)

```bash
# Filesystem watcher — generates 3 synthetic file action items
DRY_RUN=true uv run python scripts/watchers/filesystem_watcher.py --once
# Expected output: Processed 3 files

# WhatsApp watcher — generates 3 synthetic messages (no browser launched)
DRY_RUN=true uv run python scripts/watchers/whatsapp_watcher.py --once
# Expected output: Processed 3 messages (or 0 if already in state)

# Gmail watcher — generates 3 synthetic emails (no OAuth)
DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once
# Expected output: [DRY RUN] Skipping Gmail authentication → Processed 0 items

# Approval watcher — dry-run generates 2 sample approval files to exercise the path
DRY_RUN=true uv run python scripts/watchers/approval_watcher.py --once
# Expected output: Processed 0 items (or scans Approved/ for any real files)
```

### Synthetic data generated per watcher

**Gmail** → `Needs_Action/email/`:
| Priority | Subject |
|----------|---------|
| `critical` | URGENT: Overdue Invoice #2024-001 — payment required today |
| `high` | Q1 Strategy Meeting — Can you attend Thursday? |
| `low` | 50% off all products this weekend only! |

**WhatsApp** → `Needs_Action/whatsapp/`:
| Priority | Message |
|----------|---------|
| `critical` | URGENT: I need the payment processed asap! Invoice #INV-2026-001 was due yesterday |
| `high` | Can someone send me the pricing for the enterprise plan? |
| `medium` | Hey, can we reschedule our meeting to Thursday? |

**FileSystem** → `Needs_Action/file/`:
| Priority | File |
|----------|------|
| `high` | Invoice_January_2026.pdf (245 KB) |
| `medium` | Q1_Sales_Report_2026.csv (4 KB) |
| `medium` | screenshot_dashboard_2026-01.png (512 KB) |

### Verify queue after dry run

```bash
# Count items across all domains
uv run python -m scripts.utils.vault_processor counts

# List all pending items
uv run python -m scripts.utils.vault_processor list-pending

# Filter by domain
uv run python -m scripts.utils.vault_processor list-pending --subdomain email
uv run python -m scripts.utils.vault_processor list-pending --subdomain whatsapp
uv run python -m scripts.utils.vault_processor list-pending --subdomain file
```

### Orchestrator dry-run (one-shot)

```bash
DRY_RUN=true uv run python scripts/orchestrator.py --once
```

This will:
1. Start all 4 watchers as background subprocesses
2. Run one orchestrator tick (check for due scheduled tasks)
3. Update Dashboard system health
4. Stop all watchers
5. Print JSON result summary and exit

### Run all tests

```bash
uv run pytest tests/ -v --tb=short
# Expected: 451 passed
```

---

## 4. Production (Live) Mode

> Set `DRY_RUN=false` in `.env`. Real APIs. Real Gmail. Real WhatsApp. Real LinkedIn.

### Pre-flight: check prerequisites

```bash
uv run python scripts/watchers/runner.py status
```

Look for `✅ Ready` next to each watcher you want to run. `⚠️ Missing` means an env var or credential file is absent.

### One-shot live test (per watcher)

```bash
# Gmail — polls Gmail API
DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once

# FileSystem — scans /Drop/ folder
cp some_invoice.pdf Drop/
DRY_RUN=false uv run python scripts/watchers/filesystem_watcher.py --once
# Check: Needs_Action/file/FILE_*.md should appear, file moved to Attachments/

# WhatsApp — opens headless browser, reads unread messages matching keywords
DRY_RUN=false uv run python scripts/watchers/whatsapp_watcher.py --once

# Approval — scans /Approved/ and executes any pending actions via MCP
DRY_RUN=false uv run python scripts/watchers/approval_watcher.py --once
```

### Start all 4 watchers as daemons (dev mode, no PM2)

```bash
# Start all in dry-run
uv run python scripts/watchers/runner.py start --dry-run

# Start all in live mode (DRY_RUN=false in .env)
uv run python scripts/watchers/runner.py start

# Start a specific watcher
uv run python scripts/watchers/runner.py start gmail
uv run python scripts/watchers/runner.py start approval

# Check status
uv run python scripts/watchers/runner.py status

# Stop all
uv run python scripts/watchers/runner.py stop
```

Watcher logs: `Logs/watcher_{name}.log`

### Start the orchestrator (continuous)

```bash
# Dry-run, 30-second check interval (default)
DRY_RUN=true uv run python scripts/orchestrator.py

# Live, 60-second check interval
DRY_RUN=false uv run python scripts/orchestrator.py --interval 60
```

Stop with `Ctrl+C` — graceful shutdown stops all watchers first.

### Polling intervals

| Watcher | Default | Override |
|---------|---------|---------|
| `filesystem` | 30s | `--interval 30` |
| `whatsapp` | 60s | `--interval 60` |
| `gmail` | 120s | `--interval 120` |
| `approval` | 30s | `--interval 30` |

---

## 5. Skills — Claude Code Commands

Skills are invoked via Claude Code CLI. They read the vault, reason, write Plans and approval requests — nothing external is called automatically.

### email-triage

Reads `Needs_Action/email/`, classifies each email, writes a Plan, moves to `Done/`.

```bash
claude "/email-triage"
# or
claude "Process emails using email-triage skill"
```

**7 categories:** `REPLY_NEEDED` · `INVOICE_ACTION` · `MEETING_REQUEST` · `TASK_REQUEST` · `FYI_ONLY` · `ESCALATION` · `SPAM`

**What it writes:**
- `Plans/PLAN_email_{CATEGORY}_{sender}_{timestamp}.md` — analysis + draft response
- Approval file in `Pending_Approval/` if `requires_approval: true`
- Updates `Dashboard.md` queue counts and activity log

### hitl-handler

Creates structured approval files. Called internally by other skills — rarely invoked directly.

```bash
claude "Create an approval request to send an email to john@example.com"
```

**Output:** `Pending_Approval/APPROVAL_{action_type}_{target}_{timestamp}.md`

### task-planner

Breaks a complex task into dependency-tracked steps with checkbox progress.

```bash
claude "/task-planner"
# or
claude "Create a plan for: organise Q1 client outreach campaign"
```

**Output:** `Plans/PLAN_{objective}_{timestamp}.md` with `- [ ]` checkboxes per step.

### social-post

Drafts a LinkedIn post aligned with `Business_Goals.md`, then hands off to hitl-handler for approval.

```bash
claude "/social-post"
# or
claude "Draft a LinkedIn post for today"
```

**Output:** `Pending_Approval/social/APPROVAL_linkedin_post_{timestamp}.md`

**Guards built in:**
- Won't draft if a post was already created today
- Won't draft if more than 1 post is already pending approval (pile-up prevention)

---

## 6. HITL Workflow — Approve / Reject Actions

> **Nothing executes automatically.** Every sensitive action goes through this cycle.

### The approval loop

```
Skill runs
    │
    ▼
Pending_Approval/APPROVAL_*.md created
    │  (contains action type, payload, reasoning)
    │
    ▼
You review the file in Obsidian or any text editor
    │
    ├──▶  Move to /Approved/     → Approval Watcher executes via MCP → Done/
    │
    └──▶  Move to /Rejected/     → Logged, archived, no action taken
```

### What an approval file looks like

```markdown
---
type: email
action: send_email
target: client@example.com
subject: Re: Invoice #INV-001
requires_approval: true
priority: high
created: 2026-02-28T09:00:00
---

## Action Summary
Send a reply to Client Name regarding overdue invoice.

## Payload
to: client@example.com
subject: Re: Invoice #INV-001 — Payment Confirmation
body: |
  Dear Client,
  ...

## Reasoning
Email classified as INVOICE_ACTION (high priority). Company Handbook requires
approval before sending financial correspondence.

## Approve
Move this file to /Approved/ to execute.

## Reject
Move this file to /Rejected/ to discard.
```

### How to approve (from terminal)

```bash
# Move from Pending_Approval to Approved
mv "Pending_Approval/APPROVAL_email_send_client_2026-02-28T09-00-00.md" Approved/
```

The Approval Watcher detects this within its polling interval (default 30s) and executes the MCP action.

### How to reject (from terminal)

```bash
mv "Pending_Approval/APPROVAL_email_send_client_2026-02-28T09-00-00.md" Rejected/
```

The Approval Watcher logs the rejection and archives to `Done/`.

### What actions the Approval Watcher can execute

| Action type | MCP server | Tool called |
|------------|------------|------------|
| `send_email` | email-mcp | `send_email` |
| `draft_email` | email-mcp | `draft_email` |
| `reply_thread` | email-mcp | `reply_to_thread` |
| `linkedin_post` | linkedin-mcp | `create_post` |

### Stale approval alerts

If an approval file sits in `Pending_Approval/` for more than 24 hours without action, the `stale_approval_check` schedule (runs every 6 hours) flags it in the Dashboard System Health section with a warning. The file is **not** auto-rejected — only you can reject.

---

## 7. Orchestrator

The orchestrator is the master process. It coordinates watcher lifecycle and scheduled tasks in a single loop.

### Modes

```bash
# Continuous mode — runs forever, Ctrl+C to stop
uv run python scripts/orchestrator.py

# One-shot mode — starts watchers, one tick, updates health, stops watchers, exits
uv run python scripts/orchestrator.py --once

# Schedule-only mode — runs schedules without starting watchers
uv run python scripts/orchestrator.py --no-watchers

# Custom check interval
uv run python scripts/orchestrator.py --interval 60

# Dry-run (set via env, not flag)
DRY_RUN=true uv run python scripts/orchestrator.py --once
```

### What happens each tick (every `--interval` seconds)

1. **Check schedules** — run any due tasks (see Section 8)
2. **Check watcher health** (every 2nd tick) — restart any crashed watchers
3. **Persist state** (every 10th tick) — save to `.state/orchestrator_state.json`

### Crash recovery

If a watcher crashes, the orchestrator automatically restarts it. If a watcher crashes more than **5 times in 10 minutes**, auto-restart is paused and an error is flagged in the Dashboard. You'll need to investigate manually.

### State file

```
.state/orchestrator_state.json     ← tick count, last_run per schedule, restart counts
```

---

## 8. Scheduled Tasks

### List all schedules

```bash
uv run python scripts/schedules.py list
```

### Check which tasks are due right now

```bash
uv run python scripts/schedules.py check
```

### Manually trigger a task

```bash
uv run python scripts/schedules.py trigger morning_triage
uv run python scripts/schedules.py trigger linkedin_post
uv run python scripts/schedules.py trigger stale_approval_check
uv run python scripts/schedules.py trigger health_dashboard_update
uv run python scripts/schedules.py trigger daily_rollover
uv run python scripts/schedules.py trigger done_archive

# With explicit dry-run
uv run python scripts/schedules.py trigger morning_triage --dry-run
```

### Schedule registry

| Task | Frequency | Time | What it does | Requires Claude |
|------|-----------|------|-------------|----------------|
| `morning_triage` | Daily | 08:00 UTC | email-triage + task-planner + hitl-handler on all pending items | Yes |
| `linkedin_post` | Mon/Wed/Fri | 09:30 UTC | Drafts LinkedIn post via social-post skill | Yes |
| `stale_approval_check` | Every 6h | — | Flags approvals pending >24h in Dashboard | No |
| `health_dashboard_update` | Every 15m | — | Updates Dashboard System Health table | No |
| `daily_rollover` | Daily | 00:05 UTC | Archives Dashboard activity log, resets counters | No |
| `done_archive` | Daily | 01:00 UTC | Archives `/Done/` files older than 7 days | No |
| `weekly_audit_prep` | Sunday | 22:00 UTC | CEO briefing prep (disabled — Gold tier) | Yes |

### LinkedIn post guard behaviour

`linkedin_post` has built-in guards:
- If a post was **already drafted today** → `reason: already_drafted_today` → skipped
- If **more than 1 post** is pending approval → `reason: pileup` → skipped
- Otherwise → invokes Claude Code `social-post` skill → writes approval file

---

## 9. MCP Servers

MCP servers execute real external actions. They are called by the Approval Watcher after you approve an action — never directly by skills.

### email-mcp

**Location:** `mcp-servers/email-mcp/src/index.ts`

| Tool | What it does |
|------|-------------|
| `send_email` | Send an email via Gmail |
| `draft_email` | Save to Gmail Drafts (doesn't send) |
| `reply_to_thread` | Reply to an existing Gmail thread |
| `search_emails` | Search Gmail with query syntax |

**DRY_RUN behaviour:** When `DRY_RUN=true`, `send_email` and `draft_email` return a preview without calling Gmail API. `search_emails` always runs (read-only).

### linkedin-mcp

**Location:** `mcp-servers/linkedin-mcp/src/index.ts`

| Tool | What it does |
|------|-------------|
| `create_post` | Publish a text post to LinkedIn |
| `get_profile_info` | Read your LinkedIn profile (always safe) |

**DRY_RUN behaviour:** When `DRY_RUN=true`, `create_post` returns a preview and does not publish.

### Verify MCP servers are built

```bash
ls mcp-servers/email-mcp/dist/      # Should contain index.js
ls mcp-servers/linkedin-mcp/dist/   # Should contain index.js
```

If missing, rebuild:
```bash
cd mcp-servers/email-mcp && npm run build && cd ../..
cd mcp-servers/linkedin-mcp && npm run build && cd ../..
```

### Test email-mcp (dry-run)

```bash
# The MCP tool is registered in .mcp.json — Claude Code calls it automatically
# To verify it's working in dry-run, trigger an approval:
DRY_RUN=true uv run python scripts/watchers/approval_watcher.py --once
```

---

## 10. Watcher Runner Reference

```bash
# Show all registered watchers and their status
uv run python scripts/watchers/runner.py status

# Status in different formats
uv run python scripts/watchers/runner.py status --format json
uv run python scripts/watchers/runner.py status --format brief

# Start
uv run python scripts/watchers/runner.py start           # all watchers, uses .env DRY_RUN
uv run python scripts/watchers/runner.py start --dry-run # force DRY_RUN=true
uv run python scripts/watchers/runner.py start gmail
uv run python scripts/watchers/runner.py start approval

# Stop
uv run python scripts/watchers/runner.py stop            # all
uv run python scripts/watchers/runner.py stop whatsapp

# Restart
uv run python scripts/watchers/runner.py restart gmail

# Generate PM2 config
uv run python scripts/watchers/runner.py generate-pm2
uv run python scripts/watchers/runner.py generate-pm2 --output ./ecosystem.config.js
```

### PID files

Each watcher's process ID is tracked in `%TEMP%/aiemp_{name}.pid` (Windows) or `/tmp/aiemp_{name}.pid` (Linux/Mac). The runner uses these to manage cross-process stop/restart.

### State files

Deduplication state (which items have been processed) is stored per watcher in:
```
.state/gmail_processed.json
.state/filesystem_processed.json
.state/whatsapp_processed.json
.state/approval_processed.json
```

Do not delete these unless you want to reprocess everything from scratch.

---

## 11. PM2 — Production Deployment

> Use PM2 for long-running production. Handles auto-restart, memory limits, log rotation, and boot persistence.

### Install PM2
```bash
npm install -g pm2
```

### Start all watchers under PM2

```bash
# Use the committed config
pm2 start ecosystem.config.js

# Or regenerate from current settings first
uv run python scripts/watchers/runner.py generate-pm2
pm2 start ecosystem.config.js
```

### PM2 command reference

```bash
# Status
pm2 status
pm2 monit                               # Real-time resource monitor

# Logs
pm2 logs                                # Tail all watcher logs
pm2 logs aiemp-gmail-watcher           # Single watcher
pm2 logs aiemp-approval-watcher --lines 50

# Control
pm2 restart aiemp-gmail-watcher
pm2 restart all
pm2 stop all
pm2 delete all

# Persist across reboots (run once after setup)
pm2 save
pm2 startup                             # Follow the printed instructions

# Reload without downtime
pm2 reload ecosystem.config.js
```

### Resource limits (configured in ecosystem.config.js)

| Watcher | Memory limit | Max restarts | Restart delay |
|---------|-------------|-------------|--------------|
| `gmail` | 200 MB | 10 | 5s |
| `whatsapp` | 500 MB | 5 | 10s |
| `filesystem` | 100 MB | 10 | 3s |
| `approval` | 150 MB | 10 | 5s |

Logs: `Logs/pm2/{name}-watcher-{out,error}.log`

---

## 12. Complete Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  PERCEPTION (Python Watchers — background daemons)                   │
│                                                                      │
│  Gmail (120s)  ──┐                                                   │
│  WhatsApp (60s) ─┼──▶  /Needs_Action/{email,whatsapp,file}/         │
│  FileSystem (30s)┘          Structured .md with YAML frontmatter    │
└──────────────────────────────────────────────────────────────────────┘
                                        │
                         (you or morning_triage schedule)
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│  REASONING (Claude Code Skills — invoked by user or schedule)        │
│                                                                      │
│  /email-triage → classifies emails → Plans + approval requests       │
│  /task-planner → breaks tasks into steps → Plans                     │
│  /social-post  → drafts LinkedIn post → approval request             │
│  hitl-handler  → generates APPROVAL_*.md files                       │
└──────────────────────────────────────────────────────────────────────┘
                    │                         │
               No approval                Needs approval
               required                  (requires_approval: true)
                    │                         │
                    ▼                         ▼
                 Done/              Pending_Approval/
                                         │
                                  You review file
                                         │
                          ┌──────────────┴──────────────┐
                          │                             │
                    Move to Approved/            Move to Rejected/
                          │                             │
                          ▼                             ▼
┌──────────────────────────────────────┐        Logged → Done/
│  ACTION (Approval Watcher — 30s poll)│
│                                      │
│  Detects file in /Approved/          │
│  Parses action type + payload        │
│  Calls MCP server:                   │
│    • email-mcp → Gmail API           │
│    • linkedin-mcp → LinkedIn API     │
│  Archives to /Done/                  │
│  Logs to /Logs/YYYY-MM-DD.json       │
└──────────────────────────────────────┘
```

### End-to-end lifecycle example (email reply)

```
1. Gmail watcher polls → finds "URGENT: Invoice #INV-001" email
2. Creates: Needs_Action/email/EMAIL_client_2026-02-28T09-00-00.md
3. Logs:    Logs/2026-02-28.json ← watcher_detect entry

4. /email-triage runs → classifies as INVOICE_ACTION (critical)
5. Creates: Plans/PLAN_email_INVOICE_ACTION_client_2026-02-28T09-01-00.md
6. Creates: Pending_Approval/APPROVAL_email_send_client_2026-02-28T09-01-00.md
7. Moves email to: Done/EMAIL_client_2026-02-28T09-00-00.md
8. Updates: Dashboard.md (queue counts, activity log)

9. You review APPROVAL file → move to Approved/

10. Approval Watcher detects (within 30s)
11. Calls email-mcp send_email tool
12. Gmail API sends the email
13. Moves APPROVAL file to: Done/APPROVAL_email_send_client_2026-02-28T09-01-00.md
14. Logs: Logs/2026-02-28.json ← approval_execute entry
```

---

## 13. Verification Checklist

Run this sequence to confirm the full Silver tier is working end-to-end.

### Step 1 — Install
```bash
uv sync
uv run playwright install chromium
cd mcp-servers/email-mcp && npm install && npm run build && cd ../..
cd mcp-servers/linkedin-mcp && npm install && npm run build && cd ../..
```

### Step 2 — Test suite (451 tests must pass)
```bash
uv run pytest tests/ -v --tb=short
# Expected: 451 passed
```

### Step 3 — Lint (zero errors)
```bash
uv run ruff check scripts/
# Expected: All checks passed.
```

### Step 4 — Dry-run all 4 watchers

```bash
DRY_RUN=true uv run python scripts/watchers/filesystem_watcher.py --once
# Expected: Processed 3 files  (or 0 if state already has them)

DRY_RUN=true uv run python scripts/watchers/whatsapp_watcher.py --once
# Expected: Processed 3 messages  (or 0 if state already has them)

DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once
# Expected: [DRY RUN] Skipping Gmail authentication → Processed 0 items

DRY_RUN=true uv run python scripts/watchers/approval_watcher.py --once
# Expected: Processed 0 items  (nothing in /Approved/ yet)
```

### Step 5 — Queue counts
```bash
uv run python -m scripts.utils.vault_processor counts
# Expected: Needs_Action shows items from Steps above | Pending_Approval: 0
```

### Step 6 — Runner status
```bash
uv run python scripts/watchers/runner.py status
# Expected: 4 rows (gmail, whatsapp, filesystem, approval)
#           gmail + filesystem + approval = ✅ Ready
#           whatsapp = ⚠️ Missing: WHATSAPP_SESSION_PATH (expected — live only)
```

### Step 7 — Orchestrator one-shot
```bash
DRY_RUN=true uv run python scripts/orchestrator.py --once
# Expected: JSON output with watchers_started: {gmail: true, ...}
#           No errors in output
```

### Step 8 — Schedules CLI
```bash
uv run python scripts/schedules.py list
# Expected: 7 rows (6 enabled, 1 disabled = weekly_audit_prep)

uv run python scripts/schedules.py check
# Expected: Either "No tasks due right now" or list of due tasks

uv run python scripts/schedules.py trigger linkedin_post --dry-run
# Expected: {"success": true, "drafted": false, "reason": "already_drafted_today"}
#           OR Claude is invoked and writes an approval file
```

### Step 9 — Email triage skill
In Claude Code:
```
/email-triage
```
Expected:
- Reads `Needs_Action/email/*.md`
- Creates `Plans/PLAN_email_*.md` for each non-spam email
- Creates `Pending_Approval/APPROVAL_*.md` for any requiring approval
- Moves processed emails to `Done/`
- Dashboard updated (queue counts + activity log)

### Step 10 — HITL flow (manual)
```bash
# Simulate an approval file
cat > "Pending_Approval/TEST_approval_2026-02-28T00-00-00.md" << 'EOF'
---
type: test
action: send_email
requires_approval: true
---
Test approval file.
EOF

# Move to Approved
mv "Pending_Approval/TEST_approval_2026-02-28T00-00-00.md" Approved/

# Run approval watcher (DRY_RUN — won't actually send)
DRY_RUN=true uv run python scripts/watchers/approval_watcher.py --once
# Expected: file processed, moved to Done/
```

### Step 11 — Audit log
```bash
# Check today's log has entries
uv run python -c "
import json, pathlib
from datetime import date
log = pathlib.Path(f'Logs/{date.today()}.json')
if log.exists():
    entries = json.loads(log.read_text())
    print(f'Log entries today: {len(entries)}')
    for e in entries[-3:]:
        print(f'  {e[\"timestamp\"]} | {e[\"action_type\"]} | {e[\"result\"]}')
else:
    print('No log file yet — run a watcher first')
"
```

---

## 14. Troubleshooting

### `ModuleNotFoundError: No module named 'scripts'`
**Cause:** Python path not set when running from outside the vault root.
**Fix:** `uv run python` from the vault root directory resolves this automatically. If still failing:
```bash
PYTHONPATH=. uv run python scripts/watchers/gmail_watcher.py --once
```

### `UnicodeEncodeError` / box-drawing characters broken (Windows)
**Cause:** Windows cp1252 terminal can't render UTF-8 box-drawing characters.
**Fix:** Already patched — `sys.stdout.reconfigure(encoding='utf-8')` is in all `__main__` blocks. If still happening:
```bash
PYTHONUTF8=1 uv run python scripts/watchers/runner.py status
```

### WhatsApp: `TimeoutError` on `wait_for_selector`
**Cause:** Browser opened but QR scan timer expired before scan completed, or WhatsApp Web layout changed.
**Fix:** Use `setup_whatsapp_session.py` (waits for manual Enter, no timer):
```bash
uv run python scripts/setup_whatsapp_session.py
```

### WhatsApp: `⚠️ Missing: WHATSAPP_SESSION_PATH` in runner status
**Cause:** `WHATSAPP_SESSION_PATH` not set in `.env`.
**Fix:**
```env
WHATSAPP_SESSION_PATH=./sessions/whatsapp
```
Then run `setup_whatsapp_session.py` once to create the session.

### Gmail: `FileNotFoundError: credentials.json`
**Cause:** OAuth credentials not downloaded from Google Cloud Console.
**Fix:** Follow Gmail first-time setup in Section 2.

### Gmail: `RefreshError` / token expired
**Cause:** OAuth token expired and refresh failed.
**Fix:**
```bash
rm token.json
DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once
# Browser opens for re-authentication
```

### Approval Watcher: action not executing after moving to Approved/
**Cause 1:** Watcher not running.
```bash
uv run python scripts/watchers/runner.py status
uv run python scripts/watchers/runner.py start approval
```
**Cause 2:** MCP server not built.
```bash
ls mcp-servers/email-mcp/dist/index.js   # Must exist
ls mcp-servers/linkedin-mcp/dist/index.js
```
**Cause 3:** `DRY_RUN=true` — in dry-run, actions are previewed but not executed. Check logs.

### LinkedIn: `create_post` fails with 401/403
**Cause:** `li_at` session cookie expired (LinkedIn sessions expire in ~1 year).
**Fix:** Get a fresh `li_at` cookie value and update `.env`.

### Duplicate items created (same email/file processed twice)
**Cause:** State file corrupted or the `--once` flag used multiple times with different state.
**Fix:** State files in `.state/` are auto-managed. Check the relevant one:
```bash
cat .state/gmail_processed.json    # Array of processed message IDs
cat .state/filesystem_processed.json
```
Do not delete unless you want to reprocess everything.

### Dashboard.md sections look broken
**Cause:** A `## ` heading was renamed or removed — `dashboard_updater` targets sections by exact heading name.
**Fix:**
```bash
git diff Dashboard.md    # See what changed
git checkout Dashboard.md  # Restore if needed
```

### `psutil` not found (runner.py status fails)
**Cause:** `psutil` not installed (required for Windows process checks).
**Fix:**
```bash
uv sync   # psutil>=6.0.0 is in pyproject.toml
```

### Orchestrator exits immediately in `--once` mode
This is expected behaviour. `--once` starts watchers, runs one tick, updates health, stops watchers, and exits. Check the JSON output for any `error` fields.

---

*Last updated: 2026-02-28 | Phase: 🥈 Silver Tier*
*Watchers: Gmail · WhatsApp · FileSystem · Approval (4 total)*
*Skills: email-triage · hitl-handler · task-planner · social-post (4 total)*
*MCP servers: email-mcp · linkedin-mcp (2 total)*
*Tests: 451 passing*
