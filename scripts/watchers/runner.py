"""Unified watcher runner — manages all AI Employee watcher processes."""

import importlib
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as: uv run python -m scripts.watchers.runner
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.utils.logging_config import setup_logger  # noqa: E402

logger = setup_logger("runner")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class WatcherEntry:
    """Registry entry for a watcher."""

    name: str                            # Unique identifier: "gmail", "whatsapp", "filesystem"
    module_path: str                     # Python module: "scripts.watchers.gmail_watcher"
    class_name: str                      # Class to instantiate: "GmailWatcher"
    description: str                     # Human-readable description
    enabled: bool = True                 # Can be disabled without removing
    required_env_vars: list[str] = field(default_factory=list)  # Env vars for LIVE mode
    default_interval: int = 60           # Default check_interval in seconds
    extra_kwargs: dict[str, Any] = field(default_factory=dict)  # Additional constructor args


WATCHER_REGISTRY: list[WatcherEntry] = [
    WatcherEntry(
        name="gmail",
        module_path="scripts.watchers.gmail_watcher",
        class_name="GmailWatcher",
        description="Monitors Gmail for important/unread emails",
        required_env_vars=["GMAIL_CREDENTIALS_PATH"],
        default_interval=120,
    ),
    WatcherEntry(
        name="whatsapp",
        module_path="scripts.watchers.whatsapp_watcher",
        class_name="WhatsAppWatcher",
        description="Monitors WhatsApp Web for keyword-matching messages",
        required_env_vars=["WHATSAPP_SESSION_PATH"],
        default_interval=60,
    ),
    WatcherEntry(
        name="filesystem",
        module_path="scripts.watchers.filesystem_watcher",
        class_name="FileSystemWatcher",
        description="Monitors /Drop/ folder for new files",
        required_env_vars=[],
        default_interval=30,
    ),
    WatcherEntry(
        name="approval",
        module_path="scripts.watchers.approval_watcher",
        class_name="ApprovalWatcher",
        description="Monitors /Approved/ and /Rejected/ for HITL execution",
        required_env_vars=[],
        default_interval=10,
    ),
]


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class WatcherManager:
    """
    Manages watcher lifecycle in development mode (subprocess-based).
    For production, use PM2 with the generated ecosystem.config.js.
    """

    def __init__(self, vault_path: Path, registry: list[WatcherEntry] | None = None) -> None:
        self.vault_path = vault_path
        self.registry = registry or WATCHER_REGISTRY
        self._processes: dict[str, subprocess.Popen] = {}   # name → Popen
        self._start_times: dict[str, float] = {}             # name → epoch time
        self._log_handles: dict[str, Any] = {}               # name → file handle
        self._setup_signal_handlers()

    def get_registry(self) -> list[WatcherEntry]:
        """Return the watcher registry, filtered to enabled entries only."""
        return [e for e in self.registry if e.enabled]

    def get_entry(self, name: str) -> WatcherEntry:
        """Get a single registry entry by name. Raise ValueError if not found."""
        for entry in self.registry:
            if entry.name == name:
                return entry
        raise ValueError(f"No watcher named '{name}' in registry")

    def check_prerequisites(self, name: str) -> dict:
        """
        Check if a watcher's prerequisites are met.

        Returns:
        {
            "name": "gmail",
            "can_run_live": True/False,
            "can_run_dry": True,         # Always true (DRY_RUN needs no credentials)
            "missing_env_vars": [],       # List of missing required env vars
            "module_importable": True,    # Can the Python module be imported?
            "errors": [],                 # Any other issues
        }
        """
        entry = self.get_entry(name)
        missing_env_vars = [v for v in entry.required_env_vars if not os.getenv(v)]

        # Check if module can be imported
        try:
            importlib.import_module(entry.module_path)
            module_importable = True
        except (ImportError, ModuleNotFoundError):
            module_importable = False

        errors: list[str] = []
        if not module_importable:
            errors.append(f"Module '{entry.module_path}' cannot be imported")

        return {
            "name": name,
            "can_run_live": len(missing_env_vars) == 0 and module_importable,
            "can_run_dry": True,  # DRY_RUN always works
            "missing_env_vars": missing_env_vars,
            "module_importable": module_importable,
            "errors": errors,
        }

    def _pid_file(self, name: str) -> Path:
        """Return path to PID file for this watcher."""
        return Path(tempfile.gettempdir()) / f"aiemp_{name}.pid"

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is alive (cross-platform)."""
        try:
            import psutil  # type: ignore[import-untyped]
            return psutil.pid_exists(pid)
        except ImportError:
            pass
        # Fallback: os.kill(pid, 0) — works on Unix and Windows (Python 3.2+)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def start(self, name: str, dry_run: bool = False) -> bool:
        """
        Start a single watcher as a subprocess.

        1. Check prerequisites → if not met and not dry_run, fail
        2. If already running (PID alive), log warning and return
        3. Build command: ['uv', 'run', 'python', '-m', module_path, ...]
        4. If dry_run: add DRY_RUN=true to env
        5. Launch subprocess, capture PID
        6. Write PID file to /tmp/aiemp_{name}.pid
        7. Log start event
        8. Return True on success
        """
        entry = self.get_entry(name)

        if not entry.enabled:
            logger.warning("Watcher '%s' is disabled, skipping", name)
            return False

        # Check if already tracked and still running
        proc = self._processes.get(name)
        if proc is not None and proc.poll() is None:
            logger.warning("Watcher '%s' is already running (PID %d)", name, proc.pid)
            return False

        # Check PID file for externally-managed process
        pid_file = self._pid_file(name)
        if pid_file.exists():
            try:
                existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
                if self._is_process_alive(existing_pid):
                    logger.warning(
                        "Watcher '%s' already running (PID %d from file)", name, existing_pid
                    )
                    return False
            except (ValueError, OSError):
                pass  # Stale or unreadable PID file — continue

        # Check prerequisites (skip for dry_run)
        prereqs = self.check_prerequisites(name)
        if not dry_run and not prereqs["can_run_live"]:
            logger.error(
                "Watcher '%s' cannot run live: missing env vars %s",
                name,
                prereqs["missing_env_vars"],
            )
            return False

        # Build command
        cmd = [
            "uv", "run", "python", "-m", entry.module_path,
            "--vault", str(self.vault_path),
            "--interval", str(entry.default_interval),
        ]

        # Build environment
        env = os.environ.copy()
        if dry_run:
            env["DRY_RUN"] = "true"
        env["VAULT_PATH"] = str(self.vault_path)

        # Redirect subprocess output to log file
        logs_dir = self.vault_path / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"watcher_{name}.log"

        try:
            log_handle = open(log_file, "a", encoding="utf-8")  # noqa: WPS515
            self._log_handles[name] = log_handle
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=log_handle,
                stderr=log_handle,
                cwd=str(self.vault_path),
            )
        except (OSError, FileNotFoundError) as exc:
            logger.error("Failed to start watcher '%s': %s", name, exc)
            return False

        self._processes[name] = proc
        self._start_times[name] = time.time()

        # Write PID file
        try:
            pid_file.write_text(str(proc.pid), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write PID file for '%s': %s", name, exc)

        logger.info("Started watcher '%s' (PID %d)", name, proc.pid)
        return True

    def start_all(self, dry_run: bool = False) -> dict[str, bool]:
        """Start all enabled watchers. Returns {name: success_bool}."""
        results: dict[str, bool] = {}
        for entry in self.get_registry():
            results[entry.name] = self.start(entry.name, dry_run=dry_run)
        running_count = sum(results.values())
        logger.info("start_all: %d/%d watchers started", running_count, len(results))
        return results

    def stop(self, name: str) -> bool:
        """
        Stop a watcher.

        1. Look up subprocess in self._processes
        2. Send SIGTERM (graceful)
        3. Wait 5s for exit
        4. If still running: SIGKILL
        5. Remove PID file
        6. Log stop event
        7. Return True on success
        """
        proc = self._processes.get(name)

        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()  # SIGTERM (cross-platform via Popen)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()  # SIGKILL
                    proc.wait()
            except OSError as exc:
                logger.warning("Error stopping watcher '%s': %s", name, exc)

        # Remove PID file
        pid_file = self._pid_file(name)
        try:
            pid_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove PID file for '%s': %s", name, exc)

        # Close log file handle
        handle = self._log_handles.pop(name, None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

        # Remove from tracking dicts
        self._processes.pop(name, None)
        self._start_times.pop(name, None)

        logger.info("Stopped watcher '%s'", name)
        return True

    def stop_all(self) -> dict[str, bool]:
        """Stop all running watchers."""
        results: dict[str, bool] = {}
        for name in list(self._processes.keys()):
            results[name] = self.stop(name)
        return results

    def restart(self, name: str, dry_run: bool = False) -> bool:
        """Stop then start a watcher."""
        self.stop(name)
        return self.start(name, dry_run=dry_run)

    def status(self) -> list[dict]:
        """
        Get status of all registered watchers.

        Checks running by:
        1. Process is in self._processes and proc.poll() is None
        2. PID file exists and process with that PID is alive (os.kill(pid, 0))
        """
        statuses: list[dict] = []

        for entry in self.registry:
            running = False
            pid: int | None = None
            uptime: str | None = None

            # Check our tracked process dict first
            proc = self._processes.get(entry.name)
            if proc is not None and proc.poll() is None:
                running = True
                pid = proc.pid
                start_time = self._start_times.get(entry.name)
                if start_time is not None:
                    uptime = _format_uptime(time.time() - start_time)
            else:
                # Check PID file for externally-managed or previously-started process
                pid_file = self._pid_file(entry.name)
                if pid_file.exists():
                    try:
                        file_pid = int(pid_file.read_text(encoding="utf-8").strip())
                        if self._is_process_alive(file_pid):
                            running = True
                            pid = file_pid
                        # else: stale PID file — process is dead
                    except (ValueError, OSError):
                        pass

            prereqs = self.check_prerequisites(entry.name)

            # Read state file for last_check and items_processed
            last_check: str | None = None
            items_processed: int = 0
            state_file = self.vault_path / ".state" / f"{entry.name}_processed.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    last_check = data.get("last_updated")
                    items_processed = len(data.get("processed_ids", []))
                except (json.JSONDecodeError, OSError):
                    pass

            statuses.append({
                "name": entry.name,
                "enabled": entry.enabled,
                "running": running,
                "pid": pid,
                "uptime": uptime,
                "last_check": last_check,
                "items_processed": items_processed,
                "can_run_live": prereqs["can_run_live"],
                "missing_env_vars": prereqs["missing_env_vars"],
            })

        return statuses

    def _setup_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers to call stop_all."""
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._on_signal)
            except (OSError, ValueError):
                # ValueError: signal handlers can only be set in the main thread
                # OSError: signal not supported on this platform
                pass

    def _on_signal(self, signum: int, frame: Any) -> None:
        """Graceful shutdown: stop all watchers, exit cleanly."""
        logger.info("Received signal %d, stopping all watchers...", signum)
        self.stop_all()
        sys.exit(0)


# ---------------------------------------------------------------------------
# Status formatters
# ---------------------------------------------------------------------------


def _format_uptime(seconds: float) -> str:
    """Format elapsed seconds as human-readable uptime string."""
    secs = int(seconds)
    if secs >= 3600:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h}h {m}m"
    elif secs >= 60:
        m = secs // 60
        s = secs % 60
        return f"{m}m {s}s"
    else:
        return f"{secs}s"


def format_status_table(statuses: list[dict]) -> str:
    """
    Format status as a readable table:

    Watcher     │ Status     │ PID   │ Uptime  │ Processed │ Prerequisites
    ────────────┼────────────┼───────┼─────────┼───────────┼──────────────
    gmail       │ 🟢 Running │ 12345 │ 2h 15m  │ 42        │ ✅ Ready
    whatsapp    │ 🔴 Stopped │ —     │ —       │ 0         │ ⚠️  Missing: WHATSAPP_SESSION_PATH
    filesystem  │ 🟢 Running │ 12347 │ 2h 15m  │ 8         │ ✅ Ready
    """
    lines = [
        "Watcher     │ Status      │ PID   │ Uptime  │ Processed │ Prerequisites",
        "────────────┼─────────────┼───────┼─────────┼───────────┼──────────────",
    ]
    for s in statuses:
        name_col = s["name"][:10].ljust(10)
        if s["running"]:
            status_col = "🟢 Running  "
        elif not s["enabled"]:
            status_col = "⭕ Disabled  "
        else:
            status_col = "🔴 Stopped  "
        pid_col = str(s["pid"]) if s["pid"] else "—"
        uptime_col = (s["uptime"] or "—")[:7]
        processed_col = str(s["items_processed"])
        if s["missing_env_vars"]:
            prereq_col = "⚠️  Missing: " + ", ".join(s["missing_env_vars"])
        elif s["can_run_live"]:
            prereq_col = "✅ Ready"
        else:
            prereq_col = "❌ Not ready"
        lines.append(
            f"{name_col} │ {status_col} │ {pid_col:<5} │ {uptime_col:<7} │"
            f" {processed_col:<9} │ {prereq_col}"
        )
    return "\n".join(lines)


def format_status_json(statuses: list[dict]) -> str:
    """Full JSON output for programmatic consumption."""
    return json.dumps(statuses, indent=2, default=str)


def format_status_brief(statuses: list[dict]) -> str:
    """One-line summary: 'Running: 2/3 (gmail, filesystem) | Stopped: whatsapp'"""
    running = [s["name"] for s in statuses if s["running"]]
    stopped = [s["name"] for s in statuses if not s["running"] and s["enabled"]]
    total_enabled = len([s for s in statuses if s["enabled"]])
    summary = f"Running: {len(running)}/{total_enabled}"
    if running:
        summary += f" ({', '.join(running)})"
    if stopped:
        summary += f" | Stopped: {', '.join(stopped)}"
    return summary


# ---------------------------------------------------------------------------
# PM2 ecosystem config generator
# ---------------------------------------------------------------------------


def generate_pm2_config(
    vault_path: Path,
    registry: list[WatcherEntry],
    output_path: Path | None = None,
) -> str:
    """
    Generate ecosystem.config.js for PM2 process management.

    Output path default: vault_path / "ecosystem.config.js"
    """
    output_path = output_path or (vault_path / "ecosystem.config.js")
    vault_str = str(vault_path).replace("\\", "/")

    app_entries: list[str] = []
    for entry in registry:
        if not entry.enabled:
            continue

        # Build env block
        env_pairs: list[str] = [
            f'      VAULT_PATH: "{vault_str}",',
            '      DRY_RUN: "false",',
        ]
        for env_var in entry.required_env_vars:
            env_val = os.getenv(env_var, f"./config/{env_var.lower()}")
            env_pairs.append(f'      {env_var}: "{env_val}",')
        env_block = "\n".join(env_pairs)

        # PM2 tuning per watcher type
        if entry.name == "whatsapp":
            max_restarts = 5
            restart_delay = 10000
            max_memory = "500M"
            extra = "      // Playwright uses more memory\n"
        elif entry.name == "filesystem":
            max_restarts = 10
            restart_delay = 3000
            max_memory = "100M"
            extra = ""
        else:
            max_restarts = 10
            restart_delay = 5000
            max_memory = "200M"
            extra = ""

        app_entries.append(
            f"""    {{
      name: "aiemp-{entry.name}-watcher",
      script: "uv",
      args: "run python -m {entry.module_path} --vault {vault_str} --interval {entry.default_interval}",
      cwd: "{vault_str}",
      env: {{
{env_block}
      }},
      autorestart: true,
      max_restarts: {max_restarts},
      restart_delay: {restart_delay},
{extra}      max_memory_restart: "{max_memory}",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "./Logs/pm2/{entry.name}-watcher-error.log",
      out_file: "./Logs/pm2/{entry.name}-watcher-out.log",
      merge_logs: true,
      watch: false,
    }}"""
        )

    apps_block = ",\n".join(app_entries)

    content = f"""// ecosystem.config.js — Generated by runner.py
// Usage: pm2 start ecosystem.config.js

// Quick reference:
// pm2 start ecosystem.config.js          # Start all watchers
// pm2 stop all                           # Stop all
// pm2 restart aiemp-gmail-watcher        # Restart one
// pm2 logs aiemp-whatsapp-watcher        # View logs
// pm2 monit                              # Real-time monitoring dashboard
// pm2 save && pm2 startup                # Persist across reboots
// pm2 delete all                         # Remove all processes

module.exports = {{
  apps: [
{apps_block},
  ],
}};
"""

    output_path.write_text(content, encoding="utf-8")
    logger.info("PM2 config written to %s", output_path)
    return content


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    # Ensure Unicode output works on Windows (box-drawing chars, emoji)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="AI Employee Watcher Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start all watchers in dry-run mode
  uv run python scripts/watchers/runner.py start --dry-run

  # Start only Gmail watcher
  uv run python scripts/watchers/runner.py start gmail

  # Check status of all watchers
  uv run python scripts/watchers/runner.py status

  # Generate PM2 config
  uv run python scripts/watchers/runner.py generate-pm2

  # Stop all watchers
  uv run python scripts/watchers/runner.py stop
        """,
    )

    parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env or .)")
    parser.add_argument(
        "--format", choices=["table", "json", "brief"], default="table",
        help="Output format for status command",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    start_p = subparsers.add_parser("start", help="Start watchers")
    start_p.add_argument("name", nargs="?", default="all", help="Watcher name or 'all'")
    start_p.add_argument("--dry-run", action="store_true", help="Force DRY_RUN mode")

    # stop
    stop_p = subparsers.add_parser("stop", help="Stop watchers")
    stop_p.add_argument("name", nargs="?", default="all", help="Watcher name or 'all'")

    # restart
    restart_p = subparsers.add_parser("restart", help="Restart a watcher")
    restart_p.add_argument("name", help="Watcher name")

    # status
    subparsers.add_parser("status", help="Show watcher status")

    # check
    check_p = subparsers.add_parser("check", help="Check prerequisites for watchers")
    check_p.add_argument("name", nargs="?", default="all", help="Watcher name or 'all'")

    # generate-pm2
    pm2_p = subparsers.add_parser("generate-pm2", help="Generate PM2 ecosystem config")
    pm2_p.add_argument("--output", default=None, help="Output path (default: ecosystem.config.js)")

    # list
    subparsers.add_parser("list", help="List registered watchers")

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}", file=sys.stderr)
        sys.exit(1)

    manager = WatcherManager(vault_path)

    if args.command == "start":
        if args.name == "all":
            results = manager.start_all(dry_run=args.dry_run)
            for watcher_name, success in results.items():
                print(f"  {'✅' if success else '❌'} {watcher_name}")
        else:
            ok = manager.start(args.name, dry_run=args.dry_run)
            sys.exit(0 if ok else 1)

    elif args.command == "stop":
        if args.name == "all":
            results = manager.stop_all()
            for watcher_name, success in results.items():
                print(f"  {'✅' if success else '❌'} {watcher_name}")
        else:
            ok = manager.stop(args.name)
            sys.exit(0 if ok else 1)

    elif args.command == "restart":
        ok = manager.restart(args.name)
        sys.exit(0 if ok else 1)

    elif args.command == "status":
        statuses = manager.status()
        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(format_status_json(statuses))
        elif fmt == "brief":
            print(format_status_brief(statuses))
        else:
            print(format_status_table(statuses))

    elif args.command == "check":
        if args.name == "all":
            check_names = [e.name for e in manager.get_registry()]
        else:
            check_names = [args.name]
        for watcher_name in check_names:
            prereqs = manager.check_prerequisites(watcher_name)
            if prereqs["can_run_live"]:
                print(f"  ✅ {watcher_name}: Ready")
            else:
                missing = ", ".join(prereqs["missing_env_vars"])
                print(f"  ⚠️  {watcher_name}: Missing: {missing}")

    elif args.command == "generate-pm2":
        out = Path(args.output) if args.output else None
        generate_pm2_config(vault_path, manager.registry, out)
        out_path = out or vault_path / "ecosystem.config.js"
        print(f"Generated: {out_path}")

    elif args.command == "list":
        for entry in manager.registry:
            status_str = "enabled" if entry.enabled else "disabled"
            print(f"  [{status_str}] {entry.name}: {entry.description}")
