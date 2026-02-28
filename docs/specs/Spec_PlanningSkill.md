# Spec: Task Planner Agent Skill

> **Component:** `.claude/skills/task-planner/SKILL.md`
> **Type:** Agent Skill (prompt template, NOT executable code)
> **Priority:** P1 — Deepens Claude's reasoning from single-action to multi-step workflows
> **Depends On:** `vault_processor.py`, `dashboard_updater.py`, `hitl-handler` skill

## 1. Objective

Teach Claude Code how to decompose complex tasks into structured multi-step Plans
with dependency tracking, status management, and integration with the HITL workflow.

This skill is invoked when:

- A task requires more than 2 steps to complete
- Multiple domains are involved (email + calendar + accounting)
- A task has dependencies (Step 3 can't start until Step 2 completes)
- The email-triage skill identifies a TASK_REQUEST or multi-part email

## 2. SKILL.md Structure

### 2A. YAML Frontmatter

```yaml
---
name: task-planner
description: >
  Decomposes complex tasks into structured multi-step Plans with dependency
  tracking and status management. Integrates with email-triage for complex
  emails and hitl-handler for steps requiring approval. Creates Plan files
  in /Plans/ with checkbox tracking and step-level status.
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

### 2B. Skill Body Sections

---

#### Section 1: When to Plan

```markdown
# Task Planner Skill

## When to Create Multi-Step Plans

Use this skill when a task meets ANY of these criteria:

- Requires more than 2 distinct actions
- Involves multiple domains (email + calendar, email + accounting, etc.)
- Has sequential dependencies (B depends on A completing)
- Involves both automated and manual steps
- The email-triage skill classified it as TASK_REQUEST
- An email contains multiple requests in one message

For SIMPLE tasks (single action, no dependencies):

- Use email-triage's single Plan format instead
- Don't over-engineer — not everything needs a multi-step plan

## Decision Matrix

| Complexity         | Steps | Dependencies | Use                         |
| ------------------ | ----- | ------------ | --------------------------- |
| Simple email reply | 1     | None         | email-triage Plan           |
| Invoice request    | 2-3   | Sequential   | task-planner                |
| Multi-topic email  | 3-5   | Mixed        | task-planner                |
| Project workflow   | 5-10  | Complex DAG  | task-planner                |
| Simple FYI         | 0     | None         | email-triage (auto-archive) |
```

#### Section 2: Plan File Format

```markdown
## Plan File Format

### Filename

PLAN*task*{sanitized*description}*{YYYY-MM-DDTHH-MM-SS}.md

### YAML Frontmatter

---

type: plan
plan_type: multi_step
source_type: {email|whatsapp|file|manual}
source_file: {path to original task file}
title: "{Short descriptive title}"
priority: {critical|high|medium|low}
status: {pending|in_progress|blocked|done|cancelled}
total_steps: {number}
completed_steps: {number}
requires_approval: {true if ANY step requires approval}
created: {ISO 8601}
updated: {ISO 8601}
estimated_effort: "{time estimate, e.g., '30 minutes'}"
due_date: {ISO 8601 or null}
tags: ["email", "invoice", "client-b"]

---

### Body Structure

## {Plan Title}

**Source:** {description of what triggered this plan}
**Priority:** {priority}
**Status:** {overall status}
**Progress:** {completed_steps}/{total_steps} steps complete

## Steps

### Step 1: {Step Title}

- **Status:** {✅ done | ⏳ in_progress | 📋 pending | ⏸ blocked | ❌ failed | ⏭ skipped}
- **Domain:** {email | calendar | accounting | social | manual}
- **Depends On:** {None | Step N}
- **Requires Approval:** {Yes/No}
- **Assigned To:** {auto | human}
- **Notes:** {Any relevant context}

{Step details — what needs to happen and how}

### Step 2: {Step Title}

- **Status:** ⏸ blocked
- **Domain:** email
- **Depends On:** Step 1
- **Requires Approval:** Yes
- **Assigned To:** auto
- **Notes:** Cannot proceed until Step 1 is complete

{Step details}

[... more steps ...]

## Dependencies
```

Step 1 (Look up rate) ──▶ Step 2 (Generate invoice)
Step 2 (Generate invoice) ──▶ Step 3 (Send via email)
Step 1 (Look up rate) ──▶ Step 4 (Log transaction) [can start after Step 1]
Step 3 (Send email) ──▶ Step 5 (Schedule follow-up)

```

## Approval Requirements

{List which steps require approval and why}

- Step 3: Sending email to external recipient → requires HITL approval
- Step 5: Creating calendar event → auto-approved (per Company Handbook)

## Notes

{Any context, risks, or decisions made during planning}
```

#### Section 3: Step Status Lifecycle

```markdown
## Step Status Lifecycle
```

📋 pending ──▶ ⏳ in_progress ──▶ ✅ done
│ │
│ ├──▶ ❌ failed ──▶ 📋 pending (retry)
│ │
▼ ▼
⏸ blocked ⏭ skipped
(dependency) (no longer needed)

```

### Status Rules

| Status | Meaning | When to Use |
|--------|---------|-------------|
| 📋 pending | Ready to start, waiting for execution | Initial state for steps with no unmet dependencies |
| ⏳ in_progress | Currently being worked on | Claude is actively processing |
| ✅ done | Successfully completed | Step finished, output verified |
| ⏸ blocked | Cannot proceed | Depends on incomplete step |
| ❌ failed | Execution attempted but failed | Error occurred, may retry |
| ⏭ skipped | No longer needed | Parent task cancelled or conditions changed |

### Dependency Resolution

When checking if a step can start:
1. List all "Depends On" steps
2. Check each dependency's status
3. If ALL dependencies are ✅ done → step is 📋 pending (can start)
4. If ANY dependency is ❌ failed → step is ⏸ blocked
5. If ANY dependency is 📋/⏳ → step is ⏸ blocked

### Overall Plan Status

| Condition | Plan Status |
|-----------|-------------|
| All steps 📋 pending | pending |
| Any step ⏳ in_progress | in_progress |
| Any step ⏸ blocked and none ⏳ | blocked |
| All steps ✅ done or ⏭ skipped | done |
| Human cancelled | cancelled |
```

#### Section 4: Decomposition Strategies

```markdown
## Decomposition Strategies

### Email with Multiple Requests

When an email contains multiple requests (numbered list, "three things", etc.):

1. Create one step per request
2. Add a "Reply to confirm" step at the end
3. Identify which requests can be done in parallel vs. sequential

Example:

- "Send invoice, schedule meeting, discuss renewal"
  → Step 1: Look up client info (parallel start)
  → Step 2: Generate invoice (depends: Step 1)
  → Step 3: Send invoice email (depends: Step 2, requires approval)
  → Step 4: Check calendar availability (parallel with Steps 1-3)
  → Step 5: Propose meeting times (depends: Step 4)
  → Step 6: Draft renewal discussion points (parallel)
  → Step 7: Reply to client with all items (depends: Steps 3, 5, 6; requires approval)

### Invoice Workflow

Standard pattern for invoice requests:

1. Look up client rate/contract → auto
2. Generate invoice document → auto or manual
3. Send invoice via email → requires approval
4. Log transaction in /Accounting/ → auto
5. Schedule payment follow-up (net-30) → auto

### Meeting Request

Standard pattern:

1. Check calendar for availability → auto
2. Propose 2-3 time slots → auto
3. Reply with available times → requires approval
4. On confirmation: create calendar event → auto (or requires approval per Handbook)

### Client Onboarding

Complex pattern:

1. Create client file in vault → auto
2. Send welcome email → requires approval
3. Set up project folder structure → auto
4. Schedule kickoff meeting → see Meeting Request pattern
5. Send contract for signing → requires approval
6. Set up billing in /Accounting/ → auto
```

#### Section 5: Integration with Other Skills

```markdown
## Integration with Other Skills

### With email-triage

When email-triage identifies a TASK_REQUEST or multi-part email:

1. email-triage creates an initial Plan with category TASK_REQUEST
2. If task has >2 steps → invoke task-planner to decompose
3. task-planner creates a detailed multi-step Plan (replaces the simple one)
4. task-planner calls hitl-handler for steps needing approval

### With hitl-handler

For each step with requires_approval: true:

1. When that step becomes 📋 pending (all dependencies met)
2. Create an approval request via hitl-handler skill
3. Link the approval request to this Plan via source_plan field
4. Update step status to ⏳ in_progress (waiting for approval)
5. On approval → mark ✅ done, proceed to next steps
6. On rejection → mark ⏭ skipped or ❌ failed (depending on criticality)

### With vault-processor

Use vault-processor CLI for all file operations:

- Creating Plan files: write directly (vault_helpers)
- Moving files: uv run python -m scripts.utils.vault_processor move-file
- Checking queue: uv run python -m scripts.utils.vault_processor counts
- Listing items: uv run python -m scripts.utils.vault_processor list-folder Plans
```

#### Section 6: Quality Rules

```markdown
## Quality Rules

1. **Every step must be actionable** — "Think about it" is not a step
2. **Steps should be atomic** — one action per step, no compound steps
3. **Dependencies must be explicit** — never assume ordering
4. **Estimate effort** — help the human prioritize
5. **Tag for searchability** — include relevant domain tags
6. **Don't over-plan** — 2-step tasks don't need a 10-step plan
7. **Parallel when possible** — identify steps that can run concurrently
8. **Plan filenames must be unique** — include enough context to distinguish
9. **Update timestamps** — update the `updated` field whenever Plan changes
10. **Link back to source** — always include source_file reference
```

#### Section 7: Example Output

```markdown
## Example: Multi-Request Email Plan

For an email from Sarah requesting invoice + contract renewal + meeting:

---

type: plan
plan_type: multi_step
source_type: email
source_file: "Needs_Action/email/EMAIL_sarah_johnson_2026-02-27T10-00-00.md"
title: "Sarah Johnson — Invoice, Renewal, and Meeting"
priority: high
status: pending
total_steps: 7
completed_steps: 0
requires_approval: true
created: "2026-02-27T10:35:00Z"
updated: "2026-02-27T10:35:00Z"
estimated_effort: "45 minutes"
due_date: "2026-02-28T17:00:00Z"
tags: ["email", "invoice", "contract", "meeting", "client-b"]

---

## Sarah Johnson — Invoice, Renewal, and Meeting

**Source:** Email from Sarah Johnson requesting January invoice, contract renewal discussion, and meeting scheduling.
**Priority:** High
**Status:** Pending
**Progress:** 0/7 steps complete

## Steps

### Step 1: Look up Client B billing rate

- **Status:** 📋 pending
- **Domain:** accounting
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Check /Accounting/Rates.md for Client B's current rate

Look up Sarah Johnson / Client B's current billing rate and contract terms in the vault.

### Step 2: Generate January invoice

- **Status:** ⏸ blocked
- **Domain:** accounting
- **Depends On:** Step 1
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Use rate from Step 1, generate PDF

Calculate January charges based on rate, generate invoice document.

### Step 3: Send invoice via email

- **Status:** ⏸ blocked
- **Domain:** email
- **Depends On:** Step 2
- **Requires Approval:** Yes
- **Assigned To:** auto → hitl-handler
- **Notes:** Email to sarah@clientb.com with invoice attached

Draft and send invoice email. Requires HITL approval before sending.

### Step 4: Check calendar availability

- **Status:** 📋 pending
- **Domain:** calendar
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Next Tuesday or Wednesday per Sarah's request

Check calendar for available slots next Tuesday and Wednesday. Can run in parallel with Steps 1-3.

### Step 5: Draft renewal discussion points

- **Status:** 📋 pending
- **Domain:** manual
- **Depends On:** None
- **Requires Approval:** No
- **Assigned To:** human
- **Notes:** Contract expires March — prepare talking points

Prepare discussion points for contract renewal. This requires human input on terms.

### Step 6: Reply to Sarah with all items

- **Status:** ⏸ blocked
- **Domain:** email
- **Depends On:** Steps 3, 4, 5
- **Requires Approval:** Yes
- **Assigned To:** auto → hitl-handler
- **Notes:** Comprehensive reply covering all three requests

Draft a reply covering: invoice sent (Step 3), available meeting times (Step 4), and renewal discussion setup (Step 5). Requires HITL approval.

### Step 7: Log transaction

- **Status:** ⏸ blocked
- **Domain:** accounting
- **Depends On:** Step 3
- **Requires Approval:** No
- **Assigned To:** auto
- **Notes:** Record invoice in /Accounting/

Log the invoice in /Accounting/ for the CEO briefing.

## Dependencies
```

Step 1 ──▶ Step 2 ──▶ Step 3 ──▶ Step 6
Step 3 ──▶ Step 7
Step 4 ──────────────────────▶ Step 6
Step 5 ──────────────────────▶ Step 6

```

## Approval Requirements

- **Step 3:** Sending invoice email to external recipient → HITL required
- **Step 6:** Reply email to client → HITL required

## Notes

- Steps 1, 4, and 5 can start immediately (no dependencies)
- Sarah mentioned Friday deadline for invoice — prioritize Steps 1-3
- Contract renewal is less urgent but should be addressed in the reply
```

## 3. Validation Criteria

- [ ] `.claude/skills/task-planner/SKILL.md` exists with valid frontmatter
- [ ] Skill defines Plan file format with all required fields
- [ ] 6 step statuses defined with lifecycle rules
- [ ] Dependency resolution logic documented
- [ ] Decomposition strategies for 4+ common patterns
- [ ] Integration points with email-triage and hitl-handler defined
- [ ] Quality rules prevent over-planning
- [ ] Example output is complete and realistic
- [ ] File renders as valid Markdown in Obsidian
- [ ] No executable code (prompt template only)
- [ ] No modifications to existing files

---
