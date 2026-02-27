# Spec: FileSystem Watcher — Local File Drop Monitor

> **Component:** `scripts/watchers/filesystem_watcher.py`
> **Extends:** `BaseWatcher` from `scripts/watchers/base_watcher.py`
> **Priority:** P1 — Adds local file perception to the AI Employee
> **Tests:** `tests/watchers/test_filesystem_watcher.py`
> **External Dependency:** `watchdog` library (pure Python, no API keys)

## 1. Objective

Monitor the `/Drop/` folder for new files. When a user drops a file (PDF invoice,
CSV report, image, document), the watcher creates a structured `.md` action file
in `/Needs_Action/file/` with metadata about the dropped file. Claude then reasons
about what to do with it.

This is the simplest watcher — no authentication, no external APIs. It validates
that the BaseWatcher pattern works correctly for non-email domains.

## 2. Architecture

```
User drops file into /Drop/
         │
         ▼
┌─────────────────────────┐
│   FileSystemWatcher     │
│  (watchdog Observer)    │
│                         │
│  on_created(event) ─────┼──▶ /Needs_Action/file/{TYPE}_FILE_{name}_{timestamp}.md
│  on_modified(event)     │    (metadata .md with file info)
│                         │
│  Original file stays    │    Original file:
│  in /Drop/ until        │    → Copied to /Needs_Action/file/attachments/
│  Claude processes it    │    → Referenced in the .md frontmatter
└─────────────────────────┘
```

## 3. Two Operating Modes

### 3A. Event-Driven Mode (Default — Live)

Uses `watchdog.Observer` to watch `/Drop/` for filesystem events in real-time.
The `run()` method starts the observer and blocks (with `observer.join()`).

### 3B. Polling Mode (Fallback + DRY_RUN)

Inherits `BaseWatcher.run()` polling loop. Scans `/Drop/` directory for files
not yet in `_processed_ids`. Used when:
- `watchdog` Observer fails (some network drives don't support inotify)
- DRY_RUN mode (generates sample data)
- `--once` flag (single scan)

The watcher should try event-driven first, fall back to polling on error.

## 4. Detailed Requirements

### 4A. Constructor

```python
def __init__(
    self,
    vault_path: str | Path,
    drop_folder: str = "Drop",
    check_interval: int = 30,
    watch_extensions: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
    copy_originals: bool = True,
) -> None:
```

Parameters:
- `drop_folder`: Folder name under vault root to monitor. Default `"Drop"`.
- `check_interval`: For polling fallback mode. Default 30s (local is fast).
- `watch_extensions`: File extensions to process. Default: all common types.
  `[".pdf", ".csv", ".xlsx", ".xls", ".txt", ".md", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".json"]`
  If `None`, accept ALL file extensions.
- `ignore_patterns`: Glob patterns to skip. Default:
  `["*.tmp", "*.bak", "*.swp", ".DS_Store", "Thumbs.db", "~$*", ".gitkeep"]`
- `copy_originals`: If True, copy the original file to `/Needs_Action/file/attachments/`.
  If False, only create the metadata `.md` file (lighter weight).

Constructor MUST:
- Call `super().__init__(vault_path, check_interval, "filesystem", "file")`
- Create `drop_path = vault_path / drop_folder` if not exists
- Create `attachments_path = needs_action_path / "attachments"` if not exists
- Load watch_extensions and ignore_patterns from env vars if not provided:
  `FILESYSTEM_WATCH_EXTENSIONS` (comma-separated)
  `FILESYSTEM_IGNORE_PATTERNS` (comma-separated)

### 4B. `check_for_updates` (Polling Mode)

```python
def check_for_updates(self) -> list[dict]:
```

If DRY_RUN: return `self._generate_dry_run_data()`

If LIVE:
1. Scan `self.drop_path` for files (non-recursive by default)
2. Filter by `watch_extensions` (if set)
3. Filter out `ignore_patterns`
4. For each file, check `should_process(file_path_str)` → skip if seen
5. Build item dict from file metadata
6. Return list of item dicts

Item dict structure:
```python
{
    "id": str(file_path.resolve()),   # Full path as unique ID
    "type": "file_drop",
    "source": file_path.name,          # Original filename
    "subject": f"File dropped: {file_path.name}",
    "content": _extract_preview(file_path),  # First 500 chars for text files
    "received": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
    "priority": _classify_file_priority(file_path),
    "requires_approval": False,
    "file_size": file_path.stat().st_size,
    "file_extension": file_path.suffix.lower(),
    "file_mime_type": _guess_mime_type(file_path),
    "original_path": str(file_path),
}
```

### 4C. `create_action_file`

```python
def create_action_file(self, item: dict) -> Path:
```

1. Generate filename: `FILE_{sanitized_name}_{timestamp}.md`
2. If `copy_originals=True`:
   - Copy original file to `attachments/` subfolder
   - Record the attachment path in frontmatter
3. Write the action `.md` file with frontmatter + body

File content:
```markdown
---
type: file_drop
source: {original_filename}
subject: "File dropped: {original_filename}"
received: {ISO 8601}
priority: {priority}
status: pending
requires_approval: false
file_size: {bytes}
file_extension: {extension}
file_mime_type: {mime_type}
attachment_path: {relative path to copy in attachments/, or null}
original_path: {path in /Drop/}
---

## File Details

- **Filename:** {original_filename}
- **Size:** {human_readable_size}
- **Type:** {mime_type}
- **Dropped:** {timestamp}

## Content Preview

{First 500 characters for text-based files, or "Binary file — no preview available" for images/PDFs}

## Suggested Actions

- [ ] Review file contents
- [ ] Process/categorize the file
- [ ] Forward to relevant party
- [ ] Archive after processing
```

### 4D. Helper Methods

```python
def _extract_preview(self, file_path: Path) -> str:
    """
    Extract text preview for supported types:
    - .txt, .md, .csv, .json: Read first 500 chars
    - .pdf: "PDF document — use PDF reader for content"
    - .xlsx, .xls: "Spreadsheet — use appropriate tool for content"
    - .png, .jpg, .jpeg: "Image file — visual review required"
    - .doc, .docx: "Word document — use appropriate tool for content"
    Returns preview string. Never throw on read failure.
    """

def _classify_file_priority(self, file_path: Path) -> str:
    """
    Priority rules:
    - Filename contains "urgent", "asap", "critical" → "high"
    - Extension is .pdf or .xlsx and filename contains "invoice" → "high"
    - File size > 10MB → "medium" (large files may need attention)
    - Default → "medium"
    """

def _guess_mime_type(self, file_path: Path) -> str:
    """Use mimetypes.guess_type(). Fallback to 'application/octet-stream'."""

def _format_file_size(self, size_bytes: int) -> str:
    """Human-readable: '1.5 MB', '340 KB', '2.1 GB'."""

def _generate_dry_run_data(self) -> list[dict]:
    """
    Return 3 sample items:
    1. A PDF invoice (high priority)
    2. A CSV report (medium priority)
    3. A PNG screenshot (medium priority)
    Use realistic filenames like 'Invoice_January_2026.pdf'.
    """
```

### 4E. Event-Driven Mode (watchdog integration)

```python
class DropFolderHandler(FileSystemEventHandler):
    """
    Watchdog event handler that bridges to the FileSystemWatcher.
    """

    def __init__(self, watcher: "FileSystemWatcher"):
        self.watcher = watcher

    def on_created(self, event):
        """
        Fired when new file created in /Drop/.
        1. Skip directories
        2. Skip ignored patterns
        3. Skip if extension not in watch list
        4. Wait 1 second (file might still be writing)
        5. Check file size is stable (not still copying)
        6. Call watcher.process_single_file(event.src_path)
        """

    def on_modified(self, event):
        """
        Fired when file modified. Only process if not already processed.
        Some OS fire on_modified instead of on_created for move operations.
        """
```

```python
def run_event_driven(self) -> None:
    """
    Start watchdog Observer for real-time monitoring.
    Falls back to polling mode if Observer fails.
    """
    try:
        observer = Observer()
        handler = DropFolderHandler(self)
        observer.schedule(handler, str(self.drop_path), recursive=False)
        observer.start()
        self.logger.info(f"Event-driven mode active on {self.drop_path}")

        while True:
            time.sleep(1)
    except Exception as e:
        self.logger.warning(f"Event-driven mode failed: {e}. Falling back to polling.")
        self.run()  # Fall back to BaseWatcher polling loop

def run(self) -> None:
    """Override: try event-driven first, fall back to polling."""
    if not self.is_dry_run:
        self.run_event_driven()
    else:
        super().run()
```

### 4F. File Stability Check

Before processing a newly detected file, verify it's fully written:

```python
def _wait_for_stable(self, file_path: Path, timeout: int = 10) -> bool:
    """
    Wait until file size stabilizes (not still being copied).
    Check size every 0.5s. If size unchanged for 1s, it's stable.
    Return False if timeout exceeded (file may be locked).
    """
```

### 4G. `__main__` Block

```python
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
```

## 5. Test Requirements

### 5A. Fixtures

```python
@pytest.fixture
def drop_folder(tmp_vault):
    """Create /Drop/ with sample files."""
    drop = tmp_vault / "Drop"
    drop.mkdir(exist_ok=True)
    # Create sample files
    (drop / "Invoice_Jan_2026.pdf").write_bytes(b"%PDF-1.4 fake pdf")
    (drop / "report.csv").write_text("name,amount\nAlice,100\nBob,200")
    (drop / "screenshot.png").write_bytes(b"\x89PNG fake image")
    (drop / ".DS_Store").write_bytes(b"ignored")
    return drop
```

### 5B. Test Cases

- `test_init_creates_drop_folder` — /Drop/ created if missing
- `test_init_creates_attachments_folder` — /Needs_Action/file/attachments/ created
- `test_check_for_updates_finds_files` — detects files in Drop folder
- `test_check_for_updates_filters_extensions` — respects watch_extensions
- `test_check_for_updates_ignores_patterns` — skips .DS_Store, .tmp, .gitkeep
- `test_check_for_updates_skips_directories` — only files, not subdirs
- `test_check_for_updates_dry_run` — returns 3 sample items
- `test_create_action_file_writes_md` — .md file created in Needs_Action/file/
- `test_create_action_file_copies_original` — file copied to attachments/
- `test_create_action_file_no_copy_mode` — original not copied when disabled
- `test_create_action_file_frontmatter_complete` — all fields present
- `test_extract_preview_text_file` — first 500 chars extracted
- `test_extract_preview_binary_file` — "Binary file" message returned
- `test_classify_priority_invoice_pdf` — high priority
- `test_classify_priority_default` — medium priority
- `test_format_file_size` — human readable conversion
- `test_wait_for_stable` — detects file size stabilization
- `test_ignore_gitkeep` — .gitkeep never processed
- `test_run_once_end_to_end` — full cycle creates correct files
- `test_deduplication` — same file not processed twice

## 6. Edge Cases

- **Large files (>100MB):** Still create metadata .md. If `copy_originals=True`, warn in log but still copy. Consider adding a `MAX_COPY_SIZE` env var.
- **File deleted before processing:** Catch `FileNotFoundError`, log, skip.
- **File locked by another process:** Catch `PermissionError`, retry once after 2s, then skip.
- **File still being written:** `_wait_for_stable` handles this. 10s timeout.
- **Symbolic links in /Drop/:** Follow symlinks for reading, but don't copy the symlink itself.
- **Nested folders in /Drop/:** Non-recursive by default. Log a warning if subdirectory detected.
- **Filename encoding issues:** Use `errors='replace'` when reading text files.
- **Empty file (0 bytes):** Create action file with "Empty file" in preview. Set priority to "low".

## 7. Validation Criteria

- [ ] `scripts/watchers/filesystem_watcher.py` extends BaseWatcher
- [ ] Both event-driven (watchdog) and polling modes implemented
- [ ] Fallback from event-driven to polling on error
- [ ] DRY_RUN generates 3 sample files without touching /Drop/
- [ ] File stability check prevents processing incomplete uploads
- [ ] Attachments copied when `copy_originals=True`
- [ ] Correct YAML frontmatter matching CLAUDE.md schema
- [ ] All ignore patterns respected
- [ ] All tests pass
- [ ] `--once` flag works for single scan
- [ ] No modification to Bronze files
