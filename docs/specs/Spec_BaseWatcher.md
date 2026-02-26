# Spec: BaseWatcher — Abstract Watcher Foundation

> **Component:** `scripts/watchers/base_watcher.py`
> **Supporting Files:** `scripts/utils/logging_config.py`, `scripts/utils/vault_helpers.py`
> **Priority:** P0 — Every watcher (Gmail, WhatsApp, FileSystem) extends this
> **Tests:** `tests/watchers/test_base_watcher.py`, `tests/utils/test_vault_helpers.py`

## 1. Objective

Create the abstract base class that ALL watchers in the system must extend. This enforces
a consistent interface: every watcher checks for updates, creates action files with YAML
frontmatter, logs its actions, and supports DRY_RUN mode. Also create shared utilities
for logging configuration and vault file operations.

## 2. Architecture

```
BaseWatcher (ABC)
├── __init__(vault_path, check_interval, watcher_name)
├── check_for_updates() → list[dict]        # ABSTRACT - subclass implements
├── create_action_file(item: dict) → Path    # ABSTRACT - subclass implements
├── should_process(item_id: str) → bool      # Dedup check against processed set + state file
├── mark_processed(item_id: str) → None      # Add to processed set + persist to state file
├── run() → None                             # Main polling loop
├── run_once() → list[Path]                  # Single poll cycle (for testing)
├── shutdown() → None                        # Graceful cleanup
└── Properties:
    ├── vault_path: Path
    ├── needs_action_path: Path
    ├── logs_path: Path
    ├── check_interval: int
    ├── is_dry_run: bool
    ├── logger: logging.Logger
    └── _processed_ids: set[str]
```

## 3. Detailed Requirements

### 3A. Constructor: `__init__`

```python
def __init__(
    self,
    vault_path: str | Path,
    check_interval: int = 120,
    watcher_name: str = "base",
    subdomain: str = "general"
) -> None:
```

Parameters:
- `vault_path`: Root path to the Obsidian vault. Convert to `pathlib.Path`.
- `check_interval`: Seconds between polling cycles. Default 120 (2 min). Minimum 30.
- `watcher_name`: Used for logging and state file naming.
- `subdomain`: Subfolder under `/Needs_Action/` (e.g., "email", "whatsapp", "file").

Constructor MUST:
- Validate `vault_path` exists and is a directory
- Create `needs_action_path = vault_path / "Needs_Action" / subdomain` if not exists
- Set `is_dry_run` from `os.getenv("DRY_RUN", "true").lower() == "true"`
- Load processed IDs from state file: `vault_path / ".state" / f"{watcher_name}_processed.json"`
- Initialize logger via `logging_config.setup_logger(watcher_name)`

### 3B. Abstract Methods

```python
@abstractmethod
def check_for_updates(self) -> list[dict]:
    """
    Poll the external source for new items.
    Returns a list of dicts, each with at minimum:
      - "id": str (unique identifier for dedup)
      - "type": str (email, whatsapp, file_drop, etc.)
      - "source": str (sender, contact, filename)
      - "subject": str (brief description)
      - "content": str (body text or preview)
      - "priority": str (critical|high|medium|low)
      - "received": str (ISO 8601 timestamp)
      - "requires_approval": bool
    Plus any domain-specific fields.
    """
    pass

@abstractmethod
def create_action_file(self, item: dict) -> Path:
    """
    Transform raw item dict into a Markdown file with YAML frontmatter.
    Write to self.needs_action_path.
    Return the Path to the created file.
    Filename format: {TYPE}_{SOURCE}_{TIMESTAMP}.md
    """
    pass
```

### 3C. Deduplication: `should_process` and `mark_processed`

```python
def should_process(self, item_id: str) -> bool:
    """Return True if this item_id has NOT been processed before."""
    return item_id not in self._processed_ids

def mark_processed(self, item_id: str) -> None:
    """Add item_id to processed set and persist to state file."""
    self._processed_ids.add(item_id)
    self._save_state()
```

State persistence:
- State file: `{vault_path}/.state/{watcher_name}_processed.json`
- Format: `{"processed_ids": ["id1", "id2", ...], "last_updated": "ISO8601"}`
- Create `.state/` directory if not exists (add to `.gitignore`)
- Cap at 10,000 IDs. When exceeded, drop oldest 5,000 (FIFO).
- Load state on `__init__`, save on every `mark_processed` call.

### 3D. Main Loop: `run`

```python
def run(self) -> None:
    """
    Main polling loop. Runs indefinitely.
    Catches all exceptions per-cycle to prevent crashes.
    """
```

Loop behavior:
1. Log: `"Starting {watcher_name} watcher (interval={check_interval}s, dry_run={is_dry_run})"`
2. Enter `while True` loop:
   a. Call `run_once()` inside a try/except
   b. On success: log number of items processed
   c. On exception: log the full error with traceback, continue
   d. `time.sleep(self.check_interval)`
3. Handle `KeyboardInterrupt` → call `shutdown()` → exit cleanly

### 3E. Single Cycle: `run_once`

```python
def run_once(self) -> list[Path]:
    """
    Execute one polling cycle. Returns list of created file paths.
    Useful for testing without entering the infinite loop.
    """
```

Behavior:
1. Call `check_for_updates()` → get list of items
2. For each item:
   a. Check `should_process(item["id"])` → skip if already processed
   b. Call `create_action_file(item)` → get Path
   c. Call `mark_processed(item["id"])`
   d. Call `_log_action(item, created_path)`
3. Return list of created Paths

### 3F. Audit Logging: `_log_action`

```python
def _log_action(self, item: dict, output_path: Path) -> None:
    """Append a structured log entry to /Logs/YYYY-MM-DD.json"""
```

Log entry format (matches CLAUDE.md schema):
```json
{
  "timestamp": "2026-02-26T10:30:00+05:00",
  "action_type": "watcher_detect",
  "actor": "gmail_watcher",
  "input_file": null,
  "output_file": "Needs_Action/email/EMAIL_john_2026-02-26T10-30-00.md",
  "summary": "New email from john@example.com: Invoice Request",
  "result": "success",
  "error": null
}
```

Implementation:
- Read existing log file (or create empty array)
- Append new entry
- Write back atomically (write to temp, rename)
- File: `{vault_path}/Logs/{YYYY-MM-DD}.json`

### 3G. Graceful Shutdown: `shutdown`

```python
def shutdown(self) -> None:
    """Clean up resources. Save state. Log shutdown."""
```

- Save processed IDs state file
- Log: `"{watcher_name} watcher shutting down gracefully"`
- Subclasses can override to close connections (browser, API clients)

## 4. Supporting Utilities

### 4A. `scripts/utils/logging_config.py`

```python
def setup_logger(name: str, log_level: str | None = None) -> logging.Logger:
    """
    Configure and return a logger.
    - Level from LOG_LEVEL env var (default INFO)
    - Format: "[YYYY-MM-DD HH:MM:SS] [LEVEL] [name] message"
    - Output to stderr (so stdout is clean for piping)
    - Also log to file: {vault_path}/Logs/watcher_{name}.log (rotating, 5MB max, 3 backups)
    """
```

Use `logging.handlers.RotatingFileHandler` for file output.

### 4B. `scripts/utils/vault_helpers.py`

```python
def get_vault_path() -> Path:
    """Return vault path from VAULT_PATH env var. Validate it exists."""

def write_action_file(
    directory: Path,
    filename: str,
    frontmatter: dict,
    body: str
) -> Path:
    """
    Write a Markdown file with YAML frontmatter.
    - Sanitize filename (remove illegal chars, limit length to 200)
    - If file exists, append numeric suffix: _1, _2, etc.
    - Write atomically: temp file → rename
    - Return final Path
    """

def sanitize_filename(raw: str, max_length: int = 200) -> str:
    """
    Remove/replace characters illegal in filenames.
    Replace spaces with underscores. Remove: / \\ : * ? " < > |
    Truncate to max_length.
    """

def append_json_log(log_dir: Path, entry: dict) -> None:
    """
    Append a JSON log entry to /Logs/YYYY-MM-DD.json.
    Create file with empty array if not exists.
    Read → append → write atomically.
    """

def read_frontmatter(file_path: Path) -> dict:
    """
    Read YAML frontmatter from a Markdown file.
    Return the parsed dict. Return empty dict if no frontmatter.
    """

def is_dry_run() -> bool:
    """Check DRY_RUN env var. Default True (safe by default)."""
```

### 4C. `scripts/utils/__init__.py`

```python
from .logging_config import setup_logger
from .vault_helpers import (
    get_vault_path,
    write_action_file,
    sanitize_filename,
    append_json_log,
    read_frontmatter,
    is_dry_run,
)
```

### 4D. `scripts/watchers/__init__.py`

```python
from .base_watcher import BaseWatcher
```

### 4E. `scripts/__init__.py`

Empty file — makes `scripts` a package.

## 5. DRY_RUN Behavior

When `DRY_RUN=true` (the default):
- `check_for_updates()` should return **sample/mock data** (subclass responsibility)
- `create_action_file()` still writes the `.md` file to disk (so you can verify output format)
- All logs should prefix with `[DRY RUN]`
- No external API calls are made

This allows full testing of the pipeline without credentials.

## 6. Package Structure After Implementation

```
scripts/
├── __init__.py
├── watchers/
│   ├── __init__.py
│   └── base_watcher.py
└── utils/
    ├── __init__.py
    ├── logging_config.py
    └── vault_helpers.py

tests/
├── __init__.py
├── conftest.py                  # Shared fixtures (tmp_vault, etc.)
├── watchers/
│   ├── __init__.py
│   └── test_base_watcher.py
└── utils/
    ├── __init__.py
    └── test_vault_helpers.py
```

## 7. Test Requirements

### 7A. `tests/conftest.py` — Shared Fixtures

```python
@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault structure for testing."""
    # Create all required subdirectories
    # Return the tmp_path as vault root
```

### 7B. `tests/watchers/test_base_watcher.py`

Create a `ConcreteWatcher(BaseWatcher)` test subclass that returns canned data.

Test cases:
- `test_init_creates_directories` — verify Needs_Action subdomain dir created
- `test_init_validates_vault_path` — raise ValueError if path doesn't exist
- `test_init_respects_minimum_interval` — interval < 30 gets clamped to 30
- `test_should_process_new_item` — returns True for unseen ID
- `test_should_process_duplicate` — returns False for already-processed ID
- `test_mark_processed_persists` — ID saved to state file on disk
- `test_state_file_cap` — when exceeding 10,000 IDs, oldest are dropped
- `test_run_once_processes_items` — creates files and marks processed
- `test_run_once_skips_duplicates` — doesn't reprocess known IDs
- `test_run_once_handles_errors` — exception in create_action_file doesn't crash
- `test_log_action_creates_log_file` — verify log JSON structure
- `test_dry_run_flag` — respects DRY_RUN env var
- `test_shutdown_saves_state` — state file updated on shutdown

### 7C. `tests/utils/test_vault_helpers.py`

Test cases:
- `test_write_action_file_creates_md` — file exists with frontmatter
- `test_write_action_file_handles_duplicates` — appends _1, _2 suffix
- `test_sanitize_filename_removes_illegal_chars`
- `test_sanitize_filename_truncates_long_names`
- `test_append_json_log_creates_new_file`
- `test_append_json_log_appends_to_existing`
- `test_read_frontmatter_parses_yaml`
- `test_read_frontmatter_no_frontmatter_returns_empty`
- `test_is_dry_run_defaults_true`
- `test_is_dry_run_reads_env`

## 8. Edge Cases

- **Vault path doesn't exist:** Raise `ValueError` with helpful message
- **State file corrupted:** Catch JSON decode error, reset to empty set, log warning
- **Disk full:** Catch `OSError` when writing, log, continue to next cycle
- **Permission denied:** Catch `PermissionError`, log, skip item
- **Extremely long email subjects:** `sanitize_filename` truncates to 200 chars
- **Unicode in filenames:** Handle non-ASCII characters (transliterate or strip)
- **Concurrent watcher instances:** State file uses atomic write (temp+rename) to prevent corruption
- **Clock skew:** Use UTC for all timestamps in logs and frontmatter

## 9. Validation Criteria

- [ ] `scripts/watchers/base_watcher.py` contains `BaseWatcher` as an ABC
- [ ] Both abstract methods are defined with proper signatures and docstrings
- [ ] `should_process` / `mark_processed` work with state persistence
- [ ] `run_once` returns list of Paths
- [ ] `_log_action` writes JSON matching CLAUDE.md schema
- [ ] `scripts/utils/vault_helpers.py` has all 6 functions
- [ ] `scripts/utils/logging_config.py` configures rotating file + stderr handlers
- [ ] All `__init__.py` files exist with proper imports
- [ ] `tests/conftest.py` has `tmp_vault` fixture
- [ ] All tests pass: `uv run pytest tests/ -v`
- [ ] No `os.path` usage anywhere — all `pathlib.Path`
- [ ] No `print()` statements — all `logging`
- [ ] Type hints on every function signature
