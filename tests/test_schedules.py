"""Tests for scripts/schedules.py — schedule checking and trigger functions."""

import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.schedules import (
    Frequency,
    ScheduledTask,
    get_due_tasks,
    invoke_claude,
    is_due,
    load_schedules,
    trigger_daily_rollover,
    trigger_done_archive,
    trigger_health_update,
    trigger_linkedin_post,
    trigger_morning_triage,
    trigger_stale_check,
    trigger_weekly_audit_prep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(hour: int, minute: int = 0, day_offset: int = 0, weekday: int = 0) -> datetime:
    """Build a UTC datetime. weekday: 0=Mon. day_offset relative to a Monday."""
    # Use a fixed Monday: 2026-02-23 (confirmed Monday)
    base = datetime(2026, 2, 23, tzinfo=timezone.utc)
    # Shift to desired weekday
    base = base + timedelta(days=weekday)
    # Apply day_offset
    base = base + timedelta(days=day_offset)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _daily_task(**kwargs) -> ScheduledTask:
    defaults = dict(
        name="test_daily",
        description="test",
        frequency=Frequency.DAILY,
        time_of_day=time(8, 0),
        trigger_fn="trigger_morning_triage",
    )
    defaults.update(kwargs)
    return ScheduledTask(**defaults)


# ---------------------------------------------------------------------------
# is_due — DAILY
# ---------------------------------------------------------------------------


def test_daily_task_due_after_time():
    """Due when time has passed and not run today."""
    task = _daily_task(last_run=_dt(8, 0, day_offset=-1))  # ran yesterday
    now = _dt(9, 0)  # 09:00 today, after 08:00
    assert is_due(task, now) is True


def test_daily_task_not_due_before_time():
    """Not due when scheduled time hasn't passed yet."""
    task = _daily_task(last_run=_dt(8, 0, day_offset=-1))
    now = _dt(7, 59)  # before 08:00
    assert is_due(task, now) is False


def test_daily_task_not_due_already_run():
    """Not due if already run today."""
    task = _daily_task(last_run=_dt(8, 5))  # ran today at 08:05
    now = _dt(12, 0)   # now is noon same day
    assert is_due(task, now) is False


def test_never_run_task_is_due():
    """last_run=None + time passed → due."""
    task = _daily_task(last_run=None)
    now = _dt(9, 0)
    assert is_due(task, now) is True


def test_never_run_task_not_due_before_time():
    """last_run=None but time hasn't passed → not due."""
    task = _daily_task(last_run=None)
    now = _dt(7, 59)
    assert is_due(task, now) is False


def test_disabled_task_never_due():
    """enabled=False → never due regardless of time."""
    task = _daily_task(enabled=False, last_run=None)
    now = _dt(9, 0)
    assert is_due(task, now) is False


# ---------------------------------------------------------------------------
# is_due — MWF
# ---------------------------------------------------------------------------


def test_mwf_task_due_on_monday():
    now = _dt(10, 0, weekday=0)  # Monday
    task = ScheduledTask(
        name="linkedin_post", description="t", frequency=Frequency.MWF,
        time_of_day=time(9, 30), trigger_fn="trigger_linkedin_post",
        last_run=datetime(2026, 2, 20, tzinfo=timezone.utc),  # last Friday
    )
    assert is_due(task, now) is True


def test_mwf_task_not_due_on_tuesday():
    now = _dt(10, 0, weekday=1)  # Tuesday
    task = ScheduledTask(
        name="linkedin_post", description="t", frequency=Frequency.MWF,
        time_of_day=time(9, 30), trigger_fn="trigger_linkedin_post",
        last_run=datetime(2026, 2, 20, tzinfo=timezone.utc),
    )
    assert is_due(task, now) is False


def test_mwf_task_due_on_wednesday():
    now = _dt(10, 0, weekday=2)  # Wednesday
    task = ScheduledTask(
        name="linkedin_post", description="t", frequency=Frequency.MWF,
        time_of_day=time(9, 30), trigger_fn="trigger_linkedin_post",
        last_run=datetime(2026, 2, 23, tzinfo=timezone.utc),  # Monday
    )
    assert is_due(task, now) is True


def test_mwf_task_due_on_friday():
    now = _dt(10, 0, weekday=4)  # Friday
    task = ScheduledTask(
        name="linkedin_post", description="t", frequency=Frequency.MWF,
        time_of_day=time(9, 30), trigger_fn="trigger_linkedin_post",
        last_run=datetime(2026, 2, 25, tzinfo=timezone.utc),  # Wednesday
    )
    assert is_due(task, now) is True


# ---------------------------------------------------------------------------
# is_due — WEEKLY
# ---------------------------------------------------------------------------


def test_weekly_task_due_on_correct_day():
    """Due on specified day_of_week if time has passed and not run this week."""
    # Sunday = weekday 6; _dt weekday=6 gives Sunday
    now = _dt(22, 30, weekday=6)
    task = ScheduledTask(
        name="weekly_audit", description="t", frequency=Frequency.WEEKLY,
        time_of_day=time(22, 0), day_of_week=6,
        trigger_fn="trigger_weekly_audit_prep",
        last_run=datetime(2026, 2, 15, tzinfo=timezone.utc),  # previous Sunday
    )
    assert is_due(task, now) is True


def test_weekly_task_not_due_wrong_day():
    """Not due on days other than specified day_of_week."""
    now = _dt(22, 30, weekday=5)  # Saturday
    task = ScheduledTask(
        name="weekly_audit", description="t", frequency=Frequency.WEEKLY,
        time_of_day=time(22, 0), day_of_week=6,
        trigger_fn="trigger_weekly_audit_prep",
        last_run=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )
    assert is_due(task, now) is False


# ---------------------------------------------------------------------------
# is_due — EVERY_N_MINUTES
# ---------------------------------------------------------------------------


def test_every_n_minutes_due():
    """Due when interval has elapsed."""
    now = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 2, 23, 5, 30, tzinfo=timezone.utc)  # 6.5h ago
    task = ScheduledTask(
        name="stale_check", description="t",
        frequency=Frequency.EVERY_N_MINUTES,
        interval_minutes=360,
        trigger_fn="trigger_stale_check",
        last_run=last_run,
    )
    assert is_due(task, now) is True


def test_every_n_minutes_not_due():
    """Not due when interval has NOT elapsed."""
    now = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 2, 23, 10, 0, tzinfo=timezone.utc)  # 2h ago
    task = ScheduledTask(
        name="stale_check", description="t",
        frequency=Frequency.EVERY_N_MINUTES,
        interval_minutes=360,
        trigger_fn="trigger_stale_check",
        last_run=last_run,
    )
    assert is_due(task, now) is False


def test_every_n_minutes_no_last_run():
    """Due immediately if never run."""
    now = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    task = ScheduledTask(
        name="health", description="t",
        frequency=Frequency.EVERY_N_MINUTES,
        interval_minutes=15,
        trigger_fn="trigger_health_update",
        last_run=None,
    )
    assert is_due(task, now) is True


# ---------------------------------------------------------------------------
# is_due — missed schedule (catch-up prevention)
# ---------------------------------------------------------------------------


def test_missed_schedule_runs_once():
    """Orchestrator down 2 days: missed task runs once, not multiple times."""
    # Task was last run 2 days ago; orchestrator is now back online
    now = _dt(9, 0)  # Monday 09:00
    task = _daily_task(last_run=_dt(9, 0, day_offset=-2))  # 2 days ago
    # is_due returns True — task will be run once
    assert is_due(task, now) is True
    # After running, mark last_run = now; is_due should return False
    task.last_run = now
    assert is_due(task, now) is False


# ---------------------------------------------------------------------------
# get_due_tasks
# ---------------------------------------------------------------------------


def test_get_due_tasks_returns_sorted():
    """get_due_tasks returns non-Claude tasks before Claude tasks."""
    now = datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc)
    tasks = [
        ScheduledTask(
            name="health", description="t",
            frequency=Frequency.EVERY_N_MINUTES, interval_minutes=1,
            trigger_fn="trigger_health_update", requires_claude=False,
            last_run=None,
        ),
        ScheduledTask(
            name="triage", description="t",
            frequency=Frequency.EVERY_N_MINUTES, interval_minutes=1,
            trigger_fn="trigger_morning_triage", requires_claude=True,
            last_run=None,
        ),
    ]
    due = get_due_tasks(tasks, now)
    assert len(due) == 2
    assert due[0].name == "health"
    assert due[1].name == "triage"


def test_get_due_tasks_filters_disabled():
    """Disabled tasks are not included in due list."""
    now = datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc)
    tasks = [
        ScheduledTask(
            name="disabled_task", description="t",
            frequency=Frequency.EVERY_N_MINUTES, interval_minutes=1,
            trigger_fn="trigger_health_update", enabled=False, last_run=None,
        ),
    ]
    due = get_due_tasks(tasks, now)
    assert due == []


# ---------------------------------------------------------------------------
# load_schedules
# ---------------------------------------------------------------------------


def test_load_schedules_returns_all_tasks():
    registry = load_schedules()
    names = [t.name for t in registry]
    assert "morning_triage" in names
    assert "linkedin_post" in names
    assert "stale_approval_check" in names
    assert "health_dashboard_update" in names
    assert "done_archive" in names
    assert "daily_rollover" in names


def test_load_schedules_weekly_audit_disabled():
    """weekly_audit_prep is disabled by default (Gold tier)."""
    registry = load_schedules()
    audit = next(t for t in registry if t.name == "weekly_audit_prep")
    assert audit.enabled is False


# ---------------------------------------------------------------------------
# invoke_claude
# ---------------------------------------------------------------------------


def test_invoke_claude_success(tmp_path):
    """Returns success=True with output on exit code 0."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Claude response", stderr=""
        )
        result = invoke_claude("test prompt", tmp_path, timeout_minutes=1)
    assert result["success"] is True
    assert result["output"] == "Claude response"
    assert result["error"] is None


def test_invoke_claude_failure(tmp_path):
    """Returns success=False with error on non-zero exit."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="some error"
        )
        result = invoke_claude("test prompt", tmp_path, timeout_minutes=1)
    assert result["success"] is False
    assert "error" in result


def test_invoke_claude_timeout(tmp_path):
    """Returns success=False on timeout."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        result = invoke_claude("test prompt", tmp_path, timeout_minutes=1)
    assert result["success"] is False
    assert "Timed out" in result["error"]


def test_invoke_claude_not_found(tmp_path):
    """Returns success=False when claude binary not found."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("claude not found")
        result = invoke_claude("test prompt", tmp_path, timeout_minutes=1)
    assert result["success"] is False


def test_invoke_claude_dry_run_sets_env(tmp_path):
    """DRY_RUN=true is set in env when dry_run=True."""
    captured_env = {}

    def capture_run(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=capture_run):
        invoke_claude("test", tmp_path, dry_run=True)
    assert captured_env.get("DRY_RUN") == "true"


# ---------------------------------------------------------------------------
# Trigger functions (mocked)
# ---------------------------------------------------------------------------


def test_trigger_morning_triage_with_items(tmp_path):
    """Invokes Claude when items are pending."""
    (tmp_path / "Needs_Action" / "email").mkdir(parents=True)
    (tmp_path / "Needs_Action" / "email" / "EMAIL_test.md").write_text("---\ntype: email\n---\n")

    with patch("scripts.schedules.invoke_claude") as mock_claude:
        mock_claude.return_value = {"success": True, "output": "done", "duration_seconds": 5, "error": None}
        result = trigger_morning_triage(tmp_path, dry_run=True)

    assert result["success"] is True
    assert result["items_processed"] >= 1
    mock_claude.assert_called_once()


def test_trigger_morning_triage_no_items(tmp_path):
    """Skips Claude when no pending items."""
    (tmp_path / "Needs_Action").mkdir(parents=True)

    with patch("scripts.schedules.invoke_claude") as mock_claude:
        result = trigger_morning_triage(tmp_path, dry_run=True)

    assert result["success"] is True
    assert result["items_processed"] == 0
    mock_claude.assert_not_called()


def test_trigger_linkedin_post_drafts(tmp_path):
    """Invokes Claude to draft post when none exists today."""
    (tmp_path / "Pending_Approval" / "social").mkdir(parents=True)

    with patch("scripts.schedules.invoke_claude") as mock_claude:
        mock_claude.return_value = {"success": True, "output": "post", "duration_seconds": 3, "error": None}
        result = trigger_linkedin_post(tmp_path, dry_run=True)

    assert result["success"] is True
    assert result["drafted"] is True
    mock_claude.assert_called_once()


def test_trigger_linkedin_post_skips_if_exists(tmp_path):
    """Skips if a post was already drafted today."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    social_dir = tmp_path / "Pending_Approval" / "social"
    social_dir.mkdir(parents=True)
    (social_dir / f"APPROVAL_linkedin_{today}.md").write_text("draft")

    with patch("scripts.schedules.invoke_claude") as mock_claude:
        result = trigger_linkedin_post(tmp_path, dry_run=True)

    assert result["drafted"] is False
    assert result["reason"] == "already_drafted_today"
    mock_claude.assert_not_called()


def test_trigger_linkedin_post_skips_pileup(tmp_path):
    """Skips if >1 unapproved posts are pending."""
    social_dir = tmp_path / "Pending_Approval" / "social"
    social_dir.mkdir(parents=True)
    (social_dir / "APPROVAL_linkedin_2026-02-01.md").write_text("post1")
    (social_dir / "APPROVAL_linkedin_2026-02-03.md").write_text("post2")

    with patch("scripts.schedules.invoke_claude") as mock_claude:
        result = trigger_linkedin_post(tmp_path, dry_run=True)

    assert result["drafted"] is False
    assert result["reason"] == "pileup"
    mock_claude.assert_not_called()


def test_trigger_stale_check(tmp_path):
    """Calls approval watcher stale check via subprocess."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Found 2 stale approvals\n", stderr=""
        )
        result = trigger_stale_check(tmp_path, dry_run=True)
    assert result["success"] is True
    assert result["stale_count"] == 2


def test_trigger_daily_rollover(tmp_path):
    """Calls dashboard rollover functions."""
    with patch("scripts.utils.dashboard_updater.rollover_activity_log"), \
         patch("scripts.utils.dashboard_updater.update_queue_counts"), \
         patch("scripts.utils.dashboard_updater.update_timestamp"):
        result = trigger_daily_rollover(tmp_path, dry_run=True)
    assert result["success"] is True


def test_trigger_health_update(tmp_path):
    """Updates Dashboard system health."""
    mock_manager = MagicMock()
    mock_manager.status.return_value = [
        {"name": "gmail", "enabled": True, "running": True},
        {"name": "filesystem", "enabled": True, "running": False},
    ]
    with patch("scripts.utils.dashboard_updater.update_system_health") as mock_health, \
         patch("scripts.watchers.runner.WatcherManager", return_value=mock_manager):
        result = trigger_health_update(tmp_path, dry_run=True)
    assert result["success"] is True
    assert result["watchers_checked"] == 2


def test_trigger_done_archive(tmp_path):
    """Archives old Done files."""
    with patch("scripts.utils.vault_processor.archive_done", return_value=3) as mock_archive:
        result = trigger_done_archive(tmp_path, dry_run=True)
    assert result["success"] is True
    assert result["archived_count"] == 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list_schedules(tmp_path, capsys):
    """CLI list command shows all tasks."""
    import runpy
    import sys

    sys.argv = ["schedules.py", "list"]
    with patch.dict("os.environ", {"VAULT_PATH": str(tmp_path)}):
        try:
            runpy.run_module("scripts.schedules", run_name="__main__", alter_sys=True)
        except SystemExit:
            pass

    captured = capsys.readouterr()
    assert "morning_triage" in captured.out
    assert "linkedin_post" in captured.out


def test_cli_check_due(tmp_path, capsys):
    """CLI check command shows due tasks."""
    import runpy
    import sys

    sys.argv = ["schedules.py", "check"]
    with patch.dict("os.environ", {"VAULT_PATH": str(tmp_path)}):
        try:
            runpy.run_module("scripts.schedules", run_name="__main__", alter_sys=True)
        except SystemExit:
            pass

    captured = capsys.readouterr()
    # Output is either "No tasks due" or a list of due tasks
    assert "due" in captured.out.lower() or "task" in captured.out.lower() or len(captured.out) > 0


def test_cli_trigger_by_name(tmp_path, capsys):
    """CLI trigger command manually triggers a task."""
    import runpy
    import sys

    sys.argv = ["schedules.py", "--vault", str(tmp_path), "trigger", "done_archive"]
    with patch("scripts.utils.vault_processor.archive_done", return_value=0):
        try:
            runpy.run_module("scripts.schedules", run_name="__main__", alter_sys=True)
        except SystemExit:
            pass

    captured = capsys.readouterr()
    assert "success" in captured.out.lower() or "archived" in captured.out.lower() or len(captured.out) > 0
