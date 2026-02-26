"""Unit tests for scripts/utils/vault_helpers.py."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.utils.vault_helpers import (
    append_json_log,
    is_dry_run,
    read_frontmatter,
    sanitize_filename,
    write_action_file,
)


class TestWriteActionFile:
    def test_write_action_file_creates_md(self, tmp_path):
        fm = {"type": "email", "source": "test@example.com", "status": "pending"}
        body = "This is the body."
        path = write_action_file(tmp_path, "test_file.md", fm, body)

        assert path.exists()
        assert path.suffix == ".md"
        content = path.read_text(encoding="utf-8")
        assert "---" in content
        assert "type: email" in content
        assert body in content

    def test_write_action_file_handles_duplicates(self, tmp_path):
        fm = {"type": "email"}
        body = "Body"
        p1 = write_action_file(tmp_path, "dupe.md", fm, body)
        p2 = write_action_file(tmp_path, "dupe.md", fm, body)
        p3 = write_action_file(tmp_path, "dupe.md", fm, body)

        assert p1.name == "dupe.md"
        assert p2.name == "dupe_1.md"
        assert p3.name == "dupe_2.md"
        assert p1.exists() and p2.exists() and p3.exists()

    def test_write_action_file_creates_directory(self, tmp_path):
        subdir = tmp_path / "new" / "deep" / "dir"
        result = write_action_file(subdir, "file.md", {}, "body")
        assert result.exists()

    def test_write_action_file_frontmatter_parseable(self, tmp_path):
        fm = {"priority": "high", "requires_approval": True}
        path = write_action_file(tmp_path, "fm_test.md", fm, "body")
        parsed = read_frontmatter(path)
        assert parsed["priority"] == "high"
        assert parsed["requires_approval"] is True


class TestSanitizeFilename:
    def test_sanitize_removes_illegal_chars(self):
        raw = 'file/name\\with:illegal*chars?"<>|.md'
        result = sanitize_filename(raw)
        for ch in r'/\:*?"<>|':
            assert ch not in result

    def test_sanitize_replaces_spaces(self):
        result = sanitize_filename("hello world file.md")
        assert " " not in result
        assert "hello_world_file.md" == result

    def test_sanitize_truncates_long_names(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=200)
        assert len(result) == 200

    def test_sanitize_custom_max_length(self):
        result = sanitize_filename("abcdefghij", max_length=5)
        assert len(result) == 5

    def test_sanitize_unicode_stripped(self):
        result = sanitize_filename("café résumé")
        # Non-ASCII characters should be removed or transliterated
        assert all(ord(c) < 128 for c in result)

    def test_sanitize_empty_string(self):
        result = sanitize_filename("")
        assert result == ""


class TestAppendJsonLog:
    def test_append_json_log_creates_new_file(self, tmp_path):
        entry = {"event": "test", "value": 42}
        append_json_log(tmp_path, entry)

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = tmp_path / f"{today}.json"
        assert log_file.exists()

        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data == [entry]

    def test_append_json_log_appends_to_existing(self, tmp_path):
        e1 = {"n": 1}
        e2 = {"n": 2}
        append_json_log(tmp_path, e1)
        append_json_log(tmp_path, e2)

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        data = json.loads((tmp_path / f"{today}.json").read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0] == e1
        assert data[1] == e2

    def test_append_json_log_creates_directory(self, tmp_path):
        log_dir = tmp_path / "deep" / "logs"
        append_json_log(log_dir, {"k": "v"})
        assert log_dir.is_dir()


class TestReadFrontmatter:
    def test_read_frontmatter_parses_yaml(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\ntype: email\npriority: high\n---\n\nBody here.", encoding="utf-8")
        result = read_frontmatter(md)
        assert result["type"] == "email"
        assert result["priority"] == "high"

    def test_read_frontmatter_no_frontmatter_returns_empty(self, tmp_path):
        md = tmp_path / "plain.md"
        md.write_text("No frontmatter here at all.", encoding="utf-8")
        result = read_frontmatter(md)
        assert result == {}

    def test_read_frontmatter_missing_file_returns_empty(self, tmp_path):
        result = read_frontmatter(tmp_path / "nonexistent.md")
        assert result == {}

    def test_read_frontmatter_empty_frontmatter(self, tmp_path):
        md = tmp_path / "empty_fm.md"
        md.write_text("---\n---\n\nBody.", encoding="utf-8")
        result = read_frontmatter(md)
        # Empty YAML block → None → returns {}
        assert result == {}


class TestIsDryRun:
    def test_is_dry_run_defaults_true(self):
        with patch.dict("os.environ", {}, clear=True):
            # Remove DRY_RUN from env entirely
            import os
            os.environ.pop("DRY_RUN", None)
            assert is_dry_run() is True

    def test_is_dry_run_reads_env_false(self):
        with patch.dict("os.environ", {"DRY_RUN": "false"}):
            assert is_dry_run() is False

    def test_is_dry_run_reads_env_true(self):
        with patch.dict("os.environ", {"DRY_RUN": "true"}):
            assert is_dry_run() is True

    def test_is_dry_run_case_insensitive(self):
        with patch.dict("os.environ", {"DRY_RUN": "FALSE"}):
            assert is_dry_run() is False
        with patch.dict("os.environ", {"DRY_RUN": "TRUE"}):
            assert is_dry_run() is True
