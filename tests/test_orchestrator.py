"""Tests for scripts/orchestrator.py — lifecycle, main loop, health monitoring."""

import json
import signal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path):
    """Minimal vault structure for orchestrator tests."""
    for folder in ("Needs_Action", "Plans", "Pending_Approval", "Done", "Logs", ".state"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def orch(vault):
    """Orchestrator instance with mocked watcher manager."""
    o = Orchestrator(vault, dry_run=True, check_interval=1)
    mock_manager = MagicMock()
    mock_manager.start_all.return_value = {"gmail": True, "filesystem": True}
    mock_manager.stop_all.return_value = {"gmail": True, "filesystem": True}
    mock_manager.status.return_value = [
        {"name": "gmail", "enabled": True, "running": True, "pid": 1234},
        {"name": "filesystem", "enabled": True, "running": True, "pid": 5678},
    ]
    o.watcher_manager = mock_manager
    return o


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_init_creates_watcher_manager(vault):
    """WatcherManager is initialized on first access."""
    o = Orchestrator(vault, dry_run=True)
    with patch("scripts.watchers.runner.WatcherManager") as MockWM:
        MockWM.return_value = MagicMock()
        _ = o.watcher_manager
    # Accessing watcher_manager doesn't raise


def test_init_dry_run_from_env(vault, monkeypatch):
    """dry_run defaults to DRY_RUN env var."""
    monkeypatch.setenv("DRY_RUN", "false")
    o = Orchestrator(vault)
    assert o.dry_run is False

    monkeypatch.setenv("DRY_RUN", "true")
    o2 = Orchestrator(vault)
    assert o2.dry_run is True


def test_start_launches_watchers(orch):
    """start() calls watcher_manager.start_all()."""
    orch._running = False  # prevent loop from running
    with patch.object(orch, "_update_health"), \
         patch.object(orch, "_shutdown"), \
         patch.object(orch, "_load_state"):
        orch._schedule_registry = []
        # Simulate: set _running=False so loop exits immediately
        original_sleep = __import__("time").sleep

        def stop_loop(*args):
            orch._running = False

        with patch("time.sleep", side_effect=stop_loop):
            orch.start()

    orch.watcher_manager.start_all.assert_called_once_with(dry_run=True)


def test_run_once_executes_single_tick(orch):
    """run_once() performs one tick and returns results."""
    with patch.object(orch, "_tick") as mock_tick, \
         patch.object(orch, "_update_health"), \
         patch.object(orch, "_save_state"), \
         patch.object(orch, "_load_state"):
        orch._schedule_registry = []
        result = orch.run_once()

    mock_tick.assert_called_once()
    assert result["success"] is True
    assert "watchers_started" in result


def test_shutdown_stops_watchers(orch):
    """_shutdown() calls watcher_manager.stop_all()."""
    with patch.object(orch, "_update_health"), \
         patch.object(orch, "_save_state"):
        orch._shutdown()
    orch.watcher_manager.stop_all.assert_called_once()


def test_signal_handler_triggers_shutdown(orch):
    """SIGTERM/SIGINT sets _running=False."""
    orch._running = True
    orch._on_signal(signal.SIGTERM, None)
    assert orch._running is False


# ---------------------------------------------------------------------------
# Main loop — mocked clock
# ---------------------------------------------------------------------------


def test_tick_executes_due_tasks(orch):
    """Due tasks get executed during _tick()."""
    mock_task = MagicMock()
    mock_task.name = "test_task"
    mock_task.trigger_fn = "trigger_done_archive"
    mock_task.requires_claude = False

    with patch("scripts.schedules.get_due_tasks", return_value=[mock_task]) as mock_due, \
         patch("scripts.schedules.trigger_done_archive", return_value={"success": True, "archived_count": 0}) as mock_trigger:
        orch._schedule_registry = [mock_task]
        orch._tick()

    mock_trigger.assert_called_once_with(orch.vault_path, dry_run=True)


def test_tick_skips_not_due_tasks(orch):
    """Tasks that are not due are not executed."""
    with patch("scripts.schedules.get_due_tasks", return_value=[]):
        orch._schedule_registry = []
        orch._tick()
    # No exception = passed


def test_tick_updates_last_run(orch):
    """last_run is updated after task execution."""
    mock_task = MagicMock()
    mock_task.name = "done_archive"
    mock_task.trigger_fn = "trigger_done_archive"
    mock_task.requires_claude = False
    mock_task.last_run = None

    with patch("scripts.schedules.get_due_tasks", return_value=[mock_task]), \
         patch("scripts.schedules.trigger_done_archive", return_value={"success": True, "archived_count": 0}):
        orch._schedule_registry = [mock_task]
        before = datetime.now(timezone.utc)
        orch._tick()

    assert mock_task.last_run is not None
    assert mock_task.last_run >= before


def test_tick_logs_task_failure(orch):
    """Failed task is logged but doesn't crash the loop."""
    mock_task = MagicMock()
    mock_task.name = "failing_task"
    mock_task.trigger_fn = "trigger_done_archive"
    mock_task.requires_claude = False

    with patch("scripts.schedules.get_due_tasks", return_value=[mock_task]), \
         patch("scripts.schedules.trigger_done_archive", side_effect=RuntimeError("boom")):
        orch._schedule_registry = [mock_task]
        # Should not raise
        orch._tick()


def test_tick_checks_watcher_health(orch):
    """Health check is called on every 2nd tick."""
    with patch.object(orch, "_check_watcher_health") as mock_health, \
         patch("scripts.schedules.get_due_tasks", return_value=[]):
        orch._schedule_registry = []
        orch._tick_count = 1  # will become 2 after increment → trigger health
        orch._tick()

    mock_health.assert_called_once()


def test_tick_no_health_check_on_odd_tick(orch):
    """Health check is NOT called on odd ticks."""
    with patch.object(orch, "_check_watcher_health") as mock_health, \
         patch("scripts.schedules.get_due_tasks", return_value=[]):
        orch._schedule_registry = []
        orch._tick_count = 0  # will become 1 after increment → no health check
        orch._tick()

    mock_health.assert_not_called()


# ---------------------------------------------------------------------------
# Health monitoring
# ---------------------------------------------------------------------------


def test_health_check_detects_crashed_watcher(orch):
    """_check_watcher_health identifies down watchers."""
    orch.watcher_manager.status.return_value = [
        {"name": "gmail", "enabled": True, "running": False, "pid": None},
    ]
    with patch("scripts.utils.dashboard_updater.add_error") as mock_error:
        orch._check_watcher_health()
    # Attempted restart
    orch.watcher_manager.start.assert_called_once_with("gmail", dry_run=True)


def test_health_check_restarts_crashed(orch):
    """Auto-restart is triggered for crashed watchers."""
    orch.watcher_manager.status.return_value = [
        {"name": "filesystem", "enabled": True, "running": False, "pid": None},
    ]
    with patch("scripts.utils.dashboard_updater.add_error"):
        orch._check_watcher_health()
    orch.watcher_manager.start.assert_called_once_with("filesystem", dry_run=True)


def test_health_check_updates_dashboard(orch):
    """Dashboard error is logged when watcher crashes."""
    orch.watcher_manager.status.return_value = [
        {"name": "gmail", "enabled": True, "running": False, "pid": None},
    ]
    with patch("scripts.utils.dashboard_updater.add_error") as mock_error:
        orch._check_watcher_health()
    mock_error.assert_called_once()
    call_args = mock_error.call_args
    assert "gmail" in call_args[0][1]


def test_health_check_mcp_availability(orch, vault):
    """MCP file existence check updates system health."""
    # Create one MCP file to simulate availability
    mcp_dir = vault / "mcp-servers" / "email-mcp" / "src"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "index.ts").write_text("// mock")

    with patch("scripts.utils.dashboard_updater.update_system_health") as mock_health:
        orch._update_health()

    calls = [str(c) for c in mock_health.call_args_list]
    # At least one call for email-mcp with Available status
    health_str = " ".join(calls)
    assert "email-mcp" in health_str


def test_health_check_skips_disabled_watcher(orch):
    """Disabled watchers are not restarted."""
    orch.watcher_manager.status.return_value = [
        {"name": "whatsapp", "enabled": False, "running": False, "pid": None},
    ]
    with patch("scripts.utils.dashboard_updater.add_error") as mock_error:
        orch._check_watcher_health()
    orch.watcher_manager.start.assert_not_called()


def test_health_check_pauses_on_many_restarts(orch):
    """Auto-restart pauses if >5 restarts in 10 minutes."""
    import time as _time
    now = _time.time()
    orch._watcher_restart_times = [now - 30 * i for i in range(5)]  # 5 recent restarts

    orch.watcher_manager.status.return_value = [
        {"name": "gmail", "enabled": True, "running": False, "pid": None},
    ]
    with patch("scripts.utils.dashboard_updater.add_error") as mock_error:
        orch._check_watcher_health()

    # Should NOT restart since restart limit reached
    orch.watcher_manager.start.assert_not_called()
    # Should log error
    mock_error.assert_called()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def test_save_state_persists_last_run(orch):
    """State file is written with last_run timestamps."""
    mock_task = MagicMock()
    mock_task.name = "test_task"
    mock_task.last_run = datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc)
    orch._schedule_registry = [mock_task]
    orch._tick_count = 5

    orch._save_state()

    state_file = orch.vault_path / ".state" / "orchestrator_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["tick_count"] == 5
    assert "test_task" in data["schedule_last_run"]


def test_load_state_restores_last_run(orch):
    """State is restored on startup."""
    state_data = {
        "tick_count": 42,
        "watcher_restart_counts": {"gmail": 2},
        "schedule_last_run": {"morning_triage": "2026-02-23T08:00:00+00:00"},
        "start_time": None,
    }
    state_file = orch.vault_path / ".state" / "orchestrator_state.json"
    state_file.write_text(json.dumps(state_data))

    # Set up registry with a task matching the state
    mock_task = MagicMock()
    mock_task.name = "morning_triage"
    mock_task.last_run = None
    orch._schedule_registry = [mock_task]

    orch._load_state()

    assert orch._tick_count == 42
    assert orch._watcher_restart_counts == {"gmail": 2}
    assert mock_task.last_run is not None


def test_missing_state_file_handled(orch):
    """Fresh start works when no state file exists."""
    state_file = orch.vault_path / ".state" / "orchestrator_state.json"
    assert not state_file.exists()

    orch._schedule_registry = []
    # Should not raise
    orch._load_state()
    assert orch._tick_count == 0


def test_save_state_on_shutdown(orch):
    """State is saved during graceful shutdown."""
    with patch.object(orch, "_update_health"), \
         patch.object(orch, "_save_state") as mock_save:
        orch._shutdown()
    mock_save.assert_called_once()
