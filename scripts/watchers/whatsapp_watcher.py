"""WhatsApp Watcher — Monitors WhatsApp Web for business messages.

IMPORTANT: This uses WhatsApp Web browser automation via Playwright.
- This is for personal/business use monitoring YOUR OWN account
- WhatsApp's Terms of Service may restrict automated access
- Use responsibly: reasonable polling intervals, no message sending
- Rate limiting is built in (60s minimum interval, 2s between chats)
- This watcher is READ-ONLY — it never sends messages

For production use, consider WhatsApp Business API (official, paid).
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running as: python scripts/watchers/whatsapp_watcher.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.utils.vault_helpers import sanitize_filename, write_action_file  # noqa: E402
from scripts.watchers.base_watcher import BaseWatcher  # noqa: E402

# ---------------------------------------------------------------------------
# Rate-limiting and per-cycle constants
# ---------------------------------------------------------------------------

INTER_CHAT_DELAY = 2.0       # seconds between opening different chats
PAGE_LOAD_TIMEOUT = 60000    # ms to wait for page elements
MESSAGE_READ_DELAY = 1.0     # seconds to "read" messages (human-like)
MAX_CHATS_PER_CYCLE = 10     # Don't process more than 10 chats per poll

_DEFAULT_KEYWORDS: list[str] = [
    "urgent", "asap", "invoice", "payment",
    "help", "pricing", "quote", "deadline",
]

_PRIORITY_ORDER: list[str] = ["low", "medium", "high", "critical"]


class WhatsAppWatcher(BaseWatcher):
    """
    Monitors WhatsApp Web for business messages via Playwright.

    Extends BaseWatcher and implements the perception layer for WhatsApp.
    READ-ONLY — this watcher never sends messages.
    """

    # Selectors are stored as a class-level dict so they can be overridden
    # per-instance (via WHATSAPP_SELECTORS_OVERRIDE env var) or patched in tests.
    SELECTORS: dict[str, str] = {
        "chat_list": '[role="listitem"]',
        "unread_badge": '[aria-label*="unread"]',
        "chat_name": "span[title]",
        "message_text": "span.selectable-text",
        "message_container": '[role="row"]',
        "message_time": "[data-pre-plain-text]",
        "qr_code": '[data-testid="qrcode"]',
        "search_box": '[title="Search input textbox"]',
    }

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
        """
        Initialise the WhatsApp watcher.

        Parameters
        ----------
        vault_path:
            Root path to the Obsidian vault.
        session_path:
            Playwright persistent context data directory.
            Default: WHATSAPP_SESSION_PATH env var, or ./sessions/whatsapp.
        check_interval:
            Seconds between polling cycles. Minimum 30s (enforced by BaseWatcher).
            WhatsApp rate concerns recommend >=60s.
        keywords:
            Messages containing these words (case-insensitive) are captured.
            Default: WHATSAPP_KEYWORDS env var, or built-in defaults.
            Pass an empty list to capture ALL unread messages with no filter.
        headless:
            Run browser in headless mode. Set False for initial QR scan.
        max_messages_per_chat:
            How many recent messages to extract per chat. Default 5.
        monitored_chats:
            Exclusive list of chat names to monitor. None = monitor all.
        """
        super().__init__(vault_path, check_interval, "whatsapp", "whatsapp")

        # Session path — created on first launch if it doesn't exist
        self.session_path: Path = Path(
            session_path or os.getenv("WHATSAPP_SESSION_PATH", "./sessions/whatsapp")
        )
        self.session_path.mkdir(parents=True, exist_ok=True)

        # Keywords
        if keywords is not None:
            self.keywords: list[str] = [k.lower() for k in keywords]
        else:
            env_kw = os.getenv("WHATSAPP_KEYWORDS", "")
            if env_kw.strip():
                self.keywords = [k.strip().lower() for k in env_kw.split(",") if k.strip()]
            else:
                self.keywords = list(_DEFAULT_KEYWORDS)

        self.headless: bool = headless
        self.max_messages_per_chat: int = max_messages_per_chat
        self.monitored_chats: list[str] | None = monitored_chats

        # VIP chats — priority upgraded by one level for messages from these chats
        vip_env = os.getenv("WHATSAPP_VIP_CHATS", "")
        self._vip_chats: list[str] = [
            c.strip().lower() for c in vip_env.split(",") if c.strip()
        ]

        # Allow selector overrides from a JSON file (env var: WHATSAPP_SELECTORS_OVERRIDE)
        selectors_override_path = os.getenv("WHATSAPP_SELECTORS_OVERRIDE")
        if selectors_override_path:
            try:
                override_file = Path(selectors_override_path)
                if override_file.exists():
                    with override_file.open("r", encoding="utf-8") as f:
                        overrides: dict = json.load(f)
                    # Create instance-level copy so class variable is untouched
                    self.SELECTORS = {**self.SELECTORS, **overrides}
                    self.logger.info(
                        "whatsapp: loaded selector overrides from %s",
                        selectors_override_path,
                    )
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("whatsapp: failed to load selector overrides: %s", exc)

        # Browser state — lazy; NOT initialised in constructor
        self._playwright = None
        self._browser = None
        self._page = None

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def _ensure_browser(self):
        """
        Lazy-initialise Playwright browser and return the active page.

        1. If self._page is not None and responsive → return it
        2. Launch persistent context
        3. Navigate to https://web.whatsapp.com
        4. Wait for chat list OR QR code
        5. If QR code visible → log error: "QR scan required. Run with --headless=false"
        6. If chat list visible → return page
        7. On any failure → set self._page = None, raise
        """
        # Return existing responsive page
        if self._page is not None:
            try:
                _ = self._page.url  # Raises if page is closed / crashed
                return self._page
            except Exception:
                self.logger.warning(
                    "whatsapp: existing page unresponsive, re-launching browser"
                )
                self._close_browser()

        try:
            # Lazy import — keeps DRY_RUN mode free of playwright dependency
            from playwright.sync_api import sync_playwright  # noqa: PLC0415

            if self._playwright is None:
                self._playwright = sync_playwright().start()

            self._browser = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.session_path),
                headless=self.headless,
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            # Use first existing page or open a new one
            pages = self._browser.pages
            self._page = pages[0] if pages else self._browser.new_page()

            self._page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

            # Wait for chat list or QR code (whichever appears first)
            try:
                self._page.wait_for_selector(
                    f'{self.SELECTORS["chat_list"]}, {self.SELECTORS["qr_code"]}',
                    timeout=PAGE_LOAD_TIMEOUT,
                )
            except Exception as exc:
                raise RuntimeError(
                    "WhatsApp Web did not load within timeout. "
                    "Check your network connection."
                ) from exc

            # Check which element appeared
            qr = self._page.query_selector(self.SELECTORS["qr_code"])
            if qr is not None:
                self.logger.error(
                    "whatsapp: QR scan required. Run with --headless=false to authenticate."
                )
                raise RuntimeError(
                    "QR scan required. Run with --headless=false to authenticate."
                )

            self.logger.info("whatsapp: browser initialised, WhatsApp Web loaded")
            return self._page

        except Exception:
            self._page = None
            self._browser = None
            raise

    def _close_browser(self) -> None:
        """Close browser context gracefully. Session is persisted to disk."""
        if self._browser is not None:
            try:
                self._browser.close()
                self.logger.info("whatsapp: browser closed")
            except Exception as exc:
                self.logger.warning("whatsapp: error closing browser: %s", exc)
            self._browser = None
            self._page = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as exc:
                self.logger.warning("whatsapp: error stopping playwright: %s", exc)
            self._playwright = None

    def shutdown(self) -> None:
        """Override BaseWatcher: close browser on shutdown."""
        self._close_browser()
        super().shutdown()

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list[dict]:
        """Poll WhatsApp Web for new messages matching keyword filters."""
        if self.is_dry_run:
            return self._generate_dry_run_data()

        try:
            page = self._ensure_browser()
        except Exception as exc:
            self.logger.error("whatsapp: failed to ensure browser: %s", exc)
            return []

        results: list[dict] = []

        try:
            # Verify session alive — check for chat list
            try:
                page.wait_for_selector(
                    self.SELECTORS["chat_list"], timeout=PAGE_LOAD_TIMEOUT
                )
            except Exception as exc:
                self.logger.error(
                    "whatsapp: chat list not found — session may have expired. "
                    "Selector not found — WhatsApp Web may have updated. Error: %s",
                    exc,
                )
                return []

            # Collect chats with unread indicators
            unread_elements = page.query_selector_all(self.SELECTORS["unread_badge"])
            if not unread_elements:
                self.logger.debug("whatsapp: no unread chats found this cycle")
                return []

            # Cap at MAX_CHATS_PER_CYCLE
            chats_to_process: list[str] = []
            for el in unread_elements[:MAX_CHATS_PER_CYCLE]:
                try:
                    # Walk up to the listitem and read its title span
                    listitem = el.evaluate_handle(
                        "el => el.closest('[role=\"listitem\"]')"
                    )
                    name_el = listitem.query_selector(self.SELECTORS["chat_name"])
                    if name_el:
                        chat_name = name_el.get_attribute("title") or ""
                        if chat_name:
                            chats_to_process.append(chat_name)
                except Exception as exc:
                    self.logger.debug("whatsapp: error reading chat name: %s", exc)
                    continue

            for chat_name in chats_to_process:
                # Skip chats not in monitored_chats (when that filter is active)
                if self.monitored_chats is not None and chat_name not in self.monitored_chats:
                    self.logger.debug(
                        "whatsapp: skipping non-monitored chat %s", chat_name
                    )
                    continue

                try:
                    # Click on the chat to open it
                    chat_items = page.query_selector_all(self.SELECTORS["chat_list"])
                    clicked = False
                    for item in chat_items:
                        name_el = item.query_selector(self.SELECTORS["chat_name"])
                        if name_el and name_el.get_attribute("title") == chat_name:
                            item.click()
                            clicked = True
                            break

                    if not clicked:
                        self.logger.debug(
                            "whatsapp: could not find chat element for %s", chat_name
                        )
                        continue

                    page.wait_for_timeout(int(MESSAGE_READ_DELAY * 1000))

                    # Wait for message container to load
                    try:
                        page.wait_for_selector(
                            self.SELECTORS["message_container"], timeout=10000
                        )
                    except Exception:
                        self.logger.debug(
                            "whatsapp: message container not found for chat %s",
                            chat_name,
                        )
                        continue

                    messages = self._extract_messages_from_chat(page, chat_name)

                    # Find first keyword-matching incoming message
                    for msg in messages:
                        if not msg.get("is_incoming"):
                            continue

                        msg_text_lower = msg.get("text", "").lower()
                        matched_keyword: str | None = None

                        if not self.keywords:
                            # No filter — capture all incoming messages
                            matched_keyword = ""
                        else:
                            for kw in self.keywords:
                                if kw in msg_text_lower:
                                    matched_keyword = kw
                                    break

                        if matched_keyword is not None:
                            item = self._build_item(
                                chat_name=chat_name,
                                matched_message=msg,
                                context_messages=messages,
                                matched_keyword=matched_keyword,
                            )
                            results.append(item)
                            break  # One item per chat per cycle

                    time.sleep(INTER_CHAT_DELAY)

                except Exception as exc:
                    self.logger.error(
                        "whatsapp: error processing chat %s: %s", chat_name, exc
                    )
                    continue

        except Exception as exc:
            self.logger.error(
                "whatsapp: unhandled error in check_for_updates: %s", exc, exc_info=True
            )
            # Browser crash recovery — next cycle will re-launch
            self._page = None

        return results

    def create_action_file(self, item: dict) -> Path:
        """Write a Markdown action file for the given WhatsApp item."""
        chat_name = item.get("source", "unknown")
        sanitized_source = sanitize_filename(chat_name)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"WHATSAPP_{sanitized_source}_{timestamp}.md"

        frontmatter: dict = {
            "type": "whatsapp",
            "source": chat_name,
            "sender_phone": item.get("sender_phone", ""),
            "subject": item["subject"],
            "received": item["received"],
            "priority": item["priority"],
            "status": "pending",
            "requires_approval": False,
            "keyword_matched": item.get("keyword_matched", ""),
            "chat_type": item.get("chat_type", "individual"),
        }

        keyword = item.get("keyword_matched", "")
        matched_text = item.get("content", "")
        context_messages: list[dict] = item.get("context_messages", [])

        # Build conversation context block
        context_lines: list[str] = []
        for ctx in context_messages:
            sender = ctx.get("sender", "Unknown")
            ctx_time = ctx.get("time", "")
            ctx_text = ctx.get("text", "")
            context_lines.append(f"**{sender}** ({ctx_time}): {ctx_text}")
        context_block = "\n\n".join(context_lines) if context_lines else "_No context available_"
        n_context = len(context_messages)

        body = (
            f"## Message\n\n"
            f"**From:** {chat_name}\n"
            f'**Keyword Matched:** "{keyword}"\n\n'
            f"> {matched_text}\n\n"
            f"## Conversation Context (Last {n_context} Messages)\n\n"
            f"{context_block}\n\n"
            f"## Suggested Actions\n\n"
            f"- [ ] Reply to {chat_name}\n"
            f"- [ ] Forward to relevant party\n"
            f"- [ ] Create task from request\n"
            f"- [ ] Archive — no action needed\n"
        )

        return write_action_file(self.needs_action_path, filename, frontmatter, body)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_messages_from_chat(self, page, chat_name: str) -> list[dict]:
        """
        Extract recent messages from the currently open chat.

        Returns list of:
        {
            "sender": str,       # Contact name or phone number
            "text": str,         # Message text content
            "time": str,         # Message timestamp (from WhatsApp)
            "is_incoming": bool, # True if received (not sent by us)
        }

        Rules:
        - Only extract incoming messages (is_incoming=True)
        - Skip media-only messages (images/video without text)
        - Skip system messages (no data-pre-plain-text metadata)
        - Limit to max_messages_per_chat most recent
        - Handle group chats: extract sender name from data-pre-plain-text
        """
        messages: list[dict] = []
        try:
            rows = page.query_selector_all(self.SELECTORS["message_container"])
            if not rows:
                return []

            # Take only the last max_messages_per_chat rows
            rows = rows[-self.max_messages_per_chat:]

            for row in rows:
                try:
                    # Skip media-only messages (no text element)
                    text_el = row.query_selector(self.SELECTORS["message_text"])
                    if not text_el:
                        continue

                    text = text_el.inner_text().strip()
                    if not text:
                        continue

                    # Read metadata from data-pre-plain-text attribute
                    # Format: "[HH:MM, DD/MM/YYYY] SenderName: "
                    time_el = row.query_selector(self.SELECTORS["message_time"])
                    pre_plain = ""
                    if time_el:
                        pre_plain = time_el.get_attribute("data-pre-plain-text") or ""

                    if not pre_plain:
                        # No metadata → outgoing message or system message; skip
                        continue

                    # Parse sender and time from pre-plain-text
                    sender = chat_name
                    msg_time = ""
                    match = re.match(r"\[([^\]]+)\]\s+([^:]+):\s*", pre_plain)
                    if match:
                        msg_time = match.group(1)
                        sender = match.group(2).strip()

                    messages.append(
                        {
                            "sender": sender,
                            "text": text,
                            "time": msg_time,
                            "is_incoming": True,
                        }
                    )

                except Exception as exc:
                    self.logger.debug(
                        "whatsapp: error extracting message row: %s", exc
                    )
                    continue

        except Exception as exc:
            self.logger.error(
                "whatsapp: Selector not found — WhatsApp Web may have updated. Error: %s",
                exc,
            )

        return messages

    def _build_item(
        self,
        chat_name: str,
        matched_message: dict,
        context_messages: list[dict],
        matched_keyword: str,
    ) -> dict:
        """Build the standardised item dict for a matched WhatsApp message."""
        msg_text = matched_message.get("text", "")
        msg_time = matched_message.get("time", "")

        # Deterministic ID for deduplication
        hash_input = f"{chat_name}:{msg_text}:{msg_time}"
        msg_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
        item_id = f"wa_{sanitize_filename(chat_name)}_{msg_hash}"

        priority = self._classify_whatsapp_priority(msg_text, chat_name)

        # Determine group vs individual based on number of distinct senders
        senders = {m.get("sender") for m in context_messages}
        is_group = len(senders) > 1
        chat_type = "group" if is_group else "individual"

        return {
            "id": item_id,
            "type": "whatsapp",
            "source": chat_name,
            "sender_phone": matched_message.get("sender", chat_name),
            "subject": f"WhatsApp from {chat_name}",
            "content": msg_text,
            "context_messages": [
                {
                    "sender": m.get("sender", ""),
                    "text": m.get("text", ""),
                    "time": m.get("time", ""),
                }
                for m in context_messages
            ],
            "received": datetime.now(tz=timezone.utc).isoformat(),
            "priority": priority,
            "requires_approval": False,
            "keyword_matched": matched_keyword,
            "chat_type": chat_type,
            "is_group": is_group,
        }

    def _classify_whatsapp_priority(self, text: str, chat_name: str) -> str:
        """
        Classify priority from message text and chat name.

        Rules:
        - Text contains "urgent", "asap", "emergency", "critical" → "critical"
        - Text contains "invoice", "payment", "deadline" → "high"
        - Text contains "help", "pricing", "quote" → "medium"
        - Monitored VIP chat (from WHATSAPP_VIP_CHATS env) → upgrade one level
        - Default → "medium"
        """
        text_lower = text.lower()

        if any(kw in text_lower for kw in ("urgent", "asap", "emergency", "critical")):
            base_priority = "critical"
        elif any(kw in text_lower for kw in ("invoice", "payment", "deadline")):
            base_priority = "high"
        elif any(kw in text_lower for kw in ("help", "pricing", "quote")):
            base_priority = "medium"
        else:
            base_priority = "medium"

        # VIP chat: upgrade priority by one level (critical stays critical)
        if chat_name.lower() in self._vip_chats:
            idx = _PRIORITY_ORDER.index(base_priority)
            if idx < len(_PRIORITY_ORDER) - 1:
                return _PRIORITY_ORDER[idx + 1]

        return base_priority

    def _generate_dry_run_data(self) -> list[dict]:
        """
        Return 3 sample WhatsApp messages for DRY_RUN mode:
        1. Urgent client request about payment (critical)
        2. Colleague asking about meeting (medium)
        3. Group chat with pricing inquiry (high)
        """
        ts = datetime.now(tz=timezone.utc).isoformat()
        return [
            {
                "id": "wa_dry_run_client_abc123",
                "type": "whatsapp",
                "source": "John Client",
                "sender_phone": "+1234567890",
                "subject": "WhatsApp from John Client",
                "content": (
                    "URGENT: I need the payment processed asap! "
                    "Invoice #INV-2026-001 was due yesterday."
                ),
                "context_messages": [
                    {"sender": "John Client", "text": "Hi, are you there?", "time": "09:00"},
                    {
                        "sender": "John Client",
                        "text": (
                            "URGENT: I need the payment processed asap! "
                            "Invoice #INV-2026-001 was due yesterday."
                        ),
                        "time": "09:05",
                    },
                ],
                "received": ts,
                "priority": "critical",
                "requires_approval": False,
                "keyword_matched": "urgent",
                "chat_type": "individual",
                "is_group": False,
            },
            {
                "id": "wa_dry_run_sarah_def456",
                "type": "whatsapp",
                "source": "Sarah Colleague",
                "sender_phone": "Sarah Colleague",
                "subject": "WhatsApp from Sarah Colleague",
                "content": (
                    "Hey, can we reschedule our meeting to Thursday? "
                    "I have a conflict on Wednesday."
                ),
                "context_messages": [
                    {
                        "sender": "Sarah Colleague",
                        "text": (
                            "Hey, can we reschedule our meeting to Thursday? "
                            "I have a conflict on Wednesday."
                        ),
                        "time": "10:30",
                    },
                ],
                "received": ts,
                "priority": "medium",
                "requires_approval": False,
                "keyword_matched": "",
                "chat_type": "individual",
                "is_group": False,
            },
            {
                "id": "wa_dry_run_teamchat_ghi789",
                "type": "whatsapp",
                "source": "Team Chat",
                "sender_phone": "Alice Manager",
                "subject": "WhatsApp from Team Chat",
                "content": (
                    "Can someone send me the pricing for the enterprise plan? "
                    "Client is asking for a quote."
                ),
                "context_messages": [
                    {"sender": "Bob Dev", "text": "Good morning team!", "time": "08:00"},
                    {
                        "sender": "Alice Manager",
                        "text": (
                            "Can someone send me the pricing for the enterprise plan? "
                            "Client is asking for a quote."
                        ),
                        "time": "09:15",
                    },
                    {"sender": "Charlie Sales", "text": "On it!", "time": "09:16"},
                ],
                "received": ts,
                "priority": "high",
                "requires_approval": False,
                "keyword_matched": "pricing",
                "chat_type": "group",
                "is_group": True,
            },
        ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description="WhatsApp Watcher for AI Employee")
    parser.add_argument("--vault", default=None, help="Path to vault (default: VAULT_PATH env)")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit (no loop)")
    parser.add_argument(
        "--headless",
        default="true",
        choices=["true", "false"],
        help="Run browser headless (default: true)",
    )
    parser.add_argument(
        "--keywords", default=None, help="Comma-separated keywords to filter messages"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run in visible mode for QR code setup, then exit",
    )
    args = parser.parse_args()

    vault_path = args.vault or os.getenv("VAULT_PATH", ".")

    # --setup mode: open visible browser, wait for QR scan, then exit
    if args.setup:
        import logging

        logging.basicConfig(level=logging.INFO)
        print("Opening WhatsApp Web for QR code setup...")
        print("Scan the QR code with your phone, then press Enter to save the session.")
        watcher = WhatsAppWatcher(vault_path=vault_path, headless=False)
        try:
            watcher._ensure_browser()
            input("Session saved. Press Enter to exit.")
        finally:
            watcher.shutdown()
        sys.exit(0)

    # Normal operation
    watcher = WhatsAppWatcher(
        vault_path=vault_path,
        check_interval=args.interval,
        headless=args.headless == "true",
        keywords=args.keywords.split(",") if args.keywords else None,
    )

    if args.once:
        results = watcher.run_once()
        print(f"Processed {len(results)} messages")
    else:
        watcher.run()
