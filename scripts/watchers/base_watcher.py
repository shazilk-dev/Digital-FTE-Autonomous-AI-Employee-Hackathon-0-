"""Abstract base class for all AI Employee watchers."""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from scripts.utils.logging_config import setup_logger
from scripts.utils.vault_helpers import append_json_log, is_dry_run

# Maximum number of processed IDs to retain in the state file.
_STATE_MAX_IDS = 10_000
_STATE_TRIM_TO = 5_000


class BaseWatcher(ABC):
    """
    Abstract base class that all watchers must extend.

    Provides:
    - Directory setup and validation
    - Deduplication via a persisted state file
    - A polling loop (run / run_once)
    - Structured audit logging
    - DRY_RUN awareness
    """

    def __init__(
        self,
        vault_path: str | Path,
        check_interval: int = 120,
        watcher_name: str = "base",
        subdomain: str = "general",
    ) -> None:
        """
        Initialise the watcher.

        Parameters
        ----------
        vault_path:
            Root path to the Obsidian vault.
        check_interval:
            Seconds between polling cycles.  Minimum enforced: 30.
        watcher_name:
            Used for logging and state-file naming.
        subdomain:
            Sub-folder under /Needs_Action/ (e.g. "email", "whatsapp").
        """
        self.vault_path: Path = Path(vault_path)
        if not self.vault_path.exists() or not self.vault_path.is_dir():
            raise ValueError(
                f"vault_path does not exist or is not a directory: {self.vault_path}"
            )

        self.check_interval: int = max(30, check_interval)
        self.watcher_name: str = watcher_name

        # Derived paths
        self.needs_action_path: Path = self.vault_path / "Needs_Action" / subdomain
        self.needs_action_path.mkdir(parents=True, exist_ok=True)

        self.logs_path: Path = self.vault_path / "Logs"
        self.logs_path.mkdir(parents=True, exist_ok=True)

        # DRY_RUN flag
        self.is_dry_run: bool = is_dry_run()

        # Logger
        self.logger: logging.Logger = setup_logger(watcher_name)

        # Processed-IDs state
        self._state_file: Path = (
            self.vault_path / ".state" / f"{watcher_name}_processed.json"
        )
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._processed_ids: list[str] = []
        self._load_state()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def check_for_updates(self) -> list[dict]:
        """
        Poll the external source for new items.

        Returns a list of dicts, each with at minimum:
          - "id": str  (unique identifier for dedup)
          - "type": str  (email, whatsapp, file_drop, etc.)
          - "source": str  (sender, contact, filename)
          - "subject": str  (brief description)
          - "content": str  (body text or preview)
          - "priority": str  (critical|high|medium|low)
          - "received": str  (ISO 8601 timestamp)
          - "requires_approval": bool
        Plus any domain-specific fields.
        """

    @abstractmethod
    def create_action_file(self, item: dict) -> Path:
        """
        Transform a raw item dict into a Markdown file with YAML frontmatter.

        Write to self.needs_action_path.
        Return the Path to the created file.
        Filename format: {TYPE}_{SOURCE}_{TIMESTAMP}.md
        """

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def should_process(self, item_id: str) -> bool:
        """Return True if this item_id has NOT been processed before."""
        return item_id not in self._processed_ids

    def mark_processed(self, item_id: str) -> None:
        """Add item_id to the processed set and persist to the state file."""
        if item_id not in self._processed_ids:
            self._processed_ids.append(item_id)
        # Cap at _STATE_MAX_IDS — drop oldest entries (FIFO)
        if len(self._processed_ids) > _STATE_MAX_IDS:
            self._processed_ids = self._processed_ids[
                len(self._processed_ids) - _STATE_TRIM_TO :
            ]
        self._save_state()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main polling loop.  Runs indefinitely.

        Catches all exceptions per-cycle to prevent crashes.
        Handles KeyboardInterrupt for graceful shutdown.
        """
        prefix = "[DRY RUN] " if self.is_dry_run else ""
        self.logger.info(
            "%sStarting %s watcher (interval=%ds, dry_run=%s)",
            prefix,
            self.watcher_name,
            self.check_interval,
            self.is_dry_run,
        )

        try:
            while True:
                try:
                    created = self.run_once()
                    self.logger.info(
                        "%s%s: processed %d item(s) this cycle",
                        prefix,
                        self.watcher_name,
                        len(created),
                    )
                except Exception as exc:  # noqa: BLE001
                    self.logger.error(
                        "%s%s: unhandled error in cycle: %s",
                        prefix,
                        self.watcher_name,
                        exc,
                        exc_info=True,
                    )
                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            self.shutdown()

    def run_once(self) -> list[Path]:
        """
        Execute one polling cycle.

        Returns list of created file paths.
        Useful for testing without entering the infinite loop.
        """
        prefix = "[DRY RUN] " if self.is_dry_run else ""
        items = self.check_for_updates()
        created: list[Path] = []

        for item in items:
            item_id: str = item["id"]
            if not self.should_process(item_id):
                self.logger.debug(
                    "%s%s: skipping already-processed item %s",
                    prefix,
                    self.watcher_name,
                    item_id,
                )
                continue

            try:
                output_path = self.create_action_file(item)
            except (OSError, PermissionError) as exc:
                self.logger.error(
                    "%s%s: failed to create action file for item %s: %s",
                    prefix,
                    self.watcher_name,
                    item_id,
                    exc,
                )
                continue

            self.mark_processed(item_id)
            self._log_action(item, output_path)
            created.append(output_path)

        return created

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _log_action(self, item: dict, output_path: Path) -> None:
        """Append a structured log entry to /Logs/YYYY-MM-DD.json."""
        prefix = "[DRY RUN] " if self.is_dry_run else ""
        try:
            relative_output = output_path.relative_to(self.vault_path)
        except ValueError:
            relative_output = output_path

        entry: dict = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "action_type": "watcher_detect",
            "actor": self.watcher_name,
            "input_file": None,
            "output_file": str(relative_output).replace("\\", "/"),
            "summary": (
                f"{prefix}New {item.get('type', 'item')} from "
                f"{item.get('source', 'unknown')}: {item.get('subject', '')}"
            ),
            "result": "success",
            "error": None,
        }

        try:
            append_json_log(self.logs_path, entry)
        except OSError as exc:
            self.logger.error(
                "%s%s: failed to write audit log: %s",
                prefix,
                self.watcher_name,
                exc,
            )

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Clean up resources.  Save state.  Log shutdown."""
        self._save_state()
        self.logger.info(
            "%s watcher shutting down gracefully", self.watcher_name
        )

    # ------------------------------------------------------------------
    # State persistence (private)
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load processed IDs from the state file on disk."""
        if not self._state_file.exists():
            self._processed_ids = []
            return
        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._processed_ids = list(data.get("processed_ids", []))
        except (json.JSONDecodeError, OSError) as exc:
            self.logger.warning(
                "%s: state file corrupted, resetting: %s", self.watcher_name, exc
            )
            self._processed_ids = []

    def _save_state(self) -> None:
        """Persist processed IDs to the state file atomically."""
        import tempfile

        data = {
            "processed_ids": self._processed_ids,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
        state_dir = self._state_file.parent
        state_dir.mkdir(parents=True, exist_ok=True)

        import os

        tmp_fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            Path(tmp_path).replace(self._state_file)
        except OSError as exc:
            self.logger.error(
                "%s: failed to save state: %s", self.watcher_name, exc
            )
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
