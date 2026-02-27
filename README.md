# Personal AI Employee

> Your life and business on autopilot. Local-first, agent-driven, human-in-the-loop.

**Current Tier:** Bronze
**Status:** Functional — Gmail perception + Claude Code triage + Obsidian dashboard

---

## What This Is

A local-first autonomous AI agent that manages personal and business affairs. It uses Claude Code as the reasoning engine, Obsidian as the human-readable dashboard, and lightweight Python watchers for perception. The system follows a **Perception → Reasoning → Action** architecture with human-in-the-loop safety for all sensitive operations — nothing sends, pays, or executes without your explicit approval.

Built for the [Panaversity AI Employee Hackathon 0](https://github.com/panaversity).

---

## Architecture

```
┌─────────────────┐
│   Gmail API     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────────────┐
│  Gmail Watcher  │────▶│  /Needs_Action/email/    │
│   (Python)      │     │  Structured .md files    │
└─────────────────┘     └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │       Claude Code        │
                        │  (email-triage skill)    │
                        │  Read → Classify → Plan  │
                        └────────────┬─────────────┘
                                     │
                     ┌───────────────┼───────────────┐
                     ▼               ▼               ▼
             ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
             │   /Plans/    │ │ Dashboard.md │ │   /Done/     │
             │ Triage plans │ │   Updated    │ │  Archived    │
             └──────────────┘ └──────────────┘ └──────────────┘
```

**Folder pipeline:**

```
/Needs_Action/{domain}/  →  Items queued for AI processing
/Plans/                  →  AI reasoning output (one Plan per item)
/Pending_Approval/       →  Actions awaiting your sign-off
/Approved/               →  Human approved → ready to execute
/Rejected/               →  Human rejected → logged and archived
/Done/                   →  Completed tasks (audit record, never deleted)
/Logs/                   →  JSON audit trail (append-only, per day)
```

---

## Features (Bronze Tier)

- **Gmail monitoring** via OAuth 2.0 with configurable query filters
- **7-category email triage** — Reply, Invoice, Meeting, Task, FYI, Escalation, Spam
- **Structured Plan files** with analysis, recommended actions, and draft responses
- **Real-time Obsidian Dashboard** with activity log, queue counts, and system health
- **Full audit logging** — JSON, append-only, one file per day in `/Logs/`
- **DRY_RUN mode** — safe testing with synthetic data, no credentials required
- **Human-in-the-loop design** — nothing sends or executes without your approval
- **Deduplication** — persisted state prevents reprocessing the same email twice
- **Atomic file writes** — temp-file-then-rename prevents data corruption

---

## Quick Start

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13+ | [python.org](https://python.org) |
| uv | latest | `pip install uv` |
| Claude Code CLI | latest | `npm install -g @anthropic/claude-code` |
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

Skip this step if you want to test with DRY_RUN=true synthetic data.

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

### 5. Verify with tests

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

### 6. Run the Gmail watcher

**Dry-run mode (no Gmail credentials needed):**
```bash
uv run python scripts/watchers/gmail_watcher.py --once
```

This generates 3 synthetic email files in `/Needs_Action/email/` for testing.

**Live mode (real Gmail):**
```bash
# One-shot
uv run python scripts/watchers/gmail_watcher.py --once

# Continuous polling (every 2 minutes)
uv run python scripts/watchers/gmail_watcher.py
```

### 7. Open the vault in Obsidian

Open `AI_Employee_Vault/` as an Obsidian vault. The `Dashboard.md` file serves as your real-time control panel.

### 8. Triage emails with Claude Code

```bash
claude "Process emails using email-triage skill"
```

Claude reads each email in `/Needs_Action/email/`, classifies it, writes a Plan to `/Plans/`, and updates the Dashboard. All within your vault, nothing sent externally.

---

## How It Works

### Layer 1 — Perception (Python)

`GmailWatcher` polls the Gmail API for unread/important emails at a configurable interval (default: 120s). For each new email it:

1. Fetches the full message via Gmail API
2. Extracts plain-text body, headers, attachments
3. Classifies priority (`critical / high / medium / low`) from labels and subject keywords
4. Writes a structured `.md` file with YAML frontmatter to `/Needs_Action/email/`
5. Logs the action to `/Logs/YYYY-MM-DD.json`
6. Records the message ID in a state file to prevent reprocessing

### Layer 2 — Reasoning (Claude Code)

The `email-triage` skill instructs Claude to:

1. Read each pending email file
2. Consult `Company_Handbook.md` for tone and approval rules
3. Classify into one of 7 categories (Reply, Invoice, Meeting, Task, FYI, Escalation, Spam)
4. Generate a Plan file in `/Plans/` with analysis, recommended actions, and a draft response
5. Move the processed email to `/Done/`
6. Update the Dashboard activity log and queue counts

### Layer 3 — Action (Human-in-the-Loop)

Bronze tier: Plans are created for **your review**. You decide what happens next by moving files between `/Pending_Approval/`, `/Approved/`, and `/Rejected/`.

Silver+ tier *(coming soon)*: MCP servers will execute approved actions automatically.

---

## Project Structure

```
AI_Employee_Vault/
├── README.md                          # This file
├── Dashboard.md                       # Real-time Obsidian control panel
├── Company_Handbook.md                # AI Employee rules and contact tiers
├── pyproject.toml                     # Python project config (uv)
├── .env.example                       # Environment variable template
│
├── scripts/
│   ├── watchers/
│   │   ├── base_watcher.py            # Abstract base class for all watchers
│   │   └── gmail_watcher.py           # Gmail API perception layer
│   └── utils/
│       ├── gmail_auth.py              # OAuth 2.0 authentication helper
│       ├── vault_helpers.py           # File I/O and YAML frontmatter utilities
│       ├── vault_processor.py         # Pipeline file operations (list, move, count)
│       ├── dashboard_updater.py       # Dashboard.md section-targeted updater
│       └── logging_config.py         # Structured logging setup
│
├── .claude/
│   ├── CLAUDE.md                      # AI Employee project constitution
│   └── skills/
│       └── email-triage/
│           └── SKILL.md               # Email triage skill definition
│
├── tests/
│   ├── watchers/                      # Watcher unit tests
│   └── utils/                         # Utility unit tests
│
├── docs/specs/                        # Component specifications
│
├── Needs_Action/email/                # Incoming email queue
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
| `CHECK_INTERVAL_SECONDS` | `120` | Gmail polling interval (minimum 30s) |
| `GMAIL_CREDENTIALS_PATH` | `./credentials.json` | OAuth credentials file path |
| `GMAIL_TOKEN_PATH` | `./token.json` | OAuth token file path |
| `GMAIL_PRIORITY_KEYWORDS` | `urgent,asap,emergency,critical` | Subject keywords that trigger `critical` priority |

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

With `DRY_RUN=true` (the default), the watcher:
- Skips Gmail authentication entirely
- Returns 3 synthetic emails covering all priority levels
- Writes real `.md` files to `/Needs_Action/email/`
- Logs all actions normally

This lets you test the full pipeline without any Google credentials.

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

### Integration test (DRY_RUN)

```bash
# Ensure DRY_RUN=true in .env, then:
uv run python scripts/watchers/gmail_watcher.py --once

# Verify output
ls Needs_Action/email/          # Should show 3 EMAIL_*.md files
cat Logs/$(date +%Y-%m-%d).json # Should show watcher_detect entries
```

---

## Security

- **Credentials stored in `.env`** — gitignored, never committed
- **OAuth tokens stored locally** (`token.json`) — gitignored
- **No secrets in vault or git history** — `.gitignore` covers all credential files
- **All AI actions logged** to `/Logs/` (append-only JSON, audit trail)
- **Sensitive actions require human approval** — emails move to `/Pending_Approval/` first
- **DRY_RUN=true by default** — external actions disabled unless explicitly enabled
- **Rate limiting** — max 20 AI actions per hour enforced in the skill rules
- **Atomic file writes** — all file operations use temp-file-then-rename to prevent corruption

---

## Roadmap

| Tier | Status | Features |
|------|--------|----------|
| Bronze | Complete | Gmail watcher, 7-category email triage, Obsidian dashboard, audit logging |
| Silver | Coming Soon | WhatsApp watcher, Email MCP server (auto-send on approval), LinkedIn posting, HITL workflow automation |
| Gold | Planned | Social media manager, Odoo ERP integration, daily CEO briefing, feedback loops |
| Platinum | Planned | 24/7 cloud agent, multi-zone specialization, full autonomous operation |

---

## Tech Stack

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.13+ | Watcher scripts and utilities |
| uv | latest | Python package and project manager |
| Claude Code CLI | latest | AI reasoning engine (email triage skill) |
| Claude API | claude-sonnet-4-6 | Underlying LLM for reasoning |
| Google Gmail API | v1 | Email perception layer |
| google-api-python-client | 2.190+ | Gmail API client |
| google-auth-oauthlib | 1.2+ | OAuth 2.0 flow |
| PyYAML | 6.0+ | YAML frontmatter parsing |
| python-dotenv | 1.2+ | Environment variable loading |
| Obsidian | latest | Human-readable vault dashboard |
| pytest | 9.0+ | Test framework |
| ruff | 0.15+ | Python linter |

---

## License & Credits

This is a hackathon project built for the **Panaversity AI Employee Hackathon 0**.

Built with [Claude Code CLI](https://claude.ai/claude-code) by Anthropic.
