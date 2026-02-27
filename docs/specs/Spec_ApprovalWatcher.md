# Spec: Approval Watcher — HITL Execution Bridge

> **Component:** `scripts/watchers/approval_watcher.py`
> **Extends:** `BaseWatcher` from `scripts/watchers/base_watcher.py`
> **Priority:** P0 — Completes the HITL loop (approval → execution)
> **Tests:** `tests/watchers/test_approval_watcher.py`
> **Depends On:** `action_executor.py`, `vault_processor.py`, `dashboard_updater.py`

## 1. Objective

Monitor two folders:
- `/Approved/` — Human has approved an action → parse and execute it
- `/Rejected/` — Human has rejected an action → log and archive it

Also monitor `/Pending_Approval/` for stale requests (>24hr) and flag them.

This watcher is **unlike other watchers** in a key way: it doesn't create files in
`/Needs_Action/`. Instead, it CONSUMES files from `/Approved/` and `/Rejected/`,
executing or logging them and moving to `/Done/`.

## 2. Architecture

```
/Pending_Approval/{domain}/
  │
  │  Human reviews in Obsidian
  │
  ├──▶ /Approved/ACTION_*.md       ──▶ Approval Watcher
  │                                         │
  │                                    Parse action_payload
  │                                    Validate
  │                                    Execute via Action Executor
  │                                         │
  │                                    ┌────┴────┐
  │                                    ▼         ▼
  │                               Success    Failure
  │                                    │         │
  │                               Move to    Log error
  │                               /Done/     Keep in /Approved/
  │                               Log        Flag on Dashboard
  │                               Update     Retry? (configurable)
  │                               Dashboard
  │
  └──▶ /Rejected/ACTION_*.md       ──▶ Approval Watcher
                                         │
                                    Log rejection reason
                                    Move to /Done/
                                    Update Dashboard
                                    Remove from Pending Actions
```

## 3. Detailed Requirements

### 3A. Constructor

```python
def __init__(
    self,
    vault_path: str | Path,
    check_interval: int = 10,
    max_retries: int = 2,
    retry_delay: int = 30,
    expiry_hours: int = 24,
) -> None:
```

Parameters:
- `check_interval`: 10 seconds (fast — human is waiting for feedback).
- `max_retries`: How many times to retry a failed execution. Default 2.
- `retry_delay`: Seconds between retries. Default 30.
- `expiry_hours`: Hours before a pending approval is flagged stale. Default 24.
  Configurable via `HITL_EXPIRY_HOURS` env var.

Constructor MUST:
- Call `super().__init__(vault_path, check_interval, "approval", "approval")`
  NOTE: This watcher doesn't use `Needs_Action/approval/` — override the scan directories.
- Initialize `ActionExecutor` instance
- Create `/Approved/` and `/Rejected/` dirs if not exist

### 3B. Override: Scan Directories

This watcher scans `/Approved/` and `/Rejected/`, NOT `/Needs_Action/`.

```python
@property
def scan_directories(self) -> list[Path]:
    """Override to scan Approved and Rejected instead of Needs_Action."""
    return [
        self.vault_path / "Approved",
        self.vault_path / "Rejected",
    ]
```

### 3C. `check_for_updates`

```python
def check_for_updates(self) -> list[dict]:
    """
    Scan both /Approved/ and /Rejected/ for action files.

    Returns list of dicts:
    {
        "id": filename,
        "path": full_path,
        "folder": "Approved" or "Rejected",
        "type": "approval_execution" or "approval_rejection",
        ...frontmatter fields
    }

    If DRY_RUN: generate sample approval and rejection items.
    If LIVE: scan filesystem.

    Only process ACTION_*.md files. Skip other files.
    Sort by: priority (critical first), then by created timestamp (oldest first).
    """
```

### 3D. `create_action_file`

This watcher doesn't create files in `/Needs_Action/` — it's a different kind of watcher.
Override to process the item instead:

```python
def create_action_file(self, item: dict) -> Path:
    """
    Override: Instead of creating an action file, PROCESS the approved/rejected item.

    Dispatch based on item["folder"]:
    - "Approved" → self._handle_approval(item)
    - "Rejected" → self._handle_rejection(item)

    Returns the final path (in /Done/) of the processed file.
    """
```

### 3E. Approval Handler

```python
def _handle_approval(self, item: dict) -> Path:
    """
    Handle an approved action.

    Flow:
    1. Parse the approval file using ActionExecutor.parse_approval_file()
    2. Validate the action using ActionExecutor.validate_action()
       - If validation fails → log error, move to error state, return
    3. Check if expired → log warning (but still execute)
    4. Execute the action using ActionExecutor.execute()
    5. If success:
       a. Update frontmatter: status → "executed"
       b. Move file from /Approved/ to /Done/
       c. Update Dashboard: add activity log entry (success)
       d. Update Dashboard: remove from Pending Actions
       e. Update Dashboard: update queue counts
       f. Log to /Logs/
    6. If failure:
       a. If retries remaining → sleep, retry
       b. If retries exhausted:
          - Update frontmatter: status → "execution_failed"
          - Keep file in /Approved/ (don't lose it)
          - Add error to Dashboard
          - Log failure to /Logs/
          - Alert on Dashboard: "Action failed — manual intervention needed"

    Returns: Path to the file's final location
    """
```

### 3F. Rejection Handler

```python
def _handle_rejection(self, item: dict) -> Path:
    """
    Handle a rejected action.

    Flow:
    1. Parse the file frontmatter
    2. Update frontmatter: status → "rejected"
    3. Move file from /Rejected/ to /Done/
    4. Update Dashboard:
       a. Add activity log: "Rejected: {action_type} for {target}"
       b. Remove from Pending Actions
       c. Update queue counts
    5. Log to /Logs/:
       {
           "action_type": "hitl_rejection",
           "actor": "human",
           "source_file": "...",
           "action": action_type,
           "target": target,
           "result": "rejected",
       }

    Returns: Path to the file's final location (in /Done/)
    """
```

### 3G. Stale Approval Checker

```python
def check_stale_approvals(self) -> list[Path]:
    """
    Scan /Pending_Approval/ for files older than expiry_hours.

    Called once per polling cycle (or every N cycles to reduce overhead).

    For each stale file:
    1. Update frontmatter: add "stale: true"
    2. Update Dashboard:
       - Add error: "Stale approval: {action_type} for {target} (waiting {hours}h)"
    3. Log warning

    Returns list of stale file paths.

    DO NOT auto-reject stale files. They stay in Pending_Approval
    until the human acts. The flag is informational only.
    """
```

### 3H. `run` Override

```python
def run(self) -> None:
    """
    Override BaseWatcher run loop to add stale checking.

    Every cycle:
    1. check_for_updates() → process approvals and rejections
    2. Every 10th cycle: check_stale_approvals()
    """
```

### 3I. DRY_RUN Behavior

```python
def _generate_dry_run_data(self) -> list[dict]:
    """
    Generate sample data for DRY_RUN mode:
    
    1. A sample approved send_email action
    2. A sample rejected draft_email action
    
    Creates actual files in /Approved/ and /Rejected/ so the
    full processing pipeline can be exercised.
    """
```

In DRY_RUN mode:
- Sample files are created in /Approved/ and /Rejected/
- Action executor runs in DRY_RUN (simulated execution)
- Files move to /Done/ as normal
- Dashboard and logs update as normal
- Full pipeline is tested without any external action

### 3J. `__main__` Block

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Approval Watcher for AI Employee")
    parser.add_argument("--vault", default=None)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check-stale", action="store_true",
                        help="Only check for stale approvals, then exit")
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
```

## 4. Test Requirements

### 4A. Fixtures

```python
@pytest.fixture
def approved_file(tmp_vault) -> Path:
    """Create a sample approved action file in /Approved/."""
    # Full approval_request frontmatter with action_payload for send_email
    
@pytest.fixture
def rejected_file(tmp_vault) -> Path:
    """Create a sample rejected action file in /Rejected/."""

@pytest.fixture
def stale_pending_file(tmp_vault) -> Path:
    """Create a pending approval file with created timestamp >24hr ago."""

@pytest.fixture
def approval_watcher(tmp_vault) -> ApprovalWatcher:
    """ApprovalWatcher in DRY_RUN mode."""
    os.environ["DRY_RUN"] = "true"
    return ApprovalWatcher(vault_path=tmp_vault)
```

### 4B. Test Cases

**Initialization:**
- `test_init_creates_approved_dir` — /Approved/ exists
- `test_init_creates_rejected_dir` — /Rejected/ exists
- `test_init_scan_directories` — returns Approved and Rejected paths

**Check for updates:**
- `test_check_finds_approved_files` — detects ACTION_*.md in /Approved/
- `test_check_finds_rejected_files` — detects ACTION_*.md in /Rejected/
- `test_check_ignores_non_action_files` — skips random .md files
- `test_check_dry_run_generates_samples` — returns sample items
- `test_check_dedup_processed` — same file not processed twice
- `test_check_sorted_by_priority` — critical first

**Approval handling:**
- `test_handle_approval_executes_action` — ActionExecutor.execute() called
- `test_handle_approval_moves_to_done` — file ends up in /Done/
- `test_handle_approval_updates_dashboard_activity` — activity log entry added
- `test_handle_approval_removes_pending` — removed from Pending Actions table
- `test_handle_approval_logs_to_audit` — /Logs/ entry created
- `test_handle_approval_updates_status_frontmatter` — status = "executed"

**Approval failure handling:**
- `test_handle_approval_retries_on_failure` — retries up to max_retries
- `test_handle_approval_keeps_file_on_exhaust` — stays in /Approved/ after all retries fail
- `test_handle_approval_flags_error_on_dashboard` — error shown
- `test_handle_approval_validation_failure` — invalid file logged, not executed

**Rejection handling:**
- `test_handle_rejection_moves_to_done` — file ends up in /Done/
- `test_handle_rejection_logs_rejection` — audit log with rejected status
- `test_handle_rejection_updates_dashboard` — activity + removes pending
- `test_handle_rejection_updates_status_frontmatter` — status = "rejected"

**Stale checking:**
- `test_stale_detects_old_files` — files >24hr flagged
- `test_stale_ignores_recent_files` — files <24hr not flagged
- `test_stale_adds_dashboard_error` — error entry created
- `test_stale_does_not_auto_reject` — file stays in Pending_Approval
- `test_stale_configurable_expiry` — respects expiry_hours parameter

**Integration:**
- `test_run_once_processes_both_folders` — approvals and rejections in one cycle
- `test_full_cycle_dry_run` — DRY_RUN generates, processes, archives, logs

## 5. Edge Cases

- **Approval file with no action_payload:** Validation fails → log error, flag on Dashboard, don't move
- **Approval file for unimplemented action (linkedin_post):** Executor returns not-implemented → log, flag
- **File appears in both Approved and Rejected (copy instead of move):** Process from Approved first (approval takes precedence), dedup prevents re-processing from Rejected
- **MCP server not running when approval processed:** Execution fails → retry logic kicks in
- **User manually creates file in /Approved/ (not via Pending_Approval):** Still process it if valid format
- **Empty /Approved/ and /Rejected/:** Normal — return empty list, no error
- **Large batch of approvals:** Process all in priority order within one cycle
- **File locked by Obsidian:** Retry after 1 second (Obsidian may have file open)
- **Network down during execution:** Transient error → retry with exponential backoff
- **Dashboard.md locked during update:** Dashboard updater handles atomic writes

## 6. Validation Criteria

- [ ] `scripts/watchers/approval_watcher.py` extends BaseWatcher
- [ ] Monitors both `/Approved/` and `/Rejected/`
- [ ] Approval flow: parse → validate → execute → move to Done → log
- [ ] Rejection flow: parse → log → move to Done
- [ ] Stale detection: flags >24hr pending approvals
- [ ] Retry logic for failed executions (configurable max_retries)
- [ ] Failed executions stay in /Approved/ (not lost)
- [ ] Dashboard updated for all outcomes (approve, reject, fail, stale)
- [ ] Audit log entries for all HITL actions
- [ ] DRY_RUN mode exercises the full pipeline
- [ ] Registered in watcher runner registry
- [ ] `--once` and `--check-stale` flags work
- [ ] All tests pass
- [ ] No modification to existing components
