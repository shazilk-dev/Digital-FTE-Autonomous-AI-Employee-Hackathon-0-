# Spec: Dashboard.md — Real-Time Operations View

> **Component:** `Dashboard.md` (vault root)
> **Priority:** P0 — The human's primary interface to the AI Employee
> **Updated By:** Claude after every task completion
> **Platinum Rule:** Single-writer (Local agent only in Platinum tier)

## 1. Objective

Create the Dashboard that serves as the real-time operations view in Obsidian.
Claude updates this file after every action. The human opens Obsidian and immediately
sees: what's pending, what's done, what needs attention, and system health.

## 2. Design Principles

- **Glanceable:** The human should understand system state in <10 seconds
- **Structured:** Use consistent sections so Claude can programmatically update specific parts
- **Time-stamped:** Every update includes when it happened
- **Non-destructive:** Claude appends to activity log, never deletes history (roll over weekly)

## 3. Dashboard Template

The following is the EXACT template to create. Use placeholder data (dashes and zeros).
Do not add real data — that happens during runtime.

```markdown
# AI Employee Dashboard

> **Last Updated:** YYYY-MM-DD HH:MM:SS
> **System Status:** 🟢 Online | 🟡 Degraded | 🔴 Offline

---

## Pending Actions (Needs Your Attention)

| # | Type | From | Subject | Priority | Waiting Since |
|---|------|------|---------|----------|---------------|
| — | —    | —    | —       | —        | —             |

> _Items in /Pending_Approval/ appear here. Approve by moving to /Approved/._

---

## In Progress

| Task | Status | Started | Agent |
|------|--------|---------|-------|
| —    | —      | —       | local |

---

## Today's Activity Log

| Time | Action | Details | Result |
|------|--------|---------|--------|
| —    | —      | —       | —      |

---

## Queue Summary

| Folder            | Count |
|-------------------|-------|
| /Needs_Action/    | 0     |
| /Plans/           | 0     |
| /Pending_Approval/| 0     |
| /In_Progress/     | 0     |
| /Done/ (today)    | 0     |

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

| Metric              | This Week | Last Week |
|----------------------|-----------|-----------|
| Tasks Completed      | 0         | 0         |
| Emails Triaged       | 0         | 0         |
| Approvals Pending    | 0         | 0         |
| Errors               | 0         | 0         |

---

## Recent Errors

| Time | Component | Error | Resolution |
|------|-----------|-------|------------|
| —    | —         | —     | —          |

> _Errors auto-clear after 7 days. Full history in /Logs/_

---

_Managed by AI Employee v0.1 • Do not edit manually — Claude maintains this file_
```

## 4. Update Rules (How Claude Modifies This File)

### 4A. After Triaging an Item
- Increment `/Needs_Action/` count or decrement if item moved out
- Add row to "Today's Activity Log"
- Update "Last Updated" timestamp

### 4B. After Creating an Approval Request
- Add row to "Pending Actions" table with details from the approval file's frontmatter
- Increment `/Pending_Approval/` count
- Log the action in "Today's Activity Log"

### 4C. After Task Completion
- Remove from "In Progress" table (if present)
- Add to "Today's Activity Log"
- Increment `/Done/ (today)` count
- Decrement source folder count
- Update "Weekly Stats" if applicable

### 4D. On Error
- Add row to "Recent Errors" table
- Update "System Health" status for the affected component
- Change System Status emoji if system is degraded

### 4E. Daily Rollover (Scheduled, 00:00)
- Archive today's activity log entries to /Logs/YYYY-MM-DD.json
- Clear "Today's Activity Log" table (reset to placeholder row)
- Refresh all Queue Summary counts by scanning the filesystem
- Clear "Recent Errors" entries older than 7 days

### 4F. Programmatic Update Pattern

Claude should follow this pattern for safe file updates:

1. Read full Dashboard.md content
2. Find the target section by its `## Heading`
3. Find the Markdown table within that section
4. Append a new row (for logs/errors) OR update a cell value (for counts)
5. Update the `> **Last Updated:**` line with current ISO 8601 timestamp
6. Write the complete file back

**CRITICAL RULES:**
- Never truncate or lose existing table rows. Append only for activity logs.
- Roll over after 50 activity log entries to prevent file bloat.
- Archive overflow to /Logs/dashboard_archive_YYYY-MM-DD.json.
- File must be valid Markdown at ALL times — a partial write corrupts Obsidian rendering.

## 5. Validation Criteria

- [ ] File is at vault root: `Dashboard.md`
- [ ] All 7 sections present: Pending Actions, In Progress, Today's Activity Log, Queue Summary, System Health, Weekly Stats, Recent Errors
- [ ] All tables use proper Markdown pipe syntax (renders in Obsidian)
- [ ] "Last Updated" timestamp placeholder is present
- [ ] System Status emoji indicator is present (🟢/🟡/🔴)
- [ ] Footer attribution line is present
- [ ] File renders cleanly in Obsidian preview mode
- [ ] No hardcoded real data — all rows are placeholder dashes or zeros
- [ ] Queue Summary lists all 5 pipeline folders

## 6. Edge Cases

- **Concurrent updates (Platinum):** Enforce single-writer rule — only Local agent writes Dashboard.md. Cloud agent writes to /Updates/ folder instead, and Local merges on sync.
- **Large activity log:** Roll over after 50 entries. Archive to /Logs/dashboard_archive_YYYY-MM-DD.json before clearing.
- **Obsidian live preview conflict:** If user has Dashboard.md open in Obsidian while Claude writes, Obsidian auto-reloads. File must be valid Markdown at every write — never write partial content.
- **Missing folders:** If a folder listed in Queue Summary doesn't exist, show count as "—" not 0, and add to Recent Errors.
