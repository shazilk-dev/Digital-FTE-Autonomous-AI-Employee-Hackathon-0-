"""Unit tests for BaseWatcher abstract base class."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.watchers.base_watcher import BaseWatcher, _STATE_MAX_IDS, _STATE_TRIM_TO


# ---------------------------------------------------------------------------
# Concrete test subclass
# ---------------------------------------------------------------------------

class ConcreteWatcher(BaseWatcher):
    """Minimal concrete subclass for testing."""

    def __init__(self, *args, canned_items=None, fail_create=False, **kwargs):
        self._canned_items: list[dict] = canned_items or []
        self._fail_create: bool = fail_create
        super().__init__(*args, **kwargs)

    def check_for_updates(self) -> list[dict]:
        return list(self._canned_items)

    def create_action_file(self, item: dict) -> Path:
        if self._fail_create:
            raise OSError("disk full")
        filename = f"{item['type']}_{item['source']}_{item['id']}.md"
        out = self.needs_action_path / filename
        out.write_text(f"# {item['subject']}\n", encoding="utf-8")
        return out


def _sample_item(item_id: str = "id-1") -> dict:
    return {
        "id": item_id,
        "type": "email",
        "source": "test@example.com",
        "subject": "Test Subject",
        "content": "Body text",
        "priority": "medium",
        "received": "2026-02-26T10:30:00+00:00",
        "requires_approval": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBaseWatcherInit:
    def test_init_creates_directories(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, subdomain="email", watcher_name="test")
        assert (tmp_vault / "Needs_Action" / "email").is_dir()
        assert (tmp_vault / "Logs").is_dir()
        assert (tmp_vault / ".state").is_dir()

    def test_init_validates_vault_path(self, tmp_path):
        nonexistent = tmp_path / "no_such_dir"
        with pytest.raises(ValueError, match="vault_path"):
            ConcreteWatcher(nonexistent, watcher_name="test")

    def test_init_respects_minimum_interval(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, check_interval=5, watcher_name="test")
        assert w.check_interval == 30

    def test_init_interval_above_minimum_unchanged(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, check_interval=60, watcher_name="test")
        assert w.check_interval == 60


class TestDeduplication:
    def test_should_process_new_item(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, watcher_name="test")
        assert w.should_process("brand-new-id") is True

    def test_should_process_duplicate(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, watcher_name="test")
        w.mark_processed("known-id")
        assert w.should_process("known-id") is False

    def test_mark_processed_persists(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, watcher_name="test")
        w.mark_processed("persisted-id")

        # Re-load from disk
        state_file = tmp_vault / ".state" / "test_processed.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "persisted-id" in data["processed_ids"]

    def test_state_file_cap(self, tmp_vault):
        """When exceeding _STATE_MAX_IDS, oldest entries are dropped."""
        w = ConcreteWatcher(tmp_vault, watcher_name="test")
        # Fill up beyond the cap
        ids = [f"id-{i}" for i in range(_STATE_MAX_IDS + 1)]
        for item_id in ids:
            w._processed_ids.append(item_id)
        # Trigger cap logic via mark_processed with one more
        w.mark_processed("final-id")
        # After appending "final-id" (10002 total) the list is trimmed to the last
        # _STATE_TRIM_TO entries, so length == _STATE_TRIM_TO exactly.
        assert len(w._processed_ids) == _STATE_TRIM_TO
        # Oldest entries should be gone
        assert "id-0" not in w._processed_ids
        assert "final-id" in w._processed_ids


class TestRunOnce:
    def test_run_once_processes_items(self, tmp_vault):
        items = [_sample_item("a"), _sample_item("b")]
        w = ConcreteWatcher(tmp_vault, canned_items=items, watcher_name="test")
        created = w.run_once()
        assert len(created) == 2
        for p in created:
            assert p.exists()

    def test_run_once_skips_duplicates(self, tmp_vault):
        item = _sample_item("dup-id")
        w = ConcreteWatcher(tmp_vault, canned_items=[item], watcher_name="test")
        w.mark_processed("dup-id")
        created = w.run_once()
        assert created == []

    def test_run_once_handles_errors(self, tmp_vault):
        """OSError in create_action_file must not crash run_once."""
        item = _sample_item("err-id")
        w = ConcreteWatcher(
            tmp_vault, canned_items=[item], fail_create=True, watcher_name="test"
        )
        # Should not raise
        created = w.run_once()
        assert created == []
        # Item must NOT be marked processed if create failed
        assert w.should_process("err-id") is True

    def test_run_once_returns_list_of_paths(self, tmp_vault):
        items = [_sample_item("p1"), _sample_item("p2")]
        w = ConcreteWatcher(tmp_vault, canned_items=items, watcher_name="test")
        created = w.run_once()
        assert all(isinstance(p, Path) for p in created)


class TestLogAction:
    def test_log_action_creates_log_file(self, tmp_vault):
        item = _sample_item("log-id")
        w = ConcreteWatcher(tmp_vault, canned_items=[item], watcher_name="logtest")
        w.run_once()

        from datetime import datetime, timezone

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = tmp_vault / "Logs" / f"{today}.json"
        assert log_file.exists()

        entries = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(entries) >= 1
        entry = entries[0]
        assert entry["action_type"] == "watcher_detect"
        assert entry["actor"] == "logtest"
        assert entry["result"] == "success"
        assert entry["error"] is None
        assert "timestamp" in entry
        assert "output_file" in entry


class TestDryRunFlag:
    def test_dry_run_flag_true_by_default(self, tmp_vault):
        with patch.dict("os.environ", {"DRY_RUN": "true"}):
            w = ConcreteWatcher(tmp_vault, watcher_name="test")
            assert w.is_dry_run is True

    def test_dry_run_flag_false(self, tmp_vault):
        with patch.dict("os.environ", {"DRY_RUN": "false"}):
            w = ConcreteWatcher(tmp_vault, watcher_name="test")
            assert w.is_dry_run is False


class TestShutdown:
    def test_shutdown_saves_state(self, tmp_vault):
        w = ConcreteWatcher(tmp_vault, watcher_name="shutdown_test")
        w._processed_ids = ["a", "b", "c"]
        w.shutdown()

        state_file = tmp_vault / ".state" / "shutdown_test_processed.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert set(data["processed_ids"]) == {"a", "b", "c"}


class TestStateFileRecovery:
    def test_corrupted_state_file_resets_to_empty(self, tmp_vault):
        state_dir = tmp_vault / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "corrupt_processed.json"
        state_file.write_text("NOT VALID JSON{{{", encoding="utf-8")

        w = ConcreteWatcher(tmp_vault, watcher_name="corrupt")
        assert w._processed_ids == []
