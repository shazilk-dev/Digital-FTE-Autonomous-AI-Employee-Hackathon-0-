# Spec: GmailWatcher — Gmail Polling & Action File Creation

> **Component:** `scripts/watchers/gmail_watcher.py`, `scripts/utils/gmail_auth.py`
> **Extends:** `BaseWatcher` from `scripts/watchers/base_watcher.py`
> **Priority:** P0 — The first "sense" for the AI Employee
> **Tests:** `tests/watchers/test_gmail_watcher.py`
> **External Dependency:** Google Gmail API v1 via OAuth 2.0

## 1. Objective

Implement a Gmail watcher that polls for unread/important emails, extracts structured data,
and writes Markdown action files to `/Needs_Action/email/`. This is the AI Employee's first
perception layer — it turns raw emails into structured tasks Claude can reason about.

## 2. Architecture

```
GmailWatcher(BaseWatcher)
├── __init__(vault_path, credentials_path, token_path, check_interval, query_filter)
├── check_for_updates() → list[dict]        # Poll Gmail API for matching messages
├── create_action_file(item: dict) → Path    # Write structured .md to Needs_Action/email/
├── _authenticate() → gmail service          # OAuth flow via gmail_auth.py
├── _parse_message(raw_msg: dict) → dict     # Extract headers, body, attachments info
├── _classify_priority(msg: dict) → str      # Determine priority from labels/sender/content
├── _generate_dry_run_data() → list[dict]    # Sample data for DRY_RUN mode
└── shutdown() → None                        # Close API connection
```

## 3. Gmail Auth Helper: `scripts/utils/gmail_auth.py`

### 3A. Purpose

Encapsulate all Google OAuth logic in one place. The watcher should never
deal with auth internals — it just calls `get_gmail_service()`.

### 3B. Functions

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

def get_gmail_service(
    credentials_path: str | Path,
    token_path: str | Path,
    scopes: list[str] | None = None
) -> Resource:
    """
    Authenticate and return a Gmail API service object.

    Flow:
    1. Check if token_path exists and load it
    2. If token is expired but has refresh_token → refresh it
    3. If no valid token → run InstalledAppFlow (opens browser)
    4. Save the (refreshed) token to token_path
    5. Build and return gmail service: build('gmail', 'v1', credentials=creds)

    Raises:
      FileNotFoundError: if credentials_path doesn't exist
      AuthenticationError: if OAuth flow fails (custom exception)
    """

def validate_credentials_file(credentials_path: str | Path) -> bool:
    """
    Check that credentials.json exists and has required fields.
    Return True if valid, False otherwise.
    Don't throw — let caller decide what to do.
    """
```

### 3C. Error Handling

- `FileNotFoundError` for missing `credentials.json` → helpful message about Google Cloud Console setup
- `google.auth.exceptions.RefreshError` → token expired, delete token file, re-auth
- All errors logged with actionable messages (not just stack traces)

## 4. GmailWatcher Implementation

### 4A. Constructor

```python
def __init__(
    self,
    vault_path: str | Path,
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
    check_interval: int = 120,
    query_filter: str = "is:unread is:important"
) -> None:
```

Parameters:
- `credentials_path`: Path to OAuth `credentials.json`. Default from `GMAIL_CREDENTIALS_PATH` env var.
- `token_path`: Path to saved token. Default from `GMAIL_TOKEN_PATH` env var.
- `check_interval`: Polling interval in seconds. Default 120 (Gmail API quota safe).
- `query_filter`: Gmail search query. Default `"is:unread is:important"`.

Constructor MUST:
- Call `super().__init__(vault_path, check_interval, "gmail", "email")`
- Resolve credentials/token paths from env vars if not provided
- If NOT dry run: authenticate via `gmail_auth.get_gmail_service()`
- If dry run: skip authentication, set `self._service = None`
- Store query_filter for use in `check_for_updates`

### 4B. `check_for_updates`

```python
def check_for_updates(self) -> list[dict]:
```

If DRY_RUN: return `self._generate_dry_run_data()`

If LIVE:
1. Call Gmail API: `service.users().messages().list(userId='me', q=self.query_filter, maxResults=20)`
2. Handle pagination: if `nextPageToken` exists, fetch up to 50 total messages max
3. For each message ID:
   a. Check `should_process(message_id)` → skip if already seen
   b. Fetch full message: `service.users().messages().get(userId='me', id=msg_id, format='full')`
   c. Parse with `_parse_message()`
   d. Add to results list
4. Return list of parsed message dicts

API Error Handling:
- `HttpError 429` (rate limit): log warning, return empty list (will retry next cycle)
- `HttpError 401` (auth expired): attempt re-auth once, then raise
- `HttpError 403` (forbidden): log error with setup instructions, return empty
- Any other `HttpError`: log, return empty list
- `ConnectionError` / `TimeoutError`: log, return empty list

### 4C. `_parse_message`

```python
def _parse_message(self, raw_msg: dict) -> dict:
```

Extract from Gmail API message object:
```python
{
    "id": msg["id"],                          # Gmail message ID
    "thread_id": msg["threadId"],             # For conversation grouping
    "type": "email",
    "source": headers["From"],                # Full "Name <email>" string
    "sender_email": extracted_email,           # Just the email part
    "sender_name": extracted_name,             # Just the name part
    "to": headers.get("To", ""),
    "subject": headers.get("Subject", "(No Subject)"),
    "received": _parse_gmail_date(headers["Date"]),  # Convert to ISO 8601
    "content": _extract_body(msg),             # Plain text body (prefer text/plain)
    "snippet": msg.get("snippet", ""),         # Gmail's auto-generated preview
    "labels": msg.get("labelIds", []),
    "has_attachments": _check_attachments(msg),
    "attachment_names": _get_attachment_names(msg),
    "priority": self._classify_priority(...),
    "requires_approval": False,                # Triage doesn't need approval
}
```

Body extraction priority:
1. `text/plain` part → decode from base64
2. `text/html` part → strip HTML tags, decode from base64
3. Fall back to `snippet`
4. Truncate body to 2000 characters (save context window space)

### 4D. `_classify_priority`

```python
def _classify_priority(self, msg: dict) -> str:
```

Rules (evaluated in order, first match wins):
1. Labels contain `IMPORTANT` AND subject contains keywords `["urgent", "asap", "emergency", "critical"]` → `"critical"`
2. Labels contain `IMPORTANT` → `"high"`
3. Labels contain `CATEGORY_PROMOTIONS` or `CATEGORY_SOCIAL` → `"low"`
4. Labels contain `SPAM` → `"low"` (but still create file for audit)
5. Default → `"medium"`

Make keywords configurable via `GMAIL_PRIORITY_KEYWORDS` env var (comma-separated).

### 4E. `create_action_file`

```python
def create_action_file(self, item: dict) -> Path:
```

Generate filename: `EMAIL_{sanitized_sender}_{timestamp}.md`
- Use `sanitize_filename()` from vault_helpers
- Timestamp format: `YYYY-MM-DDTHH-MM-SS` (filesystem safe, no colons)

File content:
```markdown
---
type: email
source: {item["source"]}
sender_email: {item["sender_email"]}
subject: {item["subject"]}
received: {item["received"]}
priority: {item["priority"]}
status: pending
requires_approval: false
message_id: {item["id"]}
thread_id: {item["thread_id"]}
labels: {item["labels"]}
has_attachments: {item["has_attachments"]}
---

## Email Content

{item["content"]}

## Metadata

- **From:** {item["source"]}
- **To:** {item["to"]}
- **Date:** {item["received"]}
- **Attachments:** {item["attachment_names"] or "None"}

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Flag for follow-up
- [ ] Archive after processing
```

Use `vault_helpers.write_action_file()` for atomic write.

### 4F. `_generate_dry_run_data`

```python
def _generate_dry_run_data(self) -> list[dict]:
```

Return 3 sample emails with varying priorities:

1. A "critical" email: urgent client request about overdue invoice
2. A "high" email: meeting request from a colleague
3. A "low" email: newsletter/promotion

Each must have the full dict structure matching `_parse_message` output.
Use realistic but obviously fake data (e.g., `sender@example.com`).
Use unique IDs: `"dry_run_001"`, `"dry_run_002"`, `"dry_run_003"`

### 4G. `__main__` Block

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gmail Watcher for AI Employee")
    parser.add_argument("--vault", default=None, help="Path to vault (default: VAULT_PATH env)")
    parser.add_argument("--interval", type=int, default=120, help="Check interval in seconds")
    parser.add_argument("--query", default="is:unread is:important", help="Gmail search query")
    parser.add_argument("--once", action="store_true", help="Run once and exit (no loop)")
    args = parser.parse_args()

    vault_path = args.vault or os.getenv("VAULT_PATH", ".")

    watcher = GmailWatcher(
        vault_path=vault_path,
        check_interval=args.interval,
        query_filter=args.query,
    )

    if args.once:
        results = watcher.run_once()
        print(f"Processed {len(results)} items")
    else:
        watcher.run()
```

## 5. Test Requirements: `tests/watchers/test_gmail_watcher.py`

### 5A. Fixtures

```python
@pytest.fixture
def mock_gmail_service():
    """Return a mock Gmail API service with canned responses."""

@pytest.fixture
def sample_gmail_message():
    """Return a realistic Gmail API message dict."""

@pytest.fixture
def gmail_watcher(tmp_vault):
    """Create a GmailWatcher in DRY_RUN mode with tmp vault."""
```

### 5B. Test Cases

**Initialization:**
- `test_init_dry_run_skips_auth` — no Gmail API called when DRY_RUN=true
- `test_init_sets_default_query_filter`
- `test_init_reads_env_vars` — credentials/token paths from env

**check_for_updates:**
- `test_check_for_updates_dry_run_returns_samples` — returns 3 sample items
- `test_check_for_updates_live_calls_api` — mock service, verify API call params
- `test_check_for_updates_skips_processed` — items in processed set are filtered
- `test_check_for_updates_handles_rate_limit` — HttpError 429 returns empty list
- `test_check_for_updates_handles_auth_error` — HttpError 401 logged properly
- `test_check_for_updates_handles_connection_error` — returns empty, doesn't crash
- `test_check_for_updates_respects_max_results` — caps at 50 messages

**_parse_message:**
- `test_parse_message_extracts_headers` — From, To, Subject, Date
- `test_parse_message_extracts_plain_text_body` — prefers text/plain
- `test_parse_message_falls_back_to_html` — strips tags when no plain text
- `test_parse_message_truncates_long_body` — body > 2000 chars gets truncated
- `test_parse_message_handles_missing_headers` — defaults for missing fields
- `test_parse_message_detects_attachments` — has_attachments flag + names

**_classify_priority:**
- `test_classify_critical` — IMPORTANT label + urgent keyword
- `test_classify_high` — IMPORTANT label alone
- `test_classify_low_promotion` — CATEGORY_PROMOTIONS label
- `test_classify_medium_default` — no special labels

**create_action_file:**
- `test_create_action_file_writes_valid_md` — file exists on disk
- `test_create_action_file_has_yaml_frontmatter` — parseable YAML with all fields
- `test_create_action_file_correct_filename_format` — matches EMAIL_{source}_{timestamp}.md
- `test_create_action_file_sanitizes_filename` — handles special chars in sender
- `test_create_action_file_suggested_actions_present` — checkbox list exists

**Integration:**
- `test_run_once_end_to_end` — DRY_RUN creates 3 files, all parseable
- `test_run_once_logs_actions` — audit log entries created in Logs/

## 6. Gmail API Quota Considerations

- Default quota: 250 quota units/second, 1 billion/day
- `messages.list`: 5 units per call
- `messages.get`: 5 units per call
- With 20 messages per cycle, every 2 minutes: ~105 units per cycle, ~75,600 per day
- This is well within limits. No special throttling needed at Bronze.
- If approaching limits (Gold/Platinum with multiple accounts): implement exponential backoff

## 7. Package Structure After Implementation

```
scripts/
├── __init__.py
├── watchers/
│   ├── __init__.py
│   ├── base_watcher.py          # From Spec_BaseWatcher
│   └── gmail_watcher.py         # ← NEW
└── utils/
    ├── __init__.py
    ├── logging_config.py        # From Spec_BaseWatcher
    ├── vault_helpers.py         # From Spec_BaseWatcher
    └── gmail_auth.py            # ← NEW

tests/
├── __init__.py
├── conftest.py
├── watchers/
│   ├── __init__.py
│   ├── test_base_watcher.py     # From Spec_BaseWatcher
│   └── test_gmail_watcher.py    # ← NEW
└── utils/
    ├── __init__.py
    └── test_vault_helpers.py    # From Spec_BaseWatcher
```

## 8. Edge Cases

- **No unread emails:** `check_for_updates` returns empty list. This is normal, not an error.
- **Email with no body:** Use snippet as fallback. If snippet also empty, write "(No content)".
- **Extremely long subjects:** `sanitize_filename` truncates. Full subject preserved in frontmatter.
- **Non-UTF-8 email bodies:** Gmail API returns base64-encoded strings. Decode with `errors='replace'`.
- **Multipart emails with nested parts:** Recursively walk MIME parts to find text/plain or text/html.
- **Emails from same sender in same second:** `write_action_file` handles duplicate filenames with `_1`, `_2` suffix.
- **Token refresh fails:** Delete `token.json`, log error with re-auth instructions, skip cycle.
- **First run with no token.json:** OAuth browser flow triggers. This is expected and documented.
- **Running headless (no browser for OAuth):** Provide fallback instructions to generate token on a machine with a browser, then copy `token.json`.

## 9. Validation Criteria

- [ ] `scripts/watchers/gmail_watcher.py` — extends BaseWatcher, all methods implemented
- [ ] `scripts/utils/gmail_auth.py` — `get_gmail_service()` handles full OAuth flow
- [ ] `tests/watchers/test_gmail_watcher.py` — all test cases pass
- [ ] DRY_RUN mode works without any Google credentials
- [ ] DRY_RUN creates exactly 3 sample `.md` files in `Needs_Action/email/`
- [ ] Generated files have valid YAML frontmatter matching CLAUDE.md schema
- [ ] Generated filenames match pattern: `EMAIL_{source}_{timestamp}.md`
- [ ] Audit log entries appear in `Logs/YYYY-MM-DD.json`
- [ ] `--once` flag works for single-cycle execution
- [ ] `argparse` help works: `python scripts/watchers/gmail_watcher.py --help`
- [ ] No hardcoded credentials anywhere
- [ ] All API calls are mockable in tests
- [ ] Body text truncated to 2000 chars
- [ ] Priority classification matches spec rules
