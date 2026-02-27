# Spec: Email Triage Agent Skill

> **Component:** `.claude/skills/email-triage/SKILL.md`
> **Type:** Agent Skill (prompt template, NOT executable code)
> **Priority:** P0 — This is Claude's first "reasoning" capability
> **Invocation:** Auto-loaded when Claude detects email processing tasks, or manual via `/email-triage`
> **Depends On:** `vault_processor.py`, `dashboard_updater.py`, `Company_Handbook.md`

## 1. Objective

Create an Agent Skill that teaches Claude Code HOW to triage emails. When Claude encounters
email files in `/Needs_Action/email/`, this skill injects domain expertise for:
- Reading and understanding email context
- Classifying urgency and required action type
- Generating structured Plan files with recommended next steps
- Deciding what needs human approval vs. auto-processing
- Updating the Dashboard and moving files through the pipeline

This is a **prompt template**, not code. It programs Claude's behavior through instructions.

## 2. Skill Architecture

```
.claude/skills/email-triage/
└── SKILL.md          # The skill definition (frontmatter + instructions)
```

No supporting files needed for Bronze. The skill references:
- `Company_Handbook.md` for rules of engagement
- `vault_processor.py` CLI for file operations
- `dashboard_updater.py` CLI for Dashboard updates

## 3. SKILL.md Full Specification

The file MUST have this exact structure:

### 3A. YAML Frontmatter

```yaml
---
name: email-triage
description: >
  Triage email items from /Needs_Action/email/. Reads each email file,
  classifies urgency and action type, generates Plan files with recommended
  responses, updates Dashboard, and moves processed items. Follows rules
  from Company_Handbook.md.
allowed-tools:
  - Bash(uv run python -m scripts.utils.vault_processor *)
  - Bash(uv run python -m scripts.utils.dashboard_updater *)
  - Bash(cat *)
  - Bash(ls *)
  - Read
  - Write
---
```

Key frontmatter decisions:
- **No `disable-model-invocation`** — Claude should auto-detect when this skill is relevant
- **No `user-invocable: false`** — user can also invoke manually via `/email-triage`
- **`allowed-tools` scoped** — only vault processor, dashboard updater, and file read/write
- **No `context: fork`** — runs in main session so it can modify files directly

### 3B. Skill Body — The Behavioral Programming

The body of SKILL.md must contain these sections in order:

---

#### Section 1: Role & Context

```markdown
# Email Triage Skill

You are triaging emails for the AI Employee system. Your job is to process
every email file in `/Needs_Action/email/`, understand the content, classify it,
create an actionable plan, and move the file through the pipeline.

Before processing, read the rules of engagement:
- `Company_Handbook.md` — for tone, approval matrix, and contact handling rules

For file operations, use these CLI tools:
- List pending: `uv run python -m scripts.utils.vault_processor list-pending --subdomain email --format json`
- Move file: `uv run python -m scripts.utils.vault_processor move-to-done <filepath>`
- Move to other: `uv run python -m scripts.utils.vault_processor move-file <filepath> <destination>`
- Queue counts: `uv run python -m scripts.utils.vault_processor counts`
- Add activity: `uv run python -m scripts.utils.dashboard_updater add-activity "<action>" "<details>" "<result>"`
- Update counts: `uv run python -m scripts.utils.dashboard_updater update-counts`
- Add pending: `uv run python -m scripts.utils.dashboard_updater add-pending --type email --from "<sender>" --subject "<subject>" --priority <priority>`
```

#### Section 2: Processing Workflow

```markdown
## Processing Workflow

For EACH email file in /Needs_Action/email/:

### Step 1: Read & Understand
- Read the full .md file including YAML frontmatter
- Identify: sender, subject, content, priority, attachments

### Step 2: Classify Action Type
Categorize into ONE of these types:

| Category | Description | Example |
|----------|-------------|---------|
| REPLY_NEEDED | Sender expects a response | Client asking a question |
| INVOICE_ACTION | Financial document requiring processing | Invoice attached or requested |
| MEETING_REQUEST | Calendar/scheduling related | "Can we meet Tuesday?" |
| TASK_REQUEST | Someone asking you to do something | "Please review the proposal" |
| FYI_ONLY | Informational, no action needed | Newsletter, notification |
| ESCALATION | Requires immediate human attention | Complaint, legal mention |
| SPAM | Irrelevant or unsolicited | Marketing from unknown sender |

### Step 3: Apply Company Handbook Rules
- Check if sender is known (Tier 1/2/3) or unknown
- Check if action requires approval (per Approval Matrix)
- Check for sensitive keywords: "lawyer", "legal", "sue", "contract", "urgent"
- If any sensitive keyword found → category becomes ESCALATION

### Step 4: Generate Plan File
Write a Plan file to /Plans/ with this format:

---
type: plan
source_file: <original email filepath>
source_type: email
category: <REPLY_NEEDED|INVOICE_ACTION|MEETING_REQUEST|TASK_REQUEST|FYI_ONLY|ESCALATION|SPAM>
priority: <critical|high|medium|low>
sender: <email sender>
subject: <email subject>
requires_approval: <true|false>
status: pending
created: <current ISO 8601 timestamp>
---

## Triage Summary

**Category:** {category}
**Priority:** {priority}
**Sender:** {sender} ({contact_tier})
**Subject:** {subject}

## Analysis

{2-3 sentence analysis of what the email is about and why this category was assigned}

## Recommended Actions

- [ ] {Primary recommended action}
- [ ] {Secondary action if applicable}
- [ ] {Follow-up action if applicable}

## Draft Response (if REPLY_NEEDED)

{If category is REPLY_NEEDED, draft a response following Company_Handbook.md tone rules.
 Keep under 150 words. Mark as requires_approval: true.}

{If category is not REPLY_NEEDED, write "No response needed." instead.}

## Approval Required

{If requires_approval is true:}
This action requires your approval. Review the draft above, then:
- To approve: move this plan to /Approved/
- To reject: move this plan to /Rejected/

{If requires_approval is false:}
This item has been auto-processed per Company Handbook rules.

### Step 5: Handle Based on Category

| Category | Action |
|----------|--------|
| REPLY_NEEDED | Write Plan with draft → move email to Done |
| INVOICE_ACTION | Write Plan with requires_approval: true → move email to Done |
| MEETING_REQUEST | Write Plan with calendar details → move email to Done |
| TASK_REQUEST | Write Plan with task breakdown → move email to Done |
| FYI_ONLY | Skip Plan → move email directly to Done |
| ESCALATION | Write Plan with requires_approval: true, add to Pending Actions in Dashboard → move email to Done |
| SPAM | Skip Plan → move email directly to Done, log as spam |

### Step 6: Update Dashboard
After processing each email:
1. Add activity log entry via dashboard_updater
2. After ALL emails processed: update queue counts

### Step 7: Log Everything
Every action is automatically logged by vault_processor's move operations.
Verify logs exist in /Logs/ for today.
```

#### Section 3: Quality Rules

```markdown
## Quality Rules

1. **Never fabricate information** — only reference what's in the email file
2. **Never send anything** — only draft. Sending happens after HITL approval (Silver tier)
3. **When in doubt, escalate** — mark as requires_approval: true
4. **Preserve original email** — the .md file in /Done/ is the audit record
5. **One Plan per email** — never merge multiple emails into one Plan
6. **Plan filename format:** PLAN_email_{category}_{sanitized_sender}_{timestamp}.md
7. **Draft responses follow Company Handbook tone** — professional but warm
8. **If email body is empty** — note it in analysis, still classify based on subject
9. **If sender is unknown** — always set requires_approval: true per Handbook rules
10. **Batch processing** — process ALL pending emails in one session, not one at a time
```

#### Section 4: Example Output

```markdown
## Example Plan Output

For an email from "John Smith <john@clienta.com>" with subject "January Invoice Request":

---
type: plan
source_file: Needs_Action/email/EMAIL_john_smith_2026-02-27T10-30-00.md
source_type: email
category: INVOICE_ACTION
priority: high
sender: John Smith <john@clienta.com>
subject: January Invoice Request
requires_approval: true
status: pending
created: 2026-02-27T10:35:00Z
---

## Triage Summary

**Category:** INVOICE_ACTION
**Priority:** High
**Sender:** John Smith (Tier 1 — VIP Client)
**Subject:** January Invoice Request

## Analysis

Client A's primary contact is requesting the January invoice. This is a financial
action that requires human approval per the Company Handbook. The client relationship
is Tier 1, so response time target is 4 hours for high priority.

## Recommended Actions

- [ ] Generate January invoice for Client A
- [ ] Send invoice via email (requires approval)
- [ ] Log transaction in /Accounting/

## Draft Response

Hi John,

Thank you for reaching out. I'm preparing your January invoice now and will
have it sent over shortly.

Best regards

## Approval Required

This action requires your approval. Review the draft above, then:
- To approve: move this plan to /Approved/
- To reject: move this plan to /Rejected/
```

## 4. What This Skill Does NOT Do

- Does NOT send emails (no MCP — that's Silver tier)
- Does NOT access Gmail API (the watcher already did that)
- Does NOT modify the original email files (they're moved to /Done/ as-is)
- Does NOT make financial decisions (only flags for human approval)
- Does NOT run autonomously in a loop (the orchestrator triggers it — Silver tier)
- Does NOT use subagents or fork context (runs in main session)

## 5. Validation Criteria

- [ ] `.claude/skills/email-triage/SKILL.md` exists
- [ ] YAML frontmatter has: name, description, allowed-tools
- [ ] Skill body has all 4 sections: Role, Workflow, Quality Rules, Example
- [ ] 7 triage categories defined with clear descriptions
- [ ] Plan file template matches CLAUDE.md frontmatter schema
- [ ] All file operations use vault_processor/dashboard_updater CLIs (not raw file writes)
- [ ] Company Handbook is referenced for tone and approval rules
- [ ] Quality rules include "never send", "when in doubt escalate", "one plan per email"
- [ ] Example output is complete and realistic
- [ ] File renders as valid Markdown in Obsidian
- [ ] No executable code in the skill (it's a prompt template only)
- [ ] Frontmatter doesn't include `disable-model-invocation` or `user-invocable: false`

## 6. Testing Protocol

Since skills are prompt templates (not code), testing is behavioral:

1. **Generate test data:** `DRY_RUN=true uv run python scripts/watchers/gmail_watcher.py --once`
2. **Invoke skill:** Ask Claude Code to process emails (it will auto-load the skill)
3. **Verify outputs:**
   - Plan files exist in /Plans/ with correct frontmatter
   - Categories match expected (critical email → ESCALATION or REPLY_NEEDED)
   - Dashboard.md updated with activity entries
   - Original emails moved to /Done/
   - Audit log entries in /Logs/
4. **Edge case test:** Create a file with no frontmatter → skill should handle gracefully
5. **Edge case test:** Create a file with sensitive keyword in subject → should ESCALATE

## 7. Integration Points (Future Tiers)

- **Silver:** Plans with `requires_approval: true` trigger HITL workflow → /Pending_Approval/
- **Silver:** Approved plans with draft responses trigger Email MCP to send
- **Gold:** CEO Briefing skill reads completed Plans for weekly summary
- **Gold:** Ralph Wiggum loop processes the full Needs_Action queue autonomously
