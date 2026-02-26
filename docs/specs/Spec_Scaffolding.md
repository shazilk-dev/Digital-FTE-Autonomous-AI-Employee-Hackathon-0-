# Spec: Project Scaffolding

> **Component:** Vault directory structure, .gitignore, .env.example, settings.json
> **Priority:** P0 — Everything depends on this
> **Estimated Time:** 10 minutes

## 1. Objective

Create the complete folder structure for the AI Employee Vault. This is the skeleton
that all watchers, skills, agents, and MCP servers will use. Every folder has a
specific purpose in the Perception → Reasoning → Action pipeline.

## 2. Folder Structure to Create

```
AI_Employee_Vault/
├── .claude/
│   ├── skills/
│   │   ├── email-triage/
│   │   ├── task-planner/
│   │   ├── social-post/
│   │   ├── ceo-briefing/
│   │   └── social-media/
│   ├── agents/
│   └── plugins/
├── Inbox/
├── Needs_Action/
│   ├── email/
│   ├── whatsapp/
│   ├── file/
│   └── social/
├── Plans/
├── Pending_Approval/
├── Approved/
├── Rejected/
├── In_Progress/
│   ├── cloud/
│   └── local/
├── Done/
│   └── archive/
├── Logs/
├── Briefings/
├── Accounting/
├── Drop/
├── Updates/
├── docs/
│   └── specs/
├── scripts/
│   ├── watchers/
│   └── utils/
├── mcp-servers/
└── tests/
    ├── watchers/
    └── utils/
```

## 3. Files to Generate

### 3A. `.gitignore`

```gitignore
# Secrets — NEVER commit
.env
.env.local
.env.production
*.key
*.pem
credentials.json
token.json
token.pickle

# WhatsApp/Browser sessions
sessions/
playwright-data/
user-data-dir/

# Python
__pycache__/
*.pyc
*.pyo
.venv/
.uv/
dist/
*.egg-info/

# Node.js
node_modules/
package-lock.json

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/

# Temporary
*.tmp
*.bak
*.swp
```

### 3B. `.env.example`

```env
# ─── Gmail API ───
GMAIL_CLIENT_ID=your_client_id_here
GMAIL_CLIENT_SECRET=your_client_secret_here
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json

# ─── WhatsApp (Silver) ───
WHATSAPP_SESSION_PATH=./sessions/whatsapp
WHATSAPP_KEYWORDS=urgent,asap,invoice,payment,help,pricing

# ─── LinkedIn (Silver) ───
LINKEDIN_SESSION_PATH=./sessions/linkedin

# ─── Odoo ERP (Gold) ───
ODOO_URL=http://localhost:8069
ODOO_DB=ai_employee
ODOO_USER=admin
ODOO_PASSWORD=your_password_here

# ─── Cloud VM (Platinum) ───
CLOUD_VM_HOST=
CLOUD_VM_USER=
VAULT_SYNC_INTERVAL=300

# ─── Global Settings ───
VAULT_PATH=~/AI_Employee_Vault
DRY_RUN=true
LOG_LEVEL=INFO
MAX_ACTIONS_PER_HOUR=20
CHECK_INTERVAL_SECONDS=120
```

### 3C. `.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Read(**)",
      "Write(Needs_Action/**)",
      "Write(Plans/**)",
      "Write(Pending_Approval/**)",
      "Write(Done/**)",
      "Write(Logs/**)",
      "Write(Briefings/**)",
      "Write(Dashboard.md)",
      "Write(docs/**)",
      "Write(scripts/**)",
      "Write(tests/**)",
      "Write(mcp-servers/**)",
      "Bash(python *)",
      "Bash(node *)",
      "Bash(npm *)",
      "Bash(uv *)",
      "Bash(git *)",
      "Bash(pytest *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(mkdir *)",
      "Bash(cp *)",
      "Bash(mv *)"
    ],
    "deny": [
      "Write(.env)",
      "Write(credentials.json)",
      "Write(token.json)",
      "Bash(rm -rf *)",
      "Bash(curl *)",
      "Bash(wget *)"
    ]
  }
}
```

### 3D. Placeholder `.gitkeep` Files

Create an empty `.gitkeep` file inside every empty directory so Git tracks them:

- `Inbox/.gitkeep`
- `Needs_Action/email/.gitkeep`
- `Needs_Action/whatsapp/.gitkeep`
- `Needs_Action/file/.gitkeep`
- `Needs_Action/social/.gitkeep`
- `Plans/.gitkeep`
- `Pending_Approval/.gitkeep`
- `Approved/.gitkeep`
- `Rejected/.gitkeep`
- `In_Progress/cloud/.gitkeep`
- `In_Progress/local/.gitkeep`
- `Done/archive/.gitkeep`
- `Logs/.gitkeep`
- `Briefings/.gitkeep`
- `Accounting/.gitkeep`
- `Drop/.gitkeep`
- `Updates/.gitkeep`
- `scripts/watchers/.gitkeep`
- `scripts/utils/.gitkeep`
- `mcp-servers/.gitkeep`
- `tests/watchers/.gitkeep`
- `tests/utils/.gitkeep`

## 4. Validation Criteria

- [ ] All directories exist as specified above
- [ ] `.gitignore` is present and includes `.env`, `credentials.json`, `sessions/`
- [ ] `.env.example` is present with all placeholder keys
- [ ] `.claude/settings.json` has read/write permissions scoped correctly
- [ ] All empty dirs have `.gitkeep` files
- [ ] `git status` shows all files as trackable (no secrets)
- [ ] Running `tree -a -I 'node_modules|.git|__pycache__|.obsidian' .` shows the full structure

## 5. Edge Cases

- If `.claude/` directory already exists (from Claude Code init), merge — don't overwrite
- If `pyproject.toml` already exists from `uv init`, leave it as-is
- Do NOT create `CLAUDE.md`, `Company_Handbook.md`, or `Dashboard.md` yet — those are separate specs
