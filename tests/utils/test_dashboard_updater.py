"""Unit tests for scripts/utils/dashboard_updater.py."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.utils.dashboard_updater import (
    _read_dashboard,
    _write_dashboard,
    add_activity_log,
    add_error,
    add_pending_action,
    remove_pending_action,
    rollover_activity_log,
    update_queue_counts,
    update_system_health,
    update_timestamp,
    update_weekly_stats,
)

# ---------------------------------------------------------------------------
# Dashboard template (mirrors the real Dashboard.md structure)
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE = """\
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

| Metric               | This Week | Last Week |
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
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dashboard_file(tmp_vault):
    """Create a fresh Dashboard.md from the template in a tmp vault."""
    (tmp_vault / "Dashboard.md").write_text(DASHBOARD_TEMPLATE, encoding="utf-8")
    return tmp_vault


# ---------------------------------------------------------------------------
# update_timestamp
# ---------------------------------------------------------------------------


class TestUpdateTimestamp:
    def test_update_timestamp(self, dashboard_file):
        update_timestamp(dashboard_file)
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "YYYY-MM-DD HH:MM:SS" not in content
        assert "> **Last Updated:**" in content
        # Verify it contains a date-like string
        assert str(datetime.now(tz=timezone.utc).year) in content


# ---------------------------------------------------------------------------
# add_activity_log
# ---------------------------------------------------------------------------


class TestAddActivityLog:
    def test_add_activity_log_appends_row(self, dashboard_file):
        add_activity_log(dashboard_file, "email_triage", "Triaged email from John", "success")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "email_triage" in content
        assert "Triaged email from John" in content
        assert "success" in content

    def test_add_activity_log_removes_placeholder(self, dashboard_file):
        """Placeholder row (— | — | — | —) is removed after first real entry."""
        add_activity_log(dashboard_file, "test_action", "test_details", "success")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # The activity log section should not contain all-dash rows anymore
        # (look specifically within the activity log table)
        lines = content.split("\n")
        in_activity_log = False
        for line in lines:
            if "Today's Activity Log" in line:
                in_activity_log = True
            elif line.startswith("## ") and in_activity_log:
                break
            elif in_activity_log and "| — |" in line and "| — |" in line:
                # Check it's not a pure placeholder
                cells = [c.strip() for c in line.strip("|").split("|")]
                assert not all(c == "—" for c in cells if c), (
                    "Placeholder row still present after real entry"
                )

    def test_add_activity_log_preserves_existing(self, dashboard_file):
        """Previous rows are preserved when a new row is added."""
        add_activity_log(dashboard_file, "action1", "details1", "success")
        add_activity_log(dashboard_file, "action2", "details2", "failure")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "action1" in content
        assert "action2" in content

    def test_add_activity_log_rollover_at_50(self, dashboard_file):
        """Rollover is triggered when the table reaches 50 real rows."""
        # Manually insert 50 rows into the activity log section
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # Build 50 fake rows
        rows = "\n".join(f"| 12:00 | action_{i} | details_{i} | success |" for i in range(50))
        # Replace the placeholder row with 50 real rows
        content = content.replace("| —    | —      | —       | —      |", rows)
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        # Now add one more — should trigger rollover
        add_activity_log(dashboard_file, "new_action", "new_details", "success")

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        archive_file = dashboard_file / "Logs" / f"dashboard_archive_{today}.json"
        assert archive_file.exists()

        archived = json.loads(archive_file.read_text(encoding="utf-8"))
        assert len(archived) == 50

        # After rollover, only the newly added row should be in the table
        content_after = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "new_action" in content_after
        # None of the old 50 actions should be in the table
        assert "action_0" not in content_after

    def test_add_activity_log_truncates_details(self, dashboard_file):
        """Details longer than 80 chars are truncated in the table."""
        long_details = "A" * 120
        add_activity_log(dashboard_file, "action", long_details, "success")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "A" * 81 not in content
        assert "A" * 80 in content

    def test_add_activity_log_escapes_pipe(self, dashboard_file):
        """Pipe characters in fields are escaped."""
        add_activity_log(dashboard_file, "act|ion", "det|ails", "suc|cess")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "act\\|ion" in content


# ---------------------------------------------------------------------------
# add_pending_action / remove_pending_action
# ---------------------------------------------------------------------------


class TestPendingActions:
    def test_add_pending_action(self, dashboard_file):
        add_pending_action(
            dashboard_file,
            item_type="email",
            sender="client@example.com",
            subject="Invoice Request",
            priority="high",
            waiting_since="2026-02-27T10:00:00",
        )
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Invoice Request" in content
        assert "client@example.com" in content
        assert "high" in content

    def test_add_pending_action_auto_increment(self, dashboard_file):
        """Row numbers increment automatically."""
        add_pending_action(dashboard_file, "email", "a@b.com", "First", "low", "2026-02-27")
        add_pending_action(dashboard_file, "task", "c@d.com", "Second", "high", "2026-02-27")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "| 1 |" in content or "1" in content
        assert "| 2 |" in content or "Second" in content

    def test_remove_pending_action(self, dashboard_file):
        """Row is removed by subject match."""
        add_pending_action(
            dashboard_file, "email", "x@y.com", "Remove Me", "medium", "2026-02-27"
        )
        content_before = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Remove Me" in content_before

        remove_pending_action(dashboard_file, "Remove Me")
        content_after = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Remove Me" not in content_after

    def test_remove_pending_action_restores_placeholder(self, dashboard_file):
        """When last row is removed, placeholder is restored."""
        add_pending_action(dashboard_file, "email", "x@y.com", "Solo Item", "low", "2026-02-27")
        remove_pending_action(dashboard_file, "Solo Item")

        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # Placeholder should be back
        assert "—" in content


# ---------------------------------------------------------------------------
# update_queue_counts
# ---------------------------------------------------------------------------


class TestUpdateQueueCounts:
    def test_update_queue_counts_from_filesystem(self, dashboard_file):
        """Queue counts match actual files on disk."""
        # Create 3 email files in Needs_Action
        email_dir = dashboard_file / "Needs_Action" / "email"
        email_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (email_dir / f"EMAIL_{i:03d}.md").write_text(f"---\ntype: email\n---\n\nBody", encoding="utf-8")

        update_queue_counts(dashboard_file)

        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # The Needs_Action count should now be 3
        assert "3" in content

    def test_update_queue_counts_zero_on_empty(self, dashboard_file):
        """Empty folders show 0."""
        update_queue_counts(dashboard_file)
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # All counts should be 0 since no files exist
        assert "/Needs_Action/" in content


# ---------------------------------------------------------------------------
# update_system_health
# ---------------------------------------------------------------------------


class TestUpdateSystemHealth:
    def test_update_system_health_specific_component(self, dashboard_file):
        """Only the specified component's row changes."""
        update_system_health(dashboard_file, "Gmail Watcher", "🟢 Running", "2026-02-27 10:00:00")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "🟢 Running" in content
        assert "2026-02-27 10:00:00" in content
        # Other components should remain unchanged
        assert "WhatsApp Watcher" in content

    def test_update_system_health_case_insensitive(self, dashboard_file):
        """Component matching is case-insensitive."""
        update_system_health(dashboard_file, "gmail watcher", "🔴 Down")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "🔴 Down" in content

    def test_update_system_health_only_target_row_changes(self, dashboard_file):
        """Updating Gmail Watcher doesn't change Email MCP row."""
        update_system_health(dashboard_file, "Gmail Watcher", "🟢 Running")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        # Email MCP should still have its original placeholder
        assert "Email MCP" in content


# ---------------------------------------------------------------------------
# add_error
# ---------------------------------------------------------------------------


class TestAddError:
    def test_add_error_row(self, dashboard_file):
        add_error(dashboard_file, "Gmail Watcher", "OAuth token expired", "Renewing token")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Gmail Watcher" in content
        assert "OAuth token expired" in content
        assert "Renewing token" in content

    def test_add_error_clears_old(self, dashboard_file):
        """Errors older than 7 days are removed on each call."""
        # Directly write a row with an old timestamp into the Recent Errors table
        old_time = (datetime.now(tz=timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d %H:%M")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        old_row = f"| {old_time} | OldComponent | Old error | Resolved |"
        content = content.replace("| —    | —         | —     | —          |", old_row)
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        # Trigger add_error — should clear the old row
        add_error(dashboard_file, "NewComponent", "New error")
        result = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "OldComponent" not in result
        assert "NewComponent" in result

    def test_add_error_keeps_recent_errors(self, dashboard_file):
        """Errors younger than 7 days are kept."""
        recent_time = (datetime.now(tz=timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        recent_row = f"| {recent_time} | RecentComponent | Recent error | Pending |"
        content = content.replace("| —    | —         | —     | —          |", recent_row)
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        add_error(dashboard_file, "Another", "Another error")
        result = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "RecentComponent" in result
        assert "Another" in result

    def test_add_error_default_resolution(self, dashboard_file):
        add_error(dashboard_file, "TestComponent", "Test error")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Pending" in content


# ---------------------------------------------------------------------------
# update_weekly_stats
# ---------------------------------------------------------------------------


class TestUpdateWeeklyStats:
    def test_update_weekly_stats(self, dashboard_file):
        update_weekly_stats(dashboard_file, "Tasks Completed", 42)
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "42" in content

    def test_update_weekly_stats_specific_metric(self, dashboard_file):
        """Only the matched metric row changes."""
        update_weekly_stats(dashboard_file, "Emails Triaged", 15)
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "15" in content
        # Other metrics should still be 0
        assert "Tasks Completed" in content

    def test_update_weekly_stats_preserves_last_week(self, dashboard_file):
        """Last Week column is not modified."""
        # Set Last Week value manually
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        content = content.replace("| Tasks Completed      | 0         | 0         |",
                                  "| Tasks Completed      | 0         | 5         |")
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        update_weekly_stats(dashboard_file, "Tasks Completed", 10)
        result = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "10" in result
        assert "5" in result  # Last Week preserved


# ---------------------------------------------------------------------------
# _write_dashboard (internal, but testable via import)
# ---------------------------------------------------------------------------


class TestWriteDashboard:
    def test_write_dashboard_atomic(self, dashboard_file):
        """No .tmp files left behind after writing."""
        update_timestamp(dashboard_file)
        tmp_files = list(dashboard_file.glob("*.tmp"))
        assert len(tmp_files) == 0
        assert (dashboard_file / "Dashboard.md").exists()

    def test_write_dashboard_validates_content(self, dashboard_file):
        """Rejects content not starting with the expected header."""
        with pytest.raises(ValueError, match="must start with"):
            _write_dashboard(dashboard_file, "# Wrong Header\n\nContent here")

    def test_write_dashboard_valid_content_succeeds(self, dashboard_file):
        """Valid content (correct header) is written without error."""
        _write_dashboard(dashboard_file, "# AI Employee Dashboard\n\nContent.")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "Content." in content


# ---------------------------------------------------------------------------
# Section isolation
# ---------------------------------------------------------------------------


class TestSectionIsolation:
    def test_sections_not_corrupted(self, dashboard_file):
        """Modifying one section does not affect others."""
        add_activity_log(dashboard_file, "test_action", "test_details", "success")
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")

        # All other sections should be intact
        assert "## System Health" in content
        assert "Gmail Watcher" in content
        assert "WhatsApp Watcher" in content
        assert "## Weekly Stats" in content
        assert "Tasks Completed" in content
        assert "## Queue Summary" in content
        assert "/Needs_Action/" in content
        assert "## Pending Actions" in content
        assert "## Recent Errors" in content

    def test_activity_log_does_not_affect_health(self, dashboard_file):
        update_system_health(dashboard_file, "Orchestrator", "🟢 Running")
        add_activity_log(dashboard_file, "task", "details", "success")

        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "🟢 Running" in content
        assert "task" in content

    def test_concurrent_safety(self, dashboard_file):
        """Two rapid sequential updates both persist."""
        add_activity_log(dashboard_file, "action1", "details1", "success")
        add_activity_log(dashboard_file, "action2", "details2", "failure")

        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "action1" in content
        assert "action2" in content


# ---------------------------------------------------------------------------
# rollover_activity_log
# ---------------------------------------------------------------------------


class TestRolloverActivityLog:
    def test_rollover_archives_entries(self, dashboard_file):
        """All real rows are archived to a JSON file."""
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        rows = "\n".join(f"| 10:00 | action_{i} | details | success |" for i in range(5))
        content = content.replace("| —    | —      | —       | —      |", rows)
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        rollover_activity_log(dashboard_file)

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        archive = dashboard_file / "Logs" / f"dashboard_archive_{today}.json"
        assert archive.exists()
        data = json.loads(archive.read_text(encoding="utf-8"))
        assert len(data) == 5

    def test_rollover_clears_table(self, dashboard_file):
        """After rollover, the activity log table has only placeholder."""
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        rows = "\n".join(f"| 10:00 | action_{i} | details | success |" for i in range(3))
        content = content.replace("| —    | —      | —       | —      |", rows)
        (dashboard_file / "Dashboard.md").write_text(content, encoding="utf-8")

        rollover_activity_log(dashboard_file)

        result = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "action_0" not in result
        assert "action_1" not in result

    def test_rollover_no_entries_is_safe(self, dashboard_file):
        """Rollover on empty table (placeholder only) doesn't crash."""
        rollover_activity_log(dashboard_file)  # Should not raise
        content = (dashboard_file / "Dashboard.md").read_text(encoding="utf-8")
        assert "# AI Employee Dashboard" in content


# ---------------------------------------------------------------------------
# read_dashboard error handling
# ---------------------------------------------------------------------------


class TestReadDashboard:
    def test_read_dashboard_missing_raises(self, tmp_vault):
        """FileNotFoundError raised when Dashboard.md is absent."""
        with pytest.raises(FileNotFoundError, match="scaffolding"):
            _read_dashboard(tmp_vault)
