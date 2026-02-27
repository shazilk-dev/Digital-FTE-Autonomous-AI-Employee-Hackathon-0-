# Spec: Vault Processor & Dashboard Updater

> **Components:**
> - `scripts/utils/vault_processor.py` — File scanning, moving, counting across vault folders
> - `scripts/utils/dashboard_updater.py` — Safe, section-targeted Dashboard.md modifications
> **Priority:** P0 — Claude's skill needs these to operate on the vault programmatically
> **Tests:** `tests/utils/test_vault_processor.py`, `tests/utils/test_dashboard_updater.py`
> **Depends On:** `scripts/utils/vault_helpers.py` (from Phase B2)

## 1. Objective

Create two utilities that give Claude Code (and future orchestration scripts) the ability to:
1. **Vault Processor:** Scan folders, list pending items, move files between pipeline stages, count queue depths
2. **Dashboard Updater:** Safely modify specific sections of Dashboard.md without corrupting the file or losing data

These are the "hands" that Claude's skills use via Bash tool calls:
```bash
# Example: Claude's skill calls these during email triage
uv run python -m scripts.utils.vault_processor list-pending email
uv run python -m scripts.utils.vault_processor move-to-done Needs_Action/email/EMAIL_xyz.md
uv run python -m scripts.utils.dashboard_updater add-activity "email_triage" "Triaged email from John: Invoice Request" "success"
uv run python -m scripts.utils.dashboard_updater update-counts
```

## 2. Vault Processor: `scripts/utils/vault_processor.py`

### 2A. Core Functions

```python
def list_pending(
    vault_path: Path,
    subdomain: str | None = None
) -> list[dict]:
    """
    List all pending items in /Needs_Action/.

    Args:
        vault_path: Root of the vault
        subdomain: Optional filter — "email", "whatsapp", "file", "social".
                   If None, scan all subdomains.

    Returns:
        List of dicts with keys:
        - "path": relative path from vault root
        - "filename": just the filename
        - "subdomain": which subfolder
        - "frontmatter": parsed YAML frontmatter dict
        - "created": file creation timestamp (ISO 8601)

    Sort by: priority (critical > high > medium > low), then by received timestamp (oldest first)
    Skip non-.md files. Skip .gitkeep.
    """

def list_folder(
    vault_path: Path,
    folder: str
) -> list[dict]:
    """
    Generic folder listing. Works for any vault folder.
    Returns same structure as list_pending.
    folder: relative path like "Plans" or "Pending_Approval"
    """

def move_file(
    vault_path: Path,
    source: str | Path,
    destination_folder: str
) -> Path:
    """
    Move a file from its current location to a destination folder.

    Args:
        source: Relative path from vault root (e.g., "Needs_Action/email/EMAIL_xyz.md")
        destination_folder: Target folder name (e.g., "Done", "Plans", "Rejected")

    Returns:
        New Path of the moved file

    Rules:
    - Preserve original filename
    - If file already exists in destination, append _1, _2, etc.
    - Update the file's frontmatter "status" field to reflect new stage:
      - Done → status: done
      - Rejected → status: rejected
      - Plans → status: in_progress
      - Pending_Approval → status: pending_approval
    - Log the move to /Logs/ via append_json_log
    - Atomic operation: copy first, then delete source (never lose data)
    """

def get_queue_counts(vault_path: Path) -> dict[str, int]:
    """
    Count .md files (excluding .gitkeep) in each pipeline folder.

    Returns:
        {
            "Needs_Action": 5,
            "Plans": 2,
            "Pending_Approval": 1,
            "In_Progress": 0,
            "Done_today": 3,  # Only files modified today
        }
    """

def archive_done(
    vault_path: Path,
    older_than_days: int = 7
) -> int:
    """
    Move files from /Done/ to /Done/archive/ if older than threshold.
    Returns count of archived files.
    """
```

### 2B. CLI Interface

The module should be callable as a CLI for Claude's Bash tool:

```python
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Vault Processor CLI")
    subparsers = parser.add_subparsers(dest="command")

    # list-pending
    lp = subparsers.add_parser("list-pending")
    lp.add_argument("--subdomain", default=None)
    lp.add_argument("--format", choices=["json", "table", "brief"], default="brief")

    # list-folder
    lf = subparsers.add_parser("list-folder")
    lf.add_argument("folder")
    lf.add_argument("--format", choices=["json", "table", "brief"], default="brief")

    # move-to-done
    md = subparsers.add_parser("move-to-done")
    md.add_argument("file_path", help="Relative path to file")

    # move-file
    mf = subparsers.add_parser("move-file")
    mf.add_argument("file_path")
    mf.add_argument("destination")

    # counts
    subparsers.add_parser("counts")

    # archive
    ar = subparsers.add_parser("archive")
    ar.add_argument("--days", type=int, default=7)

    args = parser.parse_args()
    vault_path = Path(os.getenv("VAULT_PATH", "."))
    # ... dispatch to functions, print output
```

Output formats:
- `brief`: One line per item — `[priority] filename — subject`
- `table`: Markdown-style table
- `json`: Full JSON (for programmatic consumption)
- `counts` command outputs: `Needs_Action: 5 | Plans: 2 | Pending_Approval: 1 | Done_today: 3`

## 3. Dashboard Updater: `scripts/utils/dashboard_updater.py`

### 3A. Design Philosophy

Dashboard.md is a structured Markdown file with defined sections. The updater
MUST modify specific sections WITHOUT touching others. This is the most critical
constraint — a bad write corrupts the human's primary interface.

**Strategy: Section-based parsing**

1. Parse Dashboard.md into sections (split on `## ` headings)
2. Identify target section by heading text
3. Find the Markdown table within that section
4. Modify only that table (append row, update cell)
5. Reassemble all sections
6. Write atomically (temp file → rename)

### 3B. Core Functions

```python
def update_timestamp(vault_path: Path) -> None:
    """
    Update the '> **Last Updated:**' line with current UTC timestamp.
    """

def add_activity_log(
    vault_path: Path,
    action: str,
    details: str,
    result: str  # "success" | "failure" | "pending_approval"
) -> None:
    """
    Append a row to the 'Today's Activity Log' table.

    New row format:
    | HH:MM | {action} | {details} | {result} |

    Rules:
    - Insert BEFORE the placeholder row (| — | — | — | — |) if it exists
    - Remove the placeholder row after first real entry
    - If table has >50 rows, trigger rollover (see rollover logic)
    - Always update timestamp after modification
    """

def add_pending_action(
    vault_path: Path,
    item_type: str,
    sender: str,
    subject: str,
    priority: str,
    waiting_since: str
) -> None:
    """
    Add a row to the 'Pending Actions' table.

    Row format:
    | {auto_increment} | {type} | {sender} | {subject} | {priority} | {waiting_since} |
    """

def remove_pending_action(
    vault_path: Path,
    row_identifier: str  # Match by subject or # column
) -> None:
    """Remove a row from Pending Actions (when approved/rejected)."""

def update_queue_counts(vault_path: Path) -> None:
    """
    Refresh the 'Queue Summary' table by scanning the filesystem.

    For each row in the table:
    - Scan the actual folder
    - Count .md files (exclude .gitkeep)
    - Update the Count column

    Special: "Done (today)" counts only files with today's modified date.
    """

def update_system_health(
    vault_path: Path,
    component: str,
    status: str,  # "🟢 Running" | "🟡 Warning" | "🔴 Down" | "— Inactive"
    last_check: str | None = None  # ISO timestamp, defaults to now
) -> None:
    """
    Update a specific component's row in the 'System Health' table.
    Match by component name (case-insensitive).
    """

def add_error(
    vault_path: Path,
    component: str,
    error: str,
    resolution: str = "Pending"
) -> None:
    """
    Add a row to 'Recent Errors' table.
    Auto-clear errors older than 7 days on each call.
    """

def update_weekly_stats(
    vault_path: Path,
    metric: str,
    this_week: int | str
) -> None:
    """
    Update a specific metric in the 'Weekly Stats' table.
    Match by metric name. Only update 'This Week' column.
    'Last Week' column rolls over during weekly reset.
    """

def rollover_activity_log(vault_path: Path) -> None:
    """
    Archive current activity log entries to /Logs/dashboard_archive_YYYY-MM-DD.json.
    Clear the activity log table (keep header + placeholder row).
    Called when table exceeds 50 rows or at daily reset.
    """
```

### 3C. Internal Helpers

```python
def _read_dashboard(vault_path: Path) -> str:
    """Read Dashboard.md content. Raise FileNotFoundError if missing."""

def _write_dashboard(vault_path: Path, content: str) -> None:
    """
    Write Dashboard.md atomically.
    Write to Dashboard.md.tmp first, then rename.
    Validate content starts with '# AI Employee Dashboard' before writing.
    """

def _parse_sections(content: str) -> list[dict]:
    """
    Split Dashboard.md into sections.

    Returns list of:
    {
        "heading": "## Today's Activity Log",
        "content": "| Time | Action | ... |\n| ... |",
        "start_line": 42,
        "end_line": 55
    }
    """

def _find_table_in_section(section_content: str) -> tuple[list[str], list[list[str]]]:
    """
    Parse a Markdown table from section content.
    Returns (headers: list[str], rows: list[list[str]])
    """

def _rebuild_table(headers: list[str], rows: list[list[str]]) -> str:
    """
    Rebuild a Markdown table from headers and rows.
    Includes the |---|---| separator line.
    Pads columns for alignment.
    """

def _reassemble_dashboard(sections: list[dict]) -> str:
    """Rebuild full Dashboard.md from modified sections."""
```

### 3D. CLI Interface

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dashboard Updater CLI")
    subparsers = parser.add_subparsers(dest="command")

    # add-activity
    aa = subparsers.add_parser("add-activity")
    aa.add_argument("action")
    aa.add_argument("details")
    aa.add_argument("result")

    # update-counts
    subparsers.add_parser("update-counts")

    # add-pending
    ap = subparsers.add_parser("add-pending")
    ap.add_argument("--type", required=True)
    ap.add_argument("--from", dest="sender", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--priority", default="medium")

    # update-health
    uh = subparsers.add_parser("update-health")
    uh.add_argument("component")
    uh.add_argument("status")

    # add-error
    ae = subparsers.add_parser("add-error")
    ae.add_argument("component")
    ae.add_argument("error")
    ae.add_argument("--resolution", default="Pending")

    # rollover
    subparsers.add_parser("rollover")

    args = parser.parse_args()
    vault_path = Path(os.getenv("VAULT_PATH", "."))
    # ... dispatch to functions
```

## 4. Test Requirements

### 4A. `tests/utils/test_vault_processor.py`

Fixtures:
- `populated_vault(tmp_vault)` — tmp vault with 5 sample .md files in Needs_Action/email/

Test cases:
- `test_list_pending_returns_all_items` — finds all .md files, skips .gitkeep
- `test_list_pending_filters_by_subdomain` — only returns "email" items
- `test_list_pending_sorted_by_priority` — critical first, then high, medium, low
- `test_list_pending_includes_frontmatter` — parsed YAML in each result
- `test_list_pending_empty_folder` — returns empty list, no error
- `test_list_folder_works_for_any_folder` — Plans, Done, etc.
- `test_move_file_to_done` — file appears in Done, removed from source
- `test_move_file_updates_status` — frontmatter status changed to "done"
- `test_move_file_handles_name_collision` — appends _1 suffix
- `test_move_file_logs_action` — audit log entry created
- `test_move_file_atomic` — source not deleted until copy confirmed
- `test_move_file_nonexistent_raises` — FileNotFoundError
- `test_get_queue_counts` — correct counts for each folder
- `test_get_queue_counts_done_today_filter` — only counts today's files
- `test_archive_done_moves_old_files` — files older than threshold archived
- `test_archive_done_keeps_recent` — recent files stay in Done

### 4B. `tests/utils/test_dashboard_updater.py`

Fixtures:
- `dashboard_file(tmp_vault)` — tmp vault with a fresh Dashboard.md from template

Test cases:
- `test_update_timestamp` — Last Updated line changes
- `test_add_activity_log_appends_row` — new row in table
- `test_add_activity_log_removes_placeholder` — dash row gone after first entry
- `test_add_activity_log_preserves_existing` — previous rows untouched
- `test_add_activity_log_rollover_at_50` — triggers archive when limit hit
- `test_add_pending_action` — row added with auto-increment number
- `test_remove_pending_action` — row removed by subject match
- `test_update_queue_counts_from_filesystem` — counts match actual files
- `test_update_system_health_specific_component` — only that row changes
- `test_add_error_row` — error appears in Recent Errors
- `test_add_error_clears_old` — errors >7 days removed
- `test_update_weekly_stats` — specific metric updated
- `test_write_dashboard_atomic` — temp file used, no partial writes
- `test_write_dashboard_validates_content` — rejects content without expected header
- `test_sections_not_corrupted` — modifying one section doesn't affect others
- `test_concurrent_safety` — two rapid updates don't lose data (sequential, not parallel)

## 5. Edge Cases

- **Dashboard.md doesn't exist:** `_read_dashboard` raises `FileNotFoundError` with message "Run Phase B1 scaffolding first"
- **Dashboard.md has been manually edited:** Parser must be resilient to extra whitespace, missing rows, or added content between sections
- **Table with no data rows (only placeholder):** Handle gracefully — replace placeholder with real data
- **Very long details strings:** Truncate to 80 chars in activity log table (full info in /Logs/)
- **Special characters in email subjects:** Escape pipe `|` characters in table cells (replace with `\|`)
- **Empty Needs_Action folder:** `list_pending` returns `[]`, `get_queue_counts` shows 0. Not an error.
- **Move to folder that doesn't exist:** Create it automatically
- **Frontmatter missing in file:** `list_pending` includes file with empty frontmatter dict, doesn't skip

## 6. Validation Criteria

- [ ] `scripts/utils/vault_processor.py` — all 5 core functions + CLI
- [ ] `scripts/utils/dashboard_updater.py` — all 9 core functions + CLI
- [ ] Both CLIs work via `uv run python -m scripts.utils.vault_processor counts`
- [ ] Both CLIs work via `uv run python -m scripts.utils.dashboard_updater update-counts`
- [ ] All tests pass: `uv run pytest tests/utils/ -v`
- [ ] Dashboard.md is never corrupted (validate after every test)
- [ ] Atomic writes confirmed (no temp files left behind)
- [ ] Audit log entries created for all move operations
- [ ] Pipe characters in table cells are escaped
- [ ] No existing files modified (base_watcher.py, gmail_watcher.py untouched)
