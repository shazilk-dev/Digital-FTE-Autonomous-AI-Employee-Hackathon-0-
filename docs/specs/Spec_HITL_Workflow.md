# Spec: HITL Workflow — Approval Requests, Skill, and Action Executor

> **Components:**
> - `.claude/skills/hitl-handler/SKILL.md` — Skill that teaches Claude to write approval requests
> - `scripts/utils/action_executor.py` — Parses approved action files and executes via MCP/CLI
> **Priority:** P0 — This is the SAFETY CONTRACT. No external action without human approval.
> **Tests:** `tests/utils/test_action_executor.py`
> **Depends On:** Email MCP (S2), vault_processor.py, dashboard_updater.py

## 1. Objective

Define the complete Human-in-the-Loop workflow:

1. **Approval Request Format** — standardized `.md` files Claude writes to `/Pending_Approval/`
2. **HITL Skill** — teaches Claude WHEN and HOW to create approval requests
3. **Action Executor** — parses approved files and executes the embedded action

The HITL system is the **trust boundary** between AI reasoning and real-world action.
Everything inside the vault is reversible. Everything outside (sending email, posting
to LinkedIn) is NOT. HITL guards the boundary.

## 2. Approval Request File Format

### 2A. File Naming

```
ACTION_{action_type}_{target_sanitized}_{YYYY-MM-DDTHH-MM-SS}.md
```

Examples:
```
ACTION_send_email_john_smith_2026-02-27T10-30-00.md
ACTION_draft_email_client_a_2026-02-27T11-00-00.md
ACTION_reply_email_thread_18d1234_2026-02-27T12-00-00.md
ACTION_linkedin_post_2026-02-27T14-00-00.md
```

### 2B. File Location

```
/Pending_Approval/{domain}/ACTION_*.md
```

Domains:
- `email/` — email send, draft, reply actions
- `social/` — LinkedIn, Twitter, Facebook posts (S5+)
- `finance/` — payments, invoices (Gold tier)
- `general/` — anything that doesn't fit above

### 2C. YAML Frontmatter Schema (CRITICAL)

```yaml
---
type: approval_request
action_type: send_email          # ENUM: send_email | draft_email | reply_email | linkedin_post | generic
domain: email                    # Which domain folder
target: "john@example.com"       # Primary target (email, profile, etc.)
priority: high                   # critical | high | medium | low
status: pending_approval         # ALWAYS pending_approval when created
requires_approval: true          # ALWAYS true
created: "2026-02-27T10:30:00Z" # ISO 8601
expires: "2026-02-28T10:30:00Z" # 24 hours after created (default)
source_plan: "Plans/PLAN_email_invoice_john_2026-02-27T10-25-00.md"  # Plan that triggered this
source_task: "Needs_Action/email/EMAIL_john_smith_2026-02-27T10-00-00.md"  # Original task

# Action-specific payload (varies by action_type)
action_payload:
  tool: send_email               # MCP tool name to invoke
  server: email                  # MCP server name
  params:
    to: "john@example.com"
    subject: "Re: January Invoice Request"
    body: |
      Hi John,

      Thank you for reaching out. Please find attached your January invoice.

      Best regards
    cc: ""
    bcc: ""
---
```

### 2D. Body Format

```markdown
## Action Summary

**Type:** Send Email
**To:** john@example.com
**Subject:** Re: January Invoice Request
**Priority:** High

## Context

{Why this action is being taken — references the original email/task}

This action was triggered by an email from John Smith requesting the January invoice.
Claude's email-triage skill classified this as INVOICE_ACTION (high priority).

## Action Details

### Email Preview

**To:** john@example.com
**Subject:** Re: January Invoice Request

---

Hi John,

Thank you for reaching out. Please find attached your January invoice.

Best regards

---

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder. The action will be executed automatically.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.

### ✏️ To Modify
Edit the `action_payload` in the frontmatter above before approving.
Changes to `params.body`, `params.to`, `params.subject` will be reflected in the sent email.

## Safety Notes

- This action will send a real email when approved
- Verify the recipient address is correct
- Review the email body for accuracy
- The action expires at {expires} — after that it will be auto-flagged as stale
```

### 2E. Frontmatter Field Rules

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| type | Yes | — | Always `approval_request` |
| action_type | Yes | — | Must match a registered executor |
| domain | Yes | — | Determines subfolder |
| target | Yes | — | Human-readable target description |
| priority | Yes | — | Inherits from source task |
| status | Yes | `pending_approval` | Fixed at creation |
| requires_approval | Yes | `true` | Fixed at creation |
| created | Yes | — | Current UTC ISO 8601 |
| expires | Yes | +24 hours | Configurable via `HITL_EXPIRY_HOURS` env |
| source_plan | No | null | Path to the Plan file that triggered this |
| source_task | No | null | Path to the original task file |
| action_payload | Yes | — | Nested dict with tool, server, params |
| action_payload.tool | Yes | — | MCP tool name |
| action_payload.server | Yes | — | MCP server name from settings |
| action_payload.params | Yes | — | Tool-specific parameters |

## 3. HITL Handler Skill: `.claude/skills/hitl-handler/SKILL.md`

### 3A. Frontmatter

```yaml
---
name: hitl-handler
description: >
  Creates structured approval request files for actions that require human
  approval. Used by other skills (email-triage, social-post, task-planner)
  when they determine an action needs approval before execution.
  Reads Company_Handbook.md for approval matrix rules.
allowed-tools:
  - Bash(uv run python -m scripts.utils.vault_processor *)
  - Bash(uv run python -m scripts.utils.dashboard_updater *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(mkdir -p *)
  - Read
  - Write
---
```

### 3B. Skill Body

The skill must teach Claude:

**Section 1: When to Create Approval Requests**

```markdown
# HITL Handler Skill

## When to Create Approval Requests

ALWAYS create an approval request for:
- Sending any email (send_email, reply_email)
- Posting to social media (linkedin_post, tweet, etc.)
- Any financial action (payment, invoice creation)
- Any action involving a NEW/UNKNOWN contact
- Any action flagged requires_approval: true in the source Plan

NEVER create approval requests for:
- Reading/searching (read-only operations)
- Moving files within the vault
- Updating Dashboard.md
- Creating Plan files
- Archiving to /Done/

When in doubt: CREATE AN APPROVAL REQUEST. It's always safer.

Reference Company_Handbook.md for the full approval matrix.
```

**Section 2: How to Create Approval Requests**

```markdown
## How to Create Approval Requests

### Step 1: Determine Domain
- Email actions → domain: email
- Social media → domain: social
- Financial → domain: finance
- Everything else → domain: general

### Step 2: Build action_payload
The payload must contain everything the Action Executor needs to perform the action:

For send_email:
  tool: send_email
  server: email
  params:
    to: recipient@example.com
    subject: "Email subject"
    body: "Full email body text"
    cc: "" (optional)
    bcc: "" (optional)

For draft_email:
  tool: draft_email
  server: email
  params:
    to: recipient@example.com
    subject: "Email subject"
    body: "Full email body text"

For reply_email:
  tool: reply_to_thread
  server: email
  params:
    thread_id: "gmail_thread_id"
    body: "Reply body text"
    reply_all: false

For linkedin_post:
  tool: create_post
  server: linkedin
  params:
    content: "Post text"
    visibility: "public"

### Step 3: Create the File
- Filename: ACTION_{action_type}_{sanitized_target}_{timestamp}.md
- Location: /Pending_Approval/{domain}/
- Ensure the domain subfolder exists (mkdir -p)
- Write the file with full frontmatter and human-readable body

### Step 4: Update Dashboard
After creating the approval request:
1. Add a pending action to Dashboard:
   uv run python -m scripts.utils.dashboard_updater add-pending \
     --type "{action_type}" --from "{source}" --subject "{subject}" --priority "{priority}"
2. Log the activity:
   uv run python -m scripts.utils.dashboard_updater add-activity \
     "hitl_request" "Created approval: {action_type} for {target}" "pending_approval"

### Step 5: Inform the User
After creating the approval request, tell the user:
"I've created an approval request for [action]. Please review it in
/Pending_Approval/{domain}/ and move it to /Approved/ to proceed
or /Rejected/ to cancel."
```

**Section 3: Approval Request Template**

Include the full template from section 2C/2D above so Claude can reference it directly.

**Section 4: Integration with Email Triage**

```markdown
## Integration with Email Triage Skill

When the email-triage skill creates a Plan with requires_approval: true:

1. The Plan file already contains the draft response and action type
2. Use the Plan's content to populate the approval request
3. Copy the draft response into action_payload.params.body
4. Link back to the Plan via source_plan field
5. Link back to the original email via source_task field

The email-triage skill should call this skill for any REPLY_NEEDED,
INVOICE_ACTION, or ESCALATION category emails.
```

## 4. Action Executor: `scripts/utils/action_executor.py`

### 4A. Purpose

The Action Executor is the bridge between an approved file and the MCP server.
It reads the approved file's `action_payload`, constructs the appropriate MCP tool
call, and executes it.

**For hackathon scope:** The executor calls MCP tools via Claude Code CLI subprocess.
This is simpler than implementing MCP client protocol directly.

### 4B. Core Functions

```python
from pathlib import Path
from typing import Any
import json
import subprocess
import yaml
import os

class ActionExecutor:
    """
    Executes approved actions by invoking MCP tools via Claude Code CLI.

    For hackathon scope, actions are executed by:
    1. Parsing the approval file's action_payload
    2. Constructing a Claude Code CLI command that invokes the MCP tool
    3. Running the command as a subprocess
    4. Capturing the result
    5. Logging everything

    Future (Gold/Platinum): Direct MCP client protocol or A2A.
    """

    def __init__(
        self,
        vault_path: Path,
        dry_run: bool | None = None,
    ):
        self.vault_path = vault_path
        self.dry_run = dry_run if dry_run is not None else self._is_dry_run()
        self.supported_actions = {
            "send_email": self._execute_send_email,
            "draft_email": self._execute_draft_email,
            "reply_email": self._execute_reply_email,
            "linkedin_post": self._execute_linkedin_post,
            "generic": self._execute_generic,
        }

    def execute(self, approved_file: Path) -> dict:
        """
        Execute the action defined in an approved file.

        Args:
            approved_file: Path to the approved .md file (in /Approved/)

        Returns:
            {
                "success": True/False,
                "action_type": "send_email",
                "target": "john@example.com",
                "result": "Email sent. Message ID: 18d1234abcd",
                "dry_run": True/False,
                "timestamp": "2026-02-27T10:35:00Z",
                "error": None or "error message",
            }

        Flow:
        1. Parse the file's YAML frontmatter
        2. Validate action_payload exists and is well-formed
        3. Check action_type is supported
        4. Extract action_payload.params
        5. If DRY_RUN: return simulated result
        6. If LIVE: dispatch to action-specific executor
        7. Log the result
        8. Return result dict
        """

    def parse_approval_file(self, file_path: Path) -> dict:
        """
        Parse an approval request file.

        Returns:
        {
            "frontmatter": { full YAML frontmatter dict },
            "action_type": "send_email",
            "action_payload": { tool, server, params },
            "target": "john@example.com",
            "priority": "high",
            "source_plan": "Plans/PLAN_...",
            "source_task": "Needs_Action/...",
            "is_expired": False,
        }

        Validation:
        - type must be "approval_request"
        - action_payload must exist
        - action_payload.tool must exist
        - action_payload.params must exist
        - Check expiry: if current time > expires field → is_expired=True
        """

    def validate_action(self, parsed: dict) -> list[str]:
        """
        Validate the action is safe to execute.

        Returns list of validation errors (empty = valid).

        Checks:
        - action_type is in supported_actions
        - Required params exist for the action type
        - Email addresses are valid format (for email actions)
        - Content is not empty
        - File is not expired (warn but don't block)
        """
```

### 4C. Action-Specific Executors

```python
    def _execute_send_email(self, params: dict) -> dict:
        """
        Execute send_email via Email MCP.

        Required params: to, subject, body
        Optional params: cc, bcc

        If DRY_RUN:
            Return simulated success with preview

        If LIVE:
            Construct the MCP tool call by invoking Claude Code as a subprocess:
            
            cmd = [
                "claude", "--print",
                f'Use the email MCP tool send_email with these exact parameters: '
                f'to="{params["to"]}", '
                f'subject="{params["subject"]}", '
                f'body="{params["body"]}"'
            ]
            
            Or alternatively, call the MCP server directly via Node.js:
            
            cmd = [
                "npx", "tsx",
                "mcp-servers/email-mcp/src/tools/send_email_cli.ts",
                "--to", params["to"],
                "--subject", params["subject"],
                "--body", params["body"],
            ]

        Capture stdout, parse result, return.
        """

    def _execute_draft_email(self, params: dict) -> dict:
        """Similar to send_email but calls draft_email tool."""

    def _execute_reply_email(self, params: dict) -> dict:
        """
        Calls reply_to_thread tool.
        Required params: thread_id, body
        Optional params: reply_all
        """

    def _execute_linkedin_post(self, params: dict) -> dict:
        """
        Placeholder for Phase S5.
        Returns: {"success": False, "error": "LinkedIn MCP not yet implemented"}
        """

    def _execute_generic(self, params: dict) -> dict:
        """
        Generic executor for unknown action types.
        Logs the action but doesn't execute.
        Returns: {"success": False, "error": "Generic actions require manual execution"}
        """
```

### 4D. DRY_RUN Simulation

```python
    def _simulate_execution(self, action_type: str, params: dict) -> dict:
        """
        Return a realistic simulated result for DRY_RUN mode.

        Example for send_email:
        {
            "success": True,
            "action_type": "send_email",
            "target": params["to"],
            "result": "[DRY RUN] Would send email to john@example.com with subject 'Invoice'",
            "dry_run": True,
            "timestamp": current_iso,
            "error": None,
        }
        """
```

### 4E. Logging

```python
    def _log_execution(
        self,
        approved_file: Path,
        action_type: str,
        result: dict,
    ) -> None:
        """
        Write execution result to audit log.

        Log entry:
        {
            "timestamp": "...",
            "action_type": "hitl_execution",
            "actor": "action_executor",
            "source_file": "Approved/ACTION_send_email_...",
            "action": action_type,
            "target": result["target"],
            "result": "success" or "failure",
            "dry_run": result["dry_run"],
            "detail": result["result"] or result["error"],
            "approval_status": "approved",
            "approved_by": "human",
        }

        Uses vault_helpers.append_json_log()
        """
```

### 4F. CLI Interface

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Action Executor CLI")
    parser.add_argument("file", help="Path to approved action file")
    parser.add_argument("--vault", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Force DRY_RUN mode")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate, don't execute")

    args = parser.parse_args()
    vault_path = Path(args.vault or os.getenv("VAULT_PATH", "."))

    executor = ActionExecutor(vault_path, dry_run=args.dry_run)
    parsed = executor.parse_approval_file(Path(args.file))

    if args.validate_only:
        errors = executor.validate_action(parsed)
        if errors:
            print(f"Validation errors: {errors}")
            sys.exit(1)
        print("Valid. Ready to execute.")
        sys.exit(0)

    result = executor.execute(Path(args.file))
    print(json.dumps(result, indent=2))
```

## 5. Execution Strategy Decision

### Option A: Claude Code Subprocess (Simpler)

The action executor invokes `claude --print "Use email MCP to send..."` as a subprocess.
Claude Code connects to the MCP server and calls the tool.

**Pros:** Simple, reuses existing MCP registration, Claude handles errors naturally.
**Cons:** Slower (spawns Claude Code per action), uses API tokens.

### Option B: Direct MCP Client (More Complex)

The action executor implements MCP client protocol directly in Python,
connecting to the Email MCP server via stdio.

**Pros:** Faster, no API token usage, more deterministic.
**Cons:** More code, need to implement MCP client protocol.

### Option C: Direct CLI on MCP Server (Recommended for Hackathon)

Add a thin CLI wrapper to each MCP tool that can be called directly:

```bash
npx tsx mcp-servers/email-mcp/src/tools/send_email_cli.ts \
  --to "john@example.com" \
  --subject "Invoice" \
  --body "Please find attached..."
```

**Pros:** Fast, no API tokens, no MCP protocol overhead, simple subprocess call.
**Cons:** Need to create CLI wrappers for each tool (but they're thin).

**Recommendation:** Use Option C (direct CLI). Create a `cli.ts` entry point in the
Email MCP that exposes tools as CLI commands. This is the fastest and most reliable
approach for the hackathon.

### 5A. CLI Entry Point for Email MCP

Add to the Email MCP (modify Spec_EmailMCP if needed):

```
mcp-servers/email-mcp/src/cli.ts
```

```typescript
// cli.ts — Direct CLI for action executor
// Usage: npx tsx src/cli.ts send_email --to x --subject y --body z

import { parseArgs } from "node:util";
// Import tool implementations directly (not via MCP protocol)
```

The Action Executor spec should instruct Claude Code to create this CLI wrapper
as part of the HITL implementation.

## 6. Test Requirements

### 6A. Fixtures

```python
@pytest.fixture
def sample_approval_file(tmp_vault) -> Path:
    """Create a sample approval request file in Pending_Approval/email/."""
    content = """---
type: approval_request
action_type: send_email
domain: email
target: "test@example.com"
priority: high
status: pending_approval
requires_approval: true
created: "2026-02-27T10:30:00Z"
expires: "2026-02-28T10:30:00Z"
source_plan: null
source_task: null
action_payload:
  tool: send_email
  server: email
  params:
    to: "test@example.com"
    subject: "Test Email"
    body: "This is a test email."
    cc: ""
    bcc: ""
---

## Action Summary

**Type:** Send Email
**To:** test@example.com
"""
    path = tmp_vault / "Approved" / "ACTION_send_email_test_2026-02-27T10-30-00.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path

@pytest.fixture
def expired_approval_file(tmp_vault) -> Path:
    """Approval file with past expiry date."""

@pytest.fixture
def executor(tmp_vault) -> ActionExecutor:
    return ActionExecutor(tmp_vault, dry_run=True)
```

### 6B. Test Cases

**Parsing:**
- `test_parse_approval_file_valid` — all fields extracted correctly
- `test_parse_approval_file_missing_payload` — raises ValueError
- `test_parse_approval_file_missing_type` — raises ValueError
- `test_parse_approval_file_wrong_type` — type != approval_request → error
- `test_parse_approval_file_expired` — is_expired flag set True
- `test_parse_approval_file_not_expired` — is_expired flag set False

**Validation:**
- `test_validate_send_email_valid` — no errors
- `test_validate_send_email_missing_to` — error reported
- `test_validate_send_email_invalid_address` — error reported
- `test_validate_send_email_empty_body` — error reported
- `test_validate_unknown_action_type` — error reported
- `test_validate_expired_warns` — warning but not blocking

**Execution (DRY_RUN):**
- `test_execute_send_email_dry_run` — returns simulated success
- `test_execute_draft_email_dry_run` — returns simulated success
- `test_execute_reply_email_dry_run` — returns simulated success
- `test_execute_linkedin_not_implemented` — returns not-implemented error
- `test_execute_generic_not_supported` — returns manual-execution message

**Execution Result:**
- `test_execute_returns_success_dict` — has all required keys
- `test_execute_returns_failure_on_error` — success=False, error populated
- `test_execute_logs_to_audit` — audit log entry created
- `test_execute_dry_run_flag_in_result` — dry_run field reflects actual mode

**CLI:**
- `test_cli_validate_only` — exits 0 for valid, 1 for invalid
- `test_cli_execute_dry_run` — prints JSON result
- `test_cli_missing_file` — clear error message

## 7. Edge Cases

- **Malformed YAML frontmatter:** Catch yaml.YAMLError, return validation error
- **action_payload.params missing required fields:** Validation catches it before execution
- **Expired approval:** Execute anyway but log a warning. The expiry is advisory.
- **MCP server not running:** Subprocess fails → catch, log error, return failure result
- **Concurrent approvals:** Each file is independent. No shared state. Safe for parallel.
- **User edits action_payload before approving:** This is INTENDED. Updated params are used.
- **Empty body in email:** Validation rejects it. Body is required for sends.
- **File has no frontmatter (manually created):** parse_approval_file returns error
- **File approved twice (copied instead of moved):** Dedup via processed_ids in approval watcher
- **Very large email body (>50KB):** Pass through to MCP, let MCP handle truncation
- **Nested YAML in action_payload:** Use yaml.safe_load, handle complex structures

## 8. Validation Criteria

- [ ] HITL skill teaches Claude when and how to create approval requests
- [ ] Approval file format is fully defined with all required fields
- [ ] Action executor parses approval files correctly
- [ ] Action executor validates before executing
- [ ] DRY_RUN simulation works for all supported action types
- [ ] Audit logging for all executions (success and failure)
- [ ] CLI interface works for manual testing
- [ ] Expiry detection works (>24hr flagged)
- [ ] User can edit action_payload before approving (designed feature)
- [ ] All tests pass
- [ ] No modification to existing components
