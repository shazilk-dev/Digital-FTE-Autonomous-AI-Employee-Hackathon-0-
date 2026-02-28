---
action_payload:
  params:
    bcc: ''
    body: 'Hi,


      This is an end-to-end HITL workflow test email.


      If you are reading this, the approval pipeline is working correctly.


      Best regards,

      AI Employee

      '
    cc: ''
    subject: HITL Test
    to: test@example.com
  server: email
  tool: send_email
action_type: send_email
created: '2026-02-27T14:53:29.016401+00:00'
domain: email
expires: '2026-02-28T14:53:29.016401+00:00'
priority: high
requires_approval: true
source_plan: null
source_task: null
status: pending_approval
target: test@example.com
type: approval_request
---

## Action Summary

**Type:** Send Email
**To:** test@example.com
**Subject:** HITL Test
**Priority:** High

## Context

This is a manually created test approval request to validate the end-to-end
HITL workflow: Pending_Approval → Approved → ApprovalWatcher → Done.

## Action Details

### Email Preview

**To:** test@example.com
**Subject:** HITL Test

---

Hi,

This is an end-to-end HITL workflow test email.

If you are reading this, the approval pipeline is working correctly.

Best regards,
AI Employee

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

- This action will send a real email when approved (DRY_RUN bypasses actual sending)
- Verify the recipient address is correct
- Review the email body for accuracy
- The action expires 24 hours after created — after that it will be auto-flagged as stale
