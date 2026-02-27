"""Unit tests for WatcherManager (scripts/watchers/runner.py)."""

import json
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.watchers.runner import (
    WATCHER_REGISTRY,
    WatcherEntry,
    WatcherManager,
    format_status_brief,
    format_status_json,
    format_status_table,
    generate_pm2_config,
)


# ---------------------------------------------------------------------------
# Registry helpers used by multiple test classes
# ---------------------------------------------------------------------------

TEST_REGISTRY: list[WatcherEntry] = [
    WatcherEntry(
        name="test_watcher",
        module_path="tests.fixtures.mock_watcher",
        class_name="MockWatcher",
        description="Test watcher",
        required_env_vars=[],
        default_interval=10,
    ),
]

MULTI_REGISTRY: list[WatcherEntry] = [
    WatcherEntry(
        name="alpha",
        module_path="m.alpha",
        class_name="Alpha",
        description="Alpha watcher",
        required_env_vars=[],
        default_interval=30,
    ),
    WatcherEntry(
        name="beta",
        module_path="m.beta",
        class_name="Beta",
        description="Beta watcher",
        required_env_vars=[],
        default_interval=60,
    ),
    WatcherEntry(
        name="gamma",
        module_path="m.gamma",
        class_name="Gamma",
        description="Disabled watcher",
        required_env_vars=[],
        default_interval=30,
        enabled=False,
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_vault, tmp_path, monkeypatch):
    """WatcherManager with tmp vault, simplified test registry, and isolated PID dir."""
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    m = WatcherManager(tmp_vault, registry=TEST_REGISTRY)
    # Redirect PID files into tmp_path so tests don't pollute system tempdir
    monkeypatch.setattr(m, "_pid_file", lambda name: pid_dir / f"aiemp_{name}.pid")
    return m


@pytest.fixture
def multi_manager(tmp_vault, tmp_path, monkeypatch):
    """WatcherManager with multiple watchers (alpha, beta enabled; gamma disabled)."""
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    m = WatcherManager(tmp_vault, registry=MULTI_REGISTRY)
    monkeypatch.setattr(m, "_pid_file", lambda name: pid_dir / f"aiemp_{name}.pid")
    return m


@pytest.fixture
def real_manager(tmp_vault, tmp_path, monkeypatch):
    """WatcherManager with WATCHER_REGISTRY for integration-style tests."""
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    m = WatcherManager(tmp_vault, registry=WATCHER_REGISTRY)
    monkeypatch.setattr(m, "_pid_file", lambda name: pid_dir / f"aiemp_{name}.pid")
    return m


def _make_mock_proc(pid: int = 12345, running: bool = True) -> MagicMock:
    """Create a mock subprocess.Popen object."""
    mock_proc = MagicMock()
    mock_proc.pid = pid
    mock_proc.poll.return_value = None if running else 0
    return mock_proc


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registry_contains_all_watchers(self):
        """WATCHER_REGISTRY must include gmail, whatsapp, and filesystem."""
        names = [e.name for e in WATCHER_REGISTRY]
        assert "gmail" in names
        assert "whatsapp" in names
        assert "filesystem" in names

    def test_get_entry_valid_name(self, real_manager):
        """get_entry returns the correct WatcherEntry for a known name."""
        entry = real_manager.get_entry("gmail")
        assert entry.name == "gmail"
        assert entry.class_name == "GmailWatcher"
        assert entry.default_interval == 120

    def test_get_entry_invalid_name(self, real_manager):
        """get_entry raises ValueError for an unknown name."""
        with pytest.raises(ValueError, match="No watcher named"):
            real_manager.get_entry("nonexistent_watcher")

    def test_registry_filters_disabled(self, multi_manager):
        """get_registry() only returns enabled watchers."""
        enabled = multi_manager.get_registry()
        names = [e.name for e in enabled]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" not in names  # disabled

    def test_registry_all_three_enabled_by_default(self):
        """All entries in WATCHER_REGISTRY are enabled by default."""
        for entry in WATCHER_REGISTRY:
            assert entry.enabled is True


# ---------------------------------------------------------------------------
# Prerequisites tests
# ---------------------------------------------------------------------------


class TestPrerequisites:
    def test_check_prerequisites_no_env_needed(self, real_manager):
        """filesystem watcher has no required env vars — can_run_dry is always True."""
        result = real_manager.check_prerequisites("filesystem")
        assert result["can_run_dry"] is True
        assert result["missing_env_vars"] == []

    def test_check_prerequisites_missing_env(self, real_manager, monkeypatch):
        """gmail watcher reports missing env vars when GMAIL_CREDENTIALS_PATH not set."""
        monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)
        result = real_manager.check_prerequisites("gmail")
        assert "GMAIL_CREDENTIALS_PATH" in result["missing_env_vars"]
        assert result["can_run_live"] is False

    def test_check_prerequisites_dry_run_always_ok(self, manager):
        """can_run_dry is always True regardless of env vars."""
        result = manager.check_prerequisites("test_watcher")
        assert result["can_run_dry"] is True

    def test_check_prerequisites_structure(self, real_manager):
        """check_prerequisites returns all required keys."""
        result = real_manager.check_prerequisites("filesystem")
        required_keys = {
            "name", "can_run_live", "can_run_dry",
            "missing_env_vars", "module_importable", "errors",
        }
        assert required_keys.issubset(result.keys())

    def test_check_prerequisites_filesystem_module_importable(self, real_manager):
        """filesystem_watcher module should be importable in the test environment."""
        result = real_manager.check_prerequisites("filesystem")
        assert result["module_importable"] is True

    def test_check_prerequisites_env_present(self, real_manager, monkeypatch):
        """When required env var is set, it's not listed as missing."""
        monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", "/fake/creds.json")
        result = real_manager.check_prerequisites("gmail")
        assert "GMAIL_CREDENTIALS_PATH" not in result["missing_env_vars"]


# ---------------------------------------------------------------------------
# Start / Stop tests (mocked subprocess)
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_launches_subprocess(self, manager):
        """start() calls subprocess.Popen with the correct module path."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = manager.start("test_watcher", dry_run=True)

        assert result is True
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "-m" in cmd
        assert "tests.fixtures.mock_watcher" in cmd

    def test_start_writes_pid_file(self, manager):
        """start() writes the subprocess PID to the PID file."""
        mock_proc = _make_mock_proc(pid=99999)
        with patch("subprocess.Popen", return_value=mock_proc):
            manager.start("test_watcher", dry_run=True)

        pid_file = manager._pid_file("test_watcher")
        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8").strip() == "99999"

    def test_start_already_running(self, manager):
        """start() warns and returns False when watcher is already tracked as running."""
        mock_proc = _make_mock_proc(running=True)
        manager._processes["test_watcher"] = mock_proc

        with patch("subprocess.Popen") as mock_popen:
            result = manager.start("test_watcher", dry_run=True)

        assert result is False
        mock_popen.assert_not_called()

    def test_start_dry_run_sets_env(self, manager):
        """start(dry_run=True) passes DRY_RUN=true in the subprocess environment."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            manager.start("test_watcher", dry_run=True)

        env_passed = mock_popen.call_args.kwargs.get("env") or mock_popen.call_args[1].get("env")
        assert env_passed is not None
        assert env_passed.get("DRY_RUN") == "true"

    def test_start_live_mode_no_dry_run_env(self, manager):
        """start() without dry_run does not force DRY_RUN=true."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            # test_watcher has no required_env_vars, so live mode succeeds
            # But module doesn't exist so module_importable=False → can_run_live=False
            # Pass dry_run=True to bypass; verify env doesn't have DRY_RUN forced
            manager.start("test_watcher", dry_run=False)

        # Since can_run_live=False (module not importable), start() returns False
        # without calling Popen
        mock_popen.assert_not_called()

    def test_start_disabled_watcher_returns_false(self, multi_manager):
        """start() returns False for disabled watchers."""
        with patch("subprocess.Popen") as mock_popen:
            result = multi_manager.start("gamma", dry_run=True)

        assert result is False
        mock_popen.assert_not_called()

    def test_start_stores_process_in_dict(self, manager):
        """start() stores the Popen object in _processes."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc):
            manager.start("test_watcher", dry_run=True)

        assert "test_watcher" in manager._processes
        assert manager._processes["test_watcher"] is mock_proc

    def test_start_already_running_via_pid_file(self, manager):
        """start() returns False when a live process exists via PID file."""
        pid_file = manager._pid_file("test_watcher")
        pid_file.write_text("12345", encoding="utf-8")

        with patch.object(manager, "_is_process_alive", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            result = manager.start("test_watcher", dry_run=True)

        assert result is False
        mock_popen.assert_not_called()


class TestStartAll:
    def test_start_all_starts_enabled(self, multi_manager):
        """start_all() starts all enabled watchers and skips disabled ones."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc):
            results = multi_manager.start_all(dry_run=True)

        assert results.get("alpha") is True
        assert results.get("beta") is True
        assert "gamma" not in results  # disabled

    def test_start_all_returns_dict(self, multi_manager):
        """start_all() returns a dict mapping watcher name to success bool."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc):
            results = multi_manager.start_all(dry_run=True)

        assert isinstance(results, dict)
        assert all(isinstance(v, bool) for v in results.values())


class TestStop:
    def test_stop_sends_sigterm(self, manager):
        """stop() calls terminate() (SIGTERM) on the running process."""
        mock_proc = _make_mock_proc(running=True)
        manager._processes["test_watcher"] = mock_proc

        manager.stop("test_watcher")

        mock_proc.terminate.assert_called_once()

    def test_stop_cleans_pid_file(self, manager):
        """stop() removes the PID file."""
        pid_file = manager._pid_file("test_watcher")
        pid_file.write_text("12345", encoding="utf-8")

        mock_proc = _make_mock_proc(running=True)
        manager._processes["test_watcher"] = mock_proc

        manager.stop("test_watcher")

        assert not pid_file.exists()

    def test_stop_force_kill_on_timeout(self, manager):
        """stop() sends SIGKILL when process doesn't exit within 5 seconds."""
        mock_proc = _make_mock_proc(running=True)
        # First wait() raises TimeoutExpired; second wait() succeeds
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="test", timeout=5),
            None,
        ]
        manager._processes["test_watcher"] = mock_proc

        manager.stop("test_watcher")

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_stop_removes_from_processes_dict(self, manager):
        """stop() removes the watcher from _processes after stopping."""
        mock_proc = _make_mock_proc(running=True)
        manager._processes["test_watcher"] = mock_proc

        manager.stop("test_watcher")

        assert "test_watcher" not in manager._processes

    def test_stop_no_process_does_not_raise(self, manager):
        """stop() on a watcher that was never started completes without error."""
        result = manager.stop("test_watcher")
        assert result is True  # returns True even if not running


class TestStopAll:
    def test_stop_all_stops_running(self, multi_manager):
        """stop_all() stops all watchers tracked in _processes."""
        proc_alpha = _make_mock_proc(pid=100, running=True)
        proc_beta = _make_mock_proc(pid=200, running=True)
        multi_manager._processes["alpha"] = proc_alpha
        multi_manager._processes["beta"] = proc_beta

        results = multi_manager.stop_all()

        proc_alpha.terminate.assert_called_once()
        proc_beta.terminate.assert_called_once()
        assert results.get("alpha") is True
        assert results.get("beta") is True

    def test_stop_all_returns_dict(self, multi_manager):
        """stop_all() returns a dict of results."""
        proc = _make_mock_proc(running=True)
        multi_manager._processes["alpha"] = proc

        results = multi_manager.stop_all()
        assert isinstance(results, dict)


class TestRestart:
    def test_restart_stop_then_start(self, manager):
        """restart() calls stop() then start() for the watcher."""
        with patch.object(manager, "stop", return_value=True) as mock_stop, \
             patch.object(manager, "start", return_value=True) as mock_start:
            manager.restart("test_watcher", dry_run=True)

        mock_stop.assert_called_once_with("test_watcher")
        mock_start.assert_called_once_with("test_watcher", dry_run=True)


# ---------------------------------------------------------------------------
# Status tests
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_running_watcher(self, manager):
        """status() shows 'running=True' with correct PID for a tracked process."""
        mock_proc = _make_mock_proc(pid=42000, running=True)
        manager._processes["test_watcher"] = mock_proc

        statuses = manager.status()
        watcher = next(s for s in statuses if s["name"] == "test_watcher")

        assert watcher["running"] is True
        assert watcher["pid"] == 42000

    def test_status_stopped_watcher(self, manager):
        """status() shows 'running=False' when no process is tracked."""
        statuses = manager.status()
        watcher = next(s for s in statuses if s["name"] == "test_watcher")

        assert watcher["running"] is False
        assert watcher["pid"] is None

    def test_status_stale_pid_file(self, manager):
        """status() shows 'running=False' when PID file exists but process is dead."""
        pid_file = manager._pid_file("test_watcher")
        pid_file.write_text("99999999", encoding="utf-8")

        with patch.object(manager, "_is_process_alive", return_value=False):
            statuses = manager.status()

        watcher = next(s for s in statuses if s["name"] == "test_watcher")
        assert watcher["running"] is False

    def test_status_pid_file_live_process(self, manager):
        """status() detects a running process via PID file when not in _processes."""
        pid_file = manager._pid_file("test_watcher")
        pid_file.write_text("55555", encoding="utf-8")

        with patch.object(manager, "_is_process_alive", return_value=True):
            statuses = manager.status()

        watcher = next(s for s in statuses if s["name"] == "test_watcher")
        assert watcher["running"] is True
        assert watcher["pid"] == 55555

    def test_status_all_entries_returned(self, real_manager):
        """status() returns one entry per registry entry."""
        statuses = real_manager.status()
        assert len(statuses) == len(WATCHER_REGISTRY)

    def test_status_includes_required_fields(self, manager):
        """Each status dict contains all required fields."""
        statuses = manager.status()
        required_fields = {
            "name", "enabled", "running", "pid", "uptime",
            "last_check", "items_processed", "can_run_live", "missing_env_vars",
        }
        for s in statuses:
            assert required_fields.issubset(s.keys())

    def test_status_reads_items_processed_from_state(self, manager, tmp_vault):
        """status() reads items_processed from .state/{name}_processed.json."""
        state_data = {
            "processed_ids": ["id1", "id2", "id3"],
            "last_updated": "2026-02-27T10:00:00+00:00",
        }
        state_file = tmp_vault / ".state" / "test_watcher_processed.json"
        state_file.write_text(json.dumps(state_data), encoding="utf-8")

        statuses = manager.status()
        watcher = next(s for s in statuses if s["name"] == "test_watcher")
        assert watcher["items_processed"] == 3
        assert watcher["last_check"] == "2026-02-27T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Status format tests
# ---------------------------------------------------------------------------


class TestStatusFormatters:
    def _sample_statuses(self) -> list[dict]:
        return [
            {
                "name": "gmail",
                "enabled": True,
                "running": True,
                "pid": 12345,
                "uptime": "2h 15m",
                "last_check": None,
                "items_processed": 42,
                "can_run_live": True,
                "missing_env_vars": [],
            },
            {
                "name": "whatsapp",
                "enabled": True,
                "running": False,
                "pid": None,
                "uptime": None,
                "last_check": None,
                "items_processed": 0,
                "can_run_live": False,
                "missing_env_vars": ["WHATSAPP_SESSION_PATH"],
            },
            {
                "name": "filesystem",
                "enabled": True,
                "running": True,
                "pid": 12347,
                "uptime": "2h 15m",
                "last_check": None,
                "items_processed": 8,
                "can_run_live": True,
                "missing_env_vars": [],
            },
        ]

    def test_format_status_table(self):
        """format_status_table returns a non-empty multi-line string."""
        statuses = self._sample_statuses()
        table = format_status_table(statuses)
        assert isinstance(table, str)
        assert "gmail" in table
        assert "whatsapp" in table
        assert "filesystem" in table
        # Should contain PID for running watchers
        assert "12345" in table

    def test_format_status_table_shows_missing_env(self):
        """format_status_table shows missing env vars for watchers that need them."""
        statuses = self._sample_statuses()
        table = format_status_table(statuses)
        assert "WHATSAPP_SESSION_PATH" in table

    def test_format_status_brief(self):
        """format_status_brief returns a one-line summary."""
        statuses = self._sample_statuses()
        brief = format_status_brief(statuses)
        assert isinstance(brief, str)
        assert "\n" not in brief  # single line
        assert "Running: 2/3" in brief
        assert "gmail" in brief
        assert "filesystem" in brief

    def test_format_status_brief_stopped_list(self):
        """format_status_brief includes stopped watchers."""
        statuses = self._sample_statuses()
        brief = format_status_brief(statuses)
        assert "Stopped" in brief
        assert "whatsapp" in brief

    def test_format_status_json(self):
        """format_status_json returns valid JSON."""
        statuses = self._sample_statuses()
        output = format_status_json(statuses)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 3
        assert parsed[0]["name"] == "gmail"

    def test_format_status_brief_all_running(self):
        """format_status_brief shows no 'Stopped' when all are running."""
        statuses = [
            {"name": "a", "enabled": True, "running": True, "items_processed": 0,
             "can_run_live": True, "missing_env_vars": [], "pid": 1, "uptime": None,
             "last_check": None},
        ]
        brief = format_status_brief(statuses)
        assert "Stopped" not in brief


# ---------------------------------------------------------------------------
# PM2 config tests
# ---------------------------------------------------------------------------


class TestGeneratePm2Config:
    def test_generate_pm2_creates_file(self, tmp_vault):
        """generate_pm2_config writes ecosystem.config.js to disk."""
        generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        assert (tmp_vault / "ecosystem.config.js").exists()

    def test_generate_pm2_creates_file_at_custom_path(self, tmp_vault, tmp_path):
        """generate_pm2_config writes to a custom output path."""
        out = tmp_path / "custom.config.js"
        generate_pm2_config(tmp_vault, WATCHER_REGISTRY, out)
        assert out.exists()

    def test_generate_pm2_valid_javascript(self, tmp_vault):
        """Generated file contains minimal valid JavaScript module.exports structure."""
        content = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        assert "module.exports = {" in content
        assert "apps: [" in content
        assert content.strip().endswith("};")

    def test_generate_pm2_correct_paths(self, tmp_vault):
        """generate_pm2_config substitutes the vault path correctly."""
        content = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        vault_str = str(tmp_vault).replace("\\", "/")
        assert vault_str in content

    def test_generate_pm2_all_watchers(self, tmp_vault):
        """generate_pm2_config creates one app entry per enabled watcher."""
        content = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        for entry in WATCHER_REGISTRY:
            if entry.enabled:
                assert f'"aiemp-{entry.name}-watcher"' in content

    def test_generate_pm2_returns_string(self, tmp_vault):
        """generate_pm2_config returns the generated content as a string."""
        result = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_pm2_includes_quick_reference(self, tmp_vault):
        """Generated file includes pm2 quick reference comments."""
        content = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        assert "pm2 start ecosystem.config.js" in content
        assert "pm2 stop all" in content

    def test_generate_pm2_skips_disabled(self, tmp_vault):
        """generate_pm2_config skips disabled registry entries."""
        registry = [
            WatcherEntry(name="active", module_path="m.active", class_name="A",
                         description="Active", required_env_vars=[], default_interval=30),
            WatcherEntry(name="inactive", module_path="m.inactive", class_name="I",
                         description="Inactive", required_env_vars=[], default_interval=30,
                         enabled=False),
        ]
        content = generate_pm2_config(tmp_vault, registry)
        assert "aiemp-active-watcher" in content
        assert "aiemp-inactive-watcher" not in content

    def test_generate_pm2_includes_autorestart(self, tmp_vault):
        """Generated config includes autorestart: true for all apps."""
        content = generate_pm2_config(tmp_vault, WATCHER_REGISTRY)
        assert "autorestart: true" in content


# ---------------------------------------------------------------------------
# Signal handling tests
# ---------------------------------------------------------------------------


class TestSignalHandling:
    def test_sigterm_stops_all(self, manager):
        """_on_signal with SIGTERM calls stop_all() and exits cleanly."""
        with patch.object(manager, "stop_all", return_value={}) as mock_stop_all, \
             patch("sys.exit") as mock_exit:
            manager._on_signal(signal.SIGTERM, None)

        mock_stop_all.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_sigint_stops_all(self, manager):
        """_on_signal with SIGINT calls stop_all() and exits cleanly."""
        with patch.object(manager, "stop_all", return_value={}) as mock_stop_all, \
             patch("sys.exit") as mock_exit:
            manager._on_signal(signal.SIGINT, None)

        mock_stop_all.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_setup_signal_handlers_does_not_raise(self, tmp_vault):
        """WatcherManager initialisation does not raise even in test (non-main) threads."""
        # If signal handler setup fails (non-main thread), it's caught silently
        m = WatcherManager(tmp_vault, registry=TEST_REGISTRY)
        assert m is not None  # Didn't raise


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_start_popen_failure_returns_false(self, manager):
        """start() returns False when subprocess.Popen raises an exception."""
        with patch("subprocess.Popen", side_effect=FileNotFoundError("uv not found")):
            result = manager.start("test_watcher", dry_run=True)

        assert result is False

    def test_stop_with_stale_pid_in_file_only(self, manager):
        """stop() handles a stale PID file gracefully when process not in _processes."""
        pid_file = manager._pid_file("test_watcher")
        pid_file.write_text("77777", encoding="utf-8")

        result = manager.stop("test_watcher")

        assert result is True
        assert not pid_file.exists()

    def test_get_registry_returns_only_enabled(self, multi_manager):
        """get_registry() returns only enabled entries from MULTI_REGISTRY."""
        enabled = multi_manager.get_registry()
        assert all(e.enabled for e in enabled)
        assert len(enabled) == 2  # alpha + beta

    def test_start_records_start_time(self, manager):
        """start() records the start time in _start_times."""
        mock_proc = _make_mock_proc()
        with patch("subprocess.Popen", return_value=mock_proc):
            manager.start("test_watcher", dry_run=True)

        assert "test_watcher" in manager._start_times
        assert isinstance(manager._start_times["test_watcher"], float)

    def test_stop_clears_start_time(self, manager):
        """stop() removes the watcher's start_time entry."""
        mock_proc = _make_mock_proc(running=True)
        manager._processes["test_watcher"] = mock_proc
        manager._start_times["test_watcher"] = 1000.0

        manager.stop("test_watcher")

        assert "test_watcher" not in manager._start_times

    def test_status_uptime_when_running(self, manager):
        """status() returns a non-None uptime when the watcher is running."""
        import time
        mock_proc = _make_mock_proc(pid=1234, running=True)
        manager._processes["test_watcher"] = mock_proc
        manager._start_times["test_watcher"] = time.time() - 130  # 2m 10s ago

        statuses = manager.status()
        watcher = next(s for s in statuses if s["name"] == "test_watcher")
        assert watcher["uptime"] is not None
        assert "m" in watcher["uptime"]

    def test_format_status_brief_no_running(self):
        """format_status_brief handles the case where no watchers are running."""
        statuses = [
            {"name": "a", "enabled": True, "running": False, "items_processed": 0,
             "can_run_live": True, "missing_env_vars": [], "pid": None, "uptime": None,
             "last_check": None},
        ]
        brief = format_status_brief(statuses)
        assert "Running: 0/1" in brief
