# Personal AI Employee

> Your life and business on autopilot. Local-first, agent-driven, human-in-the-loop.

**Current Tier:** 🥈 Silver
**Status:** Functional — Multi-source perception + HITL workflow + MCP-powered execution + LinkedIn automation

---

## What This Is

A local-first autonomous AI agent that manages personal and business affairs. It uses Claude Code as the reasoning engine, Obsidian as the human-readable dashboard, and lightweight Python watchers for perception. The system follows a **Perception → Reasoning → Action** architecture with human-in-the-loop safety for all sensitive operations — nothing sends, pays, or executes without your explicit approval.

Built for the [Panaversity AI Employee Hackathon 0](https://github.com/panaversity).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        PERCEPTION LAYER                          │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  ┌────────┐ │
│  │ Gmail API   │  │ File System  │  │  WhatsApp  │  │  /     │ │
│  │ (OAuth 2.0) │  │   /Drop/     │  │  Browser   │  │Approved│ │
│  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘  └───┬────┘ │
│         │                │                 │              │      │
│  ┌──────▼──────┐  ┌──────▼───────┐  ┌─────▼──────┐  ┌───▼────┐ │
│  │   Gmail     │  │ Filesystem   │  │  WhatsApp  │  │Approval│ │
│  │   Watcher   │  │   Watcher    │  │   Watcher  │  │ Watcher│ │
│  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘  └───┬────┘ │
└─────────┼────────────────┼────────────────┼──────────────┼──────┘
          │                │                │              │
          ▼                ▼                ▼              │
┌─────────────────────────────────────────────────────┐   │
│               /Needs_Action/{domain}/               │   │
│         Structured .md files with YAML frontmatter  │   │
└─────────────────────┬───────────────────────────────┘   │
                      │                                    │
                      ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      REASONING LAYER (Claude Code)              │
│                                                                 │
│   ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│   │ email-triage │  │ task-planner │  │   social-post      │   │
│   │    skill     │  │    skill     │  │      skill         │   │
│   └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘   │
│          │                 │                     │               │
│          └────────────┬────┘                     │               │
│                       ▼                          │               │
│           ┌───────────────────────┐              │               │
│           │    hitl-handler skill │              │               │
│           │  (approval requests)  │              │               │
│           └──────────┬────────────┘              │               │
└──────────────────────┼───────────────────────────┼───────────────┘
                       │                           │
                       ▼                           ▼
          ┌────────────────────┐      ┌────────────────────┐
          │  /Pending_Approval/│      │      /Plans/        │
          │  Awaiting sign-off │      │  Reasoning output   │
          └────────┬───────────┘      └────────────────────┘
                   │
          ┌────────▼───────────┐
          │     /Approved/     │
          │  Human sign-off ✅  │
          └────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                       ACTION LAYER (MCP Servers)                 │
│                                                                  │
│         ┌─────────────────┐      ┌──────────────────┐           │
│         │   email-mcp     │      │   linkedin-mcp   │           │
│         │  (TypeScript)   │      │   (TypeScript)   │           │
│         │                 │      │                  │           │
│         │ • send_email    │      │ • create_post    │           │
│         │ • draft_email   │      │ • get_profile    │           │
│         │ • reply_thread  │      │                  │           │
│         └────────┬────────┘      └────────┬─────────┘           │
└──────────────────┼─────────────────────────┼────────────────────┘
                   │                         │
                   ▼                         ▼
           Gmail / Gmail Drafts      LinkedIn Feed
```

**Folder pipeline:**

```
/Needs_Action/{domain}/  →  Items queued for AI processing
/Plans/                  →  AI reasoning output (one Plan per item)
/Pending_Approval/       →  Actions awaiting your sign-off
/Approved/               →  Human approved → executed by Approval Watcher
/Rejected/               →  Human rejected → logged and archived
/Done/                   →  Completed tasks (audit record, never deleted)
/Logs/                   →  JSON audit trail (append-only, per day)
/Drop/                   →  File drop inbox (filesystem watcher input)
```

---

## Features

### 🥉 Bronze Tier

- **Gmail monitoring** via OAuth 2.0 with configurable query filters
- **7-category email triage** — Reply, Invoice, Meeting, Task, FYI, Escalation, Spam
- **Structured Plan files** with analysis, recommended actions, and draft responses
- **Real-time Obsidian Dashboard** with activity log, queue counts, and system health
- **Full audit logging** — JSON, append-only, one file per day in `/Logs/`
- **DRY_RUN mode** — safe testing with synthetic data, no credentials required
- **Human-in-the-loop design** — nothing sends or executes without your approval
- **Deduplication** — persisted state prevents reprocessing the same item twice
- **Atomic file writes** — temp-file-then-rename prevents data corruption

### 🥈 Silver Tier

- **WhatsApp monitoring** — keyword-triggered capture from WhatsApp Web via browser automation (VIP contact prioritisation)
- **File drop inbox** — drag any file into `/Drop/` and the Filesystem Watcher creates a structured action item (supports PDF, images, Excel, Word)
- **Approval Watcher** — monitors `/Approved/` in real time; auto-executes MCP actions as soon as you move a file there, then archives to `/Done/`
- **Email MCP server** — TypeScript server exposing `send_email`, `draft_email`, `reply_to_thread`, and `search_emails` to Claude
- **LinkedIn MCP server** — TypeScript server exposing `create_post` and `get_profile_info` to Claude
- **HITL skill** — `hitl-handler` generates structured `APPROVAL_*.md` files with action payload; ensures nothing executes before human sign-off
- **Task Planner skill** — `task-planner` decomposes complex tasks into dependency-tracked multi-step Plans with checkbox progress
- **Social Post skill** — `social-post` drafts LinkedIn thought-leadership posts aligned with `Business_Goals.md`; scheduled Mon/Wed/Fri or on demand
- **Watcher runner** — `runner.py` CLI to start/stop/restart/status all 4 watchers as background processes with PID file tracking
- **Orchestrator** — `orchestrator.py` master process that starts all watchers, runs due scheduled tasks, then exits cleanly (`--once` mode) or loops
- **Scheduled tasks** — `schedules.py` with `morning_triage` and `linkedin_post` triggers; configurable cron-style scheduling
- **PM2 config** — `ecosystem.config.js` for production process management; auto-restart on crash

---

## Quick Start

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13+ | [python.org](https://python.org) |
| uv | latest | `pip install uv` |
| Claude Code CLI | latest | `npm install -g @anthropic/claude-code` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) *(for MCP servers)* |
| PM2 | latest | `npm install -g pm2` *(optional, for production)* |
| Obsidian | latest | [obsidian.md](https://obsidian.md) *(optional but recommended)* |

### 1. Clone the repo

```bash
git clone <repo-url> AI_Employee_Vault
cd AI_Employee_Vault
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
VAULT_PATH=/absolute/path/to/AI_Employee_Vault
DRY_RUN=true
```

### 4. (Optional) Set up Gmail OAuth

Skip this step if you want to test with `DRY_RUN=true` synthetic data.

For real Gmail access:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable the **Gmail API**
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `credentials.json` → place at vault root
5. Run the first-time auth flow:
   ```bash
   uv run python scripts/watchers/gmail_watcher.py --once
   ```
   A browser window opens for Google sign-in. Token saved to `token.json`.

### 5. (Optional) Set up WhatsApp monitoring

WhatsApp Web automation requires a running Chromium/Chrome browser session.

1. Install Playwright:
   ```bash
   uv run playwright install chromium
   ```
2. Start a WhatsApp session (QR code scan):
   ```bash
   uv run python scripts/setup_whatsapp_session.py
   ```
3. Set keywords to watch in `.env`:
   ```env
   WHATSAPP_KEYWORDS=urgent,invoice,meeting,payment
   WHATSAPP_VIP_CONTACTS=Client A,Boss Name
   ```

### 6. (Optional) Set up LinkedIn MCP

1. Install the LinkedIn MCP server dependencies:
   ```bash
   cd mcp-servers/linkedin-mcp && npm install && npm run build
   cd ../..
   ```
2. Configure your LinkedIn session cookie in `.env`:
   ```env
   LINKEDIN_SESSION_COOKIE=<your li_at cookie value>
   ```
3. Register the MCP server with Claude Code (already in `.mcp.json` — just ensure the path is correct).

### 7. (Optional) Set up Email MCP

1. Install the Email MCP server dependencies:
   ```bash
   cd mcp-servers/email-mcp && npm install && npm run build
   cd ../..
   ```
2. The email MCP reuses your existing Gmail OAuth credentials (`credentials.json` + `token.json`).

### 8. Verify with tests

```bash
uv run pytest tests/ -v
```

Expected: **451 tests pass**.

### 9. Run watchers (development)

**All watchers, dry-run:**
```bash
uv run python scripts/watchers/runner.py start --dry-run
```

**Check status:**
```bash
uv run python scripts/watchers/runner.py status
```

**Stop all:**
```bash
uv run python scripts/watchers/runner.py stop
```

**One-shot orchestrator (starts watchers + runs due schedules, then exits):**
```bash
DRY_RUN=true uv run python scripts/orchestrator.py --once
```

### 10. Run in production with PM2

```bash
# Generate PM2 config (or use the committed ecosystem.config.js)
uv run python scripts/watchers/runner.py generate-pm2

# Start all watchers under PM2
pm2 start ecosystem.config.js

# Monitor
pm2 status
pm2 logs

# Persist across reboots
pm2 save && pm2 startup
```

### 11. Open the vault in Obsidian

Open `AI_Employee_Vault/` as an Obsidian vault. `Dashboard.md` is your real-time control panel showing queue counts, recent activity, and system health.

### 12. Triage with Claude Code skills

```bash
# Triage emails
claude "/email-triage"

# Draft a LinkedIn post
claude "/social-post"

# Run morning triage schedule
uv run python scripts/schedules.py trigger morning_triage
```

---

## How It Works

### Layer 1 — Perception (Python Watchers)

Four watchers run as background processes and feed structured `.md` files into `/Needs_Action/`:

| Watcher | Source | Output |
|---------|--------|--------|
| `gmail_watcher.py` | Gmail API (OAuth 2.0) | `/Needs_Action/email/EMAIL_*.md` |
| `filesystem_watcher.py` | `/Drop/` folder | `/Needs_Action/file/FILE_*.md` |
| `whatsapp_watcher.py` | WhatsApp Web (browser) | `/Needs_Action/whatsapp/WHATSAPP_*.md` |
| `approval_watcher.py` | `/Approved/` folder | Executes via MCP → `/Done/` |

Each watcher:
1. Polls its source at a configurable interval (default: 120s)
2. Classifies priority (`critical / high / medium / low`) from content and keywords
3. Writes a structured `.md` file with YAML frontmatter
4. Logs the action to `/Logs/YYYY-MM-DD.json`
5. Records processed IDs in a state file to prevent reprocessing

### Layer 2 — Reasoning (Claude Code Skills)

Four skills instruct Claude to act on vault items:

| Skill | Purpose |
|-------|---------|
| `email-triage` | Classify emails → 7 categories → write Plans |
| `task-planner` | Decompose complex tasks into dependency-tracked steps |
| `social-post` | Draft LinkedIn posts from business context |
| `hitl-handler` | Generate `APPROVAL_*.md` files for any action needing sign-off |

All skills consult `Company_Handbook.md` for tone, approval rules, and contact tiers before acting.

### Layer 3 — Action (HITL + MCP)

1. Skills write action payloads to `/Pending_Approval/`
2. You review and move the file to `/Approved/` or `/Rejected/`
3. The **Approval Watcher** detects the move within seconds
4. It calls the appropriate **MCP server** (`email-mcp` or `linkedin-mcp`) to execute
5. Result is logged and the file is archived to `/Done/`

Nothing executes until you physically move a file to `/Approved/`.

---

## Project Structure

```
AI_Employee_Vault/
├── README.md                          # This file
├── Dashboard.md                       # Real-time Obsidian control panel
├── Company_Handbook.md                # AI Employee rules and contact tiers
├── Business_Goals.md                  # Goals used by social-post skill
├── ecosystem.config.js                # PM2 production process config
├── pyproject.toml                     # Python project config (uv)
├── .env.example                       # Environment variable template
│
├── scripts/
│   ├── orchestrator.py                # Master process (start watchers + run schedules)
│   ├── schedules.py                   # Scheduled task definitions + trigger CLI
│   ├── setup_whatsapp_session.py      # WhatsApp QR code session initialiser
│   ├── watchers/
│   │   ├── base_watcher.py            # Abstract base class for all watchers
│   │   ├── gmail_watcher.py           # Gmail API perception layer
│   │   ├── filesystem_watcher.py      # File drop inbox watcher
│   │   ├── whatsapp_watcher.py        # WhatsApp Web browser watcher
│   │   ├── approval_watcher.py        # Approved/ → MCP execution watcher
│   │   └── runner.py                  # Watcher lifecycle CLI (start/stop/status)
│   └── utils/
│       ├── gmail_auth.py              # OAuth 2.0 authentication helper
│       ├── vault_helpers.py           # File I/O and YAML frontmatter utilities
│       ├── vault_processor.py         # Pipeline file operations (list, move, count)
│       ├── dashboard_updater.py       # Dashboard.md section-targeted updater
│       ├── action_executor.py         # MCP action dispatch and retry logic
│       └── logging_config.py          # Structured logging setup (UTF-8 safe)
│
├── mcp-servers/
│   ├── email-mcp/                     # TypeScript MCP server — Gmail actions
│   │   └── src/index.ts               # send_email, draft_email, reply_to_thread, search_emails
│   └── linkedin-mcp/                  # TypeScript MCP server — LinkedIn actions
│       └── src/index.ts               # create_post, get_profile_info
│
├── .claude/
│   ├── CLAUDE.md                      # AI Employee project constitution
│   └── skills/
│       ├── email-triage/SKILL.md      # Email triage skill definition
│       ├── hitl-handler/SKILL.md      # HITL approval file generator skill
│       ├── task-planner/SKILL.md      # Multi-step task decomposition skill
│       └── social-post/SKILL.md       # LinkedIn post drafting skill
│
├── tests/
│   ├── watchers/                      # Watcher unit tests (all 4 watchers + runner)
│   ├── utils/                         # Utility unit tests
│   └── test_schedules.py              # Schedules + orchestrator tests
│
├── docs/specs/                        # Component specifications
│
├── Needs_Action/
│   ├── email/                         # Incoming email queue
│   ├── whatsapp/                      # Incoming WhatsApp queue
│   └── file/                          # Incoming file drop queue
├── Drop/                              # File system watcher input
├── Plans/                             # AI-generated triage plans
├── Pending_Approval/                  # Actions awaiting human sign-off
├── Approved/                          # Human-approved actions
├── Rejected/                          # Rejected actions
├── Done/                              # Completed tasks (audit archive)
└── Logs/                              # JSON audit logs (YYYY-MM-DD.json)
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `.` | Absolute path to the vault root |
| `DRY_RUN` | `true` | `true` = synthetic data, no external calls |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MAX_ACTIONS_PER_HOUR` | `20` | Safety rate limit for AI actions |
| `CHECK_INTERVAL_SECONDS` | `120` | Default watcher polling interval (minimum 30s) |
| `GMAIL_CREDENTIALS_PATH` | `./credentials.json` | OAuth credentials file path |
| `GMAIL_TOKEN_PATH` | `./token.json` | OAuth token file path |
| `GMAIL_PRIORITY_KEYWORDS` | `urgent,asap,emergency,critical` | Subject keywords that trigger `critical` priority |
| `WHATSAPP_KEYWORDS` | `urgent,invoice,payment,meeting` | WhatsApp message keywords to capture |
| `WHATSAPP_VIP_CONTACTS` | *(empty)* | Comma-separated names — always escalate to `critical` |
| `WHATSAPP_MAX_CHATS` | `10` | Max WhatsApp chats to scan per cycle |
| `LINKEDIN_SESSION_COOKIE` | *(required for live)* | LinkedIn `li_at` session cookie |
| `LINKEDIN_DRY_RUN` | inherits `DRY_RUN` | Override DRY_RUN for LinkedIn specifically |

### Gmail Query Filter

Customize what emails the watcher fetches:

```bash
# Default: unread + important
uv run python scripts/watchers/gmail_watcher.py --query "is:unread is:important"

# All unread in inbox
uv run python scripts/watchers/gmail_watcher.py --query "is:unread in:inbox"

# Specific label
uv run python scripts/watchers/gmail_watcher.py --query "label:client-a is:unread"
```

### Company Handbook

Edit `Company_Handbook.md` to configure:
- Contact tiers (VIP clients, vendors, internal team)
- Response time targets per priority level
- Approval matrix (what actions need human sign-off)
- Tone and communication style guidelines

### DRY_RUN Mode

With `DRY_RUN=true` (the default), all watchers:
- Skip live authentication entirely
- Return synthetic sample data covering all priority levels
- Write real `.md` files to the appropriate `/Needs_Action/` subdirectory
- Log all actions normally

This lets you test the full pipeline without any credentials.

---

## Watcher Runner CLI

```bash
# Start all watchers (dry-run)
uv run python scripts/watchers/runner.py start --dry-run

# Start a single watcher
uv run python scripts/watchers/runner.py start gmail

# Show status table
uv run python scripts/watchers/runner.py status

# Stop all
uv run python scripts/watchers/runner.py stop

# Restart one watcher
uv run python scripts/watchers/runner.py restart approval

# Generate PM2 config
uv run python scripts/watchers/runner.py generate-pm2
```

---

## Scheduled Tasks

```bash
# List all schedules and next run times
uv run python scripts/schedules.py list

# Check which tasks are due now
uv run python scripts/schedules.py check-due

# Trigger a task immediately
uv run python scripts/schedules.py trigger morning_triage
uv run python scripts/schedules.py trigger linkedin_post
```

Schedules defined in `scripts/schedules.py`:

| Task | Default Schedule | What it does |
|------|-----------------|--------------|
| `morning_triage` | 08:00 daily | Run email-triage skill on all pending items |
| `linkedin_post` | Mon/Wed/Fri 09:00 | Draft + queue a LinkedIn post for review |

---

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific module tests
uv run pytest tests/watchers/ -v
uv run pytest tests/utils/ -v

# Lint check
uv run ruff check scripts/
```

### Integration smoke test (DRY_RUN)

```bash
# Gmail watcher
DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once
# → Processed 0 items (or synthetic items if Needs_Action/email/ is empty)

# Filesystem watcher
DRY_RUN=true uv run python scripts/watchers/filesystem_watcher.py --once
# → Processed 0 files

# Full orchestrator one-shot
DRY_RUN=true uv run python scripts/orchestrator.py --once
# → Starts all 4 watchers, runs due schedules, exits cleanly
```

---

## Security

- **Credentials stored in `.env`** — gitignored, never committed
- **OAuth tokens stored locally** (`token.json`) — gitignored
- **No secrets in vault or git history** — `.gitignore` covers all credential files
- **All AI actions logged** to `/Logs/` (append-only JSON, audit trail)
- **Sensitive actions require human approval** — files move to `/Pending_Approval/` first; Approval Watcher only executes from `/Approved/`
- **DRY_RUN=true by default** — external actions disabled unless explicitly enabled
- **Rate limiting** — max 20 AI actions per hour enforced in skill rules
- **Atomic file writes** — all file operations use temp-file-then-rename to prevent corruption

---

## Roadmap

| Tier | Status | Features |
|------|--------|----------|
| 🥉 Bronze | ✅ Complete | Gmail watcher, 7-category email triage, Obsidian dashboard, audit logging |
| 🥈 Silver | ✅ Complete | WhatsApp watcher, Filesystem watcher, Approval watcher, Email MCP, LinkedIn MCP, HITL skill, Task Planner skill, Social Post skill, Watcher runner, Orchestrator, Schedules, PM2 config |
| 🥇 Gold | Planned | Social media manager, Odoo ERP integration, daily CEO briefing, feedback loops |
| 💎 Platinum | Planned | 24/7 cloud agent, multi-zone specialization, full autonomous operation |

---

## Tech Stack

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.13+ | Watcher scripts and utilities |
| uv | latest | Python package and project manager |
| Claude Code CLI | latest | AI reasoning engine (triage, planning, social skills) |
| Claude API | claude-sonnet-4-6 | Underlying LLM for reasoning |
| TypeScript | 5.x | MCP server implementation |
| Node.js | 18+ | MCP server runtime |
| `@modelcontextprotocol/sdk` | latest | MCP server framework |
| Google Gmail API | v1 | Email perception + execution layer |
| google-api-python-client | 2.190+ | Gmail API client |
| google-auth-oauthlib | 1.2+ | OAuth 2.0 flow |
| Playwright | latest | WhatsApp Web browser automation |
| psutil | 6.0+ | Cross-platform process management (watcher lifecycle) |
| PyYAML | 6.0+ | YAML frontmatter parsing |
| python-dotenv | 1.2+ | Environment variable loading |
| PM2 | latest | Production process manager (optional) |
| Obsidian | latest | Human-readable vault dashboard |
| pytest | 9.0+ | Test framework (451 tests) |
| ruff | 0.15+ | Python linter |

---

## License & Credits

This is a hackathon project built for the **Panaversity AI Employee Hackathon 0**.

Built with [Claude Code CLI](https://claude.ai/claude-code) by Anthropic.
