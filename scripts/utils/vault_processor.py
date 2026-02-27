"""Vault Processor: scan, list, move, and count files across vault pipeline folders."""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.utils.vault_helpers import append_json_log, read_frontmatter

logger = logging.getLogger(__name__)

_PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_STATUS_FOR_DESTINATION: dict[str, str] = {
    "Done": "done",
    "Rejected": "rejected",
    "Plans": "in_progress",
    "Pending_Approval": "pending_approval",
}


def _parse_item(file_path: Path, vault_path: Path, subdomain: str | None = None) -> dict:
    """Build a result dict for a single .md file."""
    frontmatter = read_frontmatter(file_path)
    stat = file_path.stat()
    created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat()
    return {
        "path": str(file_path.relative_to(vault_path)),
        "filename": file_path.name,
        "subdomain": subdomain or file_path.parent.name,
        "frontmatter": frontmatter,
        "created": created,
    }


def _priority_key(item: dict) -> tuple[int, str]:
    """Sort key: priority rank first, then received timestamp (oldest first)."""
    fm = item.get("frontmatter", {})
    priority = fm.get("priority", "low")
    rank = _PRIORITY_ORDER.get(priority, 3)
    received = fm.get("received", item.get("created", ""))
    return (rank, str(received))


def list_pending(
    vault_path: Path,
    subdomain: str | None = None,
) -> list[dict]:
    """
    List all pending items in /Needs_Action/.

    Args:
        vault_path: Root of the vault
        subdomain: Optional filter — "email", "whatsapp", "file", "social".
                   If None, scan all subdomains.

    Returns:
        List of dicts with keys: path, filename, subdomain, frontmatter, created.
        Sorted by priority (critical > high > medium > low), then by received timestamp.
    """
    needs_action = vault_path / "Needs_Action"
    if not needs_action.is_dir():
        return []

    if subdomain:
        dirs = [needs_action / subdomain]
    else:
        dirs = [d for d in needs_action.iterdir() if d.is_dir()]

    items: list[dict] = []
    for folder in dirs:
        if not folder.is_dir():
            continue
        sub = folder.name
        for file_path in folder.iterdir():
            if file_path.name == ".gitkeep" or file_path.suffix != ".md":
                continue
            items.append(_parse_item(file_path, vault_path, sub))

    items.sort(key=_priority_key)
    return items


def list_folder(
    vault_path: Path,
    folder: str,
) -> list[dict]:
    """
    Generic folder listing. Works for any vault folder.

    Args:
        vault_path: Root of the vault
        folder: Relative path like "Plans" or "Pending_Approval"

    Returns:
        Same structure as list_pending.
    """
    target = vault_path / folder
    if not target.is_dir():
        return []

    items: list[dict] = []
    for file_path in target.rglob("*.md"):
        if file_path.name == ".gitkeep":
            continue
        items.append(_parse_item(file_path, vault_path))

    items.sort(key=_priority_key)
    return items


def _update_frontmatter_status(file_path: Path, new_status: str) -> None:
    """Rewrite a file's frontmatter 'status' field in-place (atomically)."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return

    if not text.startswith("---"):
        return

    end = text.find("\n---", 3)
    if end == -1:
        return

    fm_block = text[3:end].strip()
    try:
        fm = yaml.safe_load(fm_block)
    except yaml.YAMLError:
        fm = {}

    if not isinstance(fm, dict):
        fm = {}

    fm["status"] = new_status
    new_fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
    # text[end:] == "\n---\n\nbody..." — skip "\n---" (4 chars) to get "\n\nbody..."
    body_after_dash = text[end + 4:]
    new_content = f"---\n{new_fm_str}---{body_after_dash}"

    tmp_fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        Path(tmp_path).replace(file_path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def move_file(
    vault_path: Path,
    source: str | Path,
    destination_folder: str,
) -> Path:
    """
    Move a file from its current location to a destination folder.

    Args:
        vault_path: Root of the vault
        source: Relative path from vault root (e.g., "Needs_Action/email/EMAIL_xyz.md")
        destination_folder: Target folder name (e.g., "Done", "Plans", "Rejected")

    Returns:
        New Path of the moved file

    Rules:
    - Preserve original filename
    - If file already exists in destination, append _1, _2, etc.
    - Update the file's frontmatter "status" field
    - Log the move to /Logs/
    - Atomic: copy first, then delete source
    """
    if isinstance(source, str):
        source_path = vault_path / source
    else:
        source_path = source if source.is_absolute() else vault_path / source

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    dest_dir = vault_path / destination_folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Handle name collisions
    candidate = dest_dir / source_path.name
    if candidate.exists():
        stem = source_path.stem
        suffix = source_path.suffix
        counter = 1
        while True:
            candidate = dest_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                break
            counter += 1

    # Atomic copy first, then delete source (never lose data)
    shutil.copy2(str(source_path), str(candidate))

    # Update frontmatter status in destination file
    new_status = _STATUS_FOR_DESTINATION.get(destination_folder, "done")
    _update_frontmatter_status(candidate, new_status)

    # Log the move
    log_entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "action_type": "file_move",
        "actor": "claude_code",
        "input_file": str(source_path.relative_to(vault_path)),
        "output_file": str(candidate.relative_to(vault_path)),
        "summary": f"Moved {source_path.name} to {destination_folder}",
        "result": "success",
        "error": None,
    }
    append_json_log(vault_path / "Logs", log_entry)

    # Delete original only after copy confirmed
    source_path.unlink()
    logger.info("Moved %s → %s", source_path, candidate)
    return candidate


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
    today = datetime.now(tz=timezone.utc).date()

    def count_md(folder: Path) -> int:
        if not folder.is_dir():
            return 0
        return sum(1 for f in folder.rglob("*.md") if f.name != ".gitkeep")

    def count_md_today(folder: Path) -> int:
        if not folder.is_dir():
            return 0
        count = 0
        for f in folder.rglob("*.md"):
            if f.name == ".gitkeep":
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).date()
            if mtime == today:
                count += 1
        return count

    return {
        "Needs_Action": count_md(vault_path / "Needs_Action"),
        "Plans": count_md(vault_path / "Plans"),
        "Pending_Approval": count_md(vault_path / "Pending_Approval"),
        "In_Progress": count_md(vault_path / "In_Progress"),
        "Done_today": count_md_today(vault_path / "Done"),
    }


def archive_done(
    vault_path: Path,
    older_than_days: int = 7,
) -> int:
    """
    Move files from /Done/ to /Done/archive/ if older than threshold.
    Returns count of archived files.
    """
    done_dir = vault_path / "Done"
    archive_dir = done_dir / "archive"

    if not done_dir.is_dir():
        return 0

    now = datetime.now(tz=timezone.utc)
    archived = 0

    for file_path in list(done_dir.glob("*.md")):
        if file_path.name == ".gitkeep":
            continue
        age = now - datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        if age.days >= older_than_days:
            archive_dir.mkdir(parents=True, exist_ok=True)
            candidate = archive_dir / file_path.name
            if candidate.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                counter = 1
                while True:
                    candidate = archive_dir / f"{stem}_{counter}{suffix}"
                    if not candidate.exists():
                        break
                    counter += 1
            shutil.copy2(str(file_path), str(candidate))
            file_path.unlink()
            archived += 1
            logger.info("Archived %s → %s", file_path.name, candidate)

    return archived


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Vault Processor CLI")
    subparsers = parser.add_subparsers(dest="command")

    # list-pending
    lp = subparsers.add_parser("list-pending")
    lp.add_argument("--subdomain", default=None)
    lp.add_argument("--format", choices=["json", "table", "brief"], default="brief", dest="fmt")

    # list-folder
    lf = subparsers.add_parser("list-folder")
    lf.add_argument("folder")
    lf.add_argument("--format", choices=["json", "table", "brief"], default="brief", dest="fmt")

    # move-to-done
    md_p = subparsers.add_parser("move-to-done")
    md_p.add_argument("file_path", help="Relative path to file")

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

    def _format_items(items: list[dict], fmt: str) -> str:
        if fmt == "json":
            return json.dumps(items, indent=2)
        elif fmt == "table":
            if not items:
                return "(empty)"
            lines = ["| Priority | Filename | Subject |", "|----------|----------|---------|"]
            for item in items:
                priority = item["frontmatter"].get("priority", "—")
                subject = item["frontmatter"].get("subject", "—")
                lines.append(f"| {priority} | {item['filename']} | {subject} |")
            return "\n".join(lines)
        else:  # brief
            if not items:
                return "(empty)"
            parts = []
            for item in items:
                priority = item["frontmatter"].get("priority", "—")
                subject = item["frontmatter"].get("subject", item["filename"])
                parts.append(f"[{priority}] {item['filename']} — {subject}")
            return "\n".join(parts)

    if args.command == "list-pending":
        items = list_pending(vault_path, subdomain=args.subdomain)
        print(_format_items(items, args.fmt))

    elif args.command == "list-folder":
        items = list_folder(vault_path, args.folder)
        print(_format_items(items, args.fmt))

    elif args.command == "move-to-done":
        new_path = move_file(vault_path, args.file_path, "Done")
        print(f"Moved to: {new_path.relative_to(vault_path)}")

    elif args.command == "move-file":
        new_path = move_file(vault_path, args.file_path, args.destination)
        print(f"Moved to: {new_path.relative_to(vault_path)}")

    elif args.command == "counts":
        counts = get_queue_counts(vault_path)
        parts = [f"{k}: {v}" for k, v in counts.items()]
        print(" | ".join(parts))

    elif args.command == "archive":
        count = archive_done(vault_path, older_than_days=args.days)
        print(f"Archived {count} file(s)")

    else:
        parser.print_help()
        sys.exit(1)
