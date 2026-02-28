---
type: plan
plan_type: multi_step
source_type: email
source_file: "Needs_Action/email/EMAIL_complex_test_2026-02-27T10-00-00.md"
title: "Sarah Johnson — January Invoice, Contract Renewal, and Meeting"
priority: high
status: pending
total_steps: 7
completed_steps: 0
requires_approval: true
created: "2026-02-28T07:05:47Z"
updated: "2026-02-28T07:05:47Z"
estimated_effort: "45 minutes"
due_date: "2026-02-28T17:00:00Z"
tags: ["email", "invoice", "contract", "meeting", "client-b"]
---

## Sarah Johnson — January Invoice, Contract Renewal, and Meeting

**Source:** Email from Sarah Johnson <sarah@clientb.com> with three requests: January invoice (needed by Friday — URGENT), contract renewal discussion, and meeting next Tuesday or Wednesday.
**Priority:** High
**Status:** Pending
**Progress:** 0/7 steps complete

> ⚠️ **Invoice deadline note:** Sarah requested the invoice "by Friday" (2026-02-27). It is now 2026-02-28 — the invoice is overdue and should be prioritized immediately.

## Steps

### Step 1: Look up Client B billing rate

- **Status:** 📋 pending
- **Domain:** accounting
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Check /Accounting/ for Client B / Sarah Johnson's current billing rate and contract terms

Look up Sarah Johnson / Client B's current billing rate and any applicable contract terms in the vault. This data is required to generate the correct invoice in Step 2.

### Step 2: Generate January invoice

- **Status:** ⏸ blocked
- **Domain:** accounting
- **Depends On:** Step 1
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Use rate from Step 1; invoice covers January 2026 services. Deadline was Friday 2026-02-27 — treat as urgent.

Calculate January 2026 charges based on the rate retrieved in Step 1 and generate the invoice document. Log the invoice in /Accounting/ with a reference number.

### Step 3: Send invoice email to Sarah

- **Status:** ⏸ blocked
- **Domain:** email
- **Depends On:** Step 2
- **Requires Approval:** Yes
- **Assigned To:** auto → hitl-handler
- **Notes:** Email to sarah@clientb.com with invoice attached or referenced. Requires HITL approval before sending.

Draft and send the January invoice to Sarah at sarah@clientb.com. The draft is in Pending_Approval/email/. Requires HITL approval per Company Handbook (sending email to external recipient requires approval).

### Step 4: Check calendar availability (next Tuesday/Wednesday)

- **Status:** 📋 pending
- **Domain:** calendar
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Next Tuesday = 2026-03-03, next Wednesday = 2026-03-04. Check for open slots. Can run in parallel with Steps 1–3.

Check the calendar for available meeting slots on Tuesday 2026-03-03 and Wednesday 2026-03-04. Propose 2–3 time options per day to give Sarah flexibility.

### Step 5: Draft contract renewal discussion points

- **Status:** 📋 pending
- **Domain:** manual
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** human
- **Notes:** Contract expires March 2026 — prepare talking points for renewal terms. Can run in parallel with Steps 1–4. Requires human input on desired terms.

Prepare key discussion points for the Client B contract renewal: current terms, proposed changes, pricing adjustments, and any new scope items. This step requires the human to define renewal terms before the meeting.

### Step 6: Reply to Sarah with comprehensive update

- **Status:** ⏸ blocked
- **Domain:** email
- **Depends On:** Steps 3, 4, 5
- **Requires Approval:** Yes
- **Assigned To:** auto → hitl-handler
- **Notes:** Single reply covering all three items: invoice sent, meeting times proposed, renewal discussion confirmed. Requires HITL approval.

Draft a comprehensive reply to Sarah confirming: (1) invoice has been sent (Step 3), (2) available meeting times (Step 4), (3) readiness to discuss contract renewal. This reply should only be sent after Steps 3, 4, and 5 are all complete.

### Step 7: Log invoice transaction in /Accounting/

- **Status:** ⏸ blocked
- **Domain:** accounting
- **Depends On:** Step 3
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Record invoice number, amount, and date in /Accounting/ for bookkeeping.

After the invoice is sent (Step 3 approved and executed), log the transaction in /Accounting/ with full details: client name, invoice number, amount, date sent, and payment terms.

## Dependencies

```
Step 1 (Look up rate) ──▶ Step 2 (Generate invoice) ──▶ Step 3 (Send invoice email) ──▶ Step 6 (Comprehensive reply)
                                                          Step 3 ──▶ Step 7 (Log transaction)
Step 4 (Check calendar) ───────────────────────────────────────────────────────────────▶ Step 6
Step 5 (Renewal talking points) ────────────────────────────────────────────────────▶ Step 6
```

## Approval Requirements

- **Step 3:** Sending invoice email to external recipient (sarah@clientb.com) → HITL required per Company Handbook
- **Step 6:** Comprehensive reply email to client → HITL required per Company Handbook

Approval requests created in:
- `Pending_Approval/email/ACTION_send_email_invoice_sarah_clientb_com_2026-02-28T07-05-47.md`
- `Pending_Approval/email/ACTION_send_email_reply_sarah_clientb_com_2026-02-28T07-05-47.md`

## Notes

- Steps 1, 4, and 5 can start immediately (no dependencies)
- Invoice deadline was Friday 2026-02-27 — the invoice is overdue, prioritize Steps 1–3
- Contract renewal is less time-sensitive but must be addressed before March
- "Next Tuesday or Wednesday" = 2026-03-03 or 2026-03-04
- Sarah is a Client B contact — treat as Tier 1 (VIP) unless handbook specifies otherwise; response target: 4 hours (high priority)
