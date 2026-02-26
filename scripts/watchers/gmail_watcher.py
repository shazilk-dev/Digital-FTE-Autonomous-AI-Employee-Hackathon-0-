"""Gmail watcher — polls Gmail API and creates Markdown action files."""

import sys
from pathlib import Path

# Allow running as: python scripts/watchers/gmail_watcher.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import base64
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from googleapiclient.errors import HttpError

from scripts.utils.gmail_auth import get_gmail_service
from scripts.utils.vault_helpers import sanitize_filename, write_action_file
from scripts.watchers.base_watcher import BaseWatcher

_BODY_MAX_LENGTH = 2000
_MAX_MESSAGES_PER_CYCLE = 50


class GmailWatcher(BaseWatcher):
    """
    Polls Gmail API for unread/important emails and writes Markdown action files.

    Extends BaseWatcher and implements the perception layer for email.
    """

    def __init__(
        self,
        vault_path: str | Path,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        check_interval: int = 120,
        query_filter: str = "is:unread is:important",
    ) -> None:
        super().__init__(vault_path, check_interval, "gmail", "email")

        self._credentials_path = Path(
            credentials_path
            or os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
        )
        self._token_path = Path(
            token_path or os.getenv("GMAIL_TOKEN_PATH", "token.json")
        )
        self.query_filter: str = query_filter

        # Priority keywords (configurable via env var)
        keywords_env = os.getenv(
            "GMAIL_PRIORITY_KEYWORDS", "urgent,asap,emergency,critical"
        )
        self._priority_keywords: list[str] = [
            k.strip().lower() for k in keywords_env.split(",") if k.strip()
        ]

        if self.is_dry_run:
            self._service = None
            self.logger.info("[DRY RUN] Skipping Gmail authentication")
        else:
            self._service = get_gmail_service(
                self._credentials_path, self._token_path
            )

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list[dict]:
        """Poll Gmail API for new messages matching query_filter."""
        if self.is_dry_run:
            return self._generate_dry_run_data()

        results: list[dict] = []

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=self.query_filter, maxResults=20)
                .execute()
            )

            messages: list[dict] = list(response.get("messages", []))
            next_page_token: str | None = response.get("nextPageToken")

            # Paginate up to _MAX_MESSAGES_PER_CYCLE total
            while next_page_token and len(messages) < _MAX_MESSAGES_PER_CYCLE:
                remaining = _MAX_MESSAGES_PER_CYCLE - len(messages)
                page_response = (
                    self._service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=self.query_filter,
                        maxResults=min(20, remaining),
                        pageToken=next_page_token,
                    )
                    .execute()
                )
                messages.extend(page_response.get("messages", []))
                next_page_token = page_response.get("nextPageToken")

            messages = messages[:_MAX_MESSAGES_PER_CYCLE]

            for msg_stub in messages:
                msg_id: str = msg_stub["id"]
                if not self.should_process(msg_id):
                    self.logger.debug("Skipping already-processed message %s", msg_id)
                    continue

                raw_msg = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
                parsed = self._parse_message(raw_msg)
                results.append(parsed)

        except HttpError as exc:
            status = exc.resp.status if hasattr(exc, "resp") else 0
            if status == 429:
                self.logger.warning(
                    "Gmail API rate limit (429). Will retry next cycle."
                )
            elif status == 401:
                self.logger.error("Gmail auth expired (401). Attempting re-auth.")
                try:
                    self._service = get_gmail_service(
                        self._credentials_path, self._token_path
                    )
                except Exception as reauth_exc:
                    self.logger.error("Re-auth failed: %s", reauth_exc)
                    raise
            elif status == 403:
                self.logger.error(
                    "Gmail API forbidden (403). Verify the API is enabled in "
                    "Google Cloud Console and OAuth scopes are correct."
                )
            else:
                self.logger.error("Gmail API error: %s", exc)
        except (ConnectionError, TimeoutError) as exc:
            self.logger.warning("Gmail connection error: %s", exc)

        return results

    def create_action_file(self, item: dict) -> Path:
        """Write a Markdown action file for the given email item."""
        sender = item.get("sender_email") or item.get("source", "unknown")
        sanitized_sender = sanitize_filename(sender)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"EMAIL_{sanitized_sender}_{timestamp}.md"

        frontmatter = {
            "type": "email",
            "source": item["source"],
            "sender_email": item["sender_email"],
            "subject": item["subject"],
            "received": item["received"],
            "priority": item["priority"],
            "status": "pending",
            "requires_approval": False,
            "message_id": item["id"],
            "thread_id": item["thread_id"],
            "labels": item["labels"],
            "has_attachments": item["has_attachments"],
        }

        attachment_display = (
            ", ".join(item["attachment_names"]) if item["attachment_names"] else "None"
        )
        body = (
            f"## Email Content\n\n"
            f"{item['content']}\n\n"
            f"## Metadata\n\n"
            f"- **From:** {item['source']}\n"
            f"- **To:** {item['to']}\n"
            f"- **Date:** {item['received']}\n"
            f"- **Attachments:** {attachment_display}\n\n"
            f"## Suggested Actions\n\n"
            f"- [ ] Reply to sender\n"
            f"- [ ] Forward to relevant party\n"
            f"- [ ] Flag for follow-up\n"
            f"- [ ] Archive after processing\n"
        )

        return write_action_file(self.needs_action_path, filename, frontmatter, body)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_message(self, raw_msg: dict) -> dict:
        """Extract structured data from a Gmail API message object."""
        payload = raw_msg.get("payload", {})
        headers: dict[str, str] = {
            h["name"]: h["value"] for h in payload.get("headers", [])
        }

        from_header = headers.get("From", "")
        sender_name, sender_email = parseaddr(from_header)

        received = _parse_gmail_date(headers.get("Date", ""))
        content = _extract_body(raw_msg)
        if len(content) > _BODY_MAX_LENGTH:
            content = content[:_BODY_MAX_LENGTH]

        labels = raw_msg.get("labelIds", [])

        msg_dict: dict = {
            "id": raw_msg["id"],
            "thread_id": raw_msg["threadId"],
            "type": "email",
            "source": from_header,
            "sender_email": sender_email,
            "sender_name": sender_name,
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", "(No Subject)"),
            "received": received,
            "content": content,
            "snippet": raw_msg.get("snippet", ""),
            "labels": labels,
            "has_attachments": _check_attachments(raw_msg),
            "attachment_names": _get_attachment_names(raw_msg),
            "requires_approval": False,
        }
        msg_dict["priority"] = self._classify_priority(msg_dict)
        return msg_dict

    def _classify_priority(self, msg: dict) -> str:
        """Determine priority from Gmail labels and subject keywords."""
        labels: list[str] = msg.get("labels", [])
        subject: str = msg.get("subject", "").lower()

        if "IMPORTANT" in labels:
            for keyword in self._priority_keywords:
                if keyword in subject:
                    return "critical"
            return "high"

        if "CATEGORY_PROMOTIONS" in labels or "CATEGORY_SOCIAL" in labels:
            return "low"

        if "SPAM" in labels:
            return "low"

        return "medium"

    def _generate_dry_run_data(self) -> list[dict]:
        """Return 3 sample emails with varying priorities for DRY_RUN mode."""
        return [
            {
                "id": "dry_run_001",
                "thread_id": "dry_thread_001",
                "type": "email",
                "source": "Client A <client@example.com>",
                "sender_email": "client@example.com",
                "sender_name": "Client A",
                "to": "employee@company.com",
                "subject": "URGENT: Overdue Invoice #2024-001",
                "received": "2026-02-26T09:00:00+00:00",
                "content": (
                    "Hello,\n\nThis is an urgent reminder that invoice #2024-001 "
                    "for $5,000 is now 30 days overdue. Please process this "
                    "immediately or we will have to escalate.\n\nBest regards,\nClient A"
                ),
                "snippet": "URGENT: Invoice #2024-001 is 30 days overdue...",
                "labels": ["IMPORTANT", "INBOX"],
                "has_attachments": False,
                "attachment_names": [],
                "priority": "critical",
                "requires_approval": False,
            },
            {
                "id": "dry_run_002",
                "thread_id": "dry_thread_002",
                "type": "email",
                "source": "Jane Smith <jane.smith@example.com>",
                "sender_email": "jane.smith@example.com",
                "sender_name": "Jane Smith",
                "to": "employee@company.com",
                "subject": "Q1 Strategy Meeting — Can you attend Thursday?",
                "received": "2026-02-26T10:00:00+00:00",
                "content": (
                    "Hi,\n\nI'd like to schedule a Q1 strategy meeting for Thursday "
                    "at 2pm. Please let me know if you're available and I'll send a "
                    "calendar invite.\n\nBest,\nJane"
                ),
                "snippet": "Q1 strategy meeting Thursday 2pm...",
                "labels": ["IMPORTANT", "INBOX"],
                "has_attachments": False,
                "attachment_names": [],
                "priority": "high",
                "requires_approval": False,
            },
            {
                "id": "dry_run_003",
                "thread_id": "dry_thread_003",
                "type": "email",
                "source": "Newsletter <newsletter@deals.example.com>",
                "sender_email": "newsletter@deals.example.com",
                "sender_name": "Newsletter",
                "to": "employee@company.com",
                "subject": "50% off all products this weekend only!",
                "received": "2026-02-26T08:00:00+00:00",
                "content": (
                    "Don't miss out! This weekend only, get 50% off all products. "
                    "Use code WEEKEND50 at checkout. Shop now at example.com/deals"
                ),
                "snippet": "50% off all products this weekend only!",
                "labels": ["CATEGORY_PROMOTIONS", "INBOX"],
                "has_attachments": False,
                "attachment_names": [],
                "priority": "low",
                "requires_approval": False,
            },
        ]

    def shutdown(self) -> None:
        """Close the Gmail API connection and save state."""
        self._service = None
        super().shutdown()


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _parse_gmail_date(date_str: str) -> str:
    """Convert an email Date header string to ISO 8601 format."""
    if not date_str:
        return datetime.now(tz=timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


def _extract_body(msg: dict) -> str:
    """
    Extract plain-text body from a Gmail API message.

    Priority: text/plain > text/html (stripped) > snippet > '(No content)'
    """
    payload = msg.get("payload", {})

    plain = _find_part(payload, "text/plain")
    if plain:
        return plain

    html = _find_part(payload, "text/html")
    if html:
        return _strip_html(html)

    snippet = msg.get("snippet", "")
    return snippet if snippet else "(No content)"


def _find_part(part: dict, mime_type: str) -> str:
    """Recursively search MIME parts for the given mime_type and decode."""
    if part.get("mimeType") == mime_type:
        data = part.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )

    for sub_part in part.get("parts", []):
        result = _find_part(sub_part, mime_type)
        if result:
            return result

    return ""


def _strip_html(html: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _check_attachments(msg: dict) -> bool:
    """Return True if the message payload contains any attachments."""
    return _has_attachment(msg.get("payload", {}))


def _has_attachment(part: dict) -> bool:
    """Recursively check if any MIME part is an attachment."""
    if part.get("filename"):
        return True
    for sub_part in part.get("parts", []):
        if _has_attachment(sub_part):
            return True
    return False


def _get_attachment_names(msg: dict) -> list[str]:
    """Return a list of attachment filenames from the message."""
    names: list[str] = []
    _collect_attachment_names(msg.get("payload", {}), names)
    return names


def _collect_attachment_names(part: dict, names: list[str]) -> None:
    """Recursively collect non-empty filenames from MIME parts."""
    filename = part.get("filename", "")
    if filename:
        names.append(filename)
    for sub_part in part.get("parts", []):
        _collect_attachment_names(sub_part, names)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Gmail Watcher for AI Employee")
    parser.add_argument(
        "--vault", default=None, help="Path to vault (default: VAULT_PATH env)"
    )
    parser.add_argument(
        "--interval", type=int, default=120, help="Check interval in seconds"
    )
    parser.add_argument(
        "--query",
        default="is:unread is:important",
        help="Gmail search query",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit (no loop)"
    )
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
