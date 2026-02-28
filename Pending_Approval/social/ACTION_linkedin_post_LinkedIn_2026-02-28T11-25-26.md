---
type: approval_request
action_type: linkedin_post
domain: social
target: "LinkedIn"
priority: medium
status: pending_approval
requires_approval: true
created: "2026-02-28T11:25:26+00:00"
expires: "2026-03-01T11:25:26+00:00"
source_plan: null
source_task: null
action_payload:
  tool: create_post
  server: linkedin
  params:
    content: |
      Everyone wants AI to work autonomously. Nobody talks about what happens when it gets something wrong.

      I've spent the last month building what I call an "AI Employee" — a Claude Code-powered system that reads my inbox, triages emails, drafts responses, and manages task workflows without me touching it.

      Here's the uncomfortable truth I learned: the hard part isn't the AI. It's designing the safety layer.

      Every action the system wants to take — send an email, post to LinkedIn, make a payment — must pass through a human-in-the-loop checkpoint first. Not because the AI is stupid. Because business consequences are irreversible.

      The pattern that works: AI drafts → human approves → system executes. The AI's job is to make that approval so easy that "approve" takes 3 seconds.

      That shift — from "AI that does things" to "AI that prepares decisions" — is what makes it actually trustworthy in production.

      Autonomous AI isn't about removing humans. It's about putting humans where they add the most value: judgment calls.

      What's your biggest hesitation with delegating tasks to AI in your workflow?

      #AIAutomation #ProductivityTools #Entrepreneurship #WorkflowDesign
    visibility: "public"
---

## Action Summary

**Type:** LinkedIn Post
**Target:** LinkedIn (your profile)
**Priority:** Medium
**Post Type:** Insight Post
**Content Pillar:** Expertise

---

## Post Preview

*Formatted exactly as it will appear on LinkedIn:*

---

Everyone wants AI to work autonomously. Nobody talks about what happens when it gets something wrong.

I've spent the last month building what I call an "AI Employee" — a Claude Code-powered system that reads my inbox, triages emails, drafts responses, and manages task workflows without me touching it.

Here's the uncomfortable truth I learned: the hard part isn't the AI. It's designing the safety layer.

Every action the system wants to take — send an email, post to LinkedIn, make a payment — must pass through a human-in-the-loop checkpoint first. Not because the AI is stupid. Because business consequences are irreversible.

The pattern that works: AI drafts → human approves → system executes. The AI's job is to make that approval so easy that "approve" takes 3 seconds.

That shift — from "AI that does things" to "AI that prepares decisions" — is what makes it actually trustworthy in production.

Autonomous AI isn't about removing humans. It's about putting humans where they add the most value: judgment calls.

What's your biggest hesitation with delegating tasks to AI in your workflow?

#AIAutomation #ProductivityTools #Entrepreneurship #WorkflowDesign

---

## Post Metadata

| Field | Value |
|-------|-------|
| Character count | ~1,162 |
| Post type | Insight Post (counterintuitive industry take) |
| Content pillar | Expertise |
| Business goal | Online presence + demonstrating AI/automation expertise |
| Suggested posting time | **Monday 2026-03-02, 9am local** |
| Hashtag count | 4 (within 3–5 limit) |

## Context

This post was drafted by the social-post skill on 2026-02-28 (Saturday, ad-hoc).

Business_Goals.md has not yet been customized with specific objectives — the content is drawn from the most significant real activity in the vault: the AI Employee system itself. The core insight (HITL safety layer as the true challenge of AI automation) is specific, authentic, and directly demonstrates the expertise pillar.

No previous LinkedIn posts exist — this is the first post in the vault's history.

## Self-Review Checklist

- [x] Opening hook is compelling — "Nobody talks about what happens when it gets something wrong" stops the scroll
- [x] Content is authentic — drawn from what was actually built, not generic advice
- [x] Aligned with business objectives — demonstrates expertise in AI automation
- [x] Character count ~1,162 — within 800–1,300 target
- [x] Not similar to recent posts — no prior LinkedIn history
- [x] No external links in body
- [x] 4 hashtags — within 3–5 limit
- [x] Ends with engagement trigger — open question about reader's hesitations
- [x] Grammar and formatting checked

## How to Approve or Reject

### ✅ To Approve
Move this file to the `/Approved/` folder. The LinkedIn MCP will post it automatically.

### ❌ To Reject
Move this file to the `/Rejected/` folder. No action will be taken.

### ✏️ To Modify
Edit `action_payload.params.content` in the frontmatter above before approving.
The content field is what gets posted — your edits will be reflected exactly.

## Safety Notes

- This action requires `DRY_RUN=false` in the linkedin-mcp env to post for real
- Currently `DRY_RUN=true` — the MCP will simulate but not actually post
- Verify your LinkedIn session is active (`npm run setup-session` in mcp-servers/linkedin-mcp) before approving
- This approval expires 2026-03-01T11:25:26+00:00 — after that it will be flagged stale
