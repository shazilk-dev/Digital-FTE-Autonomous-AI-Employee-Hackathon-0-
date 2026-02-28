# Spec: Social Post Agent Skill — LinkedIn Content Strategy

> **Component:** `.claude/skills/social-post/SKILL.md`
> **Type:** Agent Skill (prompt template, NOT executable code)
> **Priority:** P1 — Business-value automation: thought-leadership posting
> **Depends On:** `Business_Goals.md`, `hitl-handler` skill, LinkedIn MCP (S5)

## 1. Objective

Teach Claude Code how to draft LinkedIn posts that are:
- Aligned with `Business_Goals.md` objectives
- Authentic to the user's voice and industry
- Optimized for LinkedIn engagement patterns
- Routed through HITL approval before posting

This skill is invoked:
- On a schedule (Mon/Wed/Fri via orchestrator in S6)
- Manually by the user ("Draft a LinkedIn post about X")
- Triggered by a completed project milestone (from /Done/ analysis)

## 2. SKILL.md Structure

### 2A. YAML Frontmatter

```yaml
---
name: social-post
description: >
  Drafts LinkedIn posts aligned with Business_Goals.md. Reads business context,
  recent activity, and industry trends to generate authentic thought-leadership
  content. All posts go through HITL approval before publishing.
  Supports scheduled posting (Mon/Wed/Fri) and ad-hoc drafting.
allowed-tools:
  - Bash(uv run python -m scripts.utils.vault_processor *)
  - Bash(uv run python -m scripts.utils.dashboard_updater *)
  - Bash(cat *)
  - Bash(ls *)
  - Read
  - Write
---
```

### 2B. Skill Body

---

#### Section 1: Context Gathering

```markdown
# Social Post Skill

## Step 1: Gather Context Before Drafting

Before writing ANY post, read these sources:

1. **Business_Goals.md** — current objectives, metrics, active projects
2. **Recent /Done/ files** — what was accomplished this week (fuel for posts)
3. **Previous posts** — check /Done/ for recent ACTION_linkedin_post files
   to avoid repetition and maintain content variety

Build a mental model of:
- What the business does and who it serves
- Current quarter's goals and progress
- Recent wins or milestones worth sharing
- Topics the user has posted about recently (avoid repeating)
```

#### Section 2: Content Strategy

```markdown
## Content Strategy

### Post Types (Rotate Weekly)

| Day | Post Type | Description | Example |
|-----|-----------|-------------|---------|
| Monday | Insight Post | Industry observation or lesson learned | "One thing I've noticed about X..." |
| Wednesday | Value Post | Practical tip or framework | "3 steps to improve your..." |
| Friday | Story Post | Personal experience or milestone | "This week we launched..." |

### Content Pillars

Derive content pillars from Business_Goals.md:
1. **Expertise Pillar** — demonstrate domain knowledge
2. **Growth Pillar** — share business progress and wins
3. **Community Pillar** — engage with industry trends and peers
4. **Behind-the-Scenes** — humanize the business

Rotate between pillars to maintain variety. Never post the same pillar
twice in a row.

### Engagement Optimization

LinkedIn best practices (2026):
- **Length:** 800-1300 characters performs best (not too short, not too long)
- **Opening hook:** First 2 lines must grab attention (visible before "see more")
- **Line breaks:** Use single-line paragraphs for readability
- **No hashtag spam:** 3-5 relevant hashtags maximum, at the end
- **Call to action:** End with a question or invitation to comment
- **No links in body:** LinkedIn deprioritizes posts with external links.
  If sharing a link, put it in the first comment (note in the approval file)
- **Emojis:** Sparingly — 1-2 per post max, if they fit the tone
- **Time of posting:** Weekday mornings (8-10am local) or lunch (12-1pm)
```

#### Section 3: Drafting Process

```markdown
## Drafting Process

### Step 1: Choose Post Type and Pillar
Based on the day of the week and recent posting history, select:
- Post type (Insight / Value / Story)
- Content pillar (Expertise / Growth / Community / Behind-the-Scenes)

### Step 2: Draft the Post

Follow this structure:

**Line 1-2: Hook** (visible before "see more")
A bold statement, surprising statistic, or compelling question.

**Lines 3-8: Body**
The meat of the post. Tell the story, share the insight, or deliver the value.
Use short paragraphs (1-2 sentences each).

**Line 9-10: Takeaway**
The key lesson or call-to-action.

**Last line: Hashtags**
3-5 relevant hashtags.

### Step 3: Self-Review Checklist

Before creating the approval request, verify:
- [ ] Opening hook is compelling (would YOU click "see more"?)
- [ ] Content is authentic (not generic AI slop)
- [ ] Aligned with at least one Business_Goals.md objective
- [ ] Character count is 800-1300
- [ ] Not similar to recent posts (check /Done/ for last 5 linkedin posts)
- [ ] No external links in body (put in comment note if needed)
- [ ] 3-5 hashtags (no more)
- [ ] Ends with engagement trigger (question or CTA)

### Step 4: Create Approval Request

Use the hitl-handler skill to create an approval request:

action_type: linkedin_post
domain: social
target: "LinkedIn"
action_payload:
  tool: create_post
  server: linkedin
  params:
    content: "{the drafted post text}"
    visibility: "public"

Include in the approval file body:
- The full post text (formatted as it will appear)
- Character count
- Content pillar and post type used
- Which business goal it supports
- Suggested posting time
- Optional: suggested first comment (for links or additional context)
```

#### Section 4: Scheduled Posting

```markdown
## Scheduled Posting

When invoked by the orchestrator on a schedule (Mon/Wed/Fri):

1. Check if a post was already drafted today → if yes, skip
2. Determine which post type matches today (Mon=Insight, Wed=Value, Fri=Story)
3. Gather context (Step 1)
4. Draft post (Step 2)
5. Self-review (Step 3)
6. Create approval request (Step 4)
7. Log to Dashboard: "LinkedIn post drafted, awaiting approval"

The post waits in /Pending_Approval/social/ until the human approves.
The human may:
- Approve as-is → posted automatically
- Edit the content in the approval file → posted with edits
- Reject → logged, no post
- Ignore → flagged as stale after 24hrs

### Posting Cadence Notes

- Never post more than once per day
- If the human hasn't approved Monday's post by Wednesday, skip Wednesday
  (don't pile up unapproved posts — it creates review fatigue)
- Track posting history to maintain 3x/week target
```

#### Section 5: Ad-Hoc Post Drafting

```markdown
## Ad-Hoc Post Drafting

When the user explicitly asks to draft a LinkedIn post:

1. If they provide a topic: use it directly
2. If they say "draft a LinkedIn post": gather context and suggest 2-3 options
3. Apply the same drafting process and quality checks
4. Create approval request
5. Let the user know: "Draft created in /Pending_Approval/social/. Review and approve to post."
```

#### Section 6: Milestone-Triggered Posts

```markdown
## Milestone-Triggered Posts

When a significant task completes (detected from /Done/ files):

Triggers:
- A Plan file with plan_type: multi_step moves to /Done/ with status: done
- An invoice is sent successfully (from HITL execution logs)
- A project is marked complete in Business_Goals.md

Action:
1. Draft a "win" post about the milestone
2. Keep it authentic — share the journey, not just the result
3. Route through HITL (the user decides if they want to share)
4. Lower priority than scheduled posts — don't post more than 1x/day
```

#### Section 7: Content Templates

```markdown
## Content Templates

### Template: Insight Post
```
{Hook: Bold observation or counterintuitive take}

{2-3 short paragraphs expanding on the insight}

{Why this matters for the reader}

{Question for engagement}

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Value Post
```
{Hook: Promise of value — "Here's how I..." or "N things I learned about..."}

{Step/tip 1}

{Step/tip 2}

{Step/tip 3}

{Summary takeaway}

What would you add to this list?

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Story Post
```
{Hook: Set the scene — "Last week something happened that..."}

{The challenge or situation}

{What you did}

{The result}

{The lesson}

Has anyone else experienced something similar?

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Milestone Win
```
{Hook: Announcement — "Excited to share..." or "Just shipped..."}

{What was accomplished}

{Why it matters}

{Thank you / shoutout if applicable}

{What's next}

#{hashtag1} #{hashtag2} #{hashtag3}
```
```

#### Section 8: Quality Rules

```markdown
## Quality Rules

1. **Authenticity over optimization** — don't write generic inspirational fluff
2. **Business alignment** — every post must connect to Business_Goals.md
3. **Voice consistency** — match the user's tone from Company_Handbook.md
4. **No engagement bait** — don't use "Agree?" or clickbait tactics
5. **Substance over form** — an 800-char post with real insight beats a 1300-char post with filler
6. **Variety** — never post the same template type twice in a row
7. **Humility** — share learnings, not just wins
8. **One idea per post** — don't try to cover everything
9. **Proofread** — check grammar, spelling, and formatting before approval request
10. **Respect the human's time** — the approval file should be ready to approve with minimal edits
```

## 3. Validation Criteria

- [ ] `.claude/skills/social-post/SKILL.md` exists with valid frontmatter
- [ ] Skill reads Business_Goals.md for context
- [ ] 4 post types with content templates
- [ ] 4 content pillars for variety
- [ ] Engagement optimization guidelines (length, hooks, hashtags)
- [ ] Self-review checklist before approval request
- [ ] Scheduled posting logic (Mon/Wed/Fri)
- [ ] Ad-hoc drafting process
- [ ] Milestone-triggered post detection
- [ ] All posts routed through hitl-handler
- [ ] Quality rules prevent generic AI content
- [ ] No executable code (prompt template only)
- [ ] No modifications to existing files
