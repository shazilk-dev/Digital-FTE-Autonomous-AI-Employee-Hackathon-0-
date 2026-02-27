# Spec: Watcher Runner — Unified Watcher Management

> **Component:** `scripts/watchers/runner.py`
> **Supporting:** `ecosystem.config.js` (PM2 configuration)
> **Priority:** P1 — Ties all watchers into a manageable system
> **Tests:** `tests/watchers/test_runner.py`
> **Depends On:** All watcher implementations (Gmail, WhatsApp, FileSystem)

## 1. Objective

Create a single entry point that manages all watcher processes. The runner:
1. Discovers all available watchers via a registry
2. Starts/stops/restarts individual or all watchers
3. Reports health status of each watcher
4. Generates PM2 ecosystem config for production process management
5. Handles graceful shutdown (SIGTERM/SIGINT)

The runner is NOT a process manager itself — it's a control plane that works both
standalone (for development) and with PM2 (for production).

## 2. Architecture

```
                     ┌──────────────────────┐
                     │  scripts/watchers/   │
                     │     runner.py        │
                     │                      │
                     │  WatcherRegistry     │
                     │  ┌────────────────┐  │
                     │  │ gmail_watcher  │  │
                     │  │ whatsapp_watch │  │
                     │  │ filesystem_wat │  │
                     │  └────────────────┘  │
                     │                      │
                     │  Commands:           │
                     │  • start [name|all]  │
                     │  • stop [name|all]   │
                     │  • restart [name]    │
                     │  • status            │
                     │  • generate-pm2      │
                     └──────────────────────┘
                              │
            Development       │       Production
          ┌───────────────────┼────────────────────┐
          ▼                                        ▼
   Subprocess per watcher              PM2 manages processes
   (runner owns lifecycle)             (ecosystem.config.js)
```

## 3. Watcher Registry

### 3A. Registry Design

A declarative registry of all watchers. Each entry defines how to instantiate
and configure a watcher.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class WatcherEntry:
    """Registry entry for a watcher."""
    name: str                          # Unique identifier: "gmail", "whatsapp", "filesystem"
    module_path: str                   # Python module: "scripts.watchers.gmail_watcher"
    class_name: str                    # Class to instantiate: "GmailWatcher"
    description: str                   # Human-readable: "Monitors Gmail for important emails"
    enabled: bool = True               # Can be disabled without removing
    required_env_vars: list[str] = field(default_factory=list)  # Env vars needed for LIVE mode
    default_interval: int = 60         # Default check_interval
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
]
```

### 3B. Adding New Watchers

Future watchers (Gold tier: Finance, Social Media) simply add entries to the registry.
No code changes to the runner itself. This is the extension point.

## 4. Core Functions

### 4A. WatcherManager Class

```python
class WatcherManager:
    """
    Manages watcher lifecycle in development mode (subprocess-based).
    For production, use PM2 with the generated ecosystem.config.js.
    """

    def __init__(self, vault_path: Path, registry: list[WatcherEntry] | None = None):
        self.vault_path = vault_path
        self.registry = registry or WATCHER_REGISTRY
        self._processes: dict[str, subprocess.Popen] = {}   # Running subprocesses
        self._setup_signal_handlers()

    def get_registry(self) -> list[WatcherEntry]:
        """Return the watcher registry, filtered to enabled only."""

    def get_entry(self, name: str) -> WatcherEntry:
        """Get a single registry entry by name. Raise ValueError if not found."""

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

    def start(self, name: str, dry_run: bool = False) -> bool:
        """
        Start a single watcher as a subprocess.

        1. Check prerequisites → if not met and not dry_run, fail
        2. If already running (PID alive), log warning and return
        3. Build command: ['uv', 'run', 'python', '-m', module_path,
                           '--vault', str(vault_path),
                           '--interval', str(interval)]
        4. If dry_run: add DRY_RUN=true to env
        5. Launch subprocess, capture PID
        6. Write PID file to /tmp/aiemp_{name}.pid
        7. Log start event
        8. Return True on success

        Subprocess stdout/stderr → log files: /Logs/watcher_{name}.log
        """

    def start_all(self, dry_run: bool = False) -> dict[str, bool]:
        """
        Start all enabled watchers. Returns {name: success_bool}.
        Skip disabled entries. Log summary.
        """

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

    def stop_all(self) -> dict[str, bool]:
        """Stop all running watchers."""

    def restart(self, name: str, dry_run: bool = False) -> bool:
        """Stop then start a watcher."""

    def status(self) -> list[dict]:
        """
        Get status of all registered watchers.

        Returns list of:
        {
            "name": "gmail",
            "enabled": True,
            "running": True,
            "pid": 12345,
            "uptime": "2h 15m",
            "last_check": "2026-02-27T10:30:00Z",  # From state file
            "items_processed": 42,                    # From state file count
            "can_run_live": True,
            "missing_env_vars": [],
        }

        Check running by:
        1. PID file exists at /tmp/aiemp_{name}.pid
        2. Process with that PID is alive (os.kill(pid, 0))
        """

    def _setup_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers to call stop_all."""

    def _on_signal(self, signum, frame) -> None:
        """Graceful shutdown: stop all watchers, exit cleanly."""
```

### 4B. Status Output Formats

```python
def format_status_table(statuses: list[dict]) -> str:
    """
    Format status as a readable table:

    Watcher     │ Status     │ PID   │ Uptime  │ Processed │ Prerequisites
    ────────────┼────────────┼───────┼─────────┼───────────┼──────────────
    gmail       │ 🟢 Running │ 12345 │ 2h 15m  │ 42        │ ✅ Ready
    whatsapp    │ 🔴 Stopped │ —     │ —       │ 0         │ ⚠️  Missing: WHATSAPP_SESSION_PATH
    filesystem  │ 🟢 Running │ 12347 │ 2h 15m  │ 8         │ ✅ Ready
    """

def format_status_json(statuses: list[dict]) -> str:
    """Full JSON output for programmatic consumption."""

def format_status_brief(statuses: list[dict]) -> str:
    """One-line summary: 'Running: 2/3 (gmail, filesystem) | Stopped: whatsapp'"""
```

## 5. PM2 Ecosystem Configuration

### 5A. Generator Function

```python
def generate_pm2_config(
    vault_path: Path,
    registry: list[WatcherEntry],
    output_path: Path | None = None,
) -> str:
    """
    Generate ecosystem.config.js for PM2 process management.

    Output path default: vault_path / "ecosystem.config.js"

    PM2 features used:
    - auto-restart on crash
    - log rotation
    - environment variable injection
    - startup persistence (pm2 startup)
    """
```

### 5B. Generated ecosystem.config.js Format

```javascript
// ecosystem.config.js — Generated by runner.py
// Usage: pm2 start ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "aiemp-gmail-watcher",
      script: "uv",
      args: "run python -m scripts.watchers.gmail_watcher --vault /path/to/vault --interval 120",
      cwd: "/path/to/vault",
      env: {
        VAULT_PATH: "/path/to/vault",
        DRY_RUN: "false",
        GMAIL_CREDENTIALS_PATH: "./credentials.json",
        GMAIL_TOKEN_PATH: "./token.json",
      },
      // PM2 config
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,          // 5s between restarts
      max_memory_restart: "200M",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "./Logs/pm2/gmail-watcher-error.log",
      out_file: "./Logs/pm2/gmail-watcher-out.log",
      merge_logs: true,
      // Health check
      watch: false,                  // Don't watch files (we have our own watcher!)
    },
    {
      name: "aiemp-whatsapp-watcher",
      script: "uv",
      args: "run python -m scripts.watchers.whatsapp_watcher --vault /path/to/vault --interval 60",
      cwd: "/path/to/vault",
      env: {
        VAULT_PATH: "/path/to/vault",
        DRY_RUN: "false",
        WHATSAPP_SESSION_PATH: "./sessions/whatsapp",
      },
      autorestart: true,
      max_restarts: 5,               // Fewer restarts — session issues need manual fix
      restart_delay: 10000,           // 10s — give WhatsApp time
      max_memory_restart: "500M",     // Playwright uses more memory
      error_file: "./Logs/pm2/whatsapp-watcher-error.log",
      out_file: "./Logs/pm2/whatsapp-watcher-out.log",
      merge_logs: true,
      watch: false,
    },
    {
      name: "aiemp-filesystem-watcher",
      script: "uv",
      args: "run python -m scripts.watchers.filesystem_watcher --vault /path/to/vault --interval 30",
      cwd: "/path/to/vault",
      env: {
        VAULT_PATH: "/path/to/vault",
        DRY_RUN: "false",
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      max_memory_restart: "100M",
      error_file: "./Logs/pm2/filesystem-watcher-error.log",
      out_file: "./Logs/pm2/filesystem-watcher-out.log",
      merge_logs: true,
      watch: false,
    },
  ],
};
```

### 5C. PM2 Quick Reference

Include these as comments in the generated file:

```javascript
// Quick reference:
// pm2 start ecosystem.config.js          # Start all watchers
// pm2 stop all                           # Stop all
// pm2 restart aiemp-gmail-watcher        # Restart one
// pm2 logs aiemp-whatsapp-watcher        # View logs
// pm2 monit                              # Real-time monitoring dashboard
// pm2 save && pm2 startup                # Persist across reboots
// pm2 delete all                         # Remove all processes
```

## 6. CLI Interface

```python
if __name__ == "__main__":
    import argparse

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
        """
    )

    parser.add_argument("--vault", default=None, help="Vault path")
    parser.add_argument("--format", choices=["table", "json", "brief"], default="table")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    start_p = subparsers.add_parser("start", help="Start watchers")
    start_p.add_argument("name", nargs="?", default="all", help="Watcher name or 'all'")
    start_p.add_argument("--dry-run", action="store_true", help="Force DRY_RUN mode")

    # stop
    stop_p = subparsers.add_parser("stop", help="Stop watchers")
    stop_p.add_argument("name", nargs="?", default="all")

    # restart
    restart_p = subparsers.add_parser("restart", help="Restart a watcher")
    restart_p.add_argument("name", required=True)

    # status
    subparsers.add_parser("status", help="Show watcher status")

    # check
    check_p = subparsers.add_parser("check", help="Check prerequisites")
    check_p.add_argument("name", nargs="?", default="all")

    # generate-pm2
    pm2_p = subparsers.add_parser("generate-pm2", help="Generate PM2 ecosystem config")
    pm2_p.add_argument("--output", default=None, help="Output path")

    # list
    subparsers.add_parser("list", help="List registered watchers")

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))
    manager = WatcherManager(vault_path)

    # Dispatch to appropriate method based on args.command
```

## 7. Test Requirements

### 7A. Fixtures

```python
@pytest.fixture
def manager(tmp_vault):
    """WatcherManager with tmp vault and mock registry."""
    # Use a simplified registry for testing
    test_registry = [
        WatcherEntry(
            name="test_watcher",
            module_path="tests.fixtures.mock_watcher",
            class_name="MockWatcher",
            description="Test watcher",
            required_env_vars=[],
            default_interval=10,
        ),
    ]
    return WatcherManager(tmp_vault, registry=test_registry)

@pytest.fixture
def mock_watcher_module(tmp_path):
    """Create a minimal mock watcher module for subprocess testing."""
```

### 7B. Test Cases

**Registry:**
- `test_registry_contains_all_watchers` — gmail, whatsapp, filesystem present
- `test_get_entry_valid_name` — returns correct entry
- `test_get_entry_invalid_name` — raises ValueError
- `test_registry_filters_disabled` — disabled watchers excluded from get_registry()

**Prerequisites:**
- `test_check_prerequisites_no_env_needed` — filesystem always ready
- `test_check_prerequisites_missing_env` — gmail without credentials reports missing
- `test_check_prerequisites_dry_run_always_ok` — can_run_dry always True

**Start/Stop (mocked subprocess):**
- `test_start_launches_subprocess` — subprocess.Popen called
- `test_start_writes_pid_file` — PID file created
- `test_start_already_running` — warns, doesn't double-start
- `test_start_dry_run_sets_env` — DRY_RUN=true in subprocess env
- `test_start_all_starts_enabled` — all enabled watchers launched
- `test_stop_sends_sigterm` — SIGTERM sent
- `test_stop_cleans_pid_file` — PID file removed
- `test_stop_force_kill_on_timeout` — SIGKILL after 5s
- `test_stop_all_stops_running` — all processes stopped
- `test_restart_stop_then_start` — stop called then start called

**Status:**
- `test_status_running_watcher` — shows running with PID
- `test_status_stopped_watcher` — shows stopped
- `test_status_stale_pid_file` — process dead but PID file exists → shows stopped
- `test_format_status_table` — readable table output
- `test_format_status_brief` — one-line summary

**PM2 Config:**
- `test_generate_pm2_creates_file` — ecosystem.config.js created
- `test_generate_pm2_valid_javascript` — can be parsed (basic validation)
- `test_generate_pm2_correct_paths` — vault path substituted correctly
- `test_generate_pm2_all_watchers` — one app entry per enabled watcher

**Signal Handling:**
- `test_sigterm_stops_all` — SIGTERM triggers stop_all
- `test_sigint_stops_all` — Ctrl+C triggers stop_all

## 8. Edge Cases

- **Watcher module not installed:** `check_prerequisites` returns `module_importable: False`
- **PID file exists but process dead:** `status` detects stale PID, reports stopped
- **Two runners started simultaneously:** Second runner sees PID files, reports already running
- **PM2 not installed:** `generate-pm2` still creates the config file, adds install instructions in comments
- **Vault path doesn't exist:** Fail early with clear error message
- **Permission denied on PID file:** Catch, log, continue without PID tracking
- **Windows compatibility:** PID management uses `os.kill(pid, 0)` which works on Unix. On Windows, use `psutil` if available, fallback to subprocess check.

## 9. Validation Criteria

- [ ] `scripts/watchers/runner.py` with WatcherManager class
- [ ] `ecosystem.config.js` generated correctly
- [ ] All 6 CLI commands work: start, stop, restart, status, check, generate-pm2, list
- [ ] Start/stop works for individual and all watchers
- [ ] Status output in table, json, and brief formats
- [ ] Signal handling (SIGTERM/SIGINT) for graceful shutdown
- [ ] Prerequisites check reports missing env vars
- [ ] PM2 config has correct paths and env vars
- [ ] All tests pass
- [ ] No modification to existing watcher implementations
- [ ] Logs directory for watcher output exists
