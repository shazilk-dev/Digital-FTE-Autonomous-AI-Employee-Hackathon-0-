# Spec: WhatsApp Watcher — Playwright-Based Message Monitor

> **Component:** `scripts/watchers/whatsapp_watcher.py`
> **Extends:** `BaseWatcher` from `scripts/watchers/base_watcher.py`
> **Priority:** P1 — Adds WhatsApp perception channel
> **Tests:** `tests/watchers/test_whatsapp_watcher.py`
> **External Dependency:** Playwright (Chromium), WhatsApp Web session
> **Risk Level:** HIGH — WhatsApp Web automation is fragile and ToS-sensitive

## 1. Objective

Monitor WhatsApp Web for new messages matching configurable keyword filters.
When a relevant message arrives, create a structured `.md` action file in
`/Needs_Action/whatsapp/` for Claude to reason about.

**Critical constraint:** This is a read-only watcher. It NEVER sends messages.
Sending happens via MCP in Phase S3/S5 (with HITL approval).

## 2. Architecture

```
WhatsApp Web (browser)
         │
    Playwright persistent context
    (session saved to disk)
         │
         ▼
┌──────────────────────────────┐
│    WhatsAppWatcher           │
│                              │
│  1. Open WhatsApp Web        │
│  2. Wait for chat list       │
│  3. Scan unread indicators   │
│  4. For matching chats:      │
│     - Open chat              │
│     - Read recent messages   │
│     - Extract text + sender  │
│  5. Create action .md file   │
│                              │
│  Session persists between    │
│  restarts (no re-scan QR)    │
└──────────────────────────────┘
```

## 3. WhatsApp Web Session Management

### 3A. Persistent Browser Context

Playwright's `launch_persistent_context()` saves cookies, localStorage, and
session data to a folder on disk. After the first QR code scan, subsequent
launches skip authentication.

```python
browser = playwright.chromium.launch_persistent_context(
    user_data_dir=self.session_path,
    headless=self.headless,
    viewport={"width": 1280, "height": 720},
    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ...",
)
```

Session path: from `WHATSAPP_SESSION_PATH` env var (default: `./sessions/whatsapp`).

### 3B. First-Time Setup (Manual)

First run requires QR code scan:
1. Run watcher with `--headless=false` (visible browser)
2. WhatsApp Web shows QR code
3. User scans with phone
4. Session saved to disk
5. Subsequent runs: headless, no QR needed

### 3C. Session Health Check

Before each poll cycle, verify session is alive:
- Check if "Chat list" selector is visible within 30s
- If not: session expired → log error, update Dashboard health, skip cycle
- If phone disconnected warning appears → log warning, continue (reconnects automatically)

## 4. Detailed Requirements

### 4A. Constructor

```python
def __init__(
    self,
    vault_path: str | Path,
    session_path: str | Path | None = None,
    check_interval: int = 60,
    keywords: list[str] | None = None,
    headless: bool = True,
    max_messages_per_chat: int = 5,
    monitored_chats: list[str] | None = None,
) -> None:
```

Parameters:
- `session_path`: Playwright user data dir. Default from `WHATSAPP_SESSION_PATH` env.
- `check_interval`: Polling interval. Default 60s. Minimum 30s (WhatsApp rate concerns).
- `keywords`: Keywords to filter messages. Default from `WHATSAPP_KEYWORDS` env:
  `["urgent", "asap", "invoice", "payment", "help", "pricing", "quote", "deadline"]`
  If empty list, capture ALL unread messages (no filter).
- `headless`: Run browser in headless mode. Default True.
- `max_messages_per_chat`: How many recent messages to extract per chat. Default 5.
- `monitored_chats`: Optional list of chat names to exclusively monitor.
  If None, monitor all chats with unread messages.

Constructor MUST:
- Call `super().__init__(vault_path, check_interval, "whatsapp", "whatsapp")`
- Validate session_path exists (or will be created on first launch)
- Store playwright instance as `None` (lazy init in `_ensure_browser()`)
- DO NOT launch browser in constructor (expensive, breaks testing)

### 4B. Browser Lifecycle

```python
def _ensure_browser(self) -> Page:
    """
    Lazy-initialize Playwright browser and return the active page.

    1. If self._page is not None and responsive → return it
    2. Launch persistent context
    3. Navigate to https://web.whatsapp.com
    4. Wait for chat list OR QR code
    5. If QR code visible → log error: "QR scan required. Run with --headless=false"
    6. If chat list visible → return page
    7. On any failure → set self._page = None, raise
    """

def _close_browser(self) -> None:
    """Close browser context gracefully. Save session."""

def shutdown(self) -> None:
    """Override BaseWatcher: close browser on shutdown."""
    self._close_browser()
    super().shutdown()
```

### 4C. `check_for_updates`

```python
def check_for_updates(self) -> list[dict]:
```

If DRY_RUN: return `self._generate_dry_run_data()`

If LIVE:
1. Call `_ensure_browser()` → get page
2. Wait for chat list: `page.wait_for_selector('[role="listitem"]', timeout=30000)`
3. Find unread chats: look for unread badge indicators
4. For each unread chat:
   a. If `monitored_chats` is set and chat name not in list → skip
   b. Click on the chat to open it
   c. Wait for message container to load
   d. Extract last `max_messages_per_chat` messages
   e. Check if any message text matches keywords (case-insensitive)
   f. If match (or keywords is empty) → build item dict
   g. Navigate back to chat list
5. Return list of item dicts

**Selectors (WhatsApp Web — will need maintenance):**

```python
# These selectors are current as of Feb 2026 but may change.
# Store as class constants for easy updates.
SELECTORS = {
    "chat_list": '[role="listitem"]',
    "unread_badge": '[aria-label*="unread"]',
    "chat_name": 'span[title]',
    "message_text": 'span.selectable-text',
    "message_container": '[role="row"]',
    "message_time": '[data-pre-plain-text]',
    "qr_code": '[data-testid="qrcode"]',
    "search_box": '[title="Search input textbox"]',
}
```

**CRITICAL: Selector fragility.** WhatsApp Web updates frequently. Include:
- A `WHATSAPP_SELECTORS_OVERRIDE` env var that accepts a JSON file path
  for custom selectors (so users can fix without code changes)
- Fallback logic: if primary selector fails, try alternatives
- Clear error messages: "Selector not found — WhatsApp Web may have updated"

### 4D. Message Extraction

```python
def _extract_messages_from_chat(self, page: Page, chat_name: str) -> list[dict]:
    """
    Extract recent messages from the currently open chat.

    Returns list of:
    {
        "sender": str,      # Contact name or phone number
        "text": str,         # Message text content
        "time": str,         # Message timestamp (from WhatsApp)
        "is_incoming": bool, # True if received (not sent by us)
    }

    Rules:
    - Only extract incoming messages (is_incoming=True)
    - Skip media-only messages (images/video without text)
    - Skip system messages (security code changed, etc.)
    - Limit to max_messages_per_chat most recent
    - Handle group chats: extract sender name from within message
    """
```

### 4E. Item Dict Structure

```python
{
    "id": f"wa_{chat_name}_{message_hash}",  # Deterministic ID for dedup
    "type": "whatsapp",
    "source": chat_name,                      # Contact or group name
    "sender_phone": phone_or_name,            # Phone number if visible
    "subject": f"WhatsApp from {chat_name}",
    "content": matched_message_text,           # The keyword-matching message
    "context_messages": [                      # Surrounding messages for context
        {"sender": "...", "text": "...", "time": "..."},
    ],
    "received": current_timestamp_iso,
    "priority": _classify_whatsapp_priority(matched_text, chat_name),
    "requires_approval": False,
    "keyword_matched": matched_keyword,        # Which keyword triggered
    "chat_type": "individual" | "group",
    "is_group": bool,
}
```

Message hash for dedup: `hashlib.sha256(f"{chat_name}:{message_text}:{message_time}".encode()).hexdigest()[:12]`

### 4F. `create_action_file`

File content:
```markdown
---
type: whatsapp
source: {chat_name}
sender_phone: {phone_or_name}
subject: "WhatsApp from {chat_name}"
received: {ISO 8601}
priority: {priority}
status: pending
requires_approval: false
keyword_matched: {keyword}
chat_type: {individual|group}
---

## Message

**From:** {chat_name}
**Keyword Matched:** "{keyword}"
**Time:** {message_time}

> {matched_message_text}

## Conversation Context (Last {n} Messages)

{For each context message:}
**{sender}** ({time}): {text}

## Suggested Actions

- [ ] Reply to {chat_name}
- [ ] Forward to relevant party
- [ ] Create task from request
- [ ] Archive — no action needed
```

### 4G. Priority Classification

```python
def _classify_whatsapp_priority(self, text: str, chat_name: str) -> str:
    """
    Rules:
    - Text contains "urgent", "asap", "emergency", "critical" → "critical"
    - Text contains "invoice", "payment", "deadline" → "high"
    - Text contains "help", "pricing", "quote" → "medium"
    - Monitored VIP chat (from WHATSAPP_VIP_CHATS env) → upgrade one level
    - Default → "medium"
    """
```

### 4H. DRY_RUN Data

```python
def _generate_dry_run_data(self) -> list[dict]:
    """
    Return 3 sample WhatsApp messages:
    1. Urgent client request about payment (critical)
    2. Colleague asking about meeting (medium)
    3. Group chat with pricing inquiry (high)
    """
```

### 4I. Rate Limiting & Politeness

```python
# Between chat interactions (clicking, reading)
INTER_CHAT_DELAY = 2.0       # seconds between opening different chats
PAGE_LOAD_TIMEOUT = 30000     # ms to wait for page elements
MESSAGE_READ_DELAY = 1.0      # seconds to "read" messages (human-like)

# Per-cycle limits
MAX_CHATS_PER_CYCLE = 10      # Don't process more than 10 chats per poll
```

These delays reduce the risk of WhatsApp detecting automation.

### 4J. `__main__` Block

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WhatsApp Watcher for AI Employee")
    parser.add_argument("--vault", default=None)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--headless", default="true", choices=["true", "false"])
    parser.add_argument("--keywords", default=None, help="Comma-separated keywords")
    parser.add_argument("--setup", action="store_true",
                        help="Run in visible mode for QR code setup, then exit")
    args = parser.parse_args()

    # --setup mode: visible browser, wait for QR scan, then exit
    if args.setup:
        print("Opening WhatsApp Web for QR code setup...")
        print("Scan the QR code with your phone, then press Ctrl+C")
        watcher = WhatsAppWatcher(
            vault_path=args.vault or os.getenv("VAULT_PATH", "."),
            headless=False,
        )
        try:
            watcher._ensure_browser()
            input("Session saved. Press Enter to exit.")
        finally:
            watcher.shutdown()
        sys.exit(0)

    # Normal operation
    watcher = WhatsAppWatcher(
        vault_path=args.vault or os.getenv("VAULT_PATH", "."),
        check_interval=args.interval,
        headless=args.headless == "true",
        keywords=args.keywords.split(",") if args.keywords else None,
    )

    if args.once:
        results = watcher.run_once()
        print(f"Processed {len(results)} messages")
    else:
        watcher.run()
```

## 5. Test Requirements

### 5A. Testing Strategy

Playwright is heavy and requires a browser. Tests should:
- **Mock Playwright entirely** — never launch a real browser in tests
- **Test business logic separately** from browser interaction
- **Use DRY_RUN mode** for integration-level tests

### 5B. Fixtures

```python
@pytest.fixture
def mock_playwright():
    """Mock playwright sync_api with canned page responses."""

@pytest.fixture
def mock_page():
    """Mock Playwright Page with configurable element queries."""

@pytest.fixture
def whatsapp_watcher(tmp_vault):
    """WhatsApp watcher in DRY_RUN mode."""
    os.environ["DRY_RUN"] = "true"
    return WhatsAppWatcher(vault_path=tmp_vault)
```

### 5C. Test Cases

**Initialization:**
- `test_init_dry_run_no_browser_launch` — browser not started
- `test_init_sets_default_keywords` — loaded from env or defaults
- `test_init_creates_session_path` — directory created

**check_for_updates:**
- `test_check_for_updates_dry_run` — returns 3 sample items
- `test_check_for_updates_keyword_matching` — only matching messages returned
- `test_check_for_updates_empty_keywords_captures_all` — no filter when keywords empty
- `test_check_for_updates_respects_max_chats` — caps at MAX_CHATS_PER_CYCLE
- `test_check_for_updates_skips_processed` — deduplication via message hash

**Message extraction (mocked):**
- `test_extract_messages_filters_incoming` — only incoming messages
- `test_extract_messages_skips_system` — system messages ignored
- `test_extract_messages_handles_group` — group chat sender extraction

**Priority:**
- `test_classify_priority_urgent` — critical for urgent keywords
- `test_classify_priority_invoice` — high for financial keywords
- `test_classify_priority_default` — medium default
- `test_classify_priority_vip_upgrade` — VIP chat upgrades priority

**Action file creation:**
- `test_create_action_file_valid_md` — file exists with frontmatter
- `test_create_action_file_context_messages` — conversation context included
- `test_create_action_file_keyword_recorded` — matched keyword in frontmatter

**Resilience:**
- `test_session_expired_handles_gracefully` — logs error, skips cycle
- `test_selector_not_found_falls_back` — graceful error on changed selectors
- `test_browser_crash_recovery` — sets _page to None, retries next cycle

**Integration:**
- `test_run_once_dry_run_end_to_end` — creates files in Needs_Action/whatsapp/

## 6. Graceful Degradation

WhatsApp Web automation is inherently fragile. The watcher must degrade gracefully:

| Failure Mode | Response |
|---|---|
| Session expired (QR needed) | Log error, update Dashboard health to 🔴, skip cycle |
| Selector changed (WA updated) | Log which selector failed, try fallback, skip cycle |
| Browser crash | Set `_page = None`, next cycle will re-launch |
| Phone disconnected | WhatsApp shows warning — log it, continue (auto-reconnects) |
| Rate limited by WhatsApp | Increase check_interval to 300s, log warning |
| Network timeout | Standard transient error handling from BaseWatcher |

**Never crash the watcher process.** Always catch, log, and continue.

## 7. Security & ToS Notes

Include this docstring at the top of the file:

```python
"""
WhatsApp Watcher — Monitors WhatsApp Web for business messages.

IMPORTANT: This uses WhatsApp Web browser automation via Playwright.
- This is for personal/business use monitoring YOUR OWN account
- WhatsApp's Terms of Service may restrict automated access
- Use responsibly: reasonable polling intervals, no message sending
- Rate limiting is built in (60s minimum interval, 2s between chats)
- This watcher is READ-ONLY — it never sends messages

For production use, consider WhatsApp Business API (official, paid).
"""
```

## 8. Validation Criteria

- [ ] `scripts/watchers/whatsapp_watcher.py` extends BaseWatcher
- [ ] Persistent session via `launch_persistent_context`
- [ ] `--setup` mode for QR code scanning (visible browser)
- [ ] Keyword filtering works (case-insensitive)
- [ ] DRY_RUN works without Playwright browser launch
- [ ] Rate limiting: delays between chat interactions
- [ ] Graceful degradation for all failure modes in section 6
- [ ] All tests pass (all browser interactions mocked)
- [ ] No message sending capability (read-only)
- [ ] Selectors configurable via env var override
- [ ] `--once` flag works
- [ ] No modification to Bronze files
