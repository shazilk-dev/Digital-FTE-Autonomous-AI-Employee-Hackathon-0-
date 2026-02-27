"""Approval Watcher: monitors /Approved/ and /Rejected/ for HITL execution."""

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml  # noqa: E402

from scripts.utils.action_executor import ActionExecutor  # noqa: E402
from scripts.utils.dashboard_updater import (  # noqa: E402
    add_activity_log,
    add_error,
    remove_pending_action,
    update_queue_counts,
)
from scripts.utils.vault_helpers import append_json_log, read_frontmatter  # noqa: E402
from scripts.watchers.base_watcher import BaseWatcher  # noqa: E402

_PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _update_frontmatter_fields(file_path: Path, updates: dict) -> None:
    """Update one or more frontmatter fields in a Markdown file atomically."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return

    if not text.startswith("---"):
        return

    end = text.find("\n---", 3)
    if end == -1:
        return

    fm_block = text[3:end].strip()
    try:
        fm = yaml.safe_load(fm_block)
    except yaml.YAMLError:
        fm = {}

    if not isinstance(fm, dict):
        fm = {}

    fm.update(updates)
    new_fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    body_after_dash = text[end + 4:]
    new_content = f"---\n{new_fm_str}---{body_after_dash}"

    tmp_fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        Path(tmp_path).replace(file_path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# ApprovalWatcher
# ---------------------------------------------------------------------------


class ApprovalWatcher(BaseWatcher):
    """
    Monitors /Approved/ and /Rejected/ folders for HITL action files.

    Approved actions → parse, validate, execute, archive to /Done/.
    Rejected actions → log, archive to /Done/.
    Stale pending → flag on Dashboard once per file via frontmatter stale: true.
    """

    def __init__(
        self,
        vault_path: str | Path,
        check_interval: int = 10,
        max_retries: int = 2,
        retry_delay: int = 30,
        expiry_hours: int | None = None,
    ) -> None:
        super().__init__(vault_path, check_interval, "approval", "approval")

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.expiry_hours = (
            expiry_hours
            if expiry_hours is not None
            else int(os.getenv("HITL_EXPIRY_HOURS", "24"))
        )

        self.executor = ActionExecutor(self.vault_path)

        # Ensure required directories exist
        (self.vault_path / "Approved").mkdir(parents=True, exist_ok=True)
        (self.vault_path / "Rejected").mkdir(parents=True, exist_ok=True)
        (self.vault_path / "Done").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # scan_directories override
    # ------------------------------------------------------------------

    @property
    def scan_directories(self) -> list[Path]:
        """Override to scan Approved and Rejected instead of Needs_Action."""
        return [
            self.vault_path / "Approved",
            self.vault_path / "Rejected",
        ]

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list[dict]:
        """
        Scan both /Approved/ and /Rejected/ for ACTION_*.md files.

        Returns list of item dicts sorted by priority (critical first),
        then by received/created timestamp (oldest first).

        In DRY_RUN mode: generates sample files and returns them.
        """
        if self.is_dry_run:
            return self._generate_dry_run_data()

        items: list[dict] = []

        for scan_dir in self.scan_directories:
            if not scan_dir.is_dir():
                continue

            folder_name = scan_dir.name
            item_type = (
                "approval_execution"
                if folder_name == "Approved"
                else "approval_rejection"
            )

            for file_path in scan_dir.glob("ACTION_*.md"):
                fm = read_frontmatter(file_path)
                stat = file_path.stat()
                created = datetime.fromtimestamp(
                    stat.st_ctime, tz=timezone.utc
                ).isoformat()

                item: dict = {
                    "id": file_path.name,
                    "path": file_path,
                    "folder": folder_name,
                    "type": item_type,
                    "source": fm.get("target", "unknown"),
                    "subject": fm.get("action_type", "unknown"),
                    "priority": fm.get("priority", "medium"),
                    "received": fm.get("received", created),
                    "requires_approval": False,
                    "content": "",
                }
                # Overlay frontmatter fields without overwriting computed ones
                for k, v in fm.items():
                    if k not in item:
                        item[k] = v

                items.append(item)

        items.sort(
            key=lambda x: (
                _PRIORITY_ORDER.get(str(x.get("priority", "low")), 3),
                str(x.get("received", "")),
            )
        )
        return items

    def create_action_file(self, item: dict) -> Path:
        """
        Override: Instead of creating an action file, PROCESS the approved/rejected item.

        Dispatches based on item["folder"]:
        - "Approved" → self._handle_approval(item)
        - "Rejected" → self._handle_rejection(item)

        Returns the final path of the processed file.
        """
        folder = item.get("folder", "")
        if folder == "Approved":
            return self._handle_approval(item)
        return self._handle_rejection(item)

    # ------------------------------------------------------------------
    # Approval and rejection handlers
    # ------------------------------------------------------------------

    def _handle_approval(self, item: dict) -> Path:
        """
        Handle an approved action.

        Flow:
        1. Parse (non-retriable on failure — stays in /Approved/)
        2. Validate (non-retriable on failure — stays in /Approved/)
        3. Warn if expired (but still execute)
        4. Execute with retry logic
        5. Success: update status, move to Done, log, update dashboard
        6. Exhausted retries: keep in /Approved/, flag on dashboard, log error
        """
        file_path: Path = item["path"]

        # Phase 1: Parse — permanent failure, no retry
        try:
            parsed = self.executor.parse_approval_file(file_path)
        except Exception as exc:
            self.logger.error(
                "Failed to parse approval file %s: %s", file_path.name, exc
            )
            self._try_update_frontmatter(file_path, {"status": "parse_failed"})
            self._try_add_dashboard_error(
                "approval_watcher",
                f"Parse failed: {file_path.name} — {exc}",
            )
            self._log_hitl_action(
                action_type="hitl_execution",
                actor="approval_watcher",
                source_file=file_path,
                action=item.get("action_type", "unknown"),
                target=item.get("target", str(file_path.name)),
                result="failure",
                error=str(exc),
            )
            return file_path  # Keep in /Approved/

        action_type = parsed["action_type"]
        target = parsed["target"]

        # Phase 2: Validate — permanent failure, no retry
        errors = self.executor.validate_action(parsed)
        if errors:
            error_msg = "; ".join(errors)
            self.logger.error(
                "Validation failed for %s: %s", file_path.name, error_msg
            )
            self._try_update_frontmatter(file_path, {"status": "validation_failed"})
            self._try_add_dashboard_error(
                "approval_watcher",
                f"Validation failed: {file_path.name} — {error_msg}",
            )
            self._log_hitl_action(
                action_type="hitl_execution",
                actor="approval_watcher",
                source_file=file_path,
                action=action_type,
                target=target,
                result="failure",
                error=error_msg,
            )
            return file_path  # Keep in /Approved/

        # Warn if expired — log only, still execute per spec
        if parsed.get("is_expired"):
            self.logger.warning(
                "Approval file is expired (executing anyway): %s", file_path.name
            )

        # Phase 3: Execute with retry logic
        last_result: dict = {}
        for attempt in range(self.max_retries + 1):
            last_result = self.executor.execute(file_path)
            if last_result["success"]:
                break
            if attempt < self.max_retries:
                self.logger.warning(
                    "Execution failed (attempt %d/%d) for %s: %s",
                    attempt + 1,
                    self.max_retries + 1,
                    file_path.name,
                    last_result.get("error"),
                )
                time.sleep(self.retry_delay)

        if last_result.get("success"):
            # Success path
            self._try_update_frontmatter(file_path, {"status": "executed"})
            done_path = self._move_to_done(file_path)
            self._log_hitl_action(
                action_type="hitl_execution",
                actor="approval_watcher",
                source_file=done_path,
                action=action_type,
                target=target,
                result="success",
            )
            self._try_update_dashboard(
                activity_action=f"Executed: {action_type}",
                activity_details=f"Target: {target}",
                activity_result="success",
                remove_pending_subject=target,
            )
            self.logger.info(
                "Approved action executed: %s → Done", file_path.name
            )
            return done_path

        # Exhausted retries — keep file in /Approved/, flag for manual intervention
        error_msg = last_result.get("error", "Execution failed")
        self._try_update_frontmatter(
            file_path,
            {"status": "execution_failed", "error": error_msg},
        )
        self._log_hitl_action(
            action_type="hitl_execution",
            actor="approval_watcher",
            source_file=file_path,
            action=action_type,
            target=target,
            result="failure",
            error=error_msg,
        )
        self._try_add_dashboard_error(
            "approval_watcher",
            f"Action failed — manual intervention needed: {file_path.name}",
        )
        self.logger.error(
            "Execution exhausted retries for %s: %s", file_path.name, error_msg
        )
        return file_path  # Keep in /Approved/

    def _handle_rejection(self, item: dict) -> Path:
        """
        Handle a rejected action.

        Flow: update status → move to Done → log → update dashboard
        """
        file_path: Path = item["path"]
        action_type = item.get("action_type", str(item.get("subject", "unknown")))
        target = item.get("target", str(item.get("source", "unknown")))

        self._try_update_frontmatter(file_path, {"status": "rejected"})
        done_path = self._move_to_done(file_path)

        self._log_hitl_action(
            action_type="hitl_rejection",
            actor="human",
            source_file=done_path,
            action=action_type,
            target=target,
            result="rejected",
        )
        self._try_update_dashboard(
            activity_action=f"Rejected: {action_type}",
            activity_details=f"Target: {target}",
            activity_result="rejected",
            remove_pending_subject=target,
        )
        self.logger.info("Rejection archived: %s", file_path.name)
        return done_path

    # ------------------------------------------------------------------
    # Stale approval checker
    # ------------------------------------------------------------------

    def check_stale_approvals(self) -> list[Path]:
        """
        Scan /Pending_Approval/ for files older than expiry_hours.

        For each stale file NOT already flagged (stale: true in frontmatter):
        1. Write stale: true to frontmatter FIRST — prevents Dashboard spam on next cycle
        2. Add a single Dashboard error entry
        3. Log a warning

        Files already flagged are still included in the return list.
        Does NOT auto-reject stale files — they stay for human action.
        """
        pending_dir = self.vault_path / "Pending_Approval"
        if not pending_dir.is_dir():
            return []

        stale: list[Path] = []
        now = datetime.now(tz=timezone.utc)
        expiry_seconds = self.expiry_hours * 3600

        for file_path in pending_dir.rglob("*.md"):
            if file_path.name == ".gitkeep":
                continue

            fm = read_frontmatter(file_path)

            # Already flagged — add to list but skip Dashboard (prevents spam)
            if fm.get("stale") is True:
                stale.append(file_path)
                continue

            # Use mtime for age calculation (settable in tests via os.utime)
            stat = file_path.stat()
            file_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            age_seconds = (now - file_time).total_seconds()

            if age_seconds >= expiry_seconds:
                action_type = fm.get("action_type", "unknown")
                target = fm.get("target", file_path.name)
                hours_waiting = int(age_seconds // 3600)

                # Set stale flag FIRST — prevents re-adding Dashboard error next cycle
                try:
                    _update_frontmatter_fields(file_path, {"stale": True})
                except OSError as exc:
                    self.logger.warning(
                        "Could not set stale flag on %s: %s", file_path.name, exc
                    )

                self._try_add_dashboard_error(
                    "approval_watcher",
                    (
                        f"Stale approval: {action_type} for {target} "
                        f"(waiting {hours_waiting}h)"
                    ),
                )
                self.logger.warning(
                    "Stale approval flagged: %s (waiting %dh)",
                    file_path.name,
                    hours_waiting,
                )
                stale.append(file_path)

        return stale

    # ------------------------------------------------------------------
    # run override (adds stale checking every 10th cycle)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Override BaseWatcher run loop to add stale checking every 10th cycle."""
        prefix = "[DRY RUN] " if self.is_dry_run else ""
        self.logger.info(
            "%sStarting approval watcher (interval=%ds, dry_run=%s)",
            prefix,
            self.check_interval,
            self.is_dry_run,
        )

        cycle = 0
        try:
            while True:
                try:
                    created = self.run_once()
                    self.logger.info(
                        "%sapproval: processed %d item(s) this cycle",
                        prefix,
                        len(created),
                    )
                except Exception as exc:  # noqa: BLE001
                    self.logger.error(
                        "%sapproval: unhandled error in cycle: %s",
                        prefix,
                        exc,
                        exc_info=True,
                    )

                cycle += 1
                if cycle % 10 == 0:
                    try:
                        stale = self.check_stale_approvals()
                        if stale:
                            self.logger.info(
                                "Stale check: %d stale approval(s)", len(stale)
                            )
                    except Exception as exc:  # noqa: BLE001
                        self.logger.error(
                            "Stale check error: %s", exc, exc_info=True
                        )

                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            self.shutdown()

    # ------------------------------------------------------------------
    # DRY_RUN data generator
    # ------------------------------------------------------------------

    def _generate_dry_run_data(self) -> list[dict]:
        """
        Generate sample data for DRY_RUN mode.

        Creates actual files in /Approved/ and /Rejected/ so the full
        processing pipeline can be exercised.
        """
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")

        # Sample approved send_email action
        approved_file = (
            self.vault_path / "Approved" / f"ACTION_send_email_dry_{timestamp}.md"
        )
        if not approved_file.exists():
            approved_fm = {
                "type": "approval_request",
                "action_type": "send_email",
                "target": "test@example.com",
                "priority": "high",
                "status": "approved",
                "received": datetime.now(tz=timezone.utc).isoformat(),
                "action_payload": {
                    "tool": "send_email",
                    "params": {
                        "to": "test@example.com",
                        "subject": "[DRY RUN] Test Email",
                        "body": "This is a dry-run test email.",
                    },
                },
            }
            fm_str = yaml.dump(approved_fm, default_flow_style=False, allow_unicode=True)
            approved_file.write_text(
                f"---\n{fm_str}---\n\n## Approval Request\n\nDry run test.",
                encoding="utf-8",
            )

        # Sample rejected draft_email action
        rejected_file = (
            self.vault_path / "Rejected" / f"ACTION_draft_email_dry_{timestamp}.md"
        )
        if not rejected_file.exists():
            rejected_fm = {
                "type": "approval_request",
                "action_type": "draft_email",
                "target": "boss@example.com",
                "priority": "medium",
                "status": "rejected",
                "received": datetime.now(tz=timezone.utc).isoformat(),
                "action_payload": {
                    "tool": "draft_email",
                    "params": {
                        "to": "boss@example.com",
                        "subject": "[DRY RUN] Draft Email",
                        "body": "This draft was rejected in dry-run mode.",
                    },
                },
            }
            fm_str = yaml.dump(rejected_fm, default_flow_style=False, allow_unicode=True)
            rejected_file.write_text(
                f"---\n{fm_str}---\n\n## Rejection\n\nDry run test.",
                encoding="utf-8",
            )

        return [
            {
                "id": approved_file.name,
                "path": approved_file,
                "folder": "Approved",
                "type": "approval_execution",
                "source": "test@example.com",
                "subject": "send_email",
                "priority": "high",
                "received": datetime.now(tz=timezone.utc).isoformat(),
                "requires_approval": False,
                "content": "",
                "action_type": "send_email",
                "target": "test@example.com",
            },
            {
                "id": rejected_file.name,
                "path": rejected_file,
                "folder": "Rejected",
                "type": "approval_rejection",
                "source": "boss@example.com",
                "subject": "draft_email",
                "priority": "medium",
                "received": datetime.now(tz=timezone.utc).isoformat(),
                "requires_approval": False,
                "content": "",
                "action_type": "draft_email",
                "target": "boss@example.com",
            },
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _move_to_done(self, file_path: Path) -> Path:
        """Move file to /Done/ atomically, handling name collisions."""
        done_dir = self.vault_path / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)

        candidate = done_dir / file_path.name
        if candidate.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while True:
                candidate = done_dir / f"{stem}_{counter}{suffix}"
                if not candidate.exists():
                    break
                counter += 1

        shutil.copy2(str(file_path), str(candidate))
        file_path.unlink()
        return candidate

    def _try_update_frontmatter(self, file_path: Path, updates: dict) -> None:
        """Update frontmatter fields, logging on failure."""
        try:
            _update_frontmatter_fields(file_path, updates)
        except OSError as exc:
            self.logger.warning(
                "Could not update frontmatter for %s: %s", file_path.name, exc
            )

    def _log_hitl_action(
        self,
        action_type: str,
        actor: str,
        source_file: Path,
        action: str,
        target: str,
        result: str,
        error: str | None = None,
    ) -> None:
        """Append an HITL action entry to the audit log."""
        try:
            rel_path = str(source_file.relative_to(self.vault_path))
        except ValueError:
            rel_path = str(source_file)

        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "action_type": action_type,
            "actor": actor,
            "source_file": rel_path.replace("\\", "/"),
            "action": action,
            "target": target,
            "result": result,
            "error": error,
        }
        try:
            append_json_log(self.logs_path, entry)
        except OSError as exc:
            self.logger.error("Failed to write audit log: %s", exc)

    def _try_update_dashboard(
        self,
        activity_action: str,
        activity_details: str,
        activity_result: str,
        remove_pending_subject: str,
    ) -> None:
        """Update Dashboard — silently skip if Dashboard.md doesn't exist."""
        try:
            add_activity_log(
                self.vault_path,
                action=activity_action,
                details=activity_details,
                result=activity_result,
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            self.logger.debug("Dashboard activity update skipped: %s", exc)

        try:
            remove_pending_action(self.vault_path, remove_pending_subject)
        except (FileNotFoundError, ValueError, OSError) as exc:
            self.logger.debug("Dashboard pending removal skipped: %s", exc)

        try:
            update_queue_counts(self.vault_path)
        except (FileNotFoundError, ValueError, OSError) as exc:
            self.logger.debug("Dashboard queue count update skipped: %s", exc)

    def _try_add_dashboard_error(self, component: str, error: str) -> None:
        """Add error to Dashboard — silently skip if Dashboard.md doesn't exist."""
        try:
            add_error(self.vault_path, component=component, error=error)
        except (FileNotFoundError, ValueError, OSError) as exc:
            self.logger.debug("Dashboard error update skipped: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description="Approval Watcher for AI Employee")
    parser.add_argument("--vault", default=None)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--check-stale",
        action="store_true",
        help="Only check for stale approvals, then exit",
    )
    parser.add_argument("--expiry-hours", type=int, default=24)
    args = parser.parse_args()

    watcher = ApprovalWatcher(
        vault_path=args.vault or os.getenv("VAULT_PATH", "."),
        check_interval=args.interval,
        expiry_hours=args.expiry_hours,
    )

    if args.check_stale:
        stale = watcher.check_stale_approvals()
        print(f"Found {len(stale)} stale approvals")
        sys.exit(0)

    if args.once:
        results = watcher.run_once()
        print(f"Processed {len(results)} items")
    else:
        watcher.run()
