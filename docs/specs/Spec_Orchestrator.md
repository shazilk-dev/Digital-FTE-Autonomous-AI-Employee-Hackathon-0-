# Spec: Orchestrator — Master Process with Scheduling & Health Monitoring

> **Components:**
> - `scripts/schedules.py` — Schedule definitions, trigger functions, Claude Code invocations
> - `scripts/orchestrator.py` — Master process coordinating watchers, schedules, health
> **Priority:** P0 — The backbone that makes the AI Employee "always-on"
> **Tests:** `tests/test_schedules.py`, `tests/test_orchestrator.py`
> **Depends On:** Watcher Runner (S1), all watchers, vault_processor, dashboard_updater

## 1. Objective

Create a single master process that:
1. **Starts and manages** all watchers via the Watcher Runner
2. **Runs scheduled tasks** at configured times (daily triage, LinkedIn posts, audits)
3. **Monitors health** of all sub-processes and MCP servers
4. **Updates Dashboard** with system status
5. **Handles graceful shutdown** and restart

After S6, the user's workflow is:
```
# Start everything:
pm2 start ecosystem.config.js

# Or for development:
uv run python scripts/orchestrator.py

# Walk away. Everything runs. Check Dashboard.md when you want updates.
```

## 2. Schedule Definitions: `scripts/schedules.py`

### 2A. Schedule Data Model

```python
from dataclasses import dataclass, field
from datetime import time, datetime
from enum import Enum
from typing import Callable, Any

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
    timeout_minutes: int = 10               # Max execution time
```

### 2B. Schedule Registry

```python
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
```

### 2C. Schedule Checker

```python
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
      (don't run multiple times to "catch up")
    - Respect the 'enabled' flag
    """

def get_due_tasks(
    registry: list[ScheduledTask],
    now: datetime | None = None
) -> list[ScheduledTask]:
    """Return all tasks that are currently due, sorted by priority."""
```

### 2D. Trigger Functions

```python
def trigger_morning_triage(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Morning triage: process all pending items across all domains.

    1. Count items in Needs_Action/ (all subdomains)
    2. If items exist → invoke Claude Code to process them:
       
       cmd = [
           "claude", "--print",
           "You are the AI Employee performing morning triage. "
           "Load skills: @.claude/skills/email-triage/SKILL.md "
           "@.claude/skills/task-planner/SKILL.md "
           "@.claude/skills/hitl-handler/SKILL.md "
           "Process all items in /Needs_Action/. "
           "For each item: triage, plan, create approval requests as needed. "
           "Update Dashboard when done."
       ]

    3. If no items → log "No pending items" and skip
    4. Return: {"success": True, "items_processed": N, "duration": "..."}

    If DRY_RUN: run Claude with DRY_RUN env (or just count and log)
    """

def trigger_linkedin_post(vault_path: Path, dry_run: bool = False) -> dict:
    """
    LinkedIn post: draft a post aligned with business goals.

    1. Check if a linkedin post was already drafted today
       (look in /Pending_Approval/social/ for today's files)
    2. If already drafted → skip
    3. Check for pile-up: if >1 unapproved linkedin posts pending → skip
    4. Invoke Claude Code:

       cmd = [
           "claude", "--print",
           "You are the AI Employee drafting a LinkedIn post. "
           "Load skills: @.claude/skills/social-post/SKILL.md "
           "@.claude/skills/hitl-handler/SKILL.md "
           "Read: @Business_Goals.md "
           "Draft one LinkedIn post for today and create an approval request."
       ]

    5. Return: {"success": True, "drafted": True/False}
    """

def trigger_stale_check(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Check for stale approvals by running the approval watcher's stale check.

    cmd = [
        "uv", "run", "python",
        "scripts/watchers/approval_watcher.py",
        "--vault", str(vault_path),
        "--check-stale"
    ]

    Return: {"success": True, "stale_count": N}
    """

def trigger_daily_rollover(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Daily cleanup:
    1. Rollover Dashboard activity log (archive if >50 entries)
    2. Reset daily counters in Dashboard
    3. Update "Last Updated" timestamp

    Uses dashboard_updater CLI directly — no Claude needed.
    """

def trigger_weekly_audit_prep(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Weekly audit preparation (Gold tier — disabled by default).
    Placeholder that logs "Gold tier feature — enable when ready."
    """

def trigger_health_update(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Update Dashboard system health section.
    1. Get watcher status from runner
    2. Check MCP server responsiveness (can they start?)
    3. Update each component's row in Dashboard System Health table
    """

def trigger_done_archive(vault_path: Path, dry_run: bool = False) -> dict:
    """
    Archive old /Done/ files using vault_processor.archive_done(days=7).
    """
```

### 2E. Claude Code Invocation Helper

```python
def invoke_claude(
    prompt: str,
    vault_path: Path,
    timeout_minutes: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    Invoke Claude Code CLI as a subprocess.

    Args:
        prompt: The prompt to send to Claude
        vault_path: Working directory (the vault)
        timeout_minutes: Max execution time
        dry_run: If True, add DRY_RUN=true to environment

    Returns:
        {
            "success": True/False,
            "output": "Claude's response text",
            "duration_seconds": 45,
            "error": None or "error message",
        }

    Implementation:
    1. Build command: ["claude", "--print", prompt]
    2. Set cwd to vault_path
    3. Set env: inherit current env + DRY_RUN flag
    4. Run with subprocess.run(timeout=timeout_minutes*60)
    5. Capture stdout and stderr
    6. On timeout: kill process, return failure
    7. On error: capture stderr, return failure
    8. On success: return stdout

    IMPORTANT: Use --print flag for non-interactive single-shot execution.
    Claude processes the prompt and exits. No interactive session.
    """
```

### 2F. CLI Interface

```python
if __name__ == "__main__":
    import argparse

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

    args = parser.parse_args()
    vault_path = Path(os.getenv("VAULT_PATH", "."))
    # Dispatch
```

## 3. Orchestrator: `scripts/orchestrator.py`

### 3A. Core Loop

```python
class Orchestrator:
    """
    Master process for the AI Employee.

    Coordinates:
    - Watcher lifecycle (start/monitor/restart via WatcherManager)
    - Scheduled task execution (via schedules.py)
    - Health monitoring and Dashboard updates
    """

    def __init__(
        self,
        vault_path: Path,
        dry_run: bool | None = None,
        check_interval: int = 30,
    ):
        self.vault_path = vault_path
        self.dry_run = dry_run if dry_run is not None else self._is_dry_run()
        self.check_interval = check_interval  # Main loop interval in seconds
        self.watcher_manager = WatcherManager(vault_path)
        self.schedule_registry = load_schedules()  # From schedules.py
        self._running = False
        self._setup_signal_handlers()

    def start(self) -> None:
        """
        Main entry point. Starts the orchestrator loop.

        Flow:
        1. Log startup
        2. Start all watchers via watcher_manager.start_all()
        3. Update Dashboard system health
        4. Enter main loop:
           a. Check for due scheduled tasks → execute them
           b. Check watcher health → restart any crashed watchers
           c. Sleep for check_interval seconds
           d. Repeat until shutdown signal
        """
        self._running = True
        self.logger.info("Orchestrator starting...")

        # Start watchers
        results = self.watcher_manager.start_all(dry_run=self.dry_run)
        self.logger.info(f"Watchers started: {results}")

        # Initial health update
        self._update_health()

        # Main loop
        while self._running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error(f"Orchestrator tick error: {e}")
            time.sleep(self.check_interval)

        # Shutdown
        self._shutdown()

    def _tick(self) -> None:
        """
        Single orchestrator cycle.

        1. Get due tasks from schedule
        2. Execute each due task (sequentially, not parallel)
        3. Update last_run timestamps
        4. Check watcher health (every Nth tick)
        """
        now = datetime.now()

        # Check scheduled tasks
        due_tasks = get_due_tasks(self.schedule_registry, now)
        for task in due_tasks:
            self.logger.info(f"Executing scheduled task: {task.name}")
            try:
                trigger_fn = getattr(schedules_module, task.trigger_fn)
                result = trigger_fn(self.vault_path, dry_run=self.dry_run)
                task.last_run = now
                self._log_task_execution(task, result)
            except Exception as e:
                self.logger.error(f"Task {task.name} failed: {e}")
                self._log_task_execution(task, {"success": False, "error": str(e)})

        # Health check (every 2nd tick = every 60s at default interval)
        if self._tick_count % 2 == 0:
            self._check_watcher_health()

    def _check_watcher_health(self) -> None:
        """
        Check if all watchers are still running.
        Restart any that have crashed.
        Update Dashboard system health on changes.
        """
        statuses = self.watcher_manager.status()
        for s in statuses:
            if s["enabled"] and not s["running"]:
                self.logger.warning(f"Watcher {s['name']} is down, restarting...")
                self.watcher_manager.start(s["name"], dry_run=self.dry_run)
                # Update Dashboard
                dashboard_updater.add_error(
                    self.vault_path,
                    f"watcher_{s['name']}",
                    f"Crashed and auto-restarted",
                    "Auto-restarted"
                )

    def _update_health(self) -> None:
        """
        Update Dashboard system health section with current status
        of all watchers and MCP servers.
        """
        statuses = self.watcher_manager.status()
        for s in statuses:
            status_emoji = "🟢 Running" if s["running"] else "🔴 Down"
            dashboard_updater.update_system_health(
                self.vault_path,
                component=f"{s['name']}_watcher",
                status=status_emoji,
            )

        # Check MCP servers
        for mcp_name in ["email-mcp", "linkedin-mcp"]:
            # Simple check: can the entry point file be found?
            mcp_path = self.vault_path / f"mcp-servers/{mcp_name}/src/index.ts"
            status = "🟢 Available" if mcp_path.exists() else "🔴 Missing"
            dashboard_updater.update_system_health(
                self.vault_path,
                component=mcp_name,
                status=status,
            )

    def run_once(self) -> dict:
        """
        Single-cycle mode for testing.
        Start watchers, run one tick, update health, report, stop.
        """

    def _shutdown(self) -> None:
        """Graceful shutdown: stop all watchers, save state, log."""
        self.logger.info("Orchestrator shutting down...")
        self.watcher_manager.stop_all()
        self._update_health()
        self.logger.info("Orchestrator stopped.")

    def _setup_signal_handlers(self) -> None:
        """Handle SIGTERM and SIGINT."""
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame) -> None:
        self.logger.info(f"Received signal {signum}, shutting down...")
        self._running = False
```

### 3B. State Persistence

```python
def _save_state(self) -> None:
    """
    Save orchestrator state to .state/orchestrator_state.json.

    State includes:
    - last_run timestamps for each scheduled task
    - tick count
    - start time
    - watcher restart counts

    Loaded on startup to resume schedule tracking.
    """

def _load_state(self) -> None:
    """Load saved state and apply to schedule registry."""
```

### 3C. `__main__` Block

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Employee Orchestrator — Master Process",
        epilog="""
Examples:
  # Start the orchestrator (runs forever)
  uv run python scripts/orchestrator.py

  # Single cycle for testing
  uv run python scripts/orchestrator.py --once

  # Dry-run mode (no external actions)
  DRY_RUN=true uv run python scripts/orchestrator.py

  # Custom check interval
  uv run python scripts/orchestrator.py --interval 60
        """
    )
    parser.add_argument("--vault", default=None)
    parser.add_argument("--interval", type=int, default=30,
                        help="Main loop interval in seconds")
    parser.add_argument("--once", action="store_true",
                        help="Run single cycle and exit")
    parser.add_argument("--no-watchers", action="store_true",
                        help="Don't start watchers (schedule-only mode)")

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    orch = Orchestrator(vault_path, check_interval=args.interval)

    if args.once:
        result = orch.run_once()
        print(json.dumps(result, indent=2, default=str))
    else:
        orch.start()
```

## 4. Updated PM2 Config: `ecosystem.config.js`

The orchestrator REPLACES individual watcher PM2 entries. The orchestrator manages
watchers itself. PM2 only needs to keep the orchestrator alive.

```javascript
// ecosystem.config.js — AI Employee Process Management
// Usage: pm2 start ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "aiemp-orchestrator",
      script: "uv",
      args: "run python scripts/orchestrator.py --vault .",
      cwd: "/path/to/AI_Employee_Vault",  // Replaced by generate_pm2
      env: {
        VAULT_PATH: ".",
        DRY_RUN: "false",
        PYTHONPATH: ".",
      },
      // PM2 config
      autorestart: true,
      max_restarts: 20,
      restart_delay: 10000,           // 10s between restarts
      max_memory_restart: "500M",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "./Logs/pm2/orchestrator-error.log",
      out_file: "./Logs/pm2/orchestrator-out.log",
      merge_logs: true,
      watch: false,
      kill_timeout: 10000,            // 10s for graceful shutdown
    },
  ],
};

// Quick reference:
// pm2 start ecosystem.config.js     # Start orchestrator
// pm2 logs aiemp-orchestrator        # View logs
// pm2 restart aiemp-orchestrator     # Restart
// pm2 stop aiemp-orchestrator        # Stop (also stops watchers)
// pm2 monit                          # Real-time dashboard
// pm2 save && pm2 startup            # Persist across reboots
```

**Key change:** The orchestrator is the ONLY PM2 process. It manages watchers as
child processes internally. This is simpler than having PM2 manage 5+ processes.

## 5. Test Requirements

### 5A. `tests/test_schedules.py`

**Schedule checking:**
- `test_daily_task_due_after_time` — due when time has passed, not run today
- `test_daily_task_not_due_before_time` — not due when time hasn't passed
- `test_daily_task_not_due_already_run` — not due if already run today
- `test_mwf_task_due_on_monday` — due on Monday
- `test_mwf_task_not_due_on_tuesday` — not due on Tuesday
- `test_mwf_task_due_on_wednesday` — due on Wednesday
- `test_mwf_task_due_on_friday` — due on Friday
- `test_weekly_task_due_on_correct_day` — due on specified day_of_week
- `test_weekly_task_not_due_wrong_day` — not due on other days
- `test_every_n_minutes_due` — due when interval exceeded
- `test_every_n_minutes_not_due` — not due within interval
- `test_disabled_task_never_due` — enabled=False → never due
- `test_never_run_task_is_due` — last_run=None + time passed → due
- `test_missed_schedule_runs_once` — doesn't run multiple times to catch up
- `test_get_due_tasks_returns_sorted` — ordered by priority

**Trigger functions (mocked):**
- `test_trigger_morning_triage_with_items` — invokes Claude when items pending
- `test_trigger_morning_triage_no_items` — skips when empty
- `test_trigger_linkedin_post_drafts` — invokes Claude for post
- `test_trigger_linkedin_post_skips_if_exists` — skips if already drafted today
- `test_trigger_linkedin_post_skips_pileup` — skips if >1 unapproved posts
- `test_trigger_stale_check` — calls approval watcher stale check
- `test_trigger_daily_rollover` — calls dashboard rollover
- `test_trigger_health_update` — updates Dashboard system health
- `test_trigger_done_archive` — archives old Done files

**CLI:**
- `test_cli_list_schedules` — shows all tasks
- `test_cli_check_due` — shows due tasks
- `test_cli_trigger_by_name` — manually triggers a task

### 5B. `tests/test_orchestrator.py`

**Lifecycle:**
- `test_init_creates_watcher_manager` — WatcherManager initialized
- `test_start_launches_watchers` — start_all called
- `test_run_once_executes_single_tick` — one cycle, then exit
- `test_shutdown_stops_watchers` — stop_all called on shutdown
- `test_signal_handler_triggers_shutdown` — SIGTERM sets _running=False

**Main loop (mocked clock):**
- `test_tick_executes_due_tasks` — due tasks get executed
- `test_tick_skips_not_due_tasks` — non-due tasks skipped
- `test_tick_updates_last_run` — timestamp updated after execution
- `test_tick_logs_task_failure` — failed task logged, doesn't crash loop
- `test_tick_checks_watcher_health` — health check on Nth tick

**Health monitoring:**
- `test_health_check_detects_crashed_watcher` — identifies down process
- `test_health_check_restarts_crashed` — auto-restart triggered
- `test_health_check_updates_dashboard` — system health table updated
- `test_health_check_mcp_availability` — MCP file existence check

**State persistence:**
- `test_save_state_persists_last_run` — state file written
- `test_load_state_restores_last_run` — state restored on startup
- `test_missing_state_file_handled` — fresh start works

## 6. Edge Cases

- **Orchestrator starts while watchers already running:** Runner detects PIDs, reports already running, doesn't double-start
- **Claude Code not installed:** `invoke_claude` fails → log error, skip task, don't crash
- **Claude Code hangs (timeout):** subprocess killed after timeout_minutes, task marked failed
- **All watchers crash simultaneously:** Health check restarts all. If repeated crashes (>5 restarts in 10 min), pause watchers and alert.
- **Scheduled task takes longer than check_interval:** Tasks run sequentially. Next tick waits. No parallel task execution (simplicity).
- **Clock change (DST):** Use UTC internally. `is_due` compares UTC times.
- **Orchestrator restarts after being down 2 days:** Load state, see missed tasks have last_run from 2 days ago. Each missed task runs ONCE (no catch-up flood).
- **Disk full:** Write operations fail → catch, log to stderr (can't write to Logs), alert.
- **Permission denied on PID files:** Catch, continue with reduced health monitoring.

## 7. Validation Criteria

- [ ] `scripts/schedules.py` — all schedule definitions + trigger functions + CLI
- [ ] `scripts/orchestrator.py` — main loop + health monitoring + signal handling
- [ ] `ecosystem.config.js` — single orchestrator process for PM2
- [ ] `is_due()` correctly evaluates all 6 frequency types
- [ ] Trigger functions invoke correct tools/CLIs
- [ ] `invoke_claude()` handles timeout and errors
- [ ] Health monitor restarts crashed watchers
- [ ] Dashboard system health updated regularly
- [ ] State persistence across restarts
- [ ] `--once` flag for testing
- [ ] Graceful shutdown on SIGTERM/SIGINT
- [ ] All tests pass
- [ ] No modifications to existing components
