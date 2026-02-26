"""Vault helper utilities for AI Employee watchers."""

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml


def get_vault_path() -> Path:
    """Return vault path from VAULT_PATH env var. Validate it exists."""
    raw = os.getenv("VAULT_PATH")
    if not raw:
        raise ValueError("VAULT_PATH environment variable is not set")
    vault = Path(raw)
    if not vault.exists() or not vault.is_dir():
        raise ValueError(f"VAULT_PATH does not exist or is not a directory: {vault}")
    return vault


def sanitize_filename(raw: str, max_length: int = 200) -> str:
    """
    Remove/replace characters illegal in filenames.

    Replace spaces with underscores. Remove: / \\ : * ? " < > |
    Handle non-ASCII via NFKD transliteration, stripping remaining non-ASCII.
    Truncate to max_length.
    """
    # Normalize unicode (NFKD) then encode to ASCII ignoring non-ASCII chars
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")

    # Replace spaces with underscores
    result = ascii_str.replace(" ", "_")

    # Remove illegal filename characters
    result = re.sub(r'[/\\:*?"<>|]', "", result)

    # Truncate
    return result[:max_length]


def write_action_file(
    directory: Path,
    filename: str,
    frontmatter: dict,
    body: str,
) -> Path:
    """
    Write a Markdown file with YAML frontmatter.

    - Sanitize filename (remove illegal chars, limit length to 200)
    - If file exists, append numeric suffix: _1, _2, etc.
    - Write atomically: temp file → rename
    - Return final Path
    """
    directory.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(filename)
    # Ensure .md extension
    if not safe_name.endswith(".md"):
        safe_name = safe_name + ".md"

    # Resolve collision
    candidate = directory / safe_name
    if candidate.exists():
        stem = safe_name[:-3]  # strip .md
        counter = 1
        while True:
            candidate = directory / f"{stem}_{counter}.md"
            if not candidate.exists():
                break
            counter += 1

    # Build content
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n{body}"

    # Atomic write: temp file in same dir → rename
    tmp_fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(candidate)
    except Exception:
        # Clean up temp file on error
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return candidate


def append_json_log(log_dir: Path, entry: dict) -> None:
    """
    Append a JSON log entry to /Logs/YYYY-MM-DD.json.

    Create file with empty array if not exists.
    Read → append → write atomically.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.json"

    # Read existing data
    if log_file.exists():
        try:
            with log_file.open("r", encoding="utf-8") as f:
                data: list = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = []
    else:
        data = []

    data.append(entry)

    # Atomic write
    tmp_fd, tmp_path = tempfile.mkstemp(dir=log_dir, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(log_file)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_frontmatter(file_path: Path) -> dict:
    """
    Read YAML frontmatter from a Markdown file.

    Return the parsed dict. Return empty dict if no frontmatter.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    if not text.startswith("---"):
        return {}

    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}

    fm_block = text[3:end].strip()
    try:
        result = yaml.safe_load(fm_block)
        return result if isinstance(result, dict) else {}
    except yaml.YAMLError:
        return {}


def is_dry_run() -> bool:
    """Check DRY_RUN env var. Default True (safe by default)."""
    return os.getenv("DRY_RUN", "true").lower() == "true"
