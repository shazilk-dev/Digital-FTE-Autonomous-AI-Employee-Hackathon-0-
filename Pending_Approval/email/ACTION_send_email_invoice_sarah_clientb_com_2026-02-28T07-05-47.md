---
type: approval_request
action_type: send_email
domain: email
target: "sarah@clientb.com"
priority: high
status: pending_approval
requires_approval: true
created: "2026-02-28T07:05:47Z"
expires: "2026-03-01T07:05:47Z"
source_plan: "Plans/PLAN_task_sarah_johnson_invoice_renewal_meeting_2026-02-28T07-05-47.md"
source_task: "Needs_Action/email/EMAIL_complex_test_2026-02-27T10-00-00.md"
action_payload:
  tool: send_email
  server: email
  params:
    to: "sarah@clientb.com"
    subject: "January 2026 Invoice — Client B"
    body: |
      Hi Sarah,

      Please find below your January 2026 invoice.

      [Invoice reference and details to be populated once the invoice document is generated in Step 2 of the plan.]

      Please let me know if you have any questions. I'll be in touch shortly about the meeting and contract renewal.

      Best regards
    cc: ""
    bcc: ""
---

## Action Summary

**Type:** Send Email
**To:** sarah@clientb.com
**Subject:** January 2026 Invoice — Client B
**Priority:** High
**Plan Step:** Step 3 of 7

> ⚠️ **Note:** The invoice amount and reference number must be completed in the `action_payload.params.body` above before approving. Complete Step 1 (look up billing rate) and Step 2 (generate invoice) first, then update this file with the actual invoice details.

## Context

This action was triggered by a multi-request email from Sarah Johnson (Client B) received 2026-02-27. She needs the January invoice by Friday (deadline has passed — treat as urgent). Claude's task-planner decomposed the email into a 7-step plan; this is Step 3: sending the invoice.

## Action Details

### Email Preview

**To:** sarah@clientb.com
**Subject:** January 2026 Invoice — Client B

---

Hi Sarah,

Please find below your January 2026 invoice.

[Invoice reference and details to be populated once the invoice document is generated in Step 2 of the plan.]

Please let me know if you have any questions. I'll be in touch shortly about the meeting and contract renewal.

Best regards

---

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder. The action will be executed automatically.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.

### ✏️ To Modify
Edit the `action_payload.params.body` in the frontmatter above before approving.
Update with the actual invoice reference number and amount from Step 2.

## Safety Notes

- This action will send a real email when approved
- Verify invoice details are complete before approving
- Verify recipient address: sarah@clientb.com
- The action expires 2026-03-01 — after that it will be auto-flagged as stale
