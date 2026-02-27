"""Dashboard Updater: safe, section-targeted modifications to Dashboard.md."""

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DASHBOARD_HEADER = "# AI Employee Dashboard"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_dashboard(vault_path: Path) -> str:
    """Read Dashboard.md content. Raise FileNotFoundError if missing."""
    dashboard = vault_path / "Dashboard.md"
    if not dashboard.exists():
        raise FileNotFoundError(
            "Dashboard.md not found. Run Phase B1 scaffolding first."
        )
    return dashboard.read_text(encoding="utf-8")


def _write_dashboard(vault_path: Path, content: str) -> None:
    """
    Write Dashboard.md atomically (temp file → rename).
    Validates content starts with expected header before writing.
    """
    if not content.startswith(_DASHBOARD_HEADER):
        raise ValueError(
            f"Dashboard content must start with '{_DASHBOARD_HEADER}'. "
            "Refusing to write potentially corrupted content."
        )
    dashboard = vault_path / "Dashboard.md"
    tmp_fd, tmp_path = tempfile.mkstemp(dir=vault_path, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(dashboard)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _parse_sections(content: str) -> list[dict]:
    """
    Split Dashboard.md into sections based on ## headings.

    Returns list of dicts with keys: heading, content, start_line, end_line.
    The first section (preamble) has heading=None.
    """
    lines = content.split("\n")
    sections: list[dict] = []
    current: dict = {"heading": None, "lines": [], "start_line": 0}

    for i, line in enumerate(lines):
        if line.startswith("## "):
            # Save previous section
            sections.append(
                {
                    "heading": current["heading"],
                    "content": "\n".join(current["lines"]),
                    "start_line": current["start_line"],
                    "end_line": i - 1,
                }
            )
            current = {"heading": line, "lines": [], "start_line": i}
        else:
            current["lines"].append(line)

    # Save last section
    sections.append(
        {
            "heading": current["heading"],
            "content": "\n".join(current["lines"]),
            "start_line": current["start_line"],
            "end_line": len(lines) - 1,
        }
    )
    return sections


def _reassemble_dashboard(sections: list[dict]) -> str:
    """Rebuild full Dashboard.md from modified sections."""
    parts: list[str] = []
    for section in sections:
        if section["heading"] is None:
            parts.append(section["content"])
        else:
            parts.append(section["heading"])
            if section["content"]:
                parts.append(section["content"])
    return "\n".join(parts)


def _find_section(sections: list[dict], heading_text: str) -> int:
    """Find section index by heading text (case-insensitive substring match)."""
    for i, section in enumerate(sections):
        if section["heading"] and heading_text.lower() in section["heading"].lower():
            return i
    return -1


def _is_separator_row(line: str) -> bool:
    """Return True if a table line is a separator row (|---|---|)."""
    stripped = line.strip()
    return bool(stripped) and all(c in "|-: " for c in stripped) and "-" in stripped


def _parse_row(line: str) -> list[str]:
    """Parse a single Markdown table row into a list of cell strings."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _find_table_in_section(section_content: str) -> tuple[list[str], list[list[str]]]:
    """
    Parse a Markdown table from section content.
    Returns (headers: list[str], rows: list[list[str]]).
    Separator rows are excluded from rows.
    """
    lines = section_content.split("\n")
    table_lines: list[str] = []
    table_started = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            table_lines.append(stripped)
            table_started = True
        elif table_started:
            break  # Non-table line after table → stop

    if not table_lines:
        return [], []

    headers = _parse_row(table_lines[0])
    rows = [_parse_row(line) for line in table_lines[1:] if not _is_separator_row(line)]
    return headers, rows


def _rebuild_table(headers: list[str], rows: list[list[str]]) -> str:
    """
    Rebuild a Markdown table from headers and rows.
    Includes the |---|---| separator. Pads columns for alignment.
    """
    if not headers:
        return ""

    n = len(headers)

    def normalize(row: list[str]) -> list[str]:
        r = list(row)
        while len(r) < n:
            r.append("")
        return r[:n]

    norm_headers = normalize(headers)
    norm_rows = [normalize(r) for r in rows]

    col_widths = [max(len(h), 3) for h in norm_headers]
    for row in norm_rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"
    return "\n".join([fmt(norm_headers), sep] + [fmt(r) for r in norm_rows])


def _replace_table_in_content(section_content: str, new_table: str) -> str:
    """Replace the Markdown table in section_content with new_table."""
    lines = section_content.split("\n")
    table_start = -1
    table_end = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            if table_start == -1:
                table_start = i
            table_end = i
        elif table_start != -1:
            break  # First non-table line after table started

    if table_start == -1:
        return section_content  # No table found

    new_lines = lines[:table_start] + new_table.split("\n") + lines[table_end + 1 :]
    return "\n".join(new_lines)


def _is_placeholder_row(row: list[str]) -> bool:
    """Return True if all cells are '—' or empty (placeholder row)."""
    return bool(row) and all(cell == "—" or cell == "" for cell in row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def update_timestamp(vault_path: Path) -> None:
    """Update the '> **Last Updated:**' line with current UTC timestamp."""
    content = _read_dashboard(vault_path)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_content = re.sub(
        r"> \*\*Last Updated:\*\*.*",
        f"> **Last Updated:** {now}",
        content,
    )
    _write_dashboard(vault_path, new_content)


def add_activity_log(
    vault_path: Path,
    action: str,
    details: str,
    result: str,
) -> None:
    """
    Append a row to the 'Today's Activity Log' table.

    Row format: | HH:MM | {action} | {details} | {result} |
    Removes placeholder row on first real entry.
    Triggers rollover when table reaches 50 real rows.
    """
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Today's Activity Log")
    if section_idx == -1:
        raise ValueError("Section \"Today's Activity Log\" not found in Dashboard.md")

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    real_rows = [r for r in rows if not _is_placeholder_row(r)]

    # Trigger rollover if at capacity
    if len(real_rows) >= 50:
        rollover_activity_log(vault_path)
        content = _read_dashboard(vault_path)
        sections = _parse_sections(content)
        headers, rows = _find_table_in_section(sections[section_idx]["content"])
        real_rows = [r for r in rows if not _is_placeholder_row(r)]

    now = datetime.now(tz=timezone.utc).strftime("%H:%M")
    new_row = [
        now,
        action.replace("|", "\\|"),
        details[:80].replace("|", "\\|"),
        result.replace("|", "\\|"),
    ]
    real_rows.append(new_row)

    new_table = _rebuild_table(headers, real_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def add_pending_action(
    vault_path: Path,
    item_type: str,
    sender: str,
    subject: str,
    priority: str,
    waiting_since: str,
) -> None:
    """
    Add a row to the 'Pending Actions' table.
    Row format: | {#} | {type} | {sender} | {subject} | {priority} | {waiting_since} |
    """
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Pending Actions")
    if section_idx == -1:
        raise ValueError("Section 'Pending Actions' not found in Dashboard.md")

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    real_rows = [r for r in rows if not _is_placeholder_row(r)]

    next_num = len(real_rows) + 1
    new_row = [
        str(next_num),
        item_type.replace("|", "\\|"),
        sender.replace("|", "\\|"),
        subject[:80].replace("|", "\\|"),
        priority.replace("|", "\\|"),
        waiting_since.replace("|", "\\|"),
    ]
    real_rows.append(new_row)

    new_table = _rebuild_table(headers, real_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def remove_pending_action(
    vault_path: Path,
    row_identifier: str,
) -> None:
    """Remove a row from Pending Actions by subject or # column match."""
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Pending Actions")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])

    filtered: list[list[str]] = []
    for row in rows:
        if _is_placeholder_row(row):
            continue
        # row[0] = #, row[3] = subject
        subject_match = len(row) >= 4 and row_identifier.lower() in row[3].lower()
        num_match = row[0].strip() == row_identifier.strip()
        if subject_match or num_match:
            continue  # Remove this row
        filtered.append(row)

    # Restore placeholder if no real rows remain
    if not filtered:
        filtered = [["—", "—", "—", "—", "—", "—"]]

    new_table = _rebuild_table(headers, filtered)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def update_queue_counts(vault_path: Path) -> None:
    """
    Refresh the 'Queue Summary' table by scanning the filesystem.
    Counts .md files (exclude .gitkeep). 'Done (today)' uses modified date.
    """
    # Inline count to avoid circular import concerns
    today = datetime.now(tz=timezone.utc).date()

    def _count(folder: Path) -> int:
        if not folder.is_dir():
            return 0
        return sum(1 for f in folder.rglob("*.md") if f.name != ".gitkeep")

    def _count_today(folder: Path) -> int:
        if not folder.is_dir():
            return 0
        c = 0
        for f in folder.rglob("*.md"):
            if f.name == ".gitkeep":
                continue
            if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).date() == today:
                c += 1
        return c

    counts = {
        "Needs_Action": _count(vault_path / "Needs_Action"),
        "Plans": _count(vault_path / "Plans"),
        "Pending_Approval": _count(vault_path / "Pending_Approval"),
        "In_Progress": _count(vault_path / "In_Progress"),
        "Done_today": _count_today(vault_path / "Done"),
    }

    def _resolve(cell: str) -> int | None:
        c = cell.strip()
        if "Needs_Action" in c:
            return counts["Needs_Action"]
        if "Pending_Approval" in c:
            return counts["Pending_Approval"]
        if "Plans" in c:
            return counts["Plans"]
        if "In_Progress" in c or "In Progress" in c:
            return counts["In_Progress"]
        if "Done" in c:
            return counts["Done_today"]
        return None

    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Queue Summary")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    new_rows = []
    for row in rows:
        if row and len(row) >= 2:
            resolved = _resolve(row[0])
            if resolved is not None:
                row = [row[0], str(resolved)]
        new_rows.append(row)

    new_table = _rebuild_table(headers, new_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def update_system_health(
    vault_path: Path,
    component: str,
    status: str,
    last_check: str | None = None,
) -> None:
    """
    Update a specific component's row in the 'System Health' table.
    Matches by component name (case-insensitive).
    """
    if last_check is None:
        last_check = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "System Health")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    new_rows = []
    for row in rows:
        if row and len(row) >= 1 and component.lower() in row[0].lower():
            # Extend row if needed, then update Status and Last Check columns
            while len(row) < 3:
                row.append("—")
            row = [row[0], status, last_check]
        new_rows.append(row)

    new_table = _rebuild_table(headers, new_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def add_error(
    vault_path: Path,
    component: str,
    error: str,
    resolution: str = "Pending",
) -> None:
    """
    Add a row to 'Recent Errors' table.
    Auto-clear errors older than 7 days on each call.
    """
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Recent Errors")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])

    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=7)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    # Keep rows younger than 7 days; remove placeholder rows
    valid_rows: list[list[str]] = []
    for row in rows:
        if _is_placeholder_row(row):
            continue
        if row and len(row) >= 1:
            try:
                row_time = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc
                )
                if row_time < cutoff:
                    continue  # Drop old error
            except ValueError:
                pass  # Can't parse time → keep the row
        valid_rows.append(row)

    new_row = [
        now_str,
        component.replace("|", "\\|"),
        error[:80].replace("|", "\\|"),
        resolution.replace("|", "\\|"),
    ]
    valid_rows.append(new_row)

    new_table = _rebuild_table(headers, valid_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def update_weekly_stats(
    vault_path: Path,
    metric: str,
    this_week: int | str,
) -> None:
    """
    Update a specific metric in the 'Weekly Stats' table.
    Match by metric name. Only update 'This Week' column.
    """
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Weekly Stats")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    new_rows = []
    for row in rows:
        if row and len(row) >= 1 and metric.lower() in row[0].lower():
            while len(row) < 3:
                row.append("0")
            row = [row[0], str(this_week), row[2]]  # Preserve Last Week
        new_rows.append(row)

    new_table = _rebuild_table(headers, new_rows)
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))
    update_timestamp(vault_path)


def rollover_activity_log(vault_path: Path) -> None:
    """
    Archive current activity log entries to /Logs/dashboard_archive_YYYY-MM-DD.json.
    Clear the activity log table (keep header + placeholder row).
    """
    content = _read_dashboard(vault_path)
    sections = _parse_sections(content)

    section_idx = _find_section(sections, "Today's Activity Log")
    if section_idx == -1:
        return

    headers, rows = _find_table_in_section(sections[section_idx]["content"])
    real_rows = [r for r in rows if not _is_placeholder_row(r)]

    if real_rows:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        archive_data = [
            {headers[i] if i < len(headers) else str(i): (cell if i < len(r) else "")
             for i, cell in enumerate(r)}
            for r in real_rows
        ]

        log_dir = vault_path / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        archive_file = log_dir / f"dashboard_archive_{today}.json"

        if archive_file.exists():
            try:
                existing = json.loads(archive_file.read_text(encoding="utf-8"))
                archive_data = existing + archive_data
            except (json.JSONDecodeError, OSError):
                pass

        tmp_fd, tmp_path = tempfile.mkstemp(dir=log_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(archive_data, f, indent=2, ensure_ascii=False)
            Path(tmp_path).replace(archive_file)
        except Exception:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # Clear table — keep header row + placeholder
    placeholder = ["—"] * len(headers)
    new_table = _rebuild_table(headers, [placeholder])
    sections[section_idx]["content"] = _replace_table_in_content(
        sections[section_idx]["content"], new_table
    )

    _write_dashboard(vault_path, _reassemble_dashboard(sections))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Dashboard Updater CLI")
    subparsers = parser.add_subparsers(dest="command")

    # add-activity
    aa = subparsers.add_parser("add-activity")
    aa.add_argument("action")
    aa.add_argument("details")
    aa.add_argument("result")

    # update-counts
    subparsers.add_parser("update-counts")

    # add-pending
    ap = subparsers.add_parser("add-pending")
    ap.add_argument("--type", required=True, dest="item_type")
    ap.add_argument("--from", dest="sender", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--priority", default="medium")
    ap.add_argument("--waiting-since", default=datetime.now(tz=timezone.utc).isoformat())

    # update-health
    uh = subparsers.add_parser("update-health")
    uh.add_argument("component")
    uh.add_argument("status")

    # add-error
    ae = subparsers.add_parser("add-error")
    ae.add_argument("component")
    ae.add_argument("error")
    ae.add_argument("--resolution", default="Pending")

    # rollover
    subparsers.add_parser("rollover")

    args = parser.parse_args()
    vault_path = Path(os.getenv("VAULT_PATH", "."))

    if args.command == "add-activity":
        add_activity_log(vault_path, args.action, args.details, args.result)
        print("Activity log updated.")

    elif args.command == "update-counts":
        update_queue_counts(vault_path)
        print("Queue counts updated.")

    elif args.command == "add-pending":
        add_pending_action(
            vault_path,
            item_type=args.item_type,
            sender=args.sender,
            subject=args.subject,
            priority=args.priority,
            waiting_since=args.waiting_since,
        )
        print("Pending action added.")

    elif args.command == "update-health":
        update_system_health(vault_path, args.component, args.status)
        print(f"Health updated for '{args.component}'.")

    elif args.command == "add-error":
        add_error(vault_path, args.component, args.error, resolution=args.resolution)
        print("Error logged.")

    elif args.command == "rollover":
        rollover_activity_log(vault_path)
        print("Activity log rolled over.")

    else:
        parser.print_help()
        sys.exit(1)
