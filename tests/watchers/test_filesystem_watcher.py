"""Unit tests for FileSystemWatcher."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.utils.vault_helpers import read_frontmatter
from scripts.watchers.filesystem_watcher import FileSystemWatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def drop_folder(tmp_vault):
    """Create /Drop/ with sample files."""
    drop = tmp_vault / "Drop"
    drop.mkdir(exist_ok=True)
    (drop / "Invoice_Jan_2026.pdf").write_bytes(b"%PDF-1.4 fake pdf")
    (drop / "report.csv").write_text("name,amount\nAlice,100\nBob,200")
    (drop / "screenshot.png").write_bytes(b"\x89PNG fake image")
    (drop / ".DS_Store").write_bytes(b"ignored")
    return drop


def _make_live_watcher(tmp_vault: Path, **kwargs) -> FileSystemWatcher:
    """Instantiate FileSystemWatcher with DRY_RUN=false."""
    with patch.dict("os.environ", {"DRY_RUN": "false"}):
        return FileSystemWatcher(tmp_vault, **kwargs)


def _make_dry_watcher(tmp_vault: Path, **kwargs) -> FileSystemWatcher:
    """Instantiate FileSystemWatcher with DRY_RUN=true."""
    with patch.dict("os.environ", {"DRY_RUN": "true"}):
        return FileSystemWatcher(tmp_vault, **kwargs)


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_drop_folder(self, tmp_path):
        """Drop folder is created if it does not exist."""
        watcher = _make_live_watcher(tmp_path, drop_folder="MyDrop", copy_originals=False)
        assert (tmp_path / "MyDrop").is_dir()

    def test_init_creates_attachments_folder(self, tmp_vault):
        """/Needs_Action/file/attachments/ is created on init."""
        _make_live_watcher(tmp_vault, copy_originals=False)
        assert (tmp_vault / "Needs_Action" / "file" / "attachments").is_dir()


# ---------------------------------------------------------------------------
# check_for_updates tests
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    def test_check_for_updates_finds_files(self, tmp_vault, drop_folder):
        """Detects new files in the Drop folder."""
        watcher = _make_live_watcher(tmp_vault)
        items = watcher.check_for_updates()
        sources = [i["source"] for i in items]
        assert "Invoice_Jan_2026.pdf" in sources
        assert "report.csv" in sources
        assert "screenshot.png" in sources

    def test_check_for_updates_filters_extensions(self, tmp_vault, drop_folder):
        """Only files with watched extensions are returned."""
        (drop_folder / "data.xyz").write_text("not watched")
        watcher = _make_live_watcher(tmp_vault, watch_extensions=[".csv"])
        items = watcher.check_for_updates()
        assert all(i["file_extension"] == ".csv" for i in items)
        assert len(items) == 1

    def test_check_for_updates_ignores_patterns(self, tmp_vault, drop_folder):
        """Files matching ignore patterns are skipped."""
        (drop_folder / "temp.tmp").write_text("temp")
        (drop_folder / ".gitkeep").write_bytes(b"")
        watcher = _make_live_watcher(tmp_vault)
        items = watcher.check_for_updates()
        sources = [i["source"] for i in items]
        assert ".DS_Store" not in sources
        assert "temp.tmp" not in sources
        assert ".gitkeep" not in sources

    def test_check_for_updates_skips_directories(self, tmp_vault, drop_folder):
        """Subdirectories inside /Drop/ are skipped."""
        (drop_folder / "subdir").mkdir()
        watcher = _make_live_watcher(tmp_vault)
        items = watcher.check_for_updates()
        assert all(Path(i["original_path"]).name != "subdir" for i in items)

    def test_check_for_updates_dry_run(self, tmp_vault):
        """DRY_RUN returns exactly 3 sample items."""
        watcher = _make_dry_watcher(tmp_vault)
        items = watcher.check_for_updates()
        assert len(items) == 3
        extensions = {i["file_extension"] for i in items}
        assert ".pdf" in extensions
        assert ".csv" in extensions
        assert ".png" in extensions


# ---------------------------------------------------------------------------
# create_action_file tests
# ---------------------------------------------------------------------------


class TestCreateActionFile:
    def _make_item(
        self,
        drop_folder: Path,
        filename: str = "test_file.pdf",
    ) -> dict:
        """Build a minimal item dict for a file in the drop folder."""
        file_path = drop_folder / filename
        if not file_path.exists():
            file_path.write_bytes(b"%PDF-1.4 fake")
        return {
            "id": str(file_path.resolve()),
            "type": "file_drop",
            "source": filename,
            "subject": f"File dropped: {filename}",
            "content": "PDF document — use PDF reader for content",
            "received": "2026-02-27T09:00:00",
            "priority": "high",
            "requires_approval": False,
            "file_size": 14,
            "file_extension": ".pdf",
            "file_mime_type": "application/pdf",
            "original_path": str(file_path),
        }

    def test_create_action_file_writes_md(self, tmp_vault, drop_folder):
        """.md file is created inside Needs_Action/file/."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        item = self._make_item(drop_folder)
        result = watcher.create_action_file(item)
        assert result.exists()
        assert result.suffix == ".md"
        assert result.parent == tmp_vault / "Needs_Action" / "file"

    def test_create_action_file_copies_original(self, tmp_vault, drop_folder):
        """Original file is copied to attachments/ when copy_originals=True."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=True)
        item = self._make_item(drop_folder, "Invoice_Jan_2026.pdf")
        watcher.create_action_file(item)
        assert (watcher.attachments_path / "Invoice_Jan_2026.pdf").exists()

    def test_create_action_file_no_copy_mode(self, tmp_vault, drop_folder):
        """Original is NOT copied when copy_originals=False."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        item = self._make_item(drop_folder)
        watcher.create_action_file(item)
        assert not list(watcher.attachments_path.iterdir())

    def test_create_action_file_frontmatter_complete(self, tmp_vault, drop_folder):
        """All required frontmatter fields are present and correct."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        item = self._make_item(drop_folder)
        result = watcher.create_action_file(item)
        fm = read_frontmatter(result)
        required_fields = [
            "type", "source", "subject", "received", "priority",
            "status", "requires_approval", "file_size", "file_extension",
            "file_mime_type", "attachment_path", "original_path",
        ]
        for field in required_fields:
            assert field in fm, f"Missing frontmatter field: {field}"
        assert fm["type"] == "file_drop"
        assert fm["status"] == "pending"
        assert fm["requires_approval"] is False


# ---------------------------------------------------------------------------
# _extract_preview tests
# ---------------------------------------------------------------------------


class TestExtractPreview:
    def test_extract_preview_text_file(self, tmp_vault):
        """First 500 chars extracted from text files."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        text_file = tmp_vault / "Drop" / "sample.txt"
        text_file.write_text("A" * 600, encoding="utf-8")
        preview = watcher._extract_preview(text_file)
        assert preview == "A" * 500

    def test_extract_preview_binary_file(self, tmp_vault):
        """Unknown/binary files get a generic message."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        bin_file = tmp_vault / "Drop" / "app.exe"
        bin_file.write_bytes(b"\x00\x01\x02\x03")
        preview = watcher._extract_preview(bin_file)
        assert "binary" in preview.lower() or "no preview" in preview.lower()

    def test_extract_preview_pdf(self, tmp_vault):
        """PDF files return the PDF descriptor message."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        pdf = tmp_vault / "Drop" / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        assert "PDF" in watcher._extract_preview(pdf)

    def test_extract_preview_image(self, tmp_vault):
        """Image files return the image descriptor message."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        img = tmp_vault / "Drop" / "photo.png"
        img.write_bytes(b"\x89PNG")
        assert "Image" in watcher._extract_preview(img)

    def test_extract_preview_empty_file(self, tmp_vault):
        """Empty files return 'Empty file'."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        empty = tmp_vault / "Drop" / "empty.txt"
        empty.write_bytes(b"")
        assert "Empty" in watcher._extract_preview(empty)


# ---------------------------------------------------------------------------
# _classify_file_priority tests
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    def test_classify_priority_invoice_pdf(self, tmp_vault):
        """PDF with 'invoice' in name → high priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "Invoice_Q1_2026.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert watcher._classify_file_priority(f) == "high"

    def test_classify_priority_invoice_xlsx(self, tmp_vault):
        """XLSX with 'invoice' in name → high priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "invoice_summary.xlsx"
        f.write_bytes(b"PK fake xlsx")
        assert watcher._classify_file_priority(f) == "high"

    def test_classify_priority_urgent_name(self, tmp_vault):
        """File with 'urgent' in name → high priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "urgent_report.csv"
        f.write_text("data")
        assert watcher._classify_file_priority(f) == "high"

    def test_classify_priority_asap_name(self, tmp_vault):
        """File with 'asap' in name → high priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "asap_fix.txt"
        f.write_text("fix this")
        assert watcher._classify_file_priority(f) == "high"

    def test_classify_priority_default(self, tmp_vault):
        """Regular file → medium priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "report.csv"
        f.write_text("data,value\n1,2")
        assert watcher._classify_file_priority(f) == "medium"

    def test_classify_priority_empty_file(self, tmp_vault):
        """Empty file → low priority."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        f = tmp_vault / "Drop" / "empty.txt"
        f.write_bytes(b"")
        assert watcher._classify_file_priority(f) == "low"


# ---------------------------------------------------------------------------
# _format_file_size tests
# ---------------------------------------------------------------------------


class TestFormatFileSize:
    def test_format_file_size_bytes(self, tmp_vault):
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        assert "B" in watcher._format_file_size(500)

    def test_format_file_size_kb(self, tmp_vault):
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        result = watcher._format_file_size(1536)
        assert "KB" in result
        assert "1.5" in result

    def test_format_file_size_mb(self, tmp_vault):
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        result = watcher._format_file_size(1_572_864)  # 1.5 MB
        assert "MB" in result
        assert "1.5" in result

    def test_format_file_size_gb(self, tmp_vault):
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        result = watcher._format_file_size(2_147_483_648)  # 2.0 GB
        assert "GB" in result


# ---------------------------------------------------------------------------
# _wait_for_stable tests
# ---------------------------------------------------------------------------


class TestWaitForStable:
    def test_wait_for_stable_returns_true_when_stable(self, tmp_vault):
        """File with stable size returns True once 1 s has elapsed without change."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        test_file = tmp_vault / "Drop" / "stable.txt"
        test_file.write_text("hello world")

        # time calls (in order):
        #   1. deadline = time.time() + 10  → 0 + 10 = 10
        #   2. last_change = time.time()    → 0
        #   3. while time.time() < deadline → 0.5 < 10, True (enter loop)
        #   4. time.time() - last_change    → 1.5 - 0 = 1.5 >= 1.0 → return True
        with patch("time.sleep"), patch("time.time", side_effect=[0, 0, 0.5, 1.5]):
            result = watcher._wait_for_stable(test_file, timeout=10)
        assert result is True

    def test_wait_for_stable_returns_false_on_timeout(self, tmp_vault):
        """Returns False when deadline is exceeded before file stabilises."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        test_file = tmp_vault / "Drop" / "slow.txt"
        test_file.write_text("data")

        # time calls:
        #   1. deadline = 0 + 10 = 10
        #   2. last_change = 0
        #   3. while 11 < 10 → False → skip loop → return False
        with patch("time.sleep"), patch("time.time", side_effect=[0, 0, 11]):
            result = watcher._wait_for_stable(test_file, timeout=10)
        assert result is False

    def test_wait_for_stable_missing_file(self, tmp_vault):
        """Missing file returns False immediately."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        missing = tmp_vault / "Drop" / "nonexistent.pdf"
        result = watcher._wait_for_stable(missing)
        assert result is False


# ---------------------------------------------------------------------------
# .gitkeep is never processed
# ---------------------------------------------------------------------------


class TestIgnoreGitkeep:
    def test_ignore_gitkeep(self, tmp_vault):
        """.gitkeep is never returned by check_for_updates."""
        (tmp_vault / "Drop" / ".gitkeep").write_bytes(b"")
        watcher = _make_live_watcher(tmp_vault)
        items = watcher.check_for_updates()
        assert all(i["source"] != ".gitkeep" for i in items)


# ---------------------------------------------------------------------------
# End-to-end and deduplication
# ---------------------------------------------------------------------------


class TestRunOnceEndToEnd:
    def test_run_once_end_to_end(self, tmp_vault, drop_folder):
        """Full cycle: files detected → .md files created in Needs_Action/file/."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=True)
        created = watcher.run_once()
        # 3 watchable files (pdf, csv, png); .DS_Store is ignored
        assert len(created) >= 3
        for p in created:
            assert p.exists()
            assert p.suffix == ".md"
            assert p.parent == tmp_vault / "Needs_Action" / "file"

    def test_deduplication(self, tmp_vault, drop_folder):
        """Same file is not processed twice across two run_once() calls."""
        watcher = _make_live_watcher(tmp_vault, copy_originals=False)
        first = watcher.run_once()
        second = watcher.run_once()
        assert len(first) >= 1
        assert len(second) == 0
