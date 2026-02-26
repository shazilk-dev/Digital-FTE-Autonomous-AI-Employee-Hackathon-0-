"""Unit tests for GmailWatcher."""

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from googleapiclient.errors import HttpError

from scripts.watchers.gmail_watcher import (
    GmailWatcher,
    _check_attachments,
    _extract_body,
    _get_attachment_names,
    _parse_gmail_date,
    _strip_html,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _encode(text: str) -> str:
    """URL-safe base64 encode text as Gmail API does."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _make_http_error(status: int) -> HttpError:
    """Create a mock HttpError with the given HTTP status code."""
    resp = MagicMock()
    resp.status = status
    return HttpError(resp, b"error body")


def _make_gmail_message(
    msg_id: str = "test_id_001",
    thread_id: str = "thread_001",
    from_header: str = "Test Sender <sender@example.com>",
    to_header: str = "recipient@example.com",
    subject: str = "Test Subject",
    date_header: str = "Thu, 26 Feb 2026 10:30:00 +0000",
    body_text: str = "This is the email body.",
    labels: list[str] | None = None,
    parts: list[dict] | None = None,
) -> dict:
    """Build a realistic Gmail API message dict."""
    if labels is None:
        labels = ["INBOX", "IMPORTANT"]

    headers = [
        {"name": "From", "value": from_header},
        {"name": "To", "value": to_header},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": date_header},
    ]

    if parts is not None:
        payload = {
            "mimeType": "multipart/mixed",
            "headers": headers,
            "body": {"data": ""},
            "parts": parts,
        }
    else:
        payload = {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": _encode(body_text)},
            "parts": [],
        }

    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": body_text[:100],
        "labelIds": labels,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gmail_service():
    """Return a mock Gmail API service with canned responses."""
    return MagicMock()


@pytest.fixture
def sample_gmail_message():
    """Return a realistic Gmail API message dict."""
    return _make_gmail_message()


@pytest.fixture
def gmail_watcher(tmp_vault):
    """Create a GmailWatcher in DRY_RUN mode with a tmp vault."""
    with patch.dict(os.environ, {"DRY_RUN": "true"}):
        watcher = GmailWatcher(
            vault_path=tmp_vault,
            credentials_path="/fake/credentials.json",
            token_path="/fake/token.json",
        )
    return watcher


def _make_live_watcher(tmp_vault, service: MagicMock) -> GmailWatcher:
    """Create a GmailWatcher in live mode with an injected mock service."""
    with patch(
        "scripts.watchers.gmail_watcher.get_gmail_service", return_value=service
    ):
        with patch.dict(os.environ, {"DRY_RUN": "false"}):
            watcher = GmailWatcher(
                vault_path=tmp_vault,
                credentials_path="/fake/creds.json",
                token_path="/fake/token.json",
            )
    return watcher


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_dry_run_skips_auth(self, tmp_vault):
        """No Gmail API call is made when DRY_RUN=true."""
        with patch(
            "scripts.watchers.gmail_watcher.get_gmail_service"
        ) as mock_auth:
            with patch.dict(os.environ, {"DRY_RUN": "true"}):
                watcher = GmailWatcher(
                    vault_path=tmp_vault,
                    credentials_path="/fake/creds.json",
                    token_path="/fake/token.json",
                )
            mock_auth.assert_not_called()
        assert watcher._service is None

    def test_init_sets_default_query_filter(self, tmp_vault):
        """Default query filter is 'is:unread is:important'."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = GmailWatcher(vault_path=tmp_vault)
        assert watcher.query_filter == "is:unread is:important"

    def test_init_reads_env_vars(self, tmp_vault):
        """Credentials and token paths are read from environment variables."""
        with patch.dict(
            os.environ,
            {
                "DRY_RUN": "true",
                "GMAIL_CREDENTIALS_PATH": "/env/creds.json",
                "GMAIL_TOKEN_PATH": "/env/token.json",
            },
        ):
            watcher = GmailWatcher(vault_path=tmp_vault)
        assert watcher._credentials_path == Path("/env/creds.json")
        assert watcher._token_path == Path("/env/token.json")

    def test_init_live_calls_auth(self, tmp_vault, mock_gmail_service):
        """In live mode, get_gmail_service is called once."""
        with patch(
            "scripts.watchers.gmail_watcher.get_gmail_service",
            return_value=mock_gmail_service,
        ) as mock_auth:
            with patch.dict(os.environ, {"DRY_RUN": "false"}):
                watcher = GmailWatcher(
                    vault_path=tmp_vault,
                    credentials_path="/fake/creds.json",
                    token_path="/fake/token.json",
                )
        mock_auth.assert_called_once()
        assert watcher._service is not None

    def test_init_custom_query_filter(self, tmp_vault):
        """Custom query_filter parameter is stored."""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            watcher = GmailWatcher(
                vault_path=tmp_vault, query_filter="is:unread label:invoice"
            )
        assert watcher.query_filter == "is:unread label:invoice"


# ---------------------------------------------------------------------------
# check_for_updates tests
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    def test_check_for_updates_dry_run_returns_samples(self, gmail_watcher):
        """DRY_RUN mode returns exactly 3 sample items."""
        items = gmail_watcher.check_for_updates()
        assert len(items) == 3
        assert items[0]["id"] == "dry_run_001"
        assert items[1]["id"] == "dry_run_002"
        assert items[2]["id"] == "dry_run_003"

    def test_check_for_updates_live_calls_api(self, tmp_vault, mock_gmail_service):
        """Live mode calls Gmail API and returns parsed messages."""
        msg = _make_gmail_message(msg_id="live_msg_001")
        mock_gmail_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "live_msg_001"}],
        }
        mock_gmail_service.users().messages().get().execute.return_value = msg

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()

        assert len(results) == 1
        assert results[0]["id"] == "live_msg_001"
        mock_gmail_service.users().messages().list.assert_called()
        mock_gmail_service.users().messages().get.assert_called()

    def test_check_for_updates_skips_processed(self, tmp_vault, mock_gmail_service):
        """Messages already in the processed set are not returned."""
        msg_new = _make_gmail_message(msg_id="new_msg")
        mock_gmail_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "already_seen"}, {"id": "new_msg"}],
        }
        mock_gmail_service.users().messages().get().execute.return_value = msg_new

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        watcher.mark_processed("already_seen")

        results = watcher.check_for_updates()
        result_ids = [r["id"] for r in results]
        assert "already_seen" not in result_ids
        assert "new_msg" in result_ids

    def test_check_for_updates_handles_rate_limit(self, tmp_vault, mock_gmail_service):
        """HttpError 429 returns empty list without crashing."""
        mock_gmail_service.users().messages().list().execute.side_effect = (
            _make_http_error(429)
        )

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()
        assert results == []

    def test_check_for_updates_handles_auth_error(self, tmp_vault, mock_gmail_service):
        """HttpError 401 attempts re-auth; raises if re-auth also fails."""
        mock_gmail_service.users().messages().list().execute.side_effect = (
            _make_http_error(401)
        )

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)

        with patch(
            "scripts.watchers.gmail_watcher.get_gmail_service",
            side_effect=Exception("reauth failed"),
        ):
            with pytest.raises(Exception, match="reauth failed"):
                watcher.check_for_updates()

    def test_check_for_updates_handles_forbidden(self, tmp_vault, mock_gmail_service):
        """HttpError 403 logs an error and returns empty list."""
        mock_gmail_service.users().messages().list().execute.side_effect = (
            _make_http_error(403)
        )

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()
        assert results == []

    def test_check_for_updates_handles_connection_error(
        self, tmp_vault, mock_gmail_service
    ):
        """ConnectionError returns empty list without crashing."""
        mock_gmail_service.users().messages().list().execute.side_effect = (
            ConnectionError("network down")
        )

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()
        assert results == []

    def test_check_for_updates_respects_max_results(
        self, tmp_vault, mock_gmail_service
    ):
        """Total messages fetched across pages is capped at 50."""
        first_page = [{"id": f"msg_{i}"} for i in range(30)]
        second_page = [{"id": f"msg_{i}"} for i in range(30, 60)]

        mock_gmail_service.users().messages().list().execute.side_effect = [
            {"messages": first_page, "nextPageToken": "tok_abc"},
            {"messages": second_page},
        ]
        mock_gmail_service.users().messages().get().execute.return_value = (
            _make_gmail_message()
        )

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()
        assert len(results) <= 50

    def test_check_for_updates_empty_mailbox(self, tmp_vault, mock_gmail_service):
        """No unread emails returns empty list (normal, not an error)."""
        mock_gmail_service.users().messages().list().execute.return_value = {
            "messages": [],
        }

        watcher = _make_live_watcher(tmp_vault, mock_gmail_service)
        results = watcher.check_for_updates()
        assert results == []


# ---------------------------------------------------------------------------
# _parse_message tests
# ---------------------------------------------------------------------------


class TestParseMessage:
    def test_parse_message_extracts_headers(self, gmail_watcher, sample_gmail_message):
        """From, To, Subject, Date headers are correctly extracted."""
        result = gmail_watcher._parse_message(sample_gmail_message)
        assert result["source"] == "Test Sender <sender@example.com>"
        assert result["sender_email"] == "sender@example.com"
        assert result["sender_name"] == "Test Sender"
        assert result["to"] == "recipient@example.com"
        assert result["subject"] == "Test Subject"
        assert result["id"] == "test_id_001"
        assert result["thread_id"] == "thread_001"

    def test_parse_message_extracts_plain_text_body(self, gmail_watcher):
        """text/plain part is preferred over text/html."""
        msg = _make_gmail_message(body_text="Plain text body content.")
        result = gmail_watcher._parse_message(msg)
        assert "Plain text body content." in result["content"]

    def test_parse_message_falls_back_to_html(self, gmail_watcher):
        """Falls back to HTML (stripped) when no text/plain part exists."""
        html_body = "<html><body><p>Hello <b>World</b></p></body></html>"
        html_part = {
            "mimeType": "text/html",
            "body": {"data": _encode(html_body)},
            "parts": [],
        }
        msg = _make_gmail_message(parts=[html_part])
        result = gmail_watcher._parse_message(msg)
        assert "Hello" in result["content"]
        assert "World" in result["content"]
        assert "<html>" not in result["content"]
        assert "<b>" not in result["content"]

    def test_parse_message_truncates_long_body(self, gmail_watcher):
        """Bodies longer than 2000 characters are truncated."""
        long_body = "X" * 3000
        msg = _make_gmail_message(body_text=long_body)
        result = gmail_watcher._parse_message(msg)
        assert len(result["content"]) <= 2000

    def test_parse_message_handles_missing_headers(self, gmail_watcher):
        """Sensible defaults are applied when headers are missing."""
        msg = {
            "id": "minimal_001",
            "threadId": "minimal_thread",
            "snippet": "minimal snippet",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": _encode("body text")},
                "parts": [],
            },
        }
        result = gmail_watcher._parse_message(msg)
        assert result["subject"] == "(No Subject)"
        assert result["to"] == ""
        assert result["source"] == ""

    def test_parse_message_detects_attachments(self, gmail_watcher):
        """has_attachments flag and attachment_names are populated correctly."""
        plain_part = {
            "mimeType": "text/plain",
            "body": {"data": _encode("email body")},
            "parts": [],
            "filename": "",
        }
        attachment_part = {
            "mimeType": "application/pdf",
            "body": {"attachmentId": "att_id_001"},
            "parts": [],
            "filename": "invoice.pdf",
        }
        msg = _make_gmail_message(parts=[plain_part, attachment_part])
        result = gmail_watcher._parse_message(msg)
        assert result["has_attachments"] is True
        assert "invoice.pdf" in result["attachment_names"]

    def test_parse_message_no_attachments(self, gmail_watcher, sample_gmail_message):
        """Messages without attachments report has_attachments=False."""
        result = gmail_watcher._parse_message(sample_gmail_message)
        assert result["has_attachments"] is False
        assert result["attachment_names"] == []

    def test_parse_message_sets_requires_approval_false(
        self, gmail_watcher, sample_gmail_message
    ):
        """Email triage never requires approval."""
        result = gmail_watcher._parse_message(sample_gmail_message)
        assert result["requires_approval"] is False


# ---------------------------------------------------------------------------
# _classify_priority tests
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    def test_classify_critical(self, gmail_watcher):
        """IMPORTANT label + urgent keyword in subject → critical."""
        msg = {"labels": ["IMPORTANT", "INBOX"], "subject": "URGENT: Please help"}
        assert gmail_watcher._classify_priority(msg) == "critical"

    def test_classify_critical_asap(self, gmail_watcher):
        """IMPORTANT label + 'asap' keyword → critical."""
        msg = {"labels": ["IMPORTANT", "INBOX"], "subject": "Need ASAP response"}
        assert gmail_watcher._classify_priority(msg) == "critical"

    def test_classify_high(self, gmail_watcher):
        """IMPORTANT label without urgent keywords → high."""
        msg = {"labels": ["IMPORTANT", "INBOX"], "subject": "Meeting tomorrow"}
        assert gmail_watcher._classify_priority(msg) == "high"

    def test_classify_low_promotion(self, gmail_watcher):
        """CATEGORY_PROMOTIONS label → low."""
        msg = {
            "labels": ["CATEGORY_PROMOTIONS", "INBOX"],
            "subject": "Sale on now!",
        }
        assert gmail_watcher._classify_priority(msg) == "low"

    def test_classify_low_social(self, gmail_watcher):
        """CATEGORY_SOCIAL label → low."""
        msg = {
            "labels": ["CATEGORY_SOCIAL", "INBOX"],
            "subject": "Someone liked your post",
        }
        assert gmail_watcher._classify_priority(msg) == "low"

    def test_classify_low_spam(self, gmail_watcher):
        """SPAM label → low."""
        msg = {"labels": ["SPAM"], "subject": "You won a million dollars!"}
        assert gmail_watcher._classify_priority(msg) == "low"

    def test_classify_medium_default(self, gmail_watcher):
        """No special labels → medium."""
        msg = {"labels": ["INBOX"], "subject": "Regular email"}
        assert gmail_watcher._classify_priority(msg) == "medium"

    def test_classify_medium_empty_labels(self, gmail_watcher):
        """Empty label list → medium."""
        msg = {"labels": [], "subject": "Some email"}
        assert gmail_watcher._classify_priority(msg) == "medium"


# ---------------------------------------------------------------------------
# create_action_file tests
# ---------------------------------------------------------------------------


class TestCreateActionFile:
    def _sample_item(self) -> dict:
        return {
            "id": "test_001",
            "thread_id": "thread_001",
            "type": "email",
            "source": "John Doe <john@example.com>",
            "sender_email": "john@example.com",
            "sender_name": "John Doe",
            "to": "employee@company.com",
            "subject": "Meeting request",
            "received": "2026-02-26T10:30:00+00:00",
            "content": "Can we meet tomorrow?",
            "snippet": "Can we meet tomorrow?",
            "labels": ["IMPORTANT", "INBOX"],
            "has_attachments": False,
            "attachment_names": [],
            "priority": "high",
            "requires_approval": False,
        }

    def test_create_action_file_writes_valid_md(self, gmail_watcher):
        """File is created on disk with .md extension."""
        path = gmail_watcher.create_action_file(self._sample_item())
        assert path.exists()
        assert path.suffix == ".md"

    def test_create_action_file_has_yaml_frontmatter(self, gmail_watcher):
        """File has parseable YAML frontmatter with all required fields."""
        path = gmail_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---")

        end = content.find("\n---", 3)
        fm = yaml.safe_load(content[3:end].strip())

        assert fm["type"] == "email"
        assert fm["sender_email"] == "john@example.com"
        assert fm["subject"] == "Meeting request"
        assert fm["priority"] == "high"
        assert fm["status"] == "pending"
        assert fm["requires_approval"] is False
        assert fm["message_id"] == "test_001"
        assert fm["thread_id"] == "thread_001"

    def test_create_action_file_correct_filename_format(self, gmail_watcher):
        """Filename starts with EMAIL_ and ends with .md."""
        path = gmail_watcher.create_action_file(self._sample_item())
        assert path.name.startswith("EMAIL_")
        assert path.name.endswith(".md")
        # Timestamp portion should be present (letters/digits/hyphens after sender)
        assert len(path.stem) > len("EMAIL_")

    def test_create_action_file_sanitizes_filename(self, gmail_watcher):
        """Special characters in sender email are sanitized from the filename."""
        item = self._sample_item()
        item["sender_email"] = "sender+tag@example.com"
        path = gmail_watcher.create_action_file(item)
        assert path.exists()
        # Illegal filename characters must not appear
        for char in (":", "<", ">", '"', "\\", "/", "*", "?", "|"):
            assert char not in path.name

    def test_create_action_file_suggested_actions_present(self, gmail_watcher):
        """Suggested action checkbox list is in the file body."""
        path = gmail_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert "- [ ] Reply to sender" in content
        assert "- [ ] Forward to relevant party" in content
        assert "- [ ] Flag for follow-up" in content
        assert "- [ ] Archive after processing" in content

    def test_create_action_file_content_in_body(self, gmail_watcher):
        """Email content appears in the Markdown body."""
        path = gmail_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert "Can we meet tomorrow?" in content

    def test_create_action_file_metadata_section(self, gmail_watcher):
        """Metadata section lists From, To, Date."""
        path = gmail_watcher.create_action_file(self._sample_item())
        content = path.read_text(encoding="utf-8")
        assert "**From:**" in content
        assert "**To:**" in content
        assert "**Date:**" in content


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_run_once_end_to_end(self, gmail_watcher):
        """DRY_RUN run_once creates exactly 3 files, all with valid frontmatter."""
        created = gmail_watcher.run_once()
        assert len(created) == 3

        for path in created:
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert content.startswith("---")

            end = content.find("\n---", 3)
            fm = yaml.safe_load(content[3:end].strip())
            assert fm["type"] == "email"
            assert fm["status"] == "pending"
            assert fm["priority"] in ("critical", "high", "medium", "low")

    def test_run_once_logs_actions(self, gmail_watcher):
        """Audit log entries are created in the Logs directory."""
        gmail_watcher.run_once()

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = gmail_watcher.logs_path / f"{today}.json"

        assert log_file.exists()
        entries = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(entries) >= 3
        for entry in entries:
            assert entry["action_type"] == "watcher_detect"
            assert entry["result"] == "success"
            assert "timestamp" in entry

    def test_run_once_deduplication(self, gmail_watcher):
        """Running run_once twice does not create duplicate files."""
        created_first = gmail_watcher.run_once()
        created_second = gmail_watcher.run_once()
        assert len(created_first) == 3
        assert len(created_second) == 0  # all already processed

    def test_dry_run_priorities_are_varied(self, gmail_watcher):
        """Dry-run data contains critical, high, and low priority emails."""
        items = gmail_watcher.check_for_updates()
        priorities = {item["priority"] for item in items}
        assert "critical" in priorities
        assert "high" in priorities
        assert "low" in priorities


# ---------------------------------------------------------------------------
# Module-level helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_parse_gmail_date_valid(self):
        """Valid RFC 2822 date is converted to ISO 8601."""
        result = _parse_gmail_date("Thu, 26 Feb 2026 10:30:00 +0000")
        assert "2026-02-26" in result

    def test_parse_gmail_date_empty(self):
        """Empty string returns a valid ISO 8601 timestamp."""
        result = _parse_gmail_date("")
        # Should not raise; should return something ISO-ish
        assert "T" in result

    def test_parse_gmail_date_invalid(self):
        """Unparseable date string returns current time (does not crash)."""
        result = _parse_gmail_date("not a date at all !@#$")
        assert "T" in result

    def test_extract_body_plain_text(self):
        """text/plain part is decoded correctly."""
        msg = _make_gmail_message(body_text="Hello plain text")
        result = _extract_body(msg)
        assert "Hello plain text" in result

    def test_extract_body_prefers_plain_over_html(self):
        """text/plain is chosen over text/html when both are present."""
        plain_part = {
            "mimeType": "text/plain",
            "body": {"data": _encode("Plain preferred")},
            "parts": [],
        }
        html_part = {
            "mimeType": "text/html",
            "body": {"data": _encode("<p>HTML fallback</p>")},
            "parts": [],
        }
        msg = _make_gmail_message(parts=[plain_part, html_part])
        result = _extract_body(msg)
        assert "Plain preferred" in result
        assert "HTML fallback" not in result

    def test_extract_body_fallback_snippet(self):
        """Falls back to snippet when no body parts exist."""
        msg = {
            "id": "x",
            "threadId": "y",
            "snippet": "Snippet preview text",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": ""},
                "parts": [],
            },
        }
        result = _extract_body(msg)
        assert "Snippet preview text" in result

    def test_extract_body_no_content(self):
        """Returns '(No content)' when body and snippet are both empty."""
        msg = {
            "id": "x",
            "threadId": "y",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": ""},
                "parts": [],
            },
        }
        result = _extract_body(msg)
        assert result == "(No content)"

    def test_strip_html_removes_tags(self):
        """HTML tags are stripped from text."""
        result = _strip_html("<p>Hello <b>World</b></p>")
        assert "Hello" in result
        assert "World" in result
        assert "<p>" not in result
        assert "<b>" not in result

    def test_strip_html_removes_script(self):
        """Script tags and their content are removed."""
        result = _strip_html("<script>alert('xss')</script>Hello")
        assert "alert" not in result
        assert "Hello" in result

    def test_check_attachments_true(self):
        """Returns True when payload contains a part with a filename."""
        msg = {
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {"filename": "doc.pdf", "body": {}, "parts": []},
                ],
            }
        }
        assert _check_attachments(msg) is True

    def test_check_attachments_false(self):
        """Returns False when no parts have filenames."""
        msg = _make_gmail_message()
        assert _check_attachments(msg) is False

    def test_get_attachment_names(self):
        """Returns a list of attachment filenames."""
        msg = {
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {"filename": "report.pdf", "body": {}, "parts": []},
                    {"filename": "photo.jpg", "body": {}, "parts": []},
                ],
            }
        }
        names = _get_attachment_names(msg)
        assert "report.pdf" in names
        assert "photo.jpg" in names
