"""Unit tests for ApprovalWatcher."""

import json
import os
import time as time_module
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.watchers.approval_watcher import ApprovalWatcher, _update_frontmatter_fields


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_approval_file(
    directory: Path,
    filename: str = "ACTION_send_email_test.md",
    action_type: str = "send_email",
    target: str = "user@example.com",
    priority: str = "high",
    status: str = "approved",
    body: str = "Test email body.",
) -> Path:
    """Create a valid approval action file."""
    fm = {
        "type": "approval_request",
        "action_type": action_type,
        "target": target,
        "priority": priority,
        "status": status,
        "received": datetime.now(tz=timezone.utc).isoformat(),
        "action_payload": {
            "tool": action_type,
            "params": {
                "to": target,
                "subject": "Test Subject",
                "body": body,
            },
        },
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n## Action\n\nTest file."
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _make_rejection_file(
    directory: Path,
    filename: str = "ACTION_draft_email_test.md",
    action_type: str = "draft_email",
    target: str = "boss@example.com",
    priority: str = "medium",
) -> Path:
    """Create a valid rejection action file."""
    fm = {
        "type": "approval_request",
        "action_type": action_type,
        "target": target,
        "priority": priority,
        "status": "rejected",
        "received": datetime.now(tz=timezone.utc).isoformat(),
        "action_payload": {
            "tool": action_type,
            "params": {
                "to": target,
                "subject": "Draft Subject",
                "body": "Draft body content.",
            },
        },
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n## Rejection\n\nTest file."
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _success_result(action_type: str = "send_email", target: str = "user@example.com") -> dict:
    return {
        "success": True,
        "action_type": action_type,
        "target": target,
        "result": "OK",
        "dry_run": False,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "error": None,
    }


def _fail_result(error: str = "Connection error") -> dict:
    return {
        "success": False,
        "action_type": "send_email",
        "target": "user@example.com",
        "result": None,
        "dry_run": False,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_file(tmp_vault) -> Path:
    """Create a sample approved action file in /Approved/."""
    return _make_approval_file(tmp_vault / "Approved")


@pytest.fixture
def rejected_file(tmp_vault) -> Path:
    """Create a sample rejected action file in /Rejected/."""
    return _make_rejection_file(tmp_vault / "Rejected")


@pytest.fixture
def stale_pending_file(tmp_vault) -> Path:
    """Create a pending approval file with mtime >24hr ago."""
    pending_dir = tmp_vault / "Pending_Approval"
    pending_dir.mkdir(exist_ok=True)
    file_path = pending_dir / "ACTION_old_approval.md"
    fm = {
        "type": "approval_request",
        "action_type": "send_email",
        "target": "client@example.com",
        "priority": "high",
        "status": "pending_approval",
        "received": "2026-01-01T00:00:00+00:00",
        "action_payload": {
            "tool": "send_email",
            "params": {
                "to": "client@example.com",
                "subject": "Old request",
                "body": "This is stale.",
            },
        },
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    file_path.write_text(
        f"---\n{fm_str}---\n\n## Stale Request",
        encoding="utf-8",
    )
    # Set mtime to 25 hours ago
    old_time = time_module.time() - (25 * 3600)
    os.utime(file_path, (old_time, old_time))
    return file_path


@pytest.fixture
def approval_watcher(tmp_vault, monkeypatch) -> ApprovalWatcher:
    """ApprovalWatcher in DRY_RUN mode."""
    monkeypatch.setenv("DRY_RUN", "true")
    return ApprovalWatcher(vault_path=tmp_vault)


@pytest.fixture
def live_watcher(tmp_vault, monkeypatch) -> ApprovalWatcher:
    """ApprovalWatcher in LIVE mode for unit testing (executor mocked separately)."""
    monkeypatch.setenv("DRY_RUN", "false")
    return ApprovalWatcher(vault_path=tmp_vault)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_creates_approved_dir(tmp_vault, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    ApprovalWatcher(vault_path=tmp_vault)
    assert (tmp_vault / "Approved").is_dir()


def test_init_creates_rejected_dir(tmp_vault, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    ApprovalWatcher(vault_path=tmp_vault)
    assert (tmp_vault / "Rejected").is_dir()


def test_init_scan_directories(tmp_vault, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    scan_dirs = watcher.scan_directories
    assert tmp_vault / "Approved" in scan_dirs
    assert tmp_vault / "Rejected" in scan_dirs
    assert len(scan_dirs) == 2


# ---------------------------------------------------------------------------
# check_for_updates
# ---------------------------------------------------------------------------


def test_check_finds_approved_files(tmp_vault, approved_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    items = watcher.check_for_updates()
    assert any(i["folder"] == "Approved" and i["id"] == approved_file.name for i in items)


def test_check_finds_rejected_files(tmp_vault, rejected_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    items = watcher.check_for_updates()
    assert any(i["folder"] == "Rejected" and i["id"] == rejected_file.name for i in items)


def test_check_ignores_non_action_files(tmp_vault, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    # Create files that should be skipped
    (tmp_vault / "Approved" / "APPROVAL_something.md").write_text(
        "---\ntype: approval_request\n---\n", encoding="utf-8"
    )
    (tmp_vault / "Approved" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    items = watcher.check_for_updates()
    assert not any(i["id"] == "APPROVAL_something.md" for i in items)
    assert not any(i["id"] == "notes.md" for i in items)


def test_check_dry_run_generates_samples(tmp_vault, approval_watcher):
    items = approval_watcher.check_for_updates()
    assert len(items) >= 2
    assert any(i["folder"] == "Approved" for i in items)
    assert any(i["folder"] == "Rejected" for i in items)


def test_check_dedup_processed(tmp_vault, approved_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    watcher.mark_processed(approved_file.name)
    assert not watcher.should_process(approved_file.name)


def test_check_sorted_by_priority(tmp_vault, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    _make_approval_file(
        tmp_vault / "Approved",
        filename="ACTION_low.md",
        priority="low",
    )
    _make_approval_file(
        tmp_vault / "Approved",
        filename="ACTION_critical.md",
        priority="critical",
    )
    _make_approval_file(
        tmp_vault / "Approved",
        filename="ACTION_medium.md",
        priority="medium",
    )
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    items = watcher.check_for_updates()
    priorities = [i.get("priority") for i in items]
    # Critical must precede medium, medium must precede low
    if "critical" in priorities and "medium" in priorities:
        assert priorities.index("critical") < priorities.index("medium")
    if "medium" in priorities and "low" in priorities:
        assert priorities.index("medium") < priorities.index("low")


# ---------------------------------------------------------------------------
# Approval handling — success path
# ---------------------------------------------------------------------------


def test_handle_approval_executes_action(tmp_vault, approved_file, live_watcher):
    with patch.object(
        live_watcher.executor, "execute", return_value=_success_result()
    ) as mock_exec:
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        live_watcher._handle_approval(item)
        mock_exec.assert_called_once_with(approved_file)


def test_handle_approval_moves_to_done(tmp_vault, approved_file, live_watcher):
    with patch.object(live_watcher.executor, "execute", return_value=_success_result()):
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        done_path = live_watcher._handle_approval(item)
        assert (tmp_vault / "Done" / approved_file.name).exists()
        assert not approved_file.exists()
        assert done_path == tmp_vault / "Done" / approved_file.name


def test_handle_approval_updates_dashboard_activity(tmp_vault, approved_file, live_watcher):
    with patch.object(live_watcher.executor, "execute", return_value=_success_result()):
        with patch("scripts.watchers.approval_watcher.add_activity_log") as mock_log:
            item = {
                "id": approved_file.name,
                "path": approved_file,
                "folder": "Approved",
                "action_type": "send_email",
                "target": "user@example.com",
            }
            live_watcher._handle_approval(item)
            mock_log.assert_called_once()


def test_handle_approval_removes_pending(tmp_vault, approved_file, live_watcher):
    with patch.object(live_watcher.executor, "execute", return_value=_success_result()):
        with patch("scripts.watchers.approval_watcher.remove_pending_action") as mock_rm:
            item = {
                "id": approved_file.name,
                "path": approved_file,
                "folder": "Approved",
                "action_type": "send_email",
                "target": "user@example.com",
            }
            live_watcher._handle_approval(item)
            mock_rm.assert_called_once()


def test_handle_approval_logs_to_audit(tmp_vault, approved_file, live_watcher):
    with patch.object(live_watcher.executor, "execute", return_value=_success_result()):
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        live_watcher._handle_approval(item)
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = tmp_vault / "Logs" / f"{today}.json"
        assert log_file.exists()
        entries = json.loads(log_file.read_text(encoding="utf-8"))
        assert any(e.get("action_type") == "hitl_execution" for e in entries)


def test_handle_approval_updates_status_frontmatter(tmp_vault, approved_file, live_watcher):
    with patch.object(live_watcher.executor, "execute", return_value=_success_result()):
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        done_path = live_watcher._handle_approval(item)
        done_content = done_path.read_text(encoding="utf-8")
        assert "executed" in done_content


# ---------------------------------------------------------------------------
# Approval handling — failure path
# ---------------------------------------------------------------------------


def test_handle_approval_retries_on_failure(tmp_vault, approved_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault, max_retries=2, retry_delay=0)
    with patch.object(
        watcher.executor, "execute", return_value=_fail_result()
    ) as mock_exec:
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        watcher._handle_approval(item)
        # initial + 2 retries = 3 total calls
        assert mock_exec.call_count == 3


def test_handle_approval_keeps_file_on_exhaust(tmp_vault, approved_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault, max_retries=1, retry_delay=0)
    with patch.object(watcher.executor, "execute", return_value=_fail_result()):
        item = {
            "id": approved_file.name,
            "path": approved_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "user@example.com",
        }
        result_path = watcher._handle_approval(item)
        assert approved_file.exists()
        assert not (tmp_vault / "Done" / approved_file.name).exists()
        assert result_path == approved_file


def test_handle_approval_flags_error_on_dashboard(tmp_vault, approved_file, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault, max_retries=0, retry_delay=0)
    with patch.object(watcher.executor, "execute", return_value=_fail_result()):
        with patch("scripts.watchers.approval_watcher.add_error") as mock_err:
            item = {
                "id": approved_file.name,
                "path": approved_file,
                "folder": "Approved",
                "action_type": "send_email",
                "target": "user@example.com",
            }
            watcher._handle_approval(item)
            mock_err.assert_called_once()


def test_handle_approval_validation_failure(tmp_vault, monkeypatch):
    """File with empty body fails validation — execute should NOT be called."""
    monkeypatch.setenv("DRY_RUN", "false")
    bad_file = tmp_vault / "Approved" / "ACTION_bad_body.md"
    fm = {
        "type": "approval_request",
        "action_type": "send_email",
        "target": "x@example.com",
        "priority": "medium",
        "status": "pending",
        "action_payload": {
            "tool": "send_email",
            "params": {
                "to": "x@example.com",
                "subject": "Test",
                "body": "",  # Empty body — will fail validation
            },
        },
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    bad_file.write_text(f"---\n{fm_str}---\n\nBody", encoding="utf-8")

    watcher = ApprovalWatcher(vault_path=tmp_vault)
    with patch.object(watcher.executor, "execute") as mock_exec:
        item = {
            "id": bad_file.name,
            "path": bad_file,
            "folder": "Approved",
            "action_type": "send_email",
            "target": "x@example.com",
        }
        result_path = watcher._handle_approval(item)
        mock_exec.assert_not_called()
        assert bad_file.exists()


# ---------------------------------------------------------------------------
# Rejection handling
# ---------------------------------------------------------------------------


def test_handle_rejection_moves_to_done(tmp_vault, rejected_file, live_watcher):
    item = {
        "id": rejected_file.name,
        "path": rejected_file,
        "folder": "Rejected",
        "action_type": "draft_email",
        "target": "boss@example.com",
    }
    done_path = live_watcher._handle_rejection(item)
    assert (tmp_vault / "Done" / rejected_file.name).exists()
    assert not rejected_file.exists()
    assert done_path.parent == tmp_vault / "Done"


def test_handle_rejection_logs_rejection(tmp_vault, rejected_file, live_watcher):
    item = {
        "id": rejected_file.name,
        "path": rejected_file,
        "folder": "Rejected",
        "action_type": "draft_email",
        "target": "boss@example.com",
    }
    live_watcher._handle_rejection(item)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    log_file = tmp_vault / "Logs" / f"{today}.json"
    assert log_file.exists()
    entries = json.loads(log_file.read_text(encoding="utf-8"))
    assert any(e.get("action_type") == "hitl_rejection" for e in entries)


def test_handle_rejection_updates_dashboard(tmp_vault, rejected_file, live_watcher):
    with patch("scripts.watchers.approval_watcher.add_activity_log") as mock_log:
        with patch("scripts.watchers.approval_watcher.remove_pending_action") as mock_rm:
            item = {
                "id": rejected_file.name,
                "path": rejected_file,
                "folder": "Rejected",
                "action_type": "draft_email",
                "target": "boss@example.com",
            }
            live_watcher._handle_rejection(item)
            mock_log.assert_called_once()
            mock_rm.assert_called_once()


def test_handle_rejection_updates_status_frontmatter(tmp_vault, rejected_file, live_watcher):
    item = {
        "id": rejected_file.name,
        "path": rejected_file,
        "folder": "Rejected",
        "action_type": "draft_email",
        "target": "boss@example.com",
    }
    done_path = live_watcher._handle_rejection(item)
    done_content = done_path.read_text(encoding="utf-8")
    assert "rejected" in done_content


# ---------------------------------------------------------------------------
# Stale approval checking
# ---------------------------------------------------------------------------


def test_stale_detects_old_files(tmp_vault, stale_pending_file, live_watcher):
    stale = live_watcher.check_stale_approvals()
    assert stale_pending_file in stale


def test_stale_ignores_recent_files(tmp_vault, live_watcher):
    pending_dir = tmp_vault / "Pending_Approval"
    pending_dir.mkdir(exist_ok=True)
    recent_file = pending_dir / "ACTION_recent.md"
    fm = {
        "type": "approval_request",
        "action_type": "send_email",
        "target": "user@example.com",
        "priority": "medium",
        "status": "pending_approval",
        "received": datetime.now(tz=timezone.utc).isoformat(),
        "action_payload": {
            "tool": "send_email",
            "params": {"to": "x@example.com", "subject": "y", "body": "z"},
        },
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    recent_file.write_text(f"---\n{fm_str}---\n\nBody", encoding="utf-8")
    # mtime is now (recent) — no need to call utime

    stale = live_watcher.check_stale_approvals()
    assert recent_file not in stale


def test_stale_adds_dashboard_error(tmp_vault, stale_pending_file, live_watcher):
    with patch("scripts.watchers.approval_watcher.add_error") as mock_err:
        live_watcher.check_stale_approvals()
        mock_err.assert_called_once()


def test_stale_does_not_auto_reject(tmp_vault, stale_pending_file, live_watcher):
    live_watcher.check_stale_approvals()
    # File stays in /Pending_Approval/ — not moved anywhere
    assert stale_pending_file.exists()


def test_stale_configurable_expiry(tmp_vault, monkeypatch):
    """1-hour expiry detects 25h-old file; 100-hour expiry does not."""
    monkeypatch.setenv("DRY_RUN", "false")
    pending_dir = tmp_vault / "Pending_Approval"
    pending_dir.mkdir(exist_ok=True)
    file_path = pending_dir / "ACTION_configurable.md"
    fm = {
        "type": "approval_request",
        "action_type": "send_email",
        "target": "x@example.com",
        "status": "pending",
        "action_payload": {"tool": "send_email", "params": {"to": "x", "subject": "y", "body": "z"}},
    }
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    file_path.write_text(f"---\n{fm_str}---\n\nBody", encoding="utf-8")
    old_time = time_module.time() - (25 * 3600)
    os.utime(file_path, (old_time, old_time))

    # 1-hour expiry → stale
    watcher_1h = ApprovalWatcher(vault_path=tmp_vault, expiry_hours=1)
    stale_1h = watcher_1h.check_stale_approvals()
    assert file_path in stale_1h

    # 100-hour expiry → not yet stale (but stale flag was already written)
    # Reset stale flag by rewriting the file
    fm["stale"] = False  # type: ignore[assignment]
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    file_path.write_text(f"---\n{fm_str}---\n\nBody", encoding="utf-8")
    os.utime(file_path, (old_time, old_time))

    watcher_100h = ApprovalWatcher(vault_path=tmp_vault, expiry_hours=100)
    stale_100h = watcher_100h.check_stale_approvals()
    assert file_path not in stale_100h


def test_stale_no_dashboard_spam(tmp_vault, stale_pending_file, live_watcher):
    """The stale-loop fix: second call must NOT add a second Dashboard error."""
    with patch("scripts.watchers.approval_watcher.add_error") as mock_err:
        # First call: flags file and adds Dashboard error
        live_watcher.check_stale_approvals()
        assert mock_err.call_count == 1

        # Second call: file already has stale: true — no new Dashboard error
        live_watcher.check_stale_approvals()
        assert mock_err.call_count == 1  # Still 1, not 2


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_run_once_processes_both_folders(
    tmp_vault, approved_file, rejected_file, monkeypatch
):
    monkeypatch.setenv("DRY_RUN", "false")
    watcher = ApprovalWatcher(vault_path=tmp_vault)
    with patch.object(watcher.executor, "execute", return_value=_success_result()):
        results = watcher.run_once()
    assert len(results) == 2
    assert (tmp_vault / "Done" / approved_file.name).exists()
    assert (tmp_vault / "Done" / rejected_file.name).exists()


def test_full_cycle_dry_run(tmp_vault, approval_watcher):
    """DRY_RUN: generates files, processes them, archives to Done, writes logs."""
    results = approval_watcher.run_once()
    assert len(results) >= 2

    # At least one file should end up in Done (the rejection; approval may fail in dry-run)
    done_files = list((tmp_vault / "Done").glob("*.md"))
    assert len(done_files) >= 1

    # Audit log should have entries
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    log_file = tmp_vault / "Logs" / f"{today}.json"
    assert log_file.exists()
    entries = json.loads(log_file.read_text(encoding="utf-8"))
    assert len(entries) > 0


# ---------------------------------------------------------------------------
# _update_frontmatter_fields unit tests
# ---------------------------------------------------------------------------


def test_update_frontmatter_fields_adds_field(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("---\nstatus: pending\n---\n\nBody text.", encoding="utf-8")
    _update_frontmatter_fields(f, {"status": "executed", "stale": True})
    content = f.read_text(encoding="utf-8")
    assert "executed" in content
    assert "stale: true" in content.lower()


def test_update_frontmatter_fields_noop_on_missing_file(tmp_path):
    # Should not raise
    _update_frontmatter_fields(tmp_path / "nonexistent.md", {"status": "x"})


def test_update_frontmatter_fields_noop_on_no_frontmatter(tmp_path):
    f = tmp_path / "no_fm.md"
    f.write_text("No frontmatter here.", encoding="utf-8")
    _update_frontmatter_fields(f, {"status": "x"})
    assert f.read_text() == "No frontmatter here."
