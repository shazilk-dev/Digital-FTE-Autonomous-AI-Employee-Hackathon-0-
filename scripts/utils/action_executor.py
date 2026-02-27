"""Action Executor: parses approved action files and executes via Email MCP CLI."""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.utils.vault_helpers import append_json_log, is_dry_run

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_REQUIRED_PARAMS: dict[str, list[str]] = {
    "send_email": ["to", "subject", "body"],
    "draft_email": ["to", "subject", "body"],
    "reply_to_thread": ["thread_id", "body"],
    "reply_email": ["thread_id", "body"],  # backwards-compat alias for reply_to_thread
    "linkedin_post": ["content"],
    "generic": [],
}


class ActionExecutor:
    """
    Executes approved actions by invoking MCP tools via Email MCP CLI.

    For hackathon scope, email actions are executed by:
    1. Parsing the approval file's action_payload
    2. Constructing a CLI command that calls the Email MCP's cli.ts
    3. Running the command as a subprocess
    4. Capturing and returning the result
    5. Logging everything to the audit log

    Future (Gold/Platinum): Direct MCP client protocol or A2A.
    """

    def __init__(
        self,
        vault_path: Path,
        dry_run: bool | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.dry_run = dry_run if dry_run is not None else is_dry_run()
        self.supported_actions = {
            "send_email": self._execute_send_email,
            "draft_email": self._execute_draft_email,
            "reply_to_thread": self._execute_reply_email,
            "reply_email": self._execute_reply_email,  # backwards-compat alias
            "linkedin_post": self._execute_linkedin_post,
            "generic": self._execute_generic,
        }

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def execute(self, approved_file: Path) -> dict:
        """
        Execute the action defined in an approved file.

        Returns a result dict with keys:
            success, action_type, target, result, dry_run, timestamp, error
        """
        try:
            parsed = self.parse_approval_file(approved_file)
        except (ValueError, yaml.YAMLError) as e:
            result: dict = {
                "success": False,
                "action_type": "unknown",
                "target": str(approved_file.name),
                "result": None,
                "dry_run": self.dry_run,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "error": str(e),
            }
            return result

        action_type = parsed["action_type"]
        target = parsed["target"]

        errors = self.validate_action(parsed)
        if errors:
            result = {
                "success": False,
                "action_type": action_type,
                "target": target,
                "result": None,
                "dry_run": self.dry_run,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "error": f"Validation failed: {'; '.join(errors)}",
            }
            self._log_execution(approved_file, action_type, result)
            return result

        params = parsed["action_payload"].get("params", {})

        if self.dry_run:
            result = self._simulate_execution(action_type, params)
        else:
            executor_fn = self.supported_actions.get(action_type)
            if executor_fn is None:
                result = {
                    "success": False,
                    "action_type": action_type,
                    "target": target,
                    "result": None,
                    "dry_run": self.dry_run,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "error": f"Unsupported action type: {action_type!r}",
                }
            else:
                partial = executor_fn(params)
                result = {
                    "success": partial.get("success", False),
                    "action_type": action_type,
                    "target": target,
                    "result": partial.get("result"),
                    "dry_run": self.dry_run,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "error": partial.get("error"),
                }

        self._log_execution(approved_file, action_type, result)
        return result

    def parse_approval_file(self, file_path: Path) -> dict:
        """
        Parse an approval request file.

        Returns dict with:
            frontmatter, action_type, action_payload, target,
            priority, source_plan, source_task, is_expired

        Raises ValueError on missing or invalid fields.
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"Cannot read file: {e}") from e

        if not text.startswith("---"):
            raise ValueError("File has no YAML frontmatter")

        end = text.find("\n---", 3)
        if end == -1:
            raise ValueError("Frontmatter not closed with ---")

        fm_block = text[3:end].strip()
        try:
            fm = yaml.safe_load(fm_block)
        except yaml.YAMLError as e:
            raise ValueError(f"Malformed YAML frontmatter: {e}") from e

        if not isinstance(fm, dict):
            raise ValueError("Frontmatter is not a YAML mapping")

        if fm.get("type") != "approval_request":
            raise ValueError(
                f"File type must be 'approval_request', got: {fm.get('type')!r}"
            )

        action_payload = fm.get("action_payload")
        if not action_payload:
            raise ValueError("Missing required field: action_payload")

        if not isinstance(action_payload, dict):
            raise ValueError("action_payload must be a mapping")

        if not action_payload.get("tool"):
            raise ValueError("Missing required field: action_payload.tool")

        if action_payload.get("params") is None:
            raise ValueError("Missing required field: action_payload.params")

        # Check expiry
        is_expired = False
        expires_raw = fm.get("expires")
        if expires_raw:
            try:
                expires_str = str(expires_raw).replace("Z", "+00:00")
                expires_dt = datetime.fromisoformat(expires_str)
                if datetime.now(tz=timezone.utc) > expires_dt:
                    is_expired = True
            except (ValueError, AttributeError):
                pass

        return {
            "frontmatter": fm,
            "action_type": str(fm.get("action_type", "generic")),
            "action_payload": action_payload,
            "target": str(fm.get("target", "")),
            "priority": str(fm.get("priority", "medium")),
            "source_plan": fm.get("source_plan"),
            "source_task": fm.get("source_task"),
            "is_expired": is_expired,
        }

    def validate_action(self, parsed: dict) -> list[str]:
        """
        Validate the action is safe to execute.

        Returns list of validation errors (empty = valid).
        Expired files emit a warning but are not blocked.
        """
        errors: list[str] = []
        action_type = parsed["action_type"]

        if action_type not in self.supported_actions:
            errors.append(f"Unsupported action type: {action_type!r}")
            return errors

        payload = parsed.get("action_payload", {})
        params = payload.get("params", {})
        if not isinstance(params, dict):
            errors.append("action_payload.params must be a mapping")
            return errors

        required = _REQUIRED_PARAMS.get(action_type, [])
        for field in required:
            if not params.get(field):
                errors.append(f"Missing required param: {field!r}")

        if action_type in ("send_email", "draft_email"):
            to_addr = str(params.get("to", ""))
            if to_addr and not _EMAIL_RE.match(to_addr):
                errors.append(f"Invalid email address: {to_addr!r}")
            body = str(params.get("body", "")).strip()
            if not body:
                errors.append("Email body cannot be empty")

        if parsed.get("is_expired"):
            logger.warning(
                "Approval file is expired (executing anyway): target=%s",
                parsed.get("target"),
            )

        return errors

    # ---------------------------------------------------------------------------
    # Action-specific executors (live mode)
    # ---------------------------------------------------------------------------

    def _execute_send_email(self, params: dict) -> dict:
        """Execute send_email via Email MCP CLI."""
        cmd = [
            "npx", "tsx", str(self._get_cli_path()),
            "send_email",
            "--to", params["to"],
            "--subject", params["subject"],
            "--body", params["body"],
        ]
        if params.get("cc"):
            cmd += ["--cc", str(params["cc"])]
        if params.get("bcc"):
            cmd += ["--bcc", str(params["bcc"])]
        return self._run_cli(cmd)

    def _execute_draft_email(self, params: dict) -> dict:
        """Execute draft_email via Email MCP CLI."""
        cmd = [
            "npx", "tsx", str(self._get_cli_path()),
            "draft_email",
            "--to", params["to"],
            "--subject", params["subject"],
            "--body", params["body"],
        ]
        return self._run_cli(cmd)

    def _execute_reply_email(self, params: dict) -> dict:
        """Execute reply_to_thread via Email MCP CLI."""
        cmd = [
            "npx", "tsx", str(self._get_cli_path()),
            "reply_to_thread",
            "--thread-id", params["thread_id"],
            "--body", params["body"],
        ]
        if params.get("reply_all"):
            cmd.append("--reply-all")
        return self._run_cli(cmd)

    def _execute_linkedin_post(self, params: dict) -> dict:  # noqa: ARG002
        """Placeholder for Phase S5."""
        return {
            "success": False,
            "result": None,
            "error": "LinkedIn MCP not yet implemented",
        }

    def _execute_generic(self, params: dict) -> dict:  # noqa: ARG002
        """Generic executor — logs the action but does not execute."""
        return {
            "success": False,
            "result": None,
            "error": "Generic actions require manual execution",
        }

    # ---------------------------------------------------------------------------
    # DRY RUN simulation
    # ---------------------------------------------------------------------------

    def _simulate_execution(self, action_type: str, params: dict) -> dict:
        """Return a realistic simulated result for DRY_RUN mode."""
        now = datetime.now(tz=timezone.utc).isoformat()

        if action_type == "send_email":
            target = str(params.get("to", "unknown"))
            subject = params.get("subject", "")
            result_msg = (
                f"[DRY RUN] Would send email to {target} with subject '{subject}'"
            )
        elif action_type == "draft_email":
            target = str(params.get("to", "unknown"))
            subject = params.get("subject", "")
            result_msg = (
                f"[DRY RUN] Would create draft to {target} with subject '{subject}'"
            )
        elif action_type in ("reply_to_thread", "reply_email"):
            target = str(params.get("thread_id", "unknown"))
            result_msg = f"[DRY RUN] Would reply to thread {target}"
        elif action_type == "linkedin_post":
            target = "linkedin"
            result_msg = "[DRY RUN] Would post to LinkedIn"
        else:
            target = "unknown"
            result_msg = f"[DRY RUN] Would execute {action_type}"

        return {
            "success": True,
            "action_type": action_type,
            "target": target,
            "result": result_msg,
            "dry_run": True,
            "timestamp": now,
            "error": None,
        }

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _run_cli(self, cmd: list[str]) -> dict:
        """Run a CLI subprocess command and parse the JSON result."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.vault_path),
            )
            if proc.returncode != 0:
                error_msg = (proc.stderr or proc.stdout or "").strip()
                return {
                    "success": False,
                    "result": None,
                    "error": error_msg or "CLI returned non-zero exit code",
                }

            output = proc.stdout.strip()
            try:
                data = json.loads(output)
                return {
                    "success": data.get("success", True),
                    "result": data.get("result", output),
                    "error": data.get("error"),
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "result": output,
                    "error": None,
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "result": None,
                "error": "CLI command timed out after 60 seconds",
            }
        except FileNotFoundError as e:
            return {
                "success": False,
                "result": None,
                "error": f"CLI not found: {e}",
            }

    def _get_cli_path(self) -> Path:
        """Get the path to the email MCP CLI."""
        custom = os.getenv("EMAIL_MCP_CLI_PATH")
        if custom:
            return Path(custom)
        return self.vault_path / "mcp-servers" / "email-mcp" / "src" / "cli.ts"

    def _log_execution(
        self, approved_file: Path, action_type: str, result: dict
    ) -> None:
        """Write execution result to audit log."""
        try:
            rel_path = str(approved_file.relative_to(self.vault_path))
        except ValueError:
            rel_path = str(approved_file)

        log_entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "action_type": "hitl_execution",
            "actor": "action_executor",
            "source_file": rel_path,
            "action": action_type,
            "target": result.get("target", ""),
            "result": "success" if result.get("success") else "failure",
            "dry_run": result.get("dry_run", False),
            "detail": result.get("result") or result.get("error"),
            "approval_status": "approved",
            "approved_by": "human",
        }
        try:
            append_json_log(self.vault_path / "Logs", log_entry)
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Action Executor CLI")
    parser.add_argument("file", help="Path to approved action file")
    parser.add_argument("--vault", default=None, help="Vault root path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Force DRY_RUN mode"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate, don't execute",
    )

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    executor = ActionExecutor(vault_path, dry_run=args.dry_run or None)
    parsed_action = executor.parse_approval_file(Path(args.file))

    if args.validate_only:
        validation_errors = executor.validate_action(parsed_action)
        if validation_errors:
            print(f"Validation errors: {validation_errors}")
            sys.exit(1)
        print("Valid. Ready to execute.")
        sys.exit(0)

    action_result = executor.execute(Path(args.file))
    print(json.dumps(action_result, indent=2))
