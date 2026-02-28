# AI Employee Dashboard

> **Last Updated:** 2026-02-28 11:27:05
> **System Status:** 🟢 Online | 🟡 Degraded | 🔴 Offline

---

## Pending Actions (Needs Your Attention)

| #   | Type          | From                                | Subject                                                       | Priority | Waiting Since                    |
|-----|---------------|-------------------------------------|---------------------------------------------------------------|----------|----------------------------------|
| 1   | email         | Client A <client@example.com>       | URGENT: Overdue Invoice #2024-001 — ,000 overdue 30 days      | critical | 2026-02-27T02:56:26.941932+00:00 |
| 2   | email         | Client A <client@example.com>       | URGENT: Overdue Invoice #2024-001                             | critical | 2026-02-27T09:00:47.130287+00:00 |
| 3   | email         | Client A <client@example.com>       | URGENT: Overdue Invoice #2024-001                             | critical | 2026-02-27T09:01:07.052636+00:00 |
| 4   | email         | Jane Smith <jane.smith@example.com> | Q1 Strategy Meeting — Can you attend Thursday?                | high     | 2026-02-27T09:01:13.228650+00:00 |
| 5   | email         | Jane Smith <jane.smith@example.com> | Q1 Strategy Meeting - Can you attend Thursday?                | high     | 2026-02-27T09:01:25.313475+00:00 |
| 6   | send_email    | sarah@clientb.com                   | January Invoice — step 3 of 7                                 | high     | 2026-02-28T07:10:30.023305+00:00 |
| 7   | send_email    | sarah@clientb.com                   | Comprehensive reply (invoice+meeting+renewal) — step 6 of 7   | high     | 2026-02-28T07:10:30.457722+00:00 |
| 8   | linkedin_post | social-post-skill                   | Everyone wants AI to work autonomously. Nobody talks about... | medium   | 2026-02-28T11:27:05.718861+00:00 |

> _Items in /Pending_Approval/ appear here. Approve by moving to /Approved/._

---

## In Progress

| Task | Status | Started | Agent |
|------|--------|---------|-------|
| —    | —      | —       | local |

---

## Today's Activity Log

| Time  | Action                | Details                                                                          | Result           |
|-------|-----------------------|----------------------------------------------------------------------------------|------------------|
| 02:25 | Email Triage          | ESCALATION: X security login alert for @sk_techi (new login from ChromeDesktop/W | pending_approval |
| 02:25 | Email Triage          | FYI_ONLY: X password change confirmation for @sk_techi — auto-archived, no actio | success          |
| 02:49 | Bronze Verification   | Full pipeline check — Needs_Action/email/ confirmed empty, queue counts synced   | success          |
| 02:55 | email_triage          | ESCALATION: URGENT overdue invoice #2024-001 from Client A <client@example.com>  | pending_approval |
| 02:56 | email_triage          | ESCALATION: URGENT overdue invoice #2024-001 from Client A <client@example.com>  | pending_approval |
| 02:56 | email_triage          | MEETING_REQUEST: Q1 Strategy Meeting from Jane Smith <jane.smith@example.com> —  | pending_approval |
| 02:56 | email_triage          | MEETING_REQUEST: Q1 Strategy Meeting from Jane Smith <jane.smith@example.com> —  | pending_approval |
| 02:56 | email_triage          | SPAM: Promotional newsletter from newsletter@deals.example.com — '50% off all pr | success          |
| 02:56 | email_triage          | SPAM: Promotional newsletter from newsletter@deals.example.com — duplicate promo | success          |
| 09:00 | email_triage          | ESCALATION: Overdue invoice #2024-001 from Client A — ,000, 30 days overdue, esc | pending_approval |
| 09:00 | email_triage          | MEETING_REQUEST: Q1 Strategy Meeting Thursday 2pm from Jane Smith — draft reply  | pending_approval |
| 09:00 | email_triage          | SPAM: Promotional newsletter from newsletter@deals.example.com — auto-archived,  | success          |
| 14:59 | Executed: send_email  | Target: test@example.com                                                         | success          |
| 14:59 | Rejected: draft_email | Target: boss@example.com                                                         | rejected         |
| 15:01 | Rejected: send_email  | Target: reject@example.com                                                       | rejected         |
| 15:17 | Executed: send_email  | Target: verify@example.com                                                       | success          |
| 07:10 | email_triage          | Processed multi-request email from Sarah Johnson (Client B): invoice, contract r | pending_approval |
| 07:10 | plan_create           | Created 7-step task plan: PLAN_task_sarah_johnson_invoice_renewal_meeting_2026-0 | success          |
| 07:10 | hitl_request          | Created 2 approval requests: invoice email + comprehensive reply for sarah@clien | pending_approval |
| 11:27 | linkedin_post_drafted | LinkedIn Insight post drafted for Expertise pillar — HITL safety layer insight   | pending_approval |

---

## Queue Summary

| Folder             | Count |
|--------------------|-------|
| /Needs_Action/     | 11    |
| /Plans/            | 3     |
| /Pending_Approval/ | 3     |
| /In_Progress/      | 0     |
| /Done/ (today)     | 1     |

---

## System Health

| Component       | Status | Last Check |
|-----------------|--------|------------|
| Gmail Watcher   | —      | —          |
| WhatsApp Watcher| —      | —          |
| File Watcher    | —      | —          |
| Orchestrator    | —      | —          |
| Email MCP       | —      | —          |

---

## Weekly Stats

| Metric               | This Week | Last Week |
|----------------------|-----------|-----------|
| Tasks Completed      | 0         | 0         |
| Emails Triaged       | 0         | 0         |
| Approvals Pending    | 0         | 0         |
| Errors               | 0         | 0         |

---

## Recent Errors

| Time             | Component        | Error                                                                            | Resolution |
|------------------|------------------|----------------------------------------------------------------------------------|------------|
| 2026-02-27 14:55 | approval_watcher | Action failed — manual intervention needed: ACTION_send_email_test_example_com_2 | Pending    |
| 2026-02-27 15:01 | approval_watcher | Stale approval: send_email for stale@example.com (waiting 25h)                   | Pending    |

> _Errors auto-clear after 7 days. Full history in /Logs/_

---

_Managed by AI Employee v0.1 • Do not edit manually — Claude maintains this file_
