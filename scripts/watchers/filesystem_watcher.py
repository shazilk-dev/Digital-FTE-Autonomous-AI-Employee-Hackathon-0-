"""FileSystem Watcher — monitors /Drop/ folder for new files."""

import fnmatch
import mimetypes
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from scripts.utils.vault_helpers import sanitize_filename, write_action_file
from scripts.watchers.base_watcher import BaseWatcher

_DEFAULT_EXTENSIONS: list[str] = [
    ".pdf", ".csv", ".xlsx", ".xls", ".txt", ".md",
    ".doc", ".docx", ".png", ".jpg", ".jpeg", ".json",
]

_DEFAULT_IGNORE_PATTERNS: list[str] = [
    "*.tmp", "*.bak", "*.swp", ".DS_Store", "Thumbs.db", "~$*", ".gitkeep",
]

_PREVIEW_MAX_CHARS = 500
_LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB


class DropFolderHandler(FileSystemEventHandler):
    """Watchdog event handler that bridges to FileSystemWatcher."""

    def __init__(self, watcher: "FileSystemWatcher") -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event) -> None:
        """Fired when a new file is created in /Drop/."""
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if self.watcher._is_ignored(file_path):
            return
        if not self.watcher._is_watched_extension(file_path):
            return
        # Wait 1 second — file might still be writing
        time.sleep(1)
        if not self.watcher._wait_for_stable(file_path):
            self.watcher.logger.warning(
                "File %s did not stabilize within timeout, skipping", file_path.name
            )
            return
        self.watcher.process_single_file(event.src_path)

    def on_modified(self, event) -> None:
        """Fired when a file is modified. Some OS fire this for move operations."""
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if self.watcher._is_ignored(file_path):
            return
        if not self.watcher._is_watched_extension(file_path):
            return
        item_id = str(file_path.resolve())
        if self.watcher.should_process(item_id):
            self.watcher.process_single_file(event.src_path)


class FileSystemWatcher(BaseWatcher):
    """Watches /Drop/ folder and creates Needs_Action files for dropped files."""

    def __init__(
        self,
        vault_path: str | Path,
        drop_folder: str = "Drop",
        check_interval: int = 30,
        watch_extensions: list[str] | None = None,
        ignore_patterns: list[str] | None = None,
        copy_originals: bool = True,
    ) -> None:
        super().__init__(vault_path, check_interval, "filesystem", "file")

        # Drop folder — create if missing
        self.drop_path: Path = self.vault_path / drop_folder
        self.drop_path.mkdir(parents=True, exist_ok=True)

        # Attachments subfolder
        self.attachments_path: Path = self.needs_action_path / "attachments"
        self.attachments_path.mkdir(parents=True, exist_ok=True)

        self.copy_originals: bool = copy_originals

        # Extensions — env var overrides when parameter is None
        if watch_extensions is None:
            env_ext = os.getenv("FILESYSTEM_WATCH_EXTENSIONS")
            if env_ext:
                self.watch_extensions: list[str] | None = [
                    e.strip() for e in env_ext.split(",") if e.strip()
                ]
            else:
                self.watch_extensions = list(_DEFAULT_EXTENSIONS)
        else:
            self.watch_extensions = watch_extensions

        # Ignore patterns — env var overrides when parameter is None
        if ignore_patterns is None:
            env_pat = os.getenv("FILESYSTEM_IGNORE_PATTERNS")
            if env_pat:
                self.ignore_patterns: list[str] = [
                    p.strip() for p in env_pat.split(",") if p.strip()
                ]
            else:
                self.ignore_patterns = list(_DEFAULT_IGNORE_PATTERNS)
        else:
            self.ignore_patterns = ignore_patterns

    # ------------------------------------------------------------------
    # Abstract interface implementation
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list[dict]:
        """Scan /Drop/ for unprocessed files (polling mode)."""
        if self.is_dry_run:
            return self._generate_dry_run_data()

        items: list[dict] = []
        try:
            entries = list(self.drop_path.iterdir())
        except OSError as exc:
            self.logger.error("Failed to scan drop folder %s: %s", self.drop_path, exc)
            return []

        for entry in entries:
            if entry.is_dir():
                self.logger.warning(
                    "Subdirectory detected in /Drop/ (non-recursive, ignored): %s",
                    entry.name,
                )
                continue
            if self._is_ignored(entry):
                continue
            if not self._is_watched_extension(entry):
                continue
            item_id = str(entry.resolve())
            if not self.should_process(item_id):
                continue
            try:
                item = self._build_item(entry)
                items.append(item)
            except FileNotFoundError:
                self.logger.warning("File disappeared before processing: %s", entry)
            except PermissionError as exc:
                self.logger.warning("Permission error reading %s: %s", entry, exc)

        return items

    def create_action_file(self, item: dict) -> Path:
        """Create a .md action file in /Needs_Action/file/."""
        original_filename = item["source"]
        stem = Path(original_filename).stem
        sanitized = sanitize_filename(stem)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"FILE_{sanitized}_{timestamp}.md"

        # Optionally copy the original file to attachments/
        attachment_rel_path = None
        if self.copy_originals and item.get("original_path"):
            original_path = Path(item["original_path"])
            if original_path.exists():
                dest = self.attachments_path / original_filename
                # Resolve name collisions
                if dest.exists():
                    stem_part = Path(original_filename).stem
                    suffix = Path(original_filename).suffix
                    counter = 1
                    while dest.exists():
                        dest = self.attachments_path / f"{stem_part}_{counter}{suffix}"
                        counter += 1
                try:
                    shutil.copy2(original_path, dest)
                    try:
                        attachment_rel_path = str(
                            dest.relative_to(self.vault_path)
                        ).replace("\\", "/")
                    except ValueError:
                        attachment_rel_path = str(dest)
                except (OSError, PermissionError) as exc:
                    self.logger.warning(
                        "Failed to copy %s to attachments: %s", original_filename, exc
                    )

        frontmatter: dict = {
            "type": "file_drop",
            "source": item["source"],
            "subject": item["subject"],
            "received": item["received"],
            "priority": item["priority"],
            "status": "pending",
            "requires_approval": False,
            "file_size": item["file_size"],
            "file_extension": item["file_extension"],
            "file_mime_type": item["file_mime_type"],
            "attachment_path": attachment_rel_path,
            "original_path": item["original_path"],
        }

        size_str = self._format_file_size(item["file_size"])
        preview = item.get("content", "No preview available.")

        body = (
            f"## File Details\n\n"
            f"- **Filename:** {item['source']}\n"
            f"- **Size:** {size_str}\n"
            f"- **Type:** {item['file_mime_type']}\n"
            f"- **Dropped:** {item['received']}\n\n"
            f"## Content Preview\n\n"
            f"{preview}\n\n"
            f"## Suggested Actions\n\n"
            f"- [ ] Review file contents\n"
            f"- [ ] Process/categorize the file\n"
            f"- [ ] Forward to relevant party\n"
            f"- [ ] Archive after processing\n"
        )

        return write_action_file(self.needs_action_path, filename, frontmatter, body)

    # ------------------------------------------------------------------
    # Single-file processing (used by event-driven DropFolderHandler)
    # ------------------------------------------------------------------

    def process_single_file(self, src_path: str) -> Path | None:
        """Build item and create action file for one path (event-driven mode)."""
        file_path = Path(src_path)
        item_id = str(file_path.resolve())
        if not self.should_process(item_id):
            return None

        try:
            item = self._build_item(file_path)
        except FileNotFoundError:
            self.logger.warning("File gone before processing: %s", file_path)
            return None
        except PermissionError:
            # Retry once after 2 s
            time.sleep(2)
            try:
                item = self._build_item(file_path)
            except (OSError, PermissionError) as exc:
                self.logger.warning("Skipping locked file %s: %s", file_path, exc)
                return None

        try:
            output_path = self.create_action_file(item)
        except (OSError, PermissionError) as exc:
            self.logger.error("Failed to create action file for %s: %s", file_path, exc)
            return None

        self.mark_processed(item_id)
        self._log_action(item, output_path)
        return output_path

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _build_item(self, file_path: Path) -> dict:
        """Build item dict from file metadata. May raise OSError/FileNotFoundError."""
        stat = file_path.stat()
        return {
            "id": str(file_path.resolve()),
            "type": "file_drop",
            "source": file_path.name,
            "subject": f"File dropped: {file_path.name}",
            "content": self._extract_preview(file_path),
            "received": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "priority": self._classify_file_priority(file_path),
            "requires_approval": False,
            "file_size": stat.st_size,
            "file_extension": file_path.suffix.lower(),
            "file_mime_type": self._guess_mime_type(file_path),
            "original_path": str(file_path),
        }

    def _is_ignored(self, file_path: Path) -> bool:
        """Return True if the filename matches any ignore pattern."""
        name = file_path.name
        return any(fnmatch.fnmatch(name, pat) for pat in self.ignore_patterns)

    def _is_watched_extension(self, file_path: Path) -> bool:
        """Return True if extension is in watch list (None = all extensions)."""
        if self.watch_extensions is None:
            return True
        return file_path.suffix.lower() in self.watch_extensions

    def _extract_preview(self, file_path: Path) -> str:
        """Extract text preview for text files; describe binary/unknown files."""
        try:
            if file_path.stat().st_size == 0:
                return "Empty file"
        except OSError:
            return "Could not read file"

        ext = file_path.suffix.lower()
        if ext in (".txt", ".md", ".csv", ".json"):
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                return text[:_PREVIEW_MAX_CHARS]
            except OSError:
                return "Could not read file"
        elif ext == ".pdf":
            return "PDF document — use PDF reader for content"
        elif ext in (".xlsx", ".xls"):
            return "Spreadsheet — use appropriate tool for content"
        elif ext in (".png", ".jpg", ".jpeg"):
            return "Image file — visual review required"
        elif ext in (".doc", ".docx"):
            return "Word document — use appropriate tool for content"
        else:
            return "Binary file — no preview available"

    def _classify_file_priority(self, file_path: Path) -> str:
        """Return 'high', 'medium', or 'low' based on name, extension, and size."""
        try:
            file_size = file_path.stat().st_size
        except OSError:
            return "medium"

        if file_size == 0:
            return "low"

        name_lower = file_path.name.lower()
        ext = file_path.suffix.lower()

        if any(kw in name_lower for kw in ("urgent", "asap", "critical")):
            return "high"

        if ext in (".pdf", ".xlsx") and "invoice" in name_lower:
            return "high"

        return "medium"

    def _guess_mime_type(self, file_path: Path) -> str:
        """Guess MIME type. Fallback: 'application/octet-stream'."""
        mime, _ = mimetypes.guess_type(str(file_path))
        return mime or "application/octet-stream"

    def _format_file_size(self, size_bytes: int) -> str:
        """Return human-readable file size string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def _generate_dry_run_data(self) -> list[dict]:
        """Return 3 realistic sample items without touching /Drop/."""
        now = datetime.now().isoformat()
        return [
            {
                "id": "dry-run-invoice-pdf",
                "type": "file_drop",
                "source": "Invoice_January_2026.pdf",
                "subject": "File dropped: Invoice_January_2026.pdf",
                "content": "PDF document — use PDF reader for content",
                "received": now,
                "priority": "high",
                "requires_approval": False,
                "file_size": 245_760,
                "file_extension": ".pdf",
                "file_mime_type": "application/pdf",
                "original_path": str(self.drop_path / "Invoice_January_2026.pdf"),
            },
            {
                "id": "dry-run-report-csv",
                "type": "file_drop",
                "source": "Q1_Sales_Report_2026.csv",
                "subject": "File dropped: Q1_Sales_Report_2026.csv",
                "content": "date,product,amount\n2026-01-01,Widget A,1500\n2026-01-02,Widget B,2300",
                "received": now,
                "priority": "medium",
                "requires_approval": False,
                "file_size": 4_096,
                "file_extension": ".csv",
                "file_mime_type": "text/csv",
                "original_path": str(self.drop_path / "Q1_Sales_Report_2026.csv"),
            },
            {
                "id": "dry-run-screenshot-png",
                "type": "file_drop",
                "source": "screenshot_dashboard_2026-01.png",
                "subject": "File dropped: screenshot_dashboard_2026-01.png",
                "content": "Image file — visual review required",
                "received": now,
                "priority": "medium",
                "requires_approval": False,
                "file_size": 512_000,
                "file_extension": ".png",
                "file_mime_type": "image/png",
                "original_path": str(self.drop_path / "screenshot_dashboard_2026-01.png"),
            },
        ]

    def _wait_for_stable(self, file_path: Path, timeout: int = 10) -> bool:
        """Return True when file size has been stable for >= 1 second."""
        try:
            prev_size = file_path.stat().st_size
        except OSError:
            return False

        deadline = time.time() + timeout
        last_change = time.time()
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                current_size = file_path.stat().st_size
            except OSError:
                return False
            if current_size != prev_size:
                prev_size = current_size
                last_change = time.time()
            elif time.time() - last_change >= 1.0:
                return True
        return False

    # ------------------------------------------------------------------
    # Event-driven mode
    # ------------------------------------------------------------------

    def run_event_driven(self) -> None:
        """Start watchdog Observer. Falls back to polling on error."""
        try:
            observer = Observer()
            handler = DropFolderHandler(self)
            observer.schedule(handler, str(self.drop_path), recursive=False)
            observer.start()
            self.logger.info("Event-driven mode active on %s", self.drop_path)
            while True:
                time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Event-driven mode failed: %s. Falling back to polling.", exc
            )
            super().run()

    def run(self) -> None:
        """Override BaseWatcher.run: prefer event-driven, fall back to polling."""
        if not self.is_dry_run:
            self.run_event_driven()
        else:
            super().run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FileSystem Watcher for AI Employee")
    parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env)")
    parser.add_argument("--drop", default="Drop", help="Drop folder name (default: Drop)")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval seconds")
    parser.add_argument("--once", action="store_true", help="Single scan and exit")
    parser.add_argument("--no-copy", action="store_true", help="Don't copy originals to attachments")
    parser.add_argument("--polling", action="store_true", help="Force polling mode (no watchdog events)")
    args = parser.parse_args()

    watcher = FileSystemWatcher(
        vault_path=args.vault or os.getenv("VAULT_PATH", "."),
        drop_folder=args.drop,
        check_interval=args.interval,
        copy_originals=not args.no_copy,
    )

    if args.once:
        results = watcher.run_once()
        print(f"Processed {len(results)} files")
    elif args.polling:
        super(FileSystemWatcher, watcher).run()
    else:
        watcher.run()
