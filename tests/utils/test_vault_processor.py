"""Unit tests for scripts/utils/vault_processor.py."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.utils.vault_processor import (
    archive_done,
    get_queue_counts,
    list_folder,
    list_pending,
    move_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_md_file(directory: Path, filename: str, frontmatter: dict, body: str = "Body text.") -> Path:
    """Create a .md file with YAML frontmatter in the given directory."""
    directory.mkdir(parents=True, exist_ok=True)
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n{body}"
    file_path = directory / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_vault(tmp_vault):
    """tmp vault with 5 sample .md files in Needs_Action/email/."""
    email_dir = tmp_vault / "Needs_Action" / "email"

    make_md_file(email_dir, "EMAIL_001.md", {
        "type": "email", "source": "a@example.com", "subject": "Critical Issue",
        "received": "2026-02-26T08:00:00+00:00", "priority": "critical",
        "status": "pending", "requires_approval": False,
    })
    make_md_file(email_dir, "EMAIL_002.md", {
        "type": "email", "source": "b@example.com", "subject": "High Priority Task",
        "received": "2026-02-26T09:00:00+00:00", "priority": "high",
        "status": "pending", "requires_approval": False,
    })
    make_md_file(email_dir, "EMAIL_003.md", {
        "type": "email", "source": "c@example.com", "subject": "Regular Update",
        "received": "2026-02-26T10:00:00+00:00", "priority": "medium",
        "status": "pending", "requires_approval": True,
    })
    make_md_file(email_dir, "EMAIL_004.md", {
        "type": "email", "source": "d@example.com", "subject": "Newsletter",
        "received": "2026-02-26T11:00:00+00:00", "priority": "low",
        "status": "pending", "requires_approval": False,
    })
    # Second critical — older received timestamp, should sort before the first critical
    make_md_file(email_dir, "EMAIL_005.md", {
        "type": "email", "source": "e@example.com", "subject": "Urgent Follow-up",
        "received": "2026-02-26T07:00:00+00:00", "priority": "critical",
        "status": "pending", "requires_approval": True,
    })
    # .gitkeep must be skipped
    (email_dir / ".gitkeep").write_text("", encoding="utf-8")

    return tmp_vault


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


class TestListPending:
    def test_list_pending_returns_all_items(self, populated_vault):
        items = list_pending(populated_vault)
        assert len(items) == 5

    def test_list_pending_filters_by_subdomain(self, populated_vault):
        # Add a whatsapp item
        wp_dir = populated_vault / "Needs_Action" / "whatsapp"
        make_md_file(wp_dir, "WHATSAPP_001.md", {"type": "whatsapp", "priority": "low"})

        items = list_pending(populated_vault, subdomain="email")
        assert len(items) == 5
        assert all(item["subdomain"] == "email" for item in items)

    def test_list_pending_sorted_by_priority(self, populated_vault):
        items = list_pending(populated_vault)
        priorities = [item["frontmatter"].get("priority") for item in items]
        assert priorities[0] == "critical"
        assert priorities[1] == "critical"
        assert priorities[2] == "high"
        assert priorities[3] == "medium"
        assert priorities[4] == "low"

    def test_list_pending_sorted_critical_by_received(self, populated_vault):
        """Among two critical items, older received timestamp comes first."""
        items = list_pending(populated_vault)
        critical_items = [i for i in items if i["frontmatter"].get("priority") == "critical"]
        assert len(critical_items) == 2
        # EMAIL_005 received at 07:00 < EMAIL_001 received at 08:00 → 005 should be first
        assert critical_items[0]["frontmatter"]["received"] < critical_items[1]["frontmatter"]["received"]

    def test_list_pending_includes_frontmatter(self, populated_vault):
        items = list_pending(populated_vault)
        for item in items:
            assert "frontmatter" in item
            assert isinstance(item["frontmatter"], dict)
            assert "type" in item["frontmatter"]

    def test_list_pending_empty_folder(self, tmp_vault):
        (tmp_vault / "Needs_Action" / "email").mkdir(parents=True, exist_ok=True)
        items = list_pending(tmp_vault, subdomain="email")
        assert items == []

    def test_list_pending_skips_gitkeep(self, populated_vault):
        items = list_pending(populated_vault)
        assert all(item["filename"] != ".gitkeep" for item in items)

    def test_list_pending_skips_non_md(self, tmp_vault):
        email_dir = tmp_vault / "Needs_Action" / "email"
        email_dir.mkdir(parents=True, exist_ok=True)
        (email_dir / "attachment.pdf").write_bytes(b"PDF content")
        make_md_file(email_dir, "EMAIL_001.md", {"priority": "low"})

        items = list_pending(tmp_vault)
        assert len(items) == 1

    def test_list_pending_no_needs_action_dir(self, tmp_path):
        """Returns empty list if Needs_Action doesn't exist."""
        items = list_pending(tmp_path)
        assert items == []

    def test_list_pending_includes_path_and_filename(self, populated_vault):
        items = list_pending(populated_vault, subdomain="email")
        for item in items:
            assert "path" in item
            assert "filename" in item
            assert "subdomain" in item
            assert "created" in item
            assert item["filename"].endswith(".md")


# ---------------------------------------------------------------------------
# list_folder
# ---------------------------------------------------------------------------


class TestListFolder:
    def test_list_folder_works_for_any_folder(self, tmp_vault):
        plans_dir = tmp_vault / "Plans"
        make_md_file(plans_dir, "PLAN_001.md", {"type": "task", "priority": "high"})
        make_md_file(plans_dir, "PLAN_002.md", {"type": "task", "priority": "low"})

        items = list_folder(tmp_vault, "Plans")
        assert len(items) == 2

    def test_list_folder_nonexistent_returns_empty(self, tmp_vault):
        items = list_folder(tmp_vault, "NonExistentFolder")
        assert items == []

    def test_list_folder_skips_gitkeep(self, tmp_vault):
        done_dir = tmp_vault / "Done"
        (done_dir / ".gitkeep").write_text("", encoding="utf-8")
        make_md_file(done_dir, "TASK_001.md", {"priority": "low"})

        items = list_folder(tmp_vault, "Done")
        assert len(items) == 1
        assert items[0]["filename"] != ".gitkeep"

    def test_list_folder_returns_same_structure(self, tmp_vault):
        plans_dir = tmp_vault / "Plans"
        make_md_file(plans_dir, "PLAN_001.md", {"priority": "medium", "subject": "Test Plan"})

        items = list_folder(tmp_vault, "Plans")
        assert len(items) == 1
        assert "path" in items[0]
        assert "filename" in items[0]
        assert "subdomain" in items[0]
        assert "frontmatter" in items[0]
        assert "created" in items[0]


# ---------------------------------------------------------------------------
# move_file
# ---------------------------------------------------------------------------


class TestMoveFile:
    def test_move_file_to_done(self, populated_vault):
        source = "Needs_Action/email/EMAIL_001.md"
        new_path = move_file(populated_vault, source, "Done")

        assert new_path.exists()
        assert new_path.parent == populated_vault / "Done"
        assert not (populated_vault / source).exists()

    def test_move_file_updates_status(self, populated_vault):
        source = "Needs_Action/email/EMAIL_001.md"
        new_path = move_file(populated_vault, source, "Done")

        content = new_path.read_text(encoding="utf-8")
        assert "status: done" in content

    def test_move_file_updates_status_rejected(self, populated_vault):
        source = "Needs_Action/email/EMAIL_002.md"
        new_path = move_file(populated_vault, source, "Rejected")

        content = new_path.read_text(encoding="utf-8")
        assert "status: rejected" in content

    def test_move_file_updates_status_plans(self, populated_vault):
        source = "Needs_Action/email/EMAIL_003.md"
        new_path = move_file(populated_vault, source, "Plans")

        content = new_path.read_text(encoding="utf-8")
        assert "status: in_progress" in content

    def test_move_file_handles_name_collision(self, populated_vault):
        """If filename exists in destination, append _1 suffix."""
        # Move EMAIL_001 to Done
        move_file(populated_vault, "Needs_Action/email/EMAIL_001.md", "Done")
        # Place a file with same name in Done manually
        make_md_file(
            populated_vault / "Done", "EMAIL_002.md", {"type": "email", "status": "done"}
        )
        # Now move EMAIL_002 — it should become EMAIL_002_1.md
        new_path = move_file(populated_vault, "Needs_Action/email/EMAIL_002.md", "Done")
        assert new_path.name == "EMAIL_002_1.md"
        assert new_path.exists()

    def test_move_file_logs_action(self, populated_vault):
        source = "Needs_Action/email/EMAIL_001.md"
        move_file(populated_vault, source, "Done")

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = populated_vault / "Logs" / f"{today}.json"
        assert log_file.exists()

        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["action_type"] == "file_move"
        assert data[0]["result"] == "success"

    def test_move_file_atomic(self, populated_vault):
        """Source not deleted until copy is confirmed."""
        source_relative = "Needs_Action/email/EMAIL_001.md"
        source_path = populated_vault / source_relative

        import shutil as shutil_module
        original_copy2 = shutil_module.copy2

        def failing_copy2(src, dst):
            raise OSError("Simulated copy failure")

        with patch("scripts.utils.vault_processor.shutil.copy2", side_effect=failing_copy2):
            with pytest.raises(OSError, match="Simulated copy failure"):
                move_file(populated_vault, source_relative, "Done")

        # Source must still exist after failed copy
        assert source_path.exists()

    def test_move_file_nonexistent_raises(self, tmp_vault):
        with pytest.raises(FileNotFoundError):
            move_file(tmp_vault, "Needs_Action/email/NONEXISTENT.md", "Done")

    def test_move_file_preserves_filename(self, populated_vault):
        source = "Needs_Action/email/EMAIL_001.md"
        new_path = move_file(populated_vault, source, "Done")
        assert new_path.name == "EMAIL_001.md"

    def test_move_file_creates_dest_folder(self, populated_vault):
        """Destination folder is created if it doesn't exist."""
        source = "Needs_Action/email/EMAIL_001.md"
        new_path = move_file(populated_vault, source, "CustomDestination")
        assert (populated_vault / "CustomDestination").is_dir()
        assert new_path.exists()


# ---------------------------------------------------------------------------
# get_queue_counts
# ---------------------------------------------------------------------------


class TestGetQueueCounts:
    def test_get_queue_counts(self, populated_vault):
        counts = get_queue_counts(populated_vault)

        assert "Needs_Action" in counts
        assert "Plans" in counts
        assert "Pending_Approval" in counts
        assert "In_Progress" in counts
        assert "Done_today" in counts

        assert counts["Needs_Action"] == 5
        assert counts["Plans"] == 0
        assert counts["Pending_Approval"] == 0

    def test_get_queue_counts_done_today_filter(self, tmp_vault):
        """Only files modified today count in Done_today."""
        done_dir = tmp_vault / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)

        # Create a file (modified today by default)
        today_file = make_md_file(done_dir, "TODAY.md", {"priority": "low"})

        # Create an "old" file by setting mtime to 30 days ago
        old_file = make_md_file(done_dir, "OLD.md", {"priority": "low"})
        old_mtime = datetime.now(tz=timezone.utc).timestamp() - (30 * 86400)
        import os as _os
        _os.utime(str(old_file), (old_mtime, old_mtime))

        counts = get_queue_counts(tmp_vault)
        assert counts["Done_today"] == 1

    def test_get_queue_counts_excludes_gitkeep(self, tmp_vault):
        (tmp_vault / "Plans" / ".gitkeep").write_text("", encoding="utf-8")
        counts = get_queue_counts(tmp_vault)
        assert counts["Plans"] == 0

    def test_get_queue_counts_missing_folder_returns_zero(self, tmp_vault):
        """Non-existent folders return 0, not an error."""
        counts = get_queue_counts(tmp_vault)
        assert counts["In_Progress"] == 0


# ---------------------------------------------------------------------------
# archive_done
# ---------------------------------------------------------------------------


class TestArchiveDone:
    def test_archive_done_moves_old_files(self, tmp_vault):
        """Files older than threshold are moved to Done/archive/."""
        done_dir = tmp_vault / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)

        old_file = make_md_file(done_dir, "OLD_TASK.md", {"status": "done"})
        # Set mtime to 10 days ago
        old_mtime = datetime.now(tz=timezone.utc).timestamp() - (10 * 86400)
        import os as _os
        _os.utime(str(old_file), (old_mtime, old_mtime))

        count = archive_done(tmp_vault, older_than_days=7)

        assert count == 1
        assert not old_file.exists()
        assert (done_dir / "archive" / "OLD_TASK.md").exists()

    def test_archive_done_keeps_recent(self, tmp_vault):
        """Files modified recently are NOT archived."""
        done_dir = tmp_vault / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)
        make_md_file(done_dir, "RECENT.md", {"status": "done"})

        count = archive_done(tmp_vault, older_than_days=7)

        assert count == 0
        assert (done_dir / "RECENT.md").exists()

    def test_archive_done_returns_count(self, tmp_vault):
        done_dir = tmp_vault / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)

        import os as _os
        for i in range(3):
            f = make_md_file(done_dir, f"OLD_{i}.md", {"status": "done"})
            old_mtime = datetime.now(tz=timezone.utc).timestamp() - (14 * 86400)
            _os.utime(str(f), (old_mtime, old_mtime))

        count = archive_done(tmp_vault, older_than_days=7)
        assert count == 3

    def test_archive_done_handles_collision(self, tmp_vault):
        """Collision in archive folder gets _1 suffix."""
        done_dir = tmp_vault / "Done"
        archive_dir = done_dir / "archive"
        done_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Pre-place a file in archive
        make_md_file(archive_dir, "TASK.md", {"status": "done"})

        import os as _os
        # Place old file in Done with same name
        old_file = make_md_file(done_dir, "TASK.md", {"status": "done"})
        old_mtime = datetime.now(tz=timezone.utc).timestamp() - (10 * 86400)
        _os.utime(str(old_file), (old_mtime, old_mtime))

        count = archive_done(tmp_vault, older_than_days=7)
        assert count == 1
        assert (archive_dir / "TASK_1.md").exists()

    def test_archive_done_no_done_folder(self, tmp_path):
        """Returns 0 gracefully if Done folder doesn't exist."""
        count = archive_done(tmp_path, older_than_days=7)
        assert count == 0

    def test_archive_done_skips_gitkeep(self, tmp_vault):
        done_dir = tmp_vault / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / ".gitkeep").write_text("", encoding="utf-8")

        import os as _os
        gitkeep = done_dir / ".gitkeep"
        old_mtime = datetime.now(tz=timezone.utc).timestamp() - (30 * 86400)
        _os.utime(str(gitkeep), (old_mtime, old_mtime))

        count = archive_done(tmp_vault, older_than_days=7)
        assert count == 0
        assert gitkeep.exists()
