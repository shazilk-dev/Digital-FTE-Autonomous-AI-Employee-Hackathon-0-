"""AI Employee Orchestrator — Master process coordinating watchers, schedules, health."""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.utils.logging_config import setup_logger  # noqa: E402

logger = setup_logger("orchestrator")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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
    ) -> None:
        self.vault_path = vault_path
        self.dry_run = dry_run if dry_run is not None else self._is_dry_run()
        self.check_interval = check_interval
        self._running = False
        self._tick_count = 0
        self._start_time: datetime | None = None
        self._watcher_restart_counts: dict[str, int] = {}
        self._watcher_restart_times: list[float] = []  # Rolling window

        # Lazy imports to allow mocking in tests
        self._watcher_manager: Any = None
        self._schedule_registry: list[Any] = []

        self._setup_signal_handlers()

    def _is_dry_run(self) -> bool:
        return os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")

    @property
    def watcher_manager(self) -> Any:
        if self._watcher_manager is None:
            from scripts.watchers.runner import WatcherManager
            self._watcher_manager = WatcherManager(self.vault_path)
        return self._watcher_manager

    @watcher_manager.setter
    def watcher_manager(self, value: Any) -> None:
        self._watcher_manager = value

    def _load_schedule_registry(self) -> list[Any]:
        from scripts.schedules import load_schedules
        return load_schedules()

    def start(self) -> None:
        """
        Main entry point. Starts the orchestrator loop.

        Flow:
        1. Log startup
        2. Start all watchers
        3. Update Dashboard system health
        4. Enter main loop
        5. Shutdown on signal
        """
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        self._schedule_registry = self._load_schedule_registry()
        self._load_state()

        logger.info(
            "Orchestrator starting (vault=%s, dry_run=%s, interval=%ds)",
            self.vault_path, self.dry_run, self.check_interval,
        )

        # Start watchers
        try:
            results = self.watcher_manager.start_all(dry_run=self.dry_run)
            logger.info("Watchers started: %s", results)
        except Exception as exc:
            logger.error("Failed to start watchers: %s", exc)

        # Initial health update
        self._update_health()

        # Main loop
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Orchestrator tick error: %s", exc)
            if self._running:
                time.sleep(self.check_interval)

        self._shutdown()

    def _tick(self) -> None:
        """Single orchestrator cycle."""
        from scripts.schedules import get_due_tasks
        import scripts.schedules as schedules_module

        self._tick_count += 1
        now = datetime.now(timezone.utc)

        # Check scheduled tasks
        due_tasks = get_due_tasks(self._schedule_registry, now)
        for task in due_tasks:
            logger.info("Executing scheduled task: %s", task.name)
            try:
                trigger_fn = getattr(schedules_module, task.trigger_fn)
                result = trigger_fn(self.vault_path, dry_run=self.dry_run)
                task.last_run = now
                self._log_task_execution(task, result)
            except Exception as exc:
                logger.error("Task %s failed: %s", task.name, exc)
                self._log_task_execution(task, {"success": False, "error": str(exc)})

        # Health check every 2nd tick
        if self._tick_count % 2 == 0:
            self._check_watcher_health()

        # Persist state periodically (every 10th tick)
        if self._tick_count % 10 == 0:
            self._save_state()

    def _check_watcher_health(self) -> None:
        """Check if all watchers are still running. Restart any that have crashed."""
        try:
            from scripts.utils.dashboard_updater import add_error
            statuses = self.watcher_manager.status()
        except Exception as exc:
            logger.error("Failed to get watcher status: %s", exc)
            return

        now_ts = time.time()
        # Track restart times in a 10-minute rolling window
        self._watcher_restart_times = [
            t for t in self._watcher_restart_times if now_ts - t < 600
        ]

        for s in statuses:
            if not s["enabled"] or s["running"]:
                continue

            name = s["name"]
            restart_count = self._watcher_restart_counts.get(name, 0)

            # Pause watchers if too many recent restarts (>5 in 10 min)
            if len(self._watcher_restart_times) >= 5:
                logger.warning(
                    "Too many restarts in 10 minutes, pausing auto-restart for %s", name
                )
                try:
                    add_error(
                        self.vault_path,
                        f"watcher_{name}",
                        "Repeated crashes (>5 restarts in 10 min) — auto-restart paused",
                        "Manual intervention required",
                    )
                except Exception:
                    pass
                continue

            logger.warning("Watcher %s is down, restarting...", name)
            try:
                self.watcher_manager.start(name, dry_run=self.dry_run)
                self._watcher_restart_counts[name] = restart_count + 1
                self._watcher_restart_times.append(now_ts)
            except Exception as exc:
                logger.error("Failed to restart watcher %s: %s", name, exc)

            try:
                add_error(
                    self.vault_path,
                    f"watcher_{name}",
                    "Crashed and auto-restarted",
                    "Auto-restarted",
                )
            except Exception as exc:
                logger.warning("Could not log watcher restart to Dashboard: %s", exc)

    def _update_health(self) -> None:
        """Update Dashboard system health section with current status."""
        try:
            from scripts.utils.dashboard_updater import update_system_health
            statuses = self.watcher_manager.status()
        except Exception as exc:
            logger.error("Failed to update health: %s", exc)
            return

        for s in statuses:
            status_emoji = "🟢 Running" if s["running"] else "🔴 Down"
            try:
                update_system_health(
                    self.vault_path,
                    component=f"{s['name']}_watcher",
                    status=status_emoji,
                )
            except Exception as exc:
                logger.warning("Could not update health for %s: %s", s["name"], exc)

        # Check MCP servers by file existence
        for mcp_name in ["email-mcp", "linkedin-mcp"]:
            mcp_path = self.vault_path / f"mcp-servers/{mcp_name}/src/index.ts"
            status = "🟢 Available" if mcp_path.exists() else "🔴 Missing"
            try:
                update_system_health(self.vault_path, component=mcp_name, status=status)
            except Exception as exc:
                logger.warning("Could not update MCP health for %s: %s", mcp_name, exc)

    def run_once(self) -> dict[str, Any]:
        """Single-cycle mode for testing."""
        self._schedule_registry = self._load_schedule_registry()
        self._load_state()

        logger.info("Orchestrator run_once (dry_run=%s)", self.dry_run)

        # Start watchers
        start_results: dict[str, bool] = {}
        try:
            start_results = self.watcher_manager.start_all(dry_run=self.dry_run)
        except Exception as exc:
            logger.error("Failed to start watchers: %s", exc)

        # Single tick
        self._tick()

        # Health update
        self._update_health()

        # Stop watchers
        stop_results: dict[str, bool] = {}
        try:
            stop_results = self.watcher_manager.stop_all()
        except Exception as exc:
            logger.error("Failed to stop watchers: %s", exc)

        self._save_state()

        return {
            "success": True,
            "tick_count": self._tick_count,
            "watchers_started": start_results,
            "watchers_stopped": stop_results,
        }

    def _shutdown(self) -> None:
        """Graceful shutdown: stop all watchers, save state, log."""
        logger.info("Orchestrator shutting down...")
        try:
            self.watcher_manager.stop_all()
        except Exception as exc:
            logger.error("Error stopping watchers during shutdown: %s", exc)
        self._update_health()
        self._save_state()
        logger.info("Orchestrator stopped.")

    def _log_task_execution(self, task: Any, result: dict[str, Any]) -> None:
        """Log scheduled task execution result."""
        success = result.get("success", False)
        status = "success" if success else "failure"
        logger.info(
            "Task '%s' completed: %s | result=%s",
            task.name, status, json.dumps(result, default=str),
        )

    # ---------------------------------------------------------------------------
    # State persistence
    # ---------------------------------------------------------------------------

    def _state_file(self) -> Path:
        state_dir = self.vault_path / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "orchestrator_state.json"

    def _save_state(self) -> None:
        """Save orchestrator state to .state/orchestrator_state.json."""
        state: dict[str, Any] = {
            "tick_count": self._tick_count,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "watcher_restart_counts": self._watcher_restart_counts,
            "schedule_last_run": {
                task.name: task.last_run.isoformat() if task.last_run else None
                for task in self._schedule_registry
            },
        }
        state_file = self._state_file()
        try:
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=state_file.parent, suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, default=str)
                Path(tmp_path).replace(state_file)
            except Exception:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.error("Failed to save orchestrator state: %s", exc)

    def _load_state(self) -> None:
        """Load saved state and apply to schedule registry."""
        state_file = self._state_file()
        if not state_file.exists():
            logger.info("No orchestrator state file found — fresh start")
            return
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load orchestrator state: %s", exc)
            return

        self._tick_count = data.get("tick_count", 0)
        self._watcher_restart_counts = data.get("watcher_restart_counts", {})

        last_run_map: dict[str, str | None] = data.get("schedule_last_run", {})
        for task in self._schedule_registry:
            ts = last_run_map.get(task.name)
            if ts:
                try:
                    task.last_run = datetime.fromisoformat(ts)
                    if task.last_run.tzinfo is None:
                        task.last_run = task.last_run.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

        logger.info("Orchestrator state loaded (tick_count=%d)", self._tick_count)

    # ---------------------------------------------------------------------------
    # Signal handling
    # ---------------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        """Handle SIGTERM and SIGINT."""
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._on_signal)
            except (OSError, ValueError):
                pass

    def _on_signal(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="AI Employee Orchestrator — Master Process",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        """,
    )
    parser.add_argument("--vault", default=None)
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Main loop interval in seconds",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run single cycle and exit",
    )
    parser.add_argument(
        "--no-watchers", action="store_true",
        help="Don't start watchers (schedule-only mode)",
    )

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    orch = Orchestrator(vault_path, check_interval=args.interval)

    if args.once:
        result = orch.run_once()
        print(json.dumps(result, indent=2, default=str))
    else:
        orch.start()
