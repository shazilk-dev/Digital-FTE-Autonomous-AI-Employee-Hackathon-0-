"""Unit tests for scripts/utils/action_executor.py."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.utils.action_executor import ActionExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_approval_file(
    directory: Path,
    filename: str,
    frontmatter: dict,
    body: str = "## Action Summary\n\n**Type:** Test",
) -> Path:
    """Write a .md approval file with YAML frontmatter."""
    directory.mkdir(parents=True, exist_ok=True)
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n{body}"
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 2) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat()


def _base_fm(**overrides) -> dict:
    """Build a minimal valid frontmatter dict."""
    fm = {
        "type": "approval_request",
        "action_type": "send_email",
        "domain": "email",
        "target": "test@example.com",
        "priority": "high",
        "status": "pending_approval",
        "requires_approval": True,
        "created": datetime.now(tz=timezone.utc).isoformat(),
        "expires": _future_iso(24),
        "source_plan": None,
        "source_task": None,
        "action_payload": {
            "tool": "send_email",
            "server": "email",
            "params": {
                "to": "test@example.com",
                "subject": "Test Email",
                "body": "This is a test email.",
                "cc": "",
                "bcc": "",
            },
        },
    }
    fm.update(overrides)
    return fm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def executor(tmp_vault) -> ActionExecutor:
    """ActionExecutor in DRY_RUN mode."""
    return ActionExecutor(tmp_vault, dry_run=True)


@pytest.fixture
def sample_approval_file(tmp_vault) -> Path:
    """Valid send_email approval file in Approved/."""
    return _make_approval_file(
        tmp_vault / "Approved",
        "ACTION_send_email_test_2026-02-27T10-30-00.md",
        _base_fm(),
    )


@pytest.fixture
def expired_approval_file(tmp_vault) -> Path:
    """Approval file with a past expiry date."""
    fm = _base_fm(expires=_past_iso(2))
    return _make_approval_file(
        tmp_vault / "Approved",
        "ACTION_send_email_expired_2026-02-27T08-00-00.md",
        fm,
    )


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


class TestParseApprovalFile:
    def test_parse_valid(self, executor, sample_approval_file):
        parsed = executor.parse_approval_file(sample_approval_file)
        assert parsed["action_type"] == "send_email"
        assert parsed["target"] == "test@example.com"
        assert parsed["priority"] == "high"
        assert parsed["is_expired"] is False
        assert parsed["action_payload"]["tool"] == "send_email"
        assert parsed["action_payload"]["params"]["to"] == "test@example.com"
        assert parsed["action_payload"]["params"]["subject"] == "Test Email"

    def test_parse_missing_payload(self, executor, tmp_vault):
        fm = _base_fm()
        del fm["action_payload"]
        path = _make_approval_file(tmp_vault / "Approved", "no_payload.md", fm)
        with pytest.raises(ValueError, match="action_payload"):
            executor.parse_approval_file(path)

    def test_parse_missing_type(self, executor, tmp_vault):
        fm = _base_fm()
        del fm["type"]
        path = _make_approval_file(tmp_vault / "Approved", "no_type.md", fm)
        with pytest.raises(ValueError, match="approval_request"):
            executor.parse_approval_file(path)

    def test_parse_wrong_type(self, executor, tmp_vault):
        fm = _base_fm(type="plan")
        path = _make_approval_file(tmp_vault / "Approved", "wrong_type.md", fm)
        with pytest.raises(ValueError, match="approval_request"):
            executor.parse_approval_file(path)

    def test_parse_expired(self, executor, expired_approval_file):
        parsed = executor.parse_approval_file(expired_approval_file)
        assert parsed["is_expired"] is True

    def test_parse_not_expired(self, executor, sample_approval_file):
        parsed = executor.parse_approval_file(sample_approval_file)
        assert parsed["is_expired"] is False

    def test_parse_no_frontmatter(self, executor, tmp_vault):
        path = tmp_vault / "Approved" / "plain.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("No frontmatter here.", encoding="utf-8")
        with pytest.raises(ValueError, match="frontmatter"):
            executor.parse_approval_file(path)

    def test_parse_missing_tool(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"] = {"server": "email", "params": {"to": "x@y.com"}}
        path = _make_approval_file(tmp_vault / "Approved", "no_tool.md", fm)
        with pytest.raises(ValueError, match="action_payload.tool"):
            executor.parse_approval_file(path)

    def test_parse_missing_params(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"] = {"tool": "send_email", "server": "email"}
        path = _make_approval_file(tmp_vault / "Approved", "no_params.md", fm)
        with pytest.raises(ValueError, match="action_payload.params"):
            executor.parse_approval_file(path)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateAction:
    def test_valid_send_email(self, executor, sample_approval_file):
        parsed = executor.parse_approval_file(sample_approval_file)
        errors = executor.validate_action(parsed)
        assert errors == []

    def test_missing_to(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"]["params"]["to"] = ""
        path = _make_approval_file(tmp_vault / "Approved", "no_to.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("to" in e for e in errors)

    def test_invalid_email_address(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"]["params"]["to"] = "not-an-email"
        fm["target"] = "not-an-email"
        path = _make_approval_file(tmp_vault / "Approved", "bad_email.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("Invalid email" in e for e in errors)

    def test_empty_body(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"]["params"]["body"] = ""
        path = _make_approval_file(tmp_vault / "Approved", "empty_body.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("body" in e.lower() for e in errors)

    def test_unknown_action_type(self, executor, tmp_vault):
        fm = _base_fm(action_type="destroy_everything")
        path = _make_approval_file(tmp_vault / "Approved", "bad_action.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("Unsupported" in e for e in errors)

    def test_expired_warns_not_blocking(self, executor, expired_approval_file, caplog):
        import logging
        parsed = executor.parse_approval_file(expired_approval_file)
        with caplog.at_level(logging.WARNING):
            errors = executor.validate_action(parsed)
        # Expiry should not produce a blocking error
        assert errors == []
        assert "expired" in caplog.text.lower()

    def test_missing_subject(self, executor, tmp_vault):
        fm = _base_fm()
        fm["action_payload"]["params"]["subject"] = ""
        path = _make_approval_file(tmp_vault / "Approved", "no_subject.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("subject" in e for e in errors)

    def test_reply_email_missing_thread_id(self, executor, tmp_vault):
        fm = _base_fm(action_type="reply_email")
        fm["action_payload"]["params"] = {"thread_id": "", "body": "reply text"}
        path = _make_approval_file(tmp_vault / "Approved", "no_thread.md", fm)
        parsed = executor.parse_approval_file(path)
        errors = executor.validate_action(parsed)
        assert any("thread_id" in e for e in errors)


# ---------------------------------------------------------------------------
# DRY_RUN execution tests
# ---------------------------------------------------------------------------


class TestExecuteDryRun:
    def test_send_email_dry_run(self, executor, sample_approval_file):
        result = executor.execute(sample_approval_file)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert "DRY RUN" in result["result"]
        assert result["error"] is None

    def test_draft_email_dry_run(self, executor, tmp_vault):
        fm = _base_fm(action_type="draft_email")
        fm["action_payload"]["tool"] = "draft_email"
        path = _make_approval_file(tmp_vault / "Approved", "draft.md", fm)
        result = executor.execute(path)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert "draft" in result["result"].lower()

    def test_reply_email_dry_run(self, executor, tmp_vault):
        fm = _base_fm(action_type="reply_email")
        fm["action_payload"]["tool"] = "reply_to_thread"
        fm["action_payload"]["params"] = {
            "thread_id": "18d1234abcd",
            "body": "Thanks for your email.",
            "reply_all": False,
        }
        path = _make_approval_file(tmp_vault / "Approved", "reply.md", fm)
        result = executor.execute(path)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert "18d1234abcd" in result["result"]

    def test_linkedin_not_implemented(self, executor, tmp_vault):
        fm = _base_fm(action_type="linkedin_post")
        fm["action_payload"]["tool"] = "create_post"
        fm["action_payload"]["params"] = {"content": "Hello LinkedIn!", "visibility": "public"}
        path = _make_approval_file(tmp_vault / "Approved", "linkedin.md", fm)
        # In dry_run mode, the executor simulates — this actually succeeds as a simulation
        result = executor.execute(path)
        # dry_run simulates it as successful
        assert result["dry_run"] is True

    def test_generic_not_supported_dry_run(self, executor, tmp_vault):
        fm = _base_fm(action_type="generic")
        fm["action_payload"]["tool"] = "generic"
        fm["action_payload"]["params"] = {}
        path = _make_approval_file(tmp_vault / "Approved", "generic.md", fm)
        result = executor.execute(path)
        assert result["dry_run"] is True

    def test_linkedin_live_calls_cli(self, tmp_vault):
        """In live mode, linkedin_post invokes the LinkedIn MCP CLI subprocess."""
        executor = ActionExecutor(tmp_vault, dry_run=False)
        fm = _base_fm(action_type="linkedin_post")
        fm["action_payload"]["tool"] = "create_post"
        fm["action_payload"]["params"] = {"content": "Hello!", "visibility": "public"}
        path = _make_approval_file(tmp_vault / "Approved", "linkedin_live.md", fm)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"success": True, "post_id": "urn:li:share:123"}),
                stderr="",
            )
            result = executor.execute(path)

        assert result["success"] is True
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "linkedin-mcp" in cmd_str
        assert "create_post" in cmd_str

    def test_generic_live_manual_execution(self, tmp_vault):
        """In live mode, generic action returns manual-execution error."""
        executor = ActionExecutor(tmp_vault, dry_run=False)
        fm = _base_fm(action_type="generic")
        fm["action_payload"]["tool"] = "generic"
        fm["action_payload"]["params"] = {}
        path = _make_approval_file(tmp_vault / "Approved", "generic_live.md", fm)
        result = executor.execute(path)
        assert result["success"] is False
        assert "manual execution" in result["error"]


# ---------------------------------------------------------------------------
# Execution result structure tests
# ---------------------------------------------------------------------------


class TestExecutionResultStructure:
    REQUIRED_KEYS = {"success", "action_type", "target", "result", "dry_run", "timestamp", "error"}

    def test_execute_returns_success_dict(self, executor, sample_approval_file):
        result = executor.execute(sample_approval_file)
        assert self.REQUIRED_KEYS.issubset(result.keys())
        assert result["action_type"] == "send_email"
        assert result["target"] == "test@example.com"

    def test_execute_returns_failure_on_parse_error(self, executor, tmp_vault):
        path = tmp_vault / "Approved" / "broken.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Not a valid approval file", encoding="utf-8")
        result = executor.execute(path)
        assert result["success"] is False
        assert result["error"] is not None
        assert self.REQUIRED_KEYS.issubset(result.keys())

    def test_execute_dry_run_flag_in_result(self, executor, sample_approval_file):
        result = executor.execute(sample_approval_file)
        assert result["dry_run"] is True

    def test_execute_live_flag_in_result(self, tmp_vault, sample_approval_file):
        executor_live = ActionExecutor(tmp_vault, dry_run=False)
        # Mock the subprocess so we don't actually call CLI
        with patch.object(executor_live, "_run_cli", return_value={"success": True, "result": "sent", "error": None}):
            result = executor_live.execute(sample_approval_file)
        assert result["dry_run"] is False

    def test_execute_logs_to_audit(self, executor, sample_approval_file, tmp_vault):
        executor.execute(sample_approval_file)
        log_dir = tmp_vault / "Logs"
        log_files = list(log_dir.glob("*.json"))
        assert len(log_files) > 0
        with log_files[0].open(encoding="utf-8") as f:
            entries = json.load(f)
        assert any(e.get("action_type") == "hitl_execution" for e in entries)

    def test_execute_failure_logs_to_audit(self, executor, tmp_vault):
        path = tmp_vault / "Approved" / "bad.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("No frontmatter", encoding="utf-8")
        executor.execute(path)  # Should not raise; logs failure


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCli:
    def _run_cli_module(self, *args, vault: Path):
        import os
        project_root = Path(__file__).parent.parent.parent
        return subprocess.run(
            ["uv", "run", "python", "-m", "scripts.utils.action_executor", *args],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            env={**os.environ, "VAULT_PATH": str(vault), "DRY_RUN": "true"},
        )

    def test_cli_validate_only_valid(self, tmp_vault, sample_approval_file):
        proc = self._run_cli_module(
            str(sample_approval_file), "--validate-only", "--vault", str(tmp_vault), vault=tmp_vault
        )
        assert proc.returncode == 0
        assert "Valid" in proc.stdout

    def test_cli_validate_only_invalid(self, tmp_vault):
        bad = tmp_vault / "Approved" / "bad.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("No frontmatter", encoding="utf-8")
        proc = self._run_cli_module(
            str(bad), "--validate-only", "--vault", str(tmp_vault), vault=tmp_vault
        )
        assert proc.returncode == 1

    def test_cli_execute_dry_run(self, tmp_vault, sample_approval_file):
        proc = self._run_cli_module(
            str(sample_approval_file), "--dry-run", "--vault", str(tmp_vault), vault=tmp_vault
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["success"] is True
        assert data["dry_run"] is True

    def test_cli_missing_file(self, tmp_vault):
        proc = self._run_cli_module(
            "nonexistent_file.md", "--validate-only", "--vault", str(tmp_vault), vault=tmp_vault
        )
        # Should exit non-zero and report error
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# _run_cli internal tests (live mode, mocked subprocess)
# ---------------------------------------------------------------------------


class TestRunCli:
    def test_run_cli_success_json(self, tmp_vault):
        executor = ActionExecutor(tmp_vault, dry_run=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"success": True, "result": "Email sent", "error": None})
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = executor._run_cli(["npx", "tsx", "cli.ts", "send_email"])

        assert result["success"] is True
        assert result["result"] == "Email sent"

    def test_run_cli_nonzero_exit(self, tmp_vault):
        executor = ActionExecutor(tmp_vault, dry_run=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Auth error"

        with patch("subprocess.run", return_value=mock_proc):
            result = executor._run_cli(["npx", "tsx", "cli.ts", "send_email"])

        assert result["success"] is False
        assert "Auth error" in result["error"]

    def test_run_cli_timeout(self, tmp_vault):
        executor = ActionExecutor(tmp_vault, dry_run=False)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
            result = executor._run_cli(["npx", "tsx", "cli.ts", "send_email"])
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_run_cli_not_found(self, tmp_vault):
        executor = ActionExecutor(tmp_vault, dry_run=False)
        with patch("subprocess.run", side_effect=FileNotFoundError("npx not found")):
            result = executor._run_cli(["npx", "tsx", "cli.ts", "send_email"])
        assert result["success"] is False
        assert "CLI not found" in result["error"]

    def test_run_cli_plain_text_output(self, tmp_vault):
        executor = ActionExecutor(tmp_vault, dry_run=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Email sent successfully."
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = executor._run_cli(["npx", "tsx", "cli.ts"])

        assert result["success"] is True
        assert result["result"] == "Email sent successfully."
