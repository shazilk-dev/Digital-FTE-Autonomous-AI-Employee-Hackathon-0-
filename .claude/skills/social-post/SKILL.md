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
  - Bash(ls -t Done/ACTION_linkedin_post_*.md *)
  - Bash(ls -t Done/ *)
  - Bash(mkdir -p *)
  - Read
  - Write
---

# Social Post Skill

## Step 1: Gather Context Before Drafting

Before writing ANY post, read these sources in order:

**1. Business Goals**
Read `Business_Goals.md` — current objectives, metrics, active projects, and content pillars.

**2. Recent Completed Work (fuel for posts)**
Run this command to get the 10 most recently completed tasks — do NOT read all of /Done/:
```bash
ls -t Done/ | head -n 10
```
Then read only the files that look relevant (milestones, shipped work, client wins).
Never scan the entire /Done/ folder — it may contain hundreds of files.

**3. Recent LinkedIn Post History (avoid repetition)**
Run this command to find the 5 most recent LinkedIn posts:
```bash
ls -t Done/ACTION_linkedin_post_*.md 2>/dev/null | head -n 5
```
Read each file and note: topic, post type, content pillar, and date.
If fewer than 5 exist, that's fine — proceed.

Build a mental model of:
- What the business does and who it serves
- Current quarter's goals and progress
- Recent wins or milestones worth sharing
- Topics posted about recently (avoid repeating same angle within 2 weeks)
- Which content pillars have been used recently (rotate to maintain variety)

---

## Content Strategy

### Post Types (Rotate Weekly)

| Day | Post Type | Description | Example Hook |
|-----|-----------|-------------|--------------|
| Monday | Insight Post | Industry observation or lesson learned | "One thing I've noticed about X..." |
| Wednesday | Value Post | Practical tip or framework | "3 steps to improve your..." |
| Friday | Story Post | Personal experience or milestone | "This week we launched..." |

If today is not Mon/Wed/Fri (e.g., ad-hoc request), pick the post type that best fits the topic or the type least recently used.

### Content Pillars

Derive content pillars from `Business_Goals.md` Content Pillars section.
Fall back to these universal pillars if the file has TODO placeholders:

1. **Expertise** — demonstrate domain knowledge and hard-won insights
2. **Growth** — share business progress, wins, and lessons from setbacks
3. **Community** — engage with industry trends, peer challenges, open questions
4. **Behind-the-Scenes** — humanize the business and show the process

Rotate between pillars. Never use the same pillar twice in a row.

### LinkedIn Engagement Best Practices (2026)

- **Length:** 800–1300 characters performs best — not too short, not too long
- **Opening hook:** First 2 lines must compel "see more" — bold statement, surprising stat, or question
- **Line breaks:** Single-line paragraphs; dense blocks kill engagement
- **Hashtags:** 3–5 relevant hashtags at the end. No hashtag spam.
- **No links in body:** LinkedIn deprioritizes posts with external links.
  If sharing a link, note it as a suggested first comment in the approval file.
- **Emojis:** Sparingly — 1–2 per post max, only if they fit the tone
- **CTA:** End with a question or invitation to comment — not "Agree?" (too generic)
- **Best posting time:** Weekday mornings 8–10am or lunch 12–1pm local time

---

## Drafting Process

### Step 1: Choose Post Type and Pillar

Based on:
- Day of the week (Mon=Insight, Wed=Value, Fri=Story)
- Recent posting history (pillar and type used last — avoid repeating)
- Available content from /Done/ (what's worth sharing)
- Business_Goals.md content pillars

State your choice explicitly before drafting: "Drafting a [type] post for the [pillar] pillar."

### Step 2: Draft the Post

Follow this structure:

**Lines 1–2: Hook** (visible before "see more")
A bold statement, surprising insight, or compelling question.
This must make someone stop scrolling. Write this last, after you know what the post says.

**Lines 3–8: Body**
The substance — story, insight, or value. 1–2 sentences per paragraph.
Specific > general. "We cut onboarding time from 3 days to 4 hours" beats "We improved efficiency."

**Line 9–10: Takeaway**
The key lesson or call-to-action. What should the reader walk away with?

**Last line: Hashtags**
3–5 hashtags, all lowercase, no spaces. Place on a separate line.

### Step 3: Self-Review Checklist

Before creating the approval request, verify every item:

- [ ] Opening hook is compelling — would YOU click "see more"?
- [ ] Content is authentic — specific, not generic AI fluff
- [ ] Aligned with at least one Business_Goals.md objective or pillar
- [ ] Character count is 800–1300 (count it)
- [ ] Not similar to any of the 5 most recent LinkedIn posts
- [ ] No external links in body (add to first comment note if needed)
- [ ] 3–5 hashtags, no more
- [ ] Ends with an engagement trigger (question or CTA — not "Agree?")
- [ ] Grammar, spelling, and formatting checked

If any item fails, revise before proceeding.

### Step 4: Create Approval Request

Use the hitl-handler skill to create an approval request:

```
action_type: linkedin_post
domain: social
target: "LinkedIn"
action_payload:
  tool: create_post
  server: linkedin
  params:
    content: "{the full drafted post text}"
    visibility: "public"
```

Ensure `/Pending_Approval/social/` exists:
```bash
mkdir -p Pending_Approval/social
```

Include in the approval file body (below the frontmatter):
- The full post text formatted exactly as it will appear on LinkedIn
- Character count
- Content pillar and post type used
- Which Business_Goals.md objective it supports
- Suggested posting time (e.g., "Monday 9am local")
- Optional: suggested first comment (for links or additional context)

### Step 5: Update Dashboard

```bash
uv run python -m scripts.utils.dashboard_updater add-activity \
  "linkedin_post_drafted" "LinkedIn [type] post drafted for [pillar] pillar" "pending_approval"

uv run python -m scripts.utils.dashboard_updater add-pending \
  --type "linkedin_post" --from "social-post-skill" --subject "[first 60 chars of hook]" --priority "medium"
```

---

## Scheduled Posting

When invoked by the orchestrator on a schedule (Mon/Wed/Fri):

1. Check if a LinkedIn post was already drafted today:
   ```bash
   ls -t Done/ACTION_linkedin_post_*.md Pending_Approval/social/ACTION_linkedin_post_*.md 2>/dev/null | head -n 3
   ```
   If any file was created today (check the timestamp in the filename) → skip and log "Post already drafted today."

2. Determine post type from day of week (Mon=Insight, Wed=Value, Fri=Story)
3. Gather context (Step 1)
4. Draft post (Step 2)
5. Self-review (Step 3)
6. Create approval request (Step 4)
7. Update Dashboard (Step 5)
8. Inform: "LinkedIn post drafted and awaiting approval in /Pending_Approval/social/"

### Cadence Rules

- Never post more than once per day
- If Monday's post has not been approved by Wednesday: skip Wednesday's scheduled post.
  Log: "Skipped Wednesday post — Monday post still pending approval."
  Rationale: stacking unapproved posts creates review fatigue.
- Track posting history via the 5-file ls command above

---

## Ad-Hoc Post Drafting

When the user explicitly asks to draft a LinkedIn post:

1. If they provide a topic: use it directly, skip to Step 2 of the Drafting Process
2. If they say "draft a LinkedIn post" with no topic:
   - Gather context (Step 1)
   - Suggest 2–3 topic options with the post type and pillar for each
   - Ask which they prefer before drafting
3. Apply the full drafting process and self-review checklist
4. Create approval request
5. Tell the user: "Draft created in /Pending_Approval/social/. Review and approve to post."

---

## Milestone-Triggered Posts

When a significant task completes (detected from /Done/ files via orchestrator):

**Triggers:**
- A Plan file with `plan_type: multi_step` moves to /Done/ with `status: done`
- An invoice is sent successfully (from HITL execution logs in /Done/)
- A project is marked complete in Business_Goals.md

**Action:**
1. Draft a win post about the milestone using the **Milestone Win** template
2. Keep it authentic — share the journey, not just the outcome. Mention what was hard.
3. Route through HITL approval (the user decides if they want to share)
4. If a scheduled post is already pending today: skip the milestone post for today.
   Lower priority than scheduled posts — never exceed 1 post/day.

---

## Content Templates

### Template: Insight Post
```
{Hook: Bold observation or counterintuitive take about your industry}

{Paragraph 1: Why this observation surprised you or what prompted it}

{Paragraph 2: The evidence or reasoning behind it}

{Paragraph 3: What this means for practitioners}

{Takeaway: The one-line lesson}

{Question to invite comments}

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Value Post
```
{Hook: Promise of value — "Here's how I..." or "N things I learned about..."}

{Tip/step 1: short and specific}

{Tip/step 2: short and specific}

{Tip/step 3: short and specific}

{Summary: Why these matter together}

{Question: "What would you add?"}

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Story Post
```
{Hook: Set the scene — a specific moment, not a vague opener}

{The challenge or situation: what was at stake}

{What you did: the decision or action taken}

{The result: specific, not just "it worked"}

{The lesson: what you'd do differently or what this taught you}

{Question: "Has anyone else faced this?"}

#{hashtag1} #{hashtag2} #{hashtag3}
```

### Template: Milestone Win
```
{Hook: Announcement — "Just shipped..." or "Excited to share..."}

{What was accomplished: be specific about what was built or delivered}

{Why it matters: who benefits and how}

{The journey: one honest sentence about what was hard}

{What's next: brief forward-looking note}

#{hashtag1} #{hashtag2} #{hashtag3}
```

---

## Quality Rules

1. **Authenticity over optimization** — specific insight beats polished fluff every time
2. **Business alignment** — every post connects to Business_Goals.md objectives or pillars
3. **Voice consistency** — match the user's tone from Company_Handbook.md
4. **No engagement bait** — never use "Agree?" or "Like if you..." tactics
5. **Substance over length** — an 800-char post with real insight beats 1300 chars of filler
6. **Variety** — never use the same template type or pillar twice in a row
7. **Humility** — share learnings and struggles, not just wins
8. **One idea per post** — don't try to cover three topics in one post
9. **Proofread** — check grammar, spelling, and line breaks before creating approval file
10. **Respect the human's time** — the approval file should be ready to approve with zero edits needed
