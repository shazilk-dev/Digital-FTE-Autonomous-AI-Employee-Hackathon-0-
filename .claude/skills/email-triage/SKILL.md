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

```
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
```

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

## Example Plan Output

For an email from "John Smith <john@clienta.com>" with subject "January Invoice Request":

```
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
