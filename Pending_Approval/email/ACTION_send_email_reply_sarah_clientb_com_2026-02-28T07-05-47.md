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
    subject: "Re: Need January invoice, contract renewal, and meeting next week"
    body: |
      Hi Sarah,

      Happy to help with all three items:

      1. **Invoice:** Your January invoice has been sent separately — apologies for the slight delay.

      2. **Meeting:** I'm available on the following slots next week:
         - Tuesday 3 March: [TIME SLOTS to be filled from Step 4 calendar check]
         - Wednesday 4 March: [TIME SLOTS to be filled from Step 4 calendar check]
         Let me know which works best for you.

      3. **Contract renewal:** Absolutely, happy to discuss terms. I'll come prepared with a proposal — we can cover this during our meeting.

      Looking forward to speaking soon.

      Best regards
    cc: ""
    bcc: ""
---

## Action Summary

**Type:** Send Email (Comprehensive Reply)
**To:** sarah@clientb.com
**Subject:** Re: Need January invoice, contract renewal, and meeting next week
**Priority:** High
**Plan Step:** Step 6 of 7

> ⚠️ **Blocked:** This approval request should only be actioned AFTER:
> - Step 3 (Invoice email) has been approved and sent
> - Step 4 (Calendar availability) has been checked and slots confirmed
> - Step 5 (Renewal talking points) has been drafted by human
>
> Update `action_payload.params.body` with actual meeting time slots before approving.

## Context

This is the comprehensive follow-up reply to Sarah Johnson covering all three items in her original email. It confirms the invoice was sent, proposes meeting times, and acknowledges the contract renewal discussion. This is Step 6 of the 7-step plan.

## Action Details

### Email Preview

**To:** sarah@clientb.com
**Subject:** Re: Need January invoice, contract renewal, and meeting next week

---

Hi Sarah,

Happy to help with all three items:

1. **Invoice:** Your January invoice has been sent separately — apologies for the slight delay.

2. **Meeting:** I'm available on the following slots next week:
   - Tuesday 3 March: [TIME SLOTS to be filled from Step 4 calendar check]
   - Wednesday 4 March: [TIME SLOTS to be filled from Step 4 calendar check]
   Let me know which works best for you.

3. **Contract renewal:** Absolutely, happy to discuss terms. I'll come prepared with a proposal — we can cover this during our meeting.

Looking forward to speaking soon.

Best regards

---

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder. The action will be executed automatically.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.

### ✏️ To Modify
Edit the `action_payload.params.body` in the frontmatter above before approving.
Fill in the actual meeting time slots from Step 4 before sending.

## Safety Notes

- This action will send a real email when approved
- Verify meeting time slots are filled in before approving
- Do not approve until Steps 3, 4, and 5 are all complete
- Verify recipient address: sarah@clientb.com
- The action expires 2026-03-01 — after that it will be auto-flagged as stale
