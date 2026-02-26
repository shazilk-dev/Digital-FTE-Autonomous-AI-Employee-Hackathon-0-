"""Gmail OAuth 2.0 authentication helper for AI Employee."""

import json
import logging
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when Gmail OAuth flow fails."""


def validate_credentials_file(credentials_path: str | Path) -> bool:
    """
    Check that credentials.json exists and has required fields.

    Return True if valid, False otherwise.
    Don't throw — let caller decide what to do.
    """
    path = Path(credentials_path)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return "installed" in data or "web" in data
    except (json.JSONDecodeError, OSError):
        return False


def get_gmail_service(
    credentials_path: str | Path,
    token_path: str | Path,
    scopes: list[str] | None = None,
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
    credentials_path = Path(credentials_path)
    token_path = Path(token_path)
    effective_scopes = scopes or SCOPES

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at: {credentials_path}\n"
            "Please download OAuth credentials from Google Cloud Console:\n"
            "  1. Go to https://console.cloud.google.com/apis/credentials\n"
            "  2. Create an OAuth 2.0 Client ID (Desktop application)\n"
            "  3. Download and save as credentials.json"
        )

    creds: Credentials | None = None

    # Load existing token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_path), effective_scopes
            )
        except Exception as exc:
            logger.warning("Failed to load token file %s: %s", token_path, exc)
            creds = None

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Gmail token refreshed successfully")
            except RefreshError as exc:
                logger.error(
                    "Token refresh failed: %s. Deleting token and re-authenticating.",
                    exc,
                )
                token_path.unlink(missing_ok=True)
                creds = None

        if not creds:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), effective_scopes
                )
                creds = flow.run_local_server(port=0)
                logger.info("Gmail OAuth flow completed successfully")
            except Exception as exc:
                raise AuthenticationError(
                    f"Gmail OAuth flow failed: {exc}\n"
                    "If running headless, generate token.json on a machine with a "
                    "browser, then copy it to this location."
                ) from exc

        # Persist the token
        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Gmail token saved to %s", token_path)
        except OSError as exc:
            logger.warning("Failed to save token to %s: %s", token_path, exc)

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as exc:
        raise AuthenticationError(f"Failed to build Gmail service: {exc}") from exc
