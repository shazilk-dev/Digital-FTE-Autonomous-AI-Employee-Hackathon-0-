---
name: hitl-handler
description: >
  Creates structured approval request files for actions that require human
  approval. Used by other skills (email-triage, social-post, task-planner)
  when they determine an action needs approval before execution.
  Reads Company_Handbook.md for approval matrix rules.
allowed-tools:
  - Bash(uv run python -m scripts.utils.vault_processor *)
  - Bash(uv run python -m scripts.utils.dashboard_updater *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(mkdir -p *)
  - Read
  - Write
---

# HITL Handler Skill

## When to Create Approval Requests

ALWAYS create an approval request for:
- Sending any email (send_email, reply_email)
- Posting to social media (linkedin_post, tweet, etc.)
- Any financial action (payment, invoice creation)
- Any action involving a NEW/UNKNOWN contact
- Any action flagged requires_approval: true in the source Plan

NEVER create approval requests for:
- Reading/searching (read-only operations)
- Moving files within the vault
- Updating Dashboard.md
- Creating Plan files
- Archiving to /Done/

When in doubt: CREATE AN APPROVAL REQUEST. It's always safer.

Reference Company_Handbook.md for the full approval matrix.

## How to Create Approval Requests

### Step 1: Determine Domain
- Email actions → domain: email
- Social media → domain: social
- Financial → domain: finance
- Everything else → domain: general

### Step 2: Build action_payload
The payload must contain everything the Action Executor needs to perform the action:

For send_email:
```yaml
action_payload:
  tool: send_email
  server: email
  params:
    to: recipient@example.com
    subject: "Email subject"
    body: "Full email body text"
    cc: ""
    bcc: ""
```

For draft_email:
```yaml
action_payload:
  tool: draft_email
  server: email
  params:
    to: recipient@example.com
    subject: "Email subject"
    body: "Full email body text"
```

For reply_email:
```yaml
action_payload:
  tool: reply_to_thread
  server: email
  params:
    thread_id: "gmail_thread_id"
    body: "Reply body text"
    reply_all: false
```

For linkedin_post:
```yaml
action_payload:
  tool: create_post
  server: linkedin
  params:
    content: "Post text"
    visibility: "public"
```

### Step 3: Create the File

Filename: `ACTION_{action_type}_{sanitized_target}_{timestamp}.md`
Location: `/Pending_Approval/{domain}/`

Ensure the domain subfolder exists:
```bash
mkdir -p Pending_Approval/email
mkdir -p Pending_Approval/social
mkdir -p Pending_Approval/finance
mkdir -p Pending_Approval/general
```

Write the file with full frontmatter and human-readable body using the template below.

### Step 4: Update Dashboard

After creating the approval request:
```bash
uv run python -m scripts.utils.dashboard_updater add-pending \
  --type "{action_type}" --from "{source}" --subject "{subject}" --priority "{priority}"

uv run python -m scripts.utils.dashboard_updater add-activity \
  "hitl_request" "Created approval: {action_type} for {target}" "pending_approval"
```

### Step 5: Inform the User

After creating the approval request, tell the user:
> "I've created an approval request for [action]. Please review it in
> `/Pending_Approval/{domain}/` and move it to `/Approved/` to proceed
> or `/Rejected/` to cancel."

## Approval Request Template

Use this exact format when creating approval request files:

```markdown
---
type: approval_request
action_type: send_email
domain: email
target: "john@example.com"
priority: high
status: pending_approval
requires_approval: true
created: "2026-02-27T10:30:00Z"
expires: "2026-02-28T10:30:00Z"
source_plan: "Plans/PLAN_email_invoice_john_2026-02-27T10-25-00.md"
source_task: "Needs_Action/email/EMAIL_john_smith_2026-02-27T10-00-00.md"
action_payload:
  tool: send_email
  server: email
  params:
    to: "john@example.com"
    subject: "Re: January Invoice Request"
    body: |
      Hi John,

      Thank you for reaching out. Please find attached your January invoice.

      Best regards
    cc: ""
    bcc: ""
---

## Action Summary

**Type:** Send Email
**To:** john@example.com
**Subject:** Re: January Invoice Request
**Priority:** High

## Context

This action was triggered by an email from John Smith requesting the January invoice.
Claude's email-triage skill classified this as INVOICE_ACTION (high priority).

## Action Details

### Email Preview

**To:** john@example.com
**Subject:** Re: January Invoice Request

---

Hi John,

Thank you for reaching out. Please find attached your January invoice.

Best regards

---

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder. The action will be executed automatically.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.

### ✏️ To Modify
Edit the `action_payload` in the frontmatter above before approving.
Changes to `params.body`, `params.to`, `params.subject` will be reflected in the sent email.

## Safety Notes

- This action will send a real email when approved
- Verify the recipient address is correct
- Review the email body for accuracy
- The action expires 24 hours after created — after that it will be auto-flagged as stale
```

## Frontmatter Field Reference

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| type | Yes | — | Always `approval_request` |
| action_type | Yes | — | send_email \| draft_email \| reply_email \| linkedin_post \| generic |
| domain | Yes | — | email \| social \| finance \| general |
| target | Yes | — | Human-readable target (email address, profile, etc.) |
| priority | Yes | — | Inherits from source task: critical \| high \| medium \| low |
| status | Yes | `pending_approval` | Fixed at creation |
| requires_approval | Yes | `true` | Fixed at creation |
| created | Yes | — | Current UTC ISO 8601 |
| expires | Yes | +24 hours | Configurable via `HITL_EXPIRY_HOURS` env |
| source_plan | No | null | Path to the Plan file that triggered this |
| source_task | No | null | Path to the original task file |
| action_payload | Yes | — | Nested dict with tool, server, params |
| action_payload.tool | Yes | — | MCP tool name: send_email \| draft_email \| reply_to_thread \| create_post |
| action_payload.server | Yes | — | MCP server name: email \| linkedin |
| action_payload.params | Yes | — | Tool-specific parameters |

## Integration with Email Triage Skill

When the email-triage skill creates a Plan with requires_approval: true:

1. The Plan file already contains the draft response and action type
2. Use the Plan's content to populate the approval request
3. Copy the draft response into action_payload.params.body
4. Link back to the Plan via source_plan field
5. Link back to the original email via source_task field

The email-triage skill should call this skill for any REPLY_NEEDED,
INVOICE_ACTION, or ESCALATION category emails.

## Timestamp Format

Use Python to get the current timestamp:
```bash
python -c "from datetime import datetime, timezone, timedelta; now=datetime.now(tz=timezone.utc); print('created:', now.isoformat()); print('expires:', (now+timedelta(hours=24)).isoformat())"
```
