# Spec: README.md — Project Documentation

> **Component:** `README.md` (vault root)
> **Priority:** P1 — Required for hackathon submission
> **Audience:** Hackathon judges + other developers

## 1. Required Sections

### 1A. Header & Badges

# Personal AI Employee

> Your life and business on autopilot. Local-first, agent-driven, human-in-the-loop.

**Current Tier:** 🥉 Bronze
**Status:** Functional — Gmail perception + Claude Code triage + Obsidian dashboard

### 1B. What This Is (3-4 sentences)

Explain: This is a local-first autonomous AI agent that manages personal and business
affairs. It uses Claude Code as the reasoning engine, Obsidian as the dashboard, and
lightweight Python watchers for perception. The system follows a Perception → Reasoning
→ Action architecture with human-in-the-loop safety for sensitive operations.

### 1C. Architecture Diagram (ASCII)

Use this diagram (adapt to what actually exists):
┌─────────────────┐
│ Gmail API │
└────────┬────────┘
│
▼
┌─────────────────┐ ┌──────────────────────────┐
│ Gmail Watcher │────▶│ /Needs_Action/email/ │
│ (Python) │ │ Structured .md files │
└─────────────────┘ └────────────┬─────────────┘
│
▼
┌──────────────────────────┐
│ Claude Code │
│ (email-triage skill) │
│ Read → Classify → Plan │
└────────────┬─────────────┘
│
┌────────────────┼────────────────┐
▼ ▼ ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ /Plans/ │ │ Dashboard.md │ │ /Done/ │
│ Triage plans│ │ Updated │ │ Archived │
└──────────────┘ └──────────────┘ └──────────────┘

### 1D. Features (Bronze)

- Gmail monitoring via OAuth 2.0 (configurable query filters)
- 7-category email triage (Reply, Invoice, Meeting, Task, FYI, Escalation, Spam)
- Structured Plan files with recommended actions and draft responses
- Real-time Obsidian Dashboard with activity log and queue counts
- Full audit logging (JSON, append-only)
- DRY_RUN mode for safe testing without credentials
- Human-in-the-loop design (nothing sends without approval)

### 1E. Quick Start

Step-by-step setup instructions:

1. Prerequisites (Python 3.13+, Node.js 24+, Claude Code CLI, Obsidian)
2. Clone the repo
3. Copy .env.example to .env and configure
4. Google Cloud Console setup (link to Phase B2 guide or brief steps)
5. uv sync
6. First-time OAuth: uv run python scripts/watchers/gmail_watcher.py --once
7. Open vault in Obsidian
8. Run Claude Code to process: claude "Process emails using email-triage skill"

### 1F. Project Structure

Show the folder tree with brief annotations for each directory's purpose.
Only show what ACTUALLY EXISTS, not planned Silver/Gold folders.

### 1G. How It Works

Brief explanation of the three-layer architecture:

1. **Perception:** Gmail Watcher polls for emails → creates .md files
2. **Reasoning:** Claude Code's email-triage skill reads, classifies, generates Plans
3. **Action:** (Bronze) Plans created for human review. (Silver+) MCP servers execute.

### 1H. Configuration

- Environment variables table (from .env.example)
- Gmail query filter customization
- Company Handbook customization points
- DRY_RUN mode explanation

### 1I. Testing

How to run tests:

- uv run pytest tests/ -v
- DRY_RUN integration test instructions

### 1J. Security Disclosure

- Credentials stored in .env (gitignored)
- OAuth tokens stored locally (gitignored)
- No secrets in vault or git history
- All actions logged to /Logs/
- Sensitive actions require human approval
- DRY_RUN=true by default

### 1K. Roadmap

| Tier        | Status      | Features                                             |
| ----------- | ----------- | ---------------------------------------------------- |
| 🥉 Bronze   | ✅ Complete | Gmail watcher, email triage, dashboard               |
| 🥈 Silver   | 🔜 Next     | WhatsApp, HITL workflow, Email MCP, LinkedIn posting |
| 🥇 Gold     | 📋 Planned  | Social media, Odoo ERP, CEO briefing, Ralph loops    |
| 💎 Platinum | 📋 Planned  | 24/7 cloud agent, work-zone specialization           |

### 1L. Tech Stack

Table with: Tool, Version, Purpose

### 1M. License & Credits

- Hackathon project for Panaversity AI Employee Hackathon 0
- Built with Claude Code CLI
- Link to hackathon documentation

## 2. Validation Criteria

- [ ] README.md at vault root
- [ ] All sections present
- [ ] Architecture diagram renders in GitHub Markdown
- [ ] Quick Start is copy-pasteable (someone can set up from scratch)
- [ ] Only references files/features that actually exist
- [ ] No placeholder TODOs except in the Roadmap
- [ ] Security section is present and accurate
- [ ] Renders in both GitHub and Obsidian
