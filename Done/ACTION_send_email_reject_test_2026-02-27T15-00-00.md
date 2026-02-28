---
action_payload:
  params:
    bcc: ''
    body: 'This email should NOT be sent — it is being used to test

      the rejection flow of the HITL pipeline.

      '
    cc: ''
    subject: HITL Rejection Test
    to: reject@example.com
  server: email
  tool: send_email
action_type: send_email
created: '2026-02-27T15:00:00+00:00'
domain: email
expires: '2026-02-28T15:00:00+00:00'
priority: low
requires_approval: true
source_plan: null
source_task: null
status: rejected
target: reject@example.com
type: approval_request
---

## Action Summary

**Type:** Send Email
**To:** reject@example.com
**Subject:** HITL Rejection Test
**Priority:** Low

## Context

This approval request was created to test the rejection flow.
A human reviewed it and moved it to /Rejected/.

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.
