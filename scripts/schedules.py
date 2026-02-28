"""AI Employee Schedule Manager — definitions, trigger functions, and CLI."""

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.utils.logging_config import setup_logger  # noqa: E402

logger = setup_logger("schedules")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class Frequency(Enum):
    DAILY = "daily"
    WEEKDAYS = "weekdays"       # Mon-Fri
    MWF = "mwf"                 # Mon/Wed/Fri
    WEEKLY = "weekly"           # Specific day
    HOURLY = "hourly"
    EVERY_N_MINUTES = "every_n_minutes"


@dataclass
class ScheduledTask:
    name: str                               # Unique identifier
    description: str                        # Human-readable
    frequency: Frequency
    time_of_day: time | None = None         # For daily/weekly schedules
    interval_minutes: int | None = None     # For EVERY_N_MINUTES
    day_of_week: int | None = None          # 0=Mon for WEEKLY (0-6)
    trigger_fn: str = ""                    # Function name in schedules.py to call
    enabled: bool = True
    last_run: datetime | None = None
    requires_claude: bool = True            # Does this task invoke Claude Code?
    timeout_minutes: int = 10              # Max execution time


# ---------------------------------------------------------------------------
# Schedule Registry
# ---------------------------------------------------------------------------


SCHEDULE_REGISTRY: list[ScheduledTask] = [
    ScheduledTask(
        name="morning_triage",
        description="Process all pending emails and tasks at start of day",
        frequency=Frequency.DAILY,
        time_of_day=time(8, 0),
        trigger_fn="trigger_morning_triage",
        requires_claude=True,
        timeout_minutes=15,
    ),
    ScheduledTask(
        name="linkedin_post",
        description="Draft LinkedIn post aligned with business goals",
        frequency=Frequency.MWF,
        time_of_day=time(9, 30),
        trigger_fn="trigger_linkedin_post",
        requires_claude=True,
        timeout_minutes=10,
    ),
    ScheduledTask(
        name="stale_approval_check",
        description="Flag stale approval requests (>24hr pending)",
        frequency=Frequency.EVERY_N_MINUTES,
        interval_minutes=360,           # Every 6 hours
        trigger_fn="trigger_stale_check",
        requires_claude=False,
        timeout_minutes=2,
    ),
    ScheduledTask(
        name="daily_rollover",
        description="Archive old activity log entries, reset daily counters",
        frequency=Frequency.DAILY,
        time_of_day=time(0, 5),         # Just after midnight
        trigger_fn="trigger_daily_rollover",
        requires_claude=False,
        timeout_minutes=5,
    ),
    ScheduledTask(
        name="weekly_audit_prep",
        description="Prepare data for CEO briefing (Gold tier)",
        frequency=Frequency.WEEKLY,
        day_of_week=6,                  # Sunday
        time_of_day=time(22, 0),
        trigger_fn="trigger_weekly_audit_prep",
        requires_claude=True,
        timeout_minutes=20,
        enabled=False,                  # Enabled in Gold tier
    ),
    ScheduledTask(
        name="health_dashboard_update",
        description="Update Dashboard.md system health section",
        frequency=Frequency.EVERY_N_MINUTES,
        interval_minutes=15,
        trigger_fn="trigger_health_update",
        requires_claude=False,
        timeout_minutes=1,
    ),
    ScheduledTask(
        name="done_archive",
        description="Archive old files from /Done/ (>7 days)",
        frequency=Frequency.DAILY,
        time_of_day=time(1, 0),
        trigger_fn="trigger_done_archive",
        requires_claude=False,
        timeout_minutes=2,
    ),
]


# ---------------------------------------------------------------------------
# Schedule checker
# ---------------------------------------------------------------------------


def is_due(task: ScheduledTask, now: datetime | None = None) -> bool:
    """
    Check if a scheduled task is due to run.

    Rules:
    - DAILY: due if time_of_day has passed today AND last_run was before today
    - WEEKDAYS: same as DAILY but only Mon-Fri
    - MWF: same as DAILY but only Mon/Wed/Fri
    - WEEKLY: due if today is day_of_week AND time has passed AND not run this week
    - HOURLY: due if >60 min since last_run
    - EVERY_N_MINUTES: due if >interval_minutes since last_run

    Edge cases:
    - If last_run is None → task has never run → it's due (unless time hasn't come yet)
    - If orchestrator was down and missed a schedule → run once on next check
    - Respect the 'enabled' flag
    """
    if not task.enabled:
        return False

    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure now is timezone-aware
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    freq = task.frequency

    if freq == Frequency.EVERY_N_MINUTES:
        if task.interval_minutes is None:
            return False
        if task.last_run is None:
            return True
        last = task.last_run
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds() / 60.0
        return elapsed >= task.interval_minutes

    if freq == Frequency.HOURLY:
        if task.last_run is None:
            return True
        last = task.last_run
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds() / 60.0
        return elapsed >= 60

    # Time-based frequencies: DAILY, WEEKDAYS, MWF, WEEKLY
    if task.time_of_day is None:
        return False

    today = now.date()
    weekday = today.weekday()  # 0=Mon, 6=Sun

    # Check day-of-week constraints
    if freq == Frequency.WEEKDAYS and weekday >= 5:
        return False
    if freq == Frequency.MWF and weekday not in (0, 2, 4):
        return False
    if freq == Frequency.WEEKLY:
        if task.day_of_week is None:
            return False
        if weekday != task.day_of_week:
            return False

    # Check if the scheduled time has passed today
    scheduled_dt = datetime(
        today.year, today.month, today.day,
        task.time_of_day.hour, task.time_of_day.minute,
        tzinfo=timezone.utc,
    )
    if now < scheduled_dt:
        return False

    # Check if already run today (or this week for WEEKLY)
    if task.last_run is None:
        return True

    last = task.last_run
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    if freq == Frequency.WEEKLY:
        # Not due if run any time this week (Mon-Sun)
        # Find Monday of current week
        week_start = today - __import__("datetime").timedelta(days=weekday)
        last_run_date = last.date()
        return last_run_date < week_start

    # DAILY, WEEKDAYS, MWF: not due if already run today
    return last.date() < today


def get_due_tasks(
    registry: list[ScheduledTask],
    now: datetime | None = None,
) -> list[ScheduledTask]:
    """Return all tasks that are currently due, sorted by priority (non-Claude first)."""
    if now is None:
        now = datetime.now(timezone.utc)
    due = [t for t in registry if is_due(t, now)]
    # Non-Claude tasks first (lighter-weight), then Claude tasks
    due.sort(key=lambda t: (1 if t.requires_claude else 0, t.name))
    return due


# ---------------------------------------------------------------------------
# Claude Code invocation helper
# ---------------------------------------------------------------------------


def invoke_claude(
    prompt: str,
    vault_path: Path,
    timeout_minutes: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Invoke Claude Code CLI as a subprocess.

    Returns:
        {
            "success": True/False,
            "output": "Claude's response text",
            "duration_seconds": 45,
            "error": None or "error message",
        }
    """
    import time as _time

    cmd = ["claude", "--print", prompt]
    env = os.environ.copy()
    if dry_run:
        env["DRY_RUN"] = "true"
    env["VAULT_PATH"] = str(vault_path)

    start = _time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(vault_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_minutes * 60,
            encoding="utf-8",
            errors="replace",
        )
        duration = _time.monotonic() - start
        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "duration_seconds": round(duration),
                "error": None,
            }
        else:
            return {
                "success": False,
                "output": result.stdout,
                "duration_seconds": round(duration),
                "error": result.stderr or f"Exit code {result.returncode}",
            }
    except subprocess.TimeoutExpired:
        duration = _time.monotonic() - start
        # subprocess.run kills the child process automatically on timeout
        logger.error("Claude invocation timed out after %d minutes", timeout_minutes)
        return {
            "success": False,
            "output": "",
            "duration_seconds": round(duration),
            "error": f"Timed out after {timeout_minutes} minutes",
        }
    except (OSError, FileNotFoundError) as exc:
        duration = _time.monotonic() - start
        logger.error("Failed to invoke Claude: %s", exc)
        return {
            "success": False,
            "output": "",
            "duration_seconds": round(duration),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Trigger functions
# ---------------------------------------------------------------------------


def trigger_morning_triage(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Morning triage: process all pending items across all domains.

    1. Count items in Needs_Action/
    2. If items exist → invoke Claude Code to process them
    3. If no items → log and skip
    """
    from scripts.utils.vault_processor import list_pending

    items = list_pending(vault_path)
    item_count = len(items)

    if item_count == 0:
        logger.info("Morning triage: no pending items, skipping")
        return {"success": True, "items_processed": 0, "duration": "0s"}

    logger.info("Morning triage: processing %d pending item(s)", item_count)

    prompt = (
        "You are the AI Employee performing morning triage. "
        "Load skills: @.claude/skills/email-triage/SKILL.md "
        "@.claude/skills/task-planner/SKILL.md "
        "@.claude/skills/hitl-handler/SKILL.md "
        "Process all items in /Needs_Action/. "
        "For each item: triage, plan, create approval requests as needed. "
        "Update Dashboard when done."
    )

    result = invoke_claude(prompt, vault_path, timeout_minutes=15, dry_run=dry_run)
    duration_str = f"{result['duration_seconds']}s"
    return {
        "success": result["success"],
        "items_processed": item_count,
        "duration": duration_str,
        "error": result.get("error"),
    }


def trigger_linkedin_post(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    LinkedIn post: draft a post aligned with business goals.

    1. Check if already drafted today
    2. Check for pile-up (>1 unapproved posts pending)
    3. Invoke Claude Code if needed
    """
    import datetime as _dt

    social_dir = vault_path / "Pending_Approval" / "social"
    today_str = _dt.date.today().isoformat()

    # Check for today's draft
    if social_dir.is_dir():
        today_files = [
            f for f in social_dir.iterdir()
            if f.suffix == ".md" and today_str in f.name
        ]
        if today_files:
            logger.info("LinkedIn post already drafted today, skipping")
            return {"success": True, "drafted": False, "reason": "already_drafted_today"}

        # Check pile-up: >1 unapproved pending posts
        all_pending = [f for f in social_dir.iterdir() if f.suffix == ".md"]
        if len(all_pending) > 1:
            logger.info("LinkedIn post pile-up (%d pending), skipping", len(all_pending))
            return {"success": True, "drafted": False, "reason": "pileup"}

    logger.info("Drafting LinkedIn post...")
    prompt = (
        "You are the AI Employee drafting a LinkedIn post. "
        "Load skills: @.claude/skills/social-post/SKILL.md "
        "@.claude/skills/hitl-handler/SKILL.md "
        "Read: @Business_Goals.md "
        "Draft one LinkedIn post for today and create an approval request."
    )

    result = invoke_claude(prompt, vault_path, timeout_minutes=10, dry_run=dry_run)
    return {
        "success": result["success"],
        "drafted": result["success"],
        "error": result.get("error"),
    }


def trigger_stale_check(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Check for stale approvals by running the approval watcher's stale check.
    """
    cmd = [
        "uv", "run", "python",
        "scripts/watchers/approval_watcher.py",
        "--vault", str(vault_path),
        "--check-stale",
    ]
    env = os.environ.copy()
    env["VAULT_PATH"] = str(vault_path)
    if dry_run:
        env["DRY_RUN"] = "true"

    try:
        result = subprocess.run(
            cmd,
            cwd=str(vault_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        # Parse stale count from output like "Found N stale approvals"
        stale_count = 0
        for line in result.stdout.splitlines():
            if "stale" in line.lower():
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.isdigit():
                        stale_count = int(p)
                        break
        logger.info("Stale check: %d stale approval(s)", stale_count)
        return {"success": result.returncode == 0, "stale_count": stale_count}
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Stale check failed: %s", exc)
        return {"success": False, "stale_count": 0, "error": str(exc)}


def trigger_daily_rollover(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Daily cleanup:
    1. Rollover Dashboard activity log (archive if >50 entries)
    2. Reset daily counters in Dashboard
    3. Update 'Last Updated' timestamp
    """
    try:
        from scripts.utils.dashboard_updater import (
            rollover_activity_log,
            update_queue_counts,
            update_timestamp,
        )
        rollover_activity_log(vault_path)
        update_queue_counts(vault_path)
        update_timestamp(vault_path)
        logger.info("Daily rollover complete")
        return {"success": True}
    except Exception as exc:
        logger.error("Daily rollover failed: %s", exc)
        return {"success": False, "error": str(exc)}


def trigger_weekly_audit_prep(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Weekly audit preparation (Gold tier — disabled by default).
    """
    logger.info("Weekly audit prep: Gold tier feature — enable when ready")
    return {"success": True, "skipped": True, "reason": "Gold tier feature not enabled"}


def trigger_health_update(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Update Dashboard system health section.
    1. Get watcher status from runner
    2. Check MCP server availability
    3. Update each component's row in Dashboard System Health table
    """
    try:
        from scripts.utils.dashboard_updater import update_system_health
        from scripts.watchers.runner import WatcherManager

        manager = WatcherManager(vault_path)
        statuses = manager.status()

        for s in statuses:
            status_emoji = "🟢 Running" if s["running"] else "🔴 Down"
            try:
                update_system_health(
                    vault_path,
                    component=f"{s['name']}_watcher",
                    status=status_emoji,
                )
            except Exception as exc:
                logger.warning("Could not update health for %s: %s", s["name"], exc)

        # Check MCP servers
        for mcp_name in ["email-mcp", "linkedin-mcp"]:
            mcp_path = vault_path / f"mcp-servers/{mcp_name}/src/index.ts"
            status = "🟢 Available" if mcp_path.exists() else "🔴 Missing"
            try:
                update_system_health(vault_path, component=mcp_name, status=status)
            except Exception as exc:
                logger.warning("Could not update MCP health for %s: %s", mcp_name, exc)

        logger.info("Health dashboard update complete")
        return {"success": True, "watchers_checked": len(statuses)}
    except Exception as exc:
        logger.error("Health update failed: %s", exc)
        return {"success": False, "error": str(exc)}


def trigger_done_archive(vault_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Archive old /Done/ files using vault_processor.archive_done(days=7).
    """
    try:
        from scripts.utils.vault_processor import archive_done
        count = archive_done(vault_path, older_than_days=7)
        logger.info("Done archive: archived %d file(s)", count)
        return {"success": True, "archived_count": count}
    except Exception as exc:
        logger.error("Done archive failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def load_schedules() -> list[ScheduledTask]:
    """Return a fresh copy of the schedule registry."""
    return list(SCHEDULE_REGISTRY)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()

    parser = argparse.ArgumentParser(description="AI Employee Schedule Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list — show all schedules
    subparsers.add_parser("list", help="List all scheduled tasks")

    # check — show which tasks are due now
    subparsers.add_parser("check", help="Show tasks due right now")

    # trigger — manually trigger a specific task
    trigger_p = subparsers.add_parser("trigger", help="Manually trigger a task")
    trigger_p.add_argument("task_name", help="Task name from registry")
    trigger_p.add_argument("--dry-run", action="store_true")

    # enable/disable
    enable_p = subparsers.add_parser("enable", help="Enable a task")
    enable_p.add_argument("task_name")
    disable_p = subparsers.add_parser("disable", help="Disable a task")
    disable_p.add_argument("task_name")

    parser.add_argument("--vault", default=None)

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    registry = load_schedules()

    if args.command == "list":
        for task in registry:
            status = "enabled" if task.enabled else "disabled"
            freq_str = task.frequency.value
            if task.time_of_day:
                freq_str += f" @ {task.time_of_day.strftime('%H:%M')}"
            if task.interval_minutes:
                freq_str += f" (every {task.interval_minutes}m)"
            print(f"  [{status}] {task.name}: {task.description} — {freq_str}")

    elif args.command == "check":
        now = datetime.now(timezone.utc)
        due = get_due_tasks(registry, now)
        if due:
            print(f"Due tasks ({now.strftime('%Y-%m-%d %H:%M:%S UTC')}):")
            for task in due:
                print(f"  * {task.name}: {task.description}")
        else:
            print("No tasks due right now.")

    elif args.command == "trigger":
        task_name = args.task_name
        # Find trigger function
        task = next((t for t in registry if t.name == task_name), None)
        if task is None:
            print(f"Error: No task named '{task_name}'", file=sys.stderr)
            sys.exit(1)
        fn = globals().get(task.trigger_fn)
        if fn is None:
            print(f"Error: No trigger function '{task.trigger_fn}'", file=sys.stderr)
            sys.exit(1)
        dry_run = getattr(args, "dry_run", False)
        print(f"Triggering '{task_name}'...")
        result = fn(vault_path, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "enable":
        task = next((t for t in registry if t.name == args.task_name), None)
        if task is None:
            print(f"Error: No task named '{args.task_name}'", file=sys.stderr)
            sys.exit(1)
        task.enabled = True
        print(f"Task '{args.task_name}' enabled (in-memory only; edit registry to persist).")

    elif args.command == "disable":
        task = next((t for t in registry if t.name == args.task_name), None)
        if task is None:
            print(f"Error: No task named '{args.task_name}'", file=sys.stderr)
            sys.exit(1)
        task.enabled = False
        print(f"Task '{args.task_name}' disabled (in-memory only; edit registry to persist).")
