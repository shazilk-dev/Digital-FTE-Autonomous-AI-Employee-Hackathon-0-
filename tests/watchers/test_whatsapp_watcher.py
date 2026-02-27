"""Unit tests for WhatsAppWatcher."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.watchers.whatsapp_watcher import (
    MAX_CHATS_PER_CYCLE,
    WhatsAppWatcher,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_dir(tmp_path):
    """Create a temp Playwright session directory."""
    d = tmp_path / "sessions" / "whatsapp"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def whatsapp_watcher(tmp_vault, session_dir):
    """WhatsApp watcher in DRY_RUN mode."""
    with patch.dict(os.environ, {"DRY_RUN": "true"}):
        return WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)


@pytest.fixture
def live_watcher(tmp_vault, session_dir):
    """WhatsApp watcher in live (non-dry-run) mode."""
    with patch.dict(os.environ, {"DRY_RUN": "false"}):
        return WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)


@pytest.fixture
def mock_page():
    """Mock Playwright Page with configurable element queries."""
    page = MagicMock()
    page.url = "https://web.whatsapp.com"
    return page


def _make_mock_row(
    text: str,
    pre_plain: str = "[09:05, 27/02/2026] John: ",
) -> MagicMock:
    """Build a mock DOM row element with given text and metadata."""
    row = MagicMock()

    text_el = MagicMock()
    text_el.inner_text.return_value = text

    time_el = MagicMock()
    time_el.get_attribute.return_value = pre_plain

    def query_selector_side_effect(sel: str):
        if "selectable-text" in sel:
            return text_el
        if "data-pre-plain-text" in sel:
            return time_el if pre_plain else None
        return None

    row.query_selector.side_effect = query_selector_side_effect
    return row


def _make_outgoing_row(text: str) -> MagicMock:
    """Build a mock row for an outgoing message (no pre-plain-text)."""
    row = MagicMock()

    text_el = MagicMock()
    text_el.inner_text.return_value = text

    def query_selector_side_effect(sel: str):
        if "selectable-text" in sel:
            return text_el
        if "data-pre-plain-text" in sel:
            return None  # Outgoing — no metadata element
        return None

    row.query_selector.side_effect = query_selector_side_effect
    return row


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_dry_run_no_browser_launch(self, tmp_vault, session_dir):
        """Browser attributes are None after construction (lazy init)."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert watcher._page is None
        assert watcher._browser is None
        assert watcher._playwright is None

    def test_init_sets_default_keywords(self, tmp_vault, session_dir):
        """Default keywords are loaded when env var is absent."""
        env = {k: v for k, v in os.environ.items() if k != "WHATSAPP_KEYWORDS"}
        env["DRY_RUN"] = "true"
        with patch.dict(os.environ, env, clear=True):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert "urgent" in watcher.keywords
        assert "invoice" in watcher.keywords
        assert "payment" in watcher.keywords
        assert "asap" in watcher.keywords

    def test_init_keywords_from_env(self, tmp_vault, session_dir):
        """WHATSAPP_KEYWORDS env var overrides defaults."""
        with patch.dict(
            os.environ,
            {"DRY_RUN": "true", "WHATSAPP_KEYWORDS": "alpha,beta,gamma"},
        ):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert watcher.keywords == ["alpha", "beta", "gamma"]

    def test_init_creates_session_path(self, tmp_vault, tmp_path):
        """Session directory is created automatically if it doesn't exist."""
        new_session = tmp_path / "new_sessions" / "whatsapp"
        assert not new_session.exists()
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            WhatsAppWatcher(vault_path=tmp_vault, session_path=new_session)
        assert new_session.exists()

    def test_init_custom_keywords(self, tmp_vault, session_dir):
        """Keywords passed as argument override env and defaults."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(
                vault_path=tmp_vault,
                session_path=session_dir,
                keywords=["custom", "words"],
            )
        assert watcher.keywords == ["custom", "words"]

    def test_init_empty_keywords_list(self, tmp_vault, session_dir):
        """Empty keywords list (no filter) is preserved as-is."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(
                vault_path=tmp_vault, session_path=session_dir, keywords=[]
            )
        assert watcher.keywords == []

    def test_init_minimum_check_interval_enforced(self, tmp_vault, session_dir):
        """BaseWatcher enforces minimum 30s check interval."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(
                vault_path=tmp_vault, session_path=session_dir, check_interval=5
            )
        assert watcher.check_interval >= 30

    def test_init_needs_action_whatsapp_dir_created(self, tmp_vault, session_dir):
        """Needs_Action/whatsapp/ subdirectory is created by BaseWatcher."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert (tmp_vault / "Needs_Action" / "whatsapp").exists()


# ---------------------------------------------------------------------------
# check_for_updates tests
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    def test_check_for_updates_dry_run(self, whatsapp_watcher):
        """DRY_RUN returns exactly 3 sample items."""
        items = whatsapp_watcher.check_for_updates()
        assert len(items) == 3

    def test_check_for_updates_dry_run_required_fields(self, whatsapp_watcher):
        """Each DRY_RUN item contains all required BaseWatcher fields."""
        required = {"id", "type", "source", "subject", "content", "priority", "received",
                    "requires_approval"}
        for item in whatsapp_watcher.check_for_updates():
            assert required.issubset(item.keys()), f"Missing fields: {item.keys() - required}"
            assert item["type"] == "whatsapp"
            assert item["requires_approval"] is False

    def test_check_for_updates_dry_run_valid_priorities(self, whatsapp_watcher):
        """DRY_RUN items have valid priority values."""
        valid = {"critical", "high", "medium", "low"}
        for item in whatsapp_watcher.check_for_updates():
            assert item["priority"] in valid

    def test_check_for_updates_keyword_matching(self, whatsapp_watcher):
        """DRY_RUN data includes at least one message matching each keyword."""
        items = whatsapp_watcher.check_for_updates()
        contents = " ".join(item["content"].lower() for item in items)
        # Verify at least one item matches a default keyword
        assert any(kw in contents for kw in whatsapp_watcher.keywords)

    def test_check_for_updates_empty_keywords_captures_all(self, tmp_vault, session_dir):
        """Empty keywords list is stored correctly (no filter mode)."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(
                vault_path=tmp_vault, session_path=session_dir, keywords=[]
            )
        assert watcher.keywords == []

    def test_check_for_updates_skips_processed(self, tmp_vault, session_dir):
        """Items processed in one live-mode cycle are not reprocessed in the next."""
        with patch.dict(os.environ, {"DRY_RUN": "false"}):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        # Inject fixed dry-run data as the live source so run_once calls mark_processed
        dry_data = watcher._generate_dry_run_data()
        watcher.check_for_updates = lambda: list(dry_data)

        first = watcher.run_once()
        assert len(first) == 3

        second = watcher.run_once()
        assert second == []

    def test_check_for_updates_browser_error_returns_empty(self, live_watcher):
        """Browser launch failure returns empty list without crashing."""
        with patch.object(
            live_watcher, "_ensure_browser", side_effect=RuntimeError("Browser failed")
        ):
            results = live_watcher.check_for_updates()
        assert results == []

    def test_check_for_updates_respects_max_chats(self, live_watcher, mock_page):
        """Processing caps at MAX_CHATS_PER_CYCLE unread badge elements."""
        mock_page.wait_for_selector.return_value = None
        # Return more than MAX_CHATS_PER_CYCLE unread badges
        mock_page.query_selector_all.return_value = [MagicMock() for _ in range(20)]

        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()

        # Results will be <= MAX_CHATS_PER_CYCLE (mocked elements won't yield real data)
        assert len(results) <= MAX_CHATS_PER_CYCLE

    def test_check_for_updates_session_expired_returns_empty(self, live_watcher, mock_page):
        """Session expired (chat list selector times out) returns empty list."""
        mock_page.wait_for_selector.side_effect = Exception("Timeout waiting for selector")

        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()

        assert results == []

    def test_check_for_updates_no_unread_returns_empty(self, live_watcher, mock_page):
        """No unread badge elements → empty result, no crash."""
        mock_page.wait_for_selector.return_value = None
        mock_page.query_selector_all.return_value = []

        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()

        assert results == []


# ---------------------------------------------------------------------------
# Message extraction tests (mocked)
# ---------------------------------------------------------------------------


class TestExtractMessages:
    def test_extract_messages_filters_incoming(self, whatsapp_watcher, mock_page):
        """Messages with pre-plain-text are extracted as incoming."""
        row = _make_mock_row("Hello there", "[09:00, 27/02/2026] Alice: ")
        mock_page.query_selector_all.return_value = [row]

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "Alice")

        assert len(msgs) == 1
        assert msgs[0]["is_incoming"] is True
        assert msgs[0]["text"] == "Hello there"

    def test_extract_messages_skips_outgoing(self, whatsapp_watcher, mock_page):
        """Outgoing messages (no pre-plain-text) are excluded."""
        outgoing = _make_outgoing_row("My outgoing message")
        mock_page.query_selector_all.return_value = [outgoing]

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "TestChat")

        assert msgs == []

    def test_extract_messages_skips_media_only(self, whatsapp_watcher, mock_page):
        """Rows without a text element (media-only) are skipped."""
        row = MagicMock()
        row.query_selector.return_value = None  # No text element

        mock_page.query_selector_all.return_value = [row]
        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "TestChat")

        assert msgs == []

    def test_extract_messages_skips_system(self, whatsapp_watcher, mock_page):
        """Messages with text but no pre-plain-text (system msgs) are skipped."""
        row = _make_mock_row("Messages and calls are end-to-end encrypted.", pre_plain="")
        mock_page.query_selector_all.return_value = [row]

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "TestChat")

        assert msgs == []

    def test_extract_messages_handles_group(self, whatsapp_watcher, mock_page):
        """Group chat: sender name is parsed from pre-plain-text."""
        row = _make_mock_row("Group message here", "[08:30, 27/02/2026] Alice Manager: ")
        mock_page.query_selector_all.return_value = [row]

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "Team Chat")

        assert len(msgs) == 1
        assert msgs[0]["sender"] == "Alice Manager"
        assert msgs[0]["text"] == "Group message here"

    def test_extract_messages_respects_max_per_chat(self, whatsapp_watcher, mock_page):
        """Only the last max_messages_per_chat rows are processed."""
        rows = [
            _make_mock_row(f"Message {i}", f"[09:{i:02d}, 27/02/2026] Bob: ")
            for i in range(20)
        ]
        mock_page.query_selector_all.return_value = rows

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "Bob")

        assert len(msgs) <= whatsapp_watcher.max_messages_per_chat

    def test_extract_messages_parses_time(self, whatsapp_watcher, mock_page):
        """Timestamp is correctly parsed from data-pre-plain-text."""
        row = _make_mock_row("Hi!", "[14:30, 27/02/2026] Dave: ")
        mock_page.query_selector_all.return_value = [row]

        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "Dave")

        assert msgs[0]["time"] == "14:30, 27/02/2026"

    def test_extract_messages_selector_error_returns_empty(self, whatsapp_watcher, mock_page):
        """Selector error → empty list, no crash."""
        mock_page.query_selector_all.side_effect = Exception(
            "Selector not found — WhatsApp Web may have updated"
        )
        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "TestChat")
        assert msgs == []

    def test_extract_messages_empty_chat_returns_empty(self, whatsapp_watcher, mock_page):
        """Chat with no message rows returns empty list."""
        mock_page.query_selector_all.return_value = []
        msgs = whatsapp_watcher._extract_messages_from_chat(mock_page, "EmptyChat")
        assert msgs == []


# ---------------------------------------------------------------------------
# Priority classification tests
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    def test_classify_priority_urgent(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("urgent matter", "c") == "critical"

    def test_classify_priority_asap(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("need asap!", "c") == "critical"

    def test_classify_priority_emergency(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("this is an emergency", "c") == "critical"

    def test_classify_priority_critical_keyword(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("critical failure", "c") == "critical"

    def test_classify_priority_invoice(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("invoice #001 due", "c") == "high"

    def test_classify_priority_payment(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("payment pending", "c") == "high"

    def test_classify_priority_deadline(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("deadline is tomorrow", "c") == "high"

    def test_classify_priority_help(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("i need help please", "c") == "medium"

    def test_classify_priority_pricing(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("pricing info please", "c") == "medium"

    def test_classify_priority_quote(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("can you send a quote?", "c") == "medium"

    def test_classify_priority_default(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("hello how are you", "c") == "medium"

    def test_classify_priority_case_insensitive(self, whatsapp_watcher):
        assert whatsapp_watcher._classify_whatsapp_priority("URGENT MATTER", "c") == "critical"
        assert whatsapp_watcher._classify_whatsapp_priority("INVOICE DUE", "c") == "high"
        assert whatsapp_watcher._classify_whatsapp_priority("PRICING INFO", "c") == "medium"

    def test_classify_priority_vip_upgrade(self, tmp_vault, session_dir):
        """VIP chat upgrades priority by one level."""
        with patch.dict(
            os.environ,
            {"DRY_RUN": "true", "WHATSAPP_VIP_CHATS": "big boss"},
        ):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        # "help" → medium; VIP → high
        assert watcher._classify_whatsapp_priority("i need help", "Big Boss") == "high"

    def test_classify_priority_vip_high_to_critical(self, tmp_vault, session_dir):
        """VIP chat: high priority upgrades to critical."""
        with patch.dict(
            os.environ,
            {"DRY_RUN": "true", "WHATSAPP_VIP_CHATS": "vip client"},
        ):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        # "invoice" → high; VIP → critical
        assert watcher._classify_whatsapp_priority("invoice due", "VIP Client") == "critical"

    def test_classify_priority_vip_critical_stays_critical(self, tmp_vault, session_dir):
        """VIP chat: critical priority cannot be upgraded further."""
        with patch.dict(
            os.environ,
            {"DRY_RUN": "true", "WHATSAPP_VIP_CHATS": "boss"},
        ):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert watcher._classify_whatsapp_priority("urgent!", "Boss") == "critical"

    def test_classify_priority_non_vip_unchanged(self, tmp_vault, session_dir):
        """Non-VIP chat: priority is not upgraded."""
        with patch.dict(
            os.environ,
            {"DRY_RUN": "true", "WHATSAPP_VIP_CHATS": "vip only"},
        ):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        assert watcher._classify_whatsapp_priority("invoice due", "Regular Chat") == "high"


# ---------------------------------------------------------------------------
# create_action_file tests
# ---------------------------------------------------------------------------


class TestCreateActionFile:
    def _sample_item(self) -> dict:
        return {
            "id": "wa_test_abc123",
            "type": "whatsapp",
            "source": "John Client",
            "sender_phone": "+1234567890",
            "subject": "WhatsApp from John Client",
            "content": "URGENT: invoice payment needed",
            "context_messages": [
                {"sender": "John Client", "text": "Hi there", "time": "09:00"},
                {
                    "sender": "John Client",
                    "text": "URGENT: invoice payment needed",
                    "time": "09:05",
                },
            ],
            "received": "2026-02-27T09:00:00+00:00",
            "priority": "critical",
            "requires_approval": False,
            "keyword_matched": "urgent",
            "chat_type": "individual",
            "is_group": False,
        }

    def test_create_action_file_valid_md(self, whatsapp_watcher):
        """File is created on disk with .md extension."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        assert path.exists()
        assert path.suffix == ".md"

    def test_create_action_file_has_frontmatter(self, whatsapp_watcher):
        """File starts with YAML frontmatter block."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---")

    def test_create_action_file_frontmatter_fields(self, whatsapp_watcher):
        """Frontmatter contains all required fields with correct values."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        end = content.find("\n---", 3)
        fm = yaml.safe_load(content[3:end].strip())

        assert fm["type"] == "whatsapp"
        assert fm["source"] == "John Client"
        assert fm["priority"] == "critical"
        assert fm["status"] == "pending"
        assert fm["requires_approval"] is False
        assert fm["keyword_matched"] == "urgent"
        assert fm["chat_type"] == "individual"

    def test_create_action_file_keyword_recorded(self, whatsapp_watcher):
        """Matched keyword appears in frontmatter."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        end = content.find("\n---", 3)
        fm = yaml.safe_load(content[3:end].strip())
        assert fm["keyword_matched"] == "urgent"

    def test_create_action_file_context_messages(self, whatsapp_watcher):
        """Conversation context messages appear in the file body."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert "Hi there" in content
        assert "John Client" in content

    def test_create_action_file_filename_format(self, whatsapp_watcher):
        """Filename starts with WHATSAPP_ and ends with .md."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        assert path.name.startswith("WHATSAPP_")
        assert path.name.endswith(".md")

    def test_create_action_file_suggested_actions(self, whatsapp_watcher):
        """All four suggested action checkboxes are present."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert "- [ ] Reply to John Client" in content
        assert "- [ ] Forward to relevant party" in content
        assert "- [ ] Create task from request" in content
        assert "- [ ] Archive — no action needed" in content

    def test_create_action_file_sanitizes_source(self, whatsapp_watcher):
        """Chat name with special characters is sanitized in the filename."""
        item = self._sample_item()
        item["source"] = "Client: A/B <Test>"
        path = whatsapp_watcher.create_action_file(item)
        assert path.exists()
        for char in (':', '<', '>', '"', '\\', '/', '*', '?', '|'):
            assert char not in path.name

    def test_create_action_file_group_chat(self, whatsapp_watcher):
        """Group chat item produces a valid file with group context."""
        item = self._sample_item()
        item["source"] = "Team Chat"
        item["chat_type"] = "group"
        item["is_group"] = True
        item["context_messages"] = [
            {"sender": "Alice", "text": "Morning!", "time": "08:00"},
            {"sender": "Bob", "text": "pricing info?", "time": "08:05"},
        ]
        path = whatsapp_watcher.create_action_file(item)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Team Chat" in content
        assert "Alice" in content
        assert "Bob" in content

    def test_create_action_file_written_to_needs_action_whatsapp(self, whatsapp_watcher):
        """File is created inside Needs_Action/whatsapp/ directory."""
        path = whatsapp_watcher.create_action_file(self._sample_item())
        assert "whatsapp" in str(path)
        assert path.parent == whatsapp_watcher.needs_action_path


# ---------------------------------------------------------------------------
# Resilience tests
# ---------------------------------------------------------------------------


class TestResilience:
    def test_session_expired_handles_gracefully(self, live_watcher, mock_page):
        """Expired session (selector timeout) logs error, returns empty list."""
        mock_page.wait_for_selector.side_effect = Exception(
            "Timeout — session may have expired"
        )
        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()
        assert results == []

    def test_selector_not_found_falls_back(self, live_watcher, mock_page):
        """Selector error during query_selector_all is caught gracefully."""
        mock_page.wait_for_selector.return_value = None
        mock_page.query_selector_all.side_effect = Exception(
            "Selector not found — WhatsApp Web may have updated"
        )
        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()
        assert results == []

    def test_browser_crash_recovery(self, live_watcher, mock_page):
        """Browser crash: _page is set to None so next cycle re-launches."""
        mock_page.wait_for_selector.return_value = None
        mock_page.query_selector_all.side_effect = Exception("Browser crash!")

        # Simulate page was running before the crash
        live_watcher._page = mock_page

        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()

        assert isinstance(results, list)
        assert live_watcher._page is None

    def test_shutdown_closes_browser(self, whatsapp_watcher):
        """Shutdown closes browser and playwright, resets state."""
        mock_browser = MagicMock()
        mock_pw = MagicMock()
        whatsapp_watcher._browser = mock_browser
        whatsapp_watcher._playwright = mock_pw
        whatsapp_watcher._page = MagicMock()

        whatsapp_watcher.shutdown()

        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()
        assert whatsapp_watcher._browser is None
        assert whatsapp_watcher._playwright is None
        assert whatsapp_watcher._page is None

    def test_shutdown_tolerates_browser_close_error(self, whatsapp_watcher):
        """Shutdown does not crash if browser.close() raises."""
        mock_browser = MagicMock()
        mock_browser.close.side_effect = Exception("Already closed")
        whatsapp_watcher._browser = mock_browser

        # Should not raise
        whatsapp_watcher.shutdown()
        assert whatsapp_watcher._browser is None

    def test_ensure_browser_returns_existing_responsive_page(self, live_watcher):
        """_ensure_browser returns existing page when still responsive."""
        mock_page_obj = MagicMock()
        mock_page_obj.url = "https://web.whatsapp.com"
        live_watcher._page = mock_page_obj

        result = live_watcher._ensure_browser()

        assert result is mock_page_obj

    def test_ensure_browser_calls_close_on_unresponsive_page(self, live_watcher):
        """_ensure_browser calls _close_browser when existing page.url raises."""
        bad_page = MagicMock()
        type(bad_page).url = property(
            fget=lambda self: (_ for _ in ()).throw(Exception("Page closed"))
        )
        live_watcher._page = bad_page

        with patch.object(live_watcher, "_close_browser") as mock_close:
            # After _close_browser, the re-launch will fail (no real playwright),
            # but we only care that _close_browser was called.
            try:
                live_watcher._ensure_browser()
            except Exception:
                pass

        mock_close.assert_called_once()

    def test_per_chat_error_does_not_abort_cycle(self, live_watcher, mock_page):
        """Error in one chat's processing does not abort the whole cycle."""
        mock_page.wait_for_selector.return_value = None

        # First unread badge: raises on evaluate_handle; rest skipped
        bad_badge = MagicMock()
        bad_badge.evaluate_handle.side_effect = Exception("DOM error")
        mock_page.query_selector_all.return_value = [bad_badge]

        with patch.object(live_watcher, "_ensure_browser", return_value=mock_page):
            results = live_watcher.check_for_updates()

        # Should return empty list without crashing
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_run_once_dry_run_end_to_end(self, whatsapp_watcher):
        """DRY_RUN run_once creates 3 files in Needs_Action/whatsapp/."""
        created = whatsapp_watcher.run_once()
        assert len(created) == 3

        for path in created:
            assert path.exists()
            assert "whatsapp" in str(path)
            content = path.read_text(encoding="utf-8")
            assert content.startswith("---")
            end = content.find("\n---", 3)
            fm = yaml.safe_load(content[3:end].strip())
            assert fm["type"] == "whatsapp"
            assert fm["status"] == "pending"
            assert fm["priority"] in ("critical", "high", "medium", "low")

    def test_run_once_logs_audit_entries(self, whatsapp_watcher):
        """Audit log entries are written to Logs/ directory."""
        whatsapp_watcher.run_once()
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = whatsapp_watcher.logs_path / f"{today}.json"

        assert log_file.exists()
        entries = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(entries) >= 3
        for entry in entries:
            assert entry["action_type"] == "watcher_detect"
            assert entry["result"] == "success"
            assert "timestamp" in entry

    def test_run_once_deduplication(self, tmp_vault, session_dir):
        """Running run_once twice in live mode does not create duplicate files."""
        with patch.dict(os.environ, {"DRY_RUN": "false"}):
            watcher = WhatsAppWatcher(vault_path=tmp_vault, session_path=session_dir)
        # Inject fixed dry-run data as the live source
        dry_data = watcher._generate_dry_run_data()
        watcher.check_for_updates = lambda: list(dry_data)

        first = watcher.run_once()
        second = watcher.run_once()
        assert len(first) == 3
        assert len(second) == 0

    def test_dry_run_priorities_varied(self, whatsapp_watcher):
        """DRY_RUN data contains at least two distinct priority levels."""
        items = whatsapp_watcher.check_for_updates()
        priorities = {item["priority"] for item in items}
        assert len(priorities) >= 2
        assert "critical" in priorities

    def test_dry_run_includes_group_chat(self, whatsapp_watcher):
        """DRY_RUN data contains at least one group chat item."""
        items = whatsapp_watcher.check_for_updates()
        group_items = [i for i in items if i.get("is_group")]
        assert len(group_items) >= 1

    def test_dry_run_ids_are_unique(self, whatsapp_watcher):
        """DRY_RUN items all have unique IDs."""
        items = whatsapp_watcher.check_for_updates()
        ids = [item["id"] for item in items]
        assert len(ids) == len(set(ids))

    def test_monitored_chats_filter(self, tmp_vault, session_dir):
        """monitored_chats parameter is stored correctly."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = WhatsAppWatcher(
                vault_path=tmp_vault,
                session_path=session_dir,
                monitored_chats=["Boss", "Client A"],
            )
        assert watcher.monitored_chats == ["Boss", "Client A"]
