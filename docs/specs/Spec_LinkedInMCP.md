# Spec: LinkedIn MCP Server — Playwright-Based Posting

> **Component:** `mcp-servers/linkedin-mcp/` (Node.js/TypeScript)
> **Protocol:** Model Context Protocol (MCP) over stdio
> **Priority:** P1 — First social media action capability
> **External Dependency:** Playwright (Chromium), LinkedIn Web session
> **Risk Level:** MEDIUM — Browser automation, rate limit strictly

## 1. Objective

Build an MCP server that enables Claude Code to post content to LinkedIn via
Playwright browser automation. The server exposes tools for creating posts
and reading profile info, with persistent session management and DRY_RUN safety.

## 2. File Structure

```
mcp-servers/linkedin-mcp/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts                  # MCP server entry
│   ├── tools/
│   │   ├── create_post.ts        # Create a LinkedIn post
│   │   └── get_profile_info.ts   # Read profile (for context)
│   ├── utils/
│   │   ├── browser_session.ts    # Persistent Playwright session manager
│   │   ├── setup_session.ts      # First-time login helper (standalone)
│   │   ├── dry_run.ts            # DRY_RUN gate (same pattern as Email MCP)
│   │   ├── logger.ts             # Structured stderr logging
│   │   └── rate_limiter.ts       # LinkedIn-specific rate limiting
│   └── cli.ts                    # Direct CLI for Action Executor
└── tests/                        # Optional
```

## 3. MCP Server Entry: `src/index.ts`

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({
  name: "linkedin-mcp",
  version: "0.2.0",
  description: "LinkedIn integration for the AI Employee. Create posts and read profile info.",
});
```

Register two tools: `create_post` and `get_profile_info`.

## 4. Tool Specifications

### 4A. `create_post`

**Purpose:** Publish a text post to LinkedIn.

**Input Schema:**
```typescript
{
  content: z.string().min(1).max(3000).describe("Post text content (LinkedIn max ~3000 chars)"),
  visibility: z.enum(["public", "connections"]).default("public")
    .describe("Post visibility: public or connections only"),
}
```

**Handler Logic:**

1. Check DRY_RUN → if true, return draft preview
2. Check rate limiter → if exceeded, return rate limit message
3. Get browser page via `BrowserSession.getPage()`
4. Navigate to LinkedIn feed: `https://www.linkedin.com/feed/`
5. Wait for feed to load (selector: post creation area)
6. Click "Start a post" button
7. Wait for post modal to appear
8. Type content character-by-character with human-like delays
9. If visibility == "connections": click visibility selector, choose connections
10. Click "Post" button
11. Wait for post confirmation (URL changes or success indicator)
12. Return success with post URL if available

**DRY_RUN Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "[DRY RUN] Would post to LinkedIn:\n\nVisibility: public\nContent (247 chars):\n---\nExcited to share that our Q1 project...\n---\n\nSet DRY_RUN=false to post for real."
  }]
}
```

**Live Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "Posted to LinkedIn successfully.\n  Visibility: public\n  Content: (247 chars)\n  Time: 2026-02-27T14:30:00Z"
  }]
}
```

**Error Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "Failed to post to LinkedIn: Session expired. Run setup_session to re-login."
  }],
  "isError": true
}
```

### 4B. `get_profile_info`

**Purpose:** Read the authenticated user's LinkedIn profile for context.
Useful for the social-post skill to personalize content.

**Input Schema:**
```typescript
{
  // No required inputs — reads the authenticated user's own profile
}
```

**Handler Logic:**

1. DRY_RUN check NOT needed (read-only, safe)
2. Get browser page
3. Navigate to `https://www.linkedin.com/in/me/`
4. Extract: name, headline, about summary, recent post count
5. Return formatted profile info

**Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "LinkedIn Profile:\n  Name: Your Name\n  Headline: CEO at Example Corp\n  About: Building the future of...\n  Recent posts: 12 in last 30 days"
  }]
}
```

## 5. Browser Session Manager: `src/utils/browser_session.ts`

### 5A. Design

Same persistent context pattern as WhatsApp Watcher, adapted for Node.js Playwright.

```typescript
import { chromium, BrowserContext, Page } from "playwright";

class BrowserSession {
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private sessionPath: string;
  private headless: boolean;

  constructor(sessionPath?: string, headless?: boolean) {
    this.sessionPath = sessionPath || process.env.LINKEDIN_SESSION_PATH || "./sessions/linkedin";
    this.headless = headless ?? (process.env.LINKEDIN_HEADLESS !== "false");
  }

  async getPage(): Promise<Page> {
    /**
     * Lazy-initialize browser and return active page.
     *
     * 1. If page exists and responsive → return it
     * 2. Launch persistent context with session path
     * 3. Navigate to LinkedIn
     * 4. Check if logged in (profile nav element visible)
     * 5. If not logged in → throw SessionExpiredError
     * 6. Return page
     */
  }

  async close(): Promise<void> {
    /** Close browser, save session. */
  }

  async isLoggedIn(page: Page): Promise<boolean> {
    /**
     * Check if the LinkedIn session is still valid.
     * Look for authenticated UI elements (profile picture, nav bar).
     * Timeout: 15 seconds.
     */
  }
}
```

### 5B. Session Path

```
sessions/linkedin/
├── Default/          # Chromium profile data
├── Cookies           # Session cookies
└── Local Storage/    # LinkedIn tokens
```

This path MUST be in `.gitignore` (already covered by `sessions/` pattern).

### 5C. First-Time Setup: `src/utils/setup_session.ts`

Standalone script (not part of MCP server) for initial LinkedIn login:

```typescript
// Usage: npx tsx src/utils/setup_session.ts [--visible]
//
// Opens a visible Chromium browser pointed at LinkedIn.
// User logs in manually. Session is saved to disk.
// Subsequent MCP server launches use the saved session headlessly.

import { chromium } from "playwright";

async function setup() {
  const sessionPath = process.env.LINKEDIN_SESSION_PATH || "./sessions/linkedin";

  console.log("Opening LinkedIn for login...");
  console.log("Log in, then press Enter in this terminal to save and exit.");

  const context = await chromium.launchPersistentContext(sessionPath, {
    headless: false,
    viewport: { width: 1280, height: 720 },
  });

  const page = context.pages()[0] || await context.newPage();
  await page.goto("https://www.linkedin.com/login");

  // Wait for user to log in
  await new Promise<void>((resolve) => {
    process.stdin.once("data", () => resolve());
  });

  // Verify login
  await page.goto("https://www.linkedin.com/feed/");
  // Check for authenticated elements

  console.log("Session saved. You can now run the MCP server in headless mode.");
  await context.close();
}

setup().catch(console.error);
```

## 6. Rate Limiter: `src/utils/rate_limiter.ts`

LinkedIn is strict about automation. Conservative limits:

```typescript
class LinkedInRateLimiter {
  private postTimestamps: number[] = [];

  // Hard limits
  private readonly MAX_POSTS_PER_DAY = 3;
  private readonly MAX_POSTS_PER_HOUR = 1;
  private readonly MIN_DELAY_BETWEEN_POSTS_MS = 30 * 60 * 1000; // 30 minutes

  async canPost(): Promise<{ allowed: boolean; reason?: string; retryAfterMs?: number }> {
    /**
     * Check if posting is allowed right now.
     *
     * Returns:
     * - allowed: true if within rate limits
     * - reason: why it's blocked (if not allowed)
     * - retryAfterMs: how long to wait (if not allowed)
     */
  }

  recordPost(): void {
    /** Record a successful post timestamp. */
  }
}
```

## 7. Human-Like Interaction Delays

Critical for avoiding detection:

```typescript
const DELAYS = {
  PAGE_LOAD: 3000,              // Wait after page navigation
  BEFORE_CLICK: randomDelay(500, 1500),   // Before clicking any element
  BETWEEN_KEYSTROKES: randomDelay(30, 80), // Typing speed
  AFTER_TYPING: randomDelay(1000, 3000),   // Pause after typing content
  BEFORE_POST: randomDelay(2000, 5000),    // Final pause before clicking Post
  AFTER_POST: randomDelay(3000, 6000),     // Wait after posting
};

function randomDelay(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

async function humanDelay(type: keyof typeof DELAYS): Promise<void> {
  const delay = typeof DELAYS[type] === "function" ? DELAYS[type]() : DELAYS[type];
  await new Promise(resolve => setTimeout(resolve, delay));
}
```

## 8. LinkedIn Selectors

```typescript
// Current as of Feb 2026 — will need maintenance
const SELECTORS = {
  // Feed page
  feed_loaded: '[data-test-id="feed-page"]',
  start_post_button: '.share-box-feed-entry__trigger',
  start_post_fallback: '[aria-label*="Start a post"]',

  // Post creation modal
  post_modal: '.share-creation-state__text-editor',
  post_text_area: '[role="textbox"][aria-label*="Text editor"]',
  post_text_fallback: '.ql-editor',
  visibility_button: '.share-creation-state__visibility-button',
  post_button: '.share-actions__primary-action',
  post_button_fallback: 'button[aria-label*="Post"]',

  // Post confirmation
  post_success: '.feed-shared-update-v2',

  // Login detection
  logged_in_indicator: '.global-nav__me',
  login_page: '#username',

  // Profile page
  profile_name: '.text-heading-xlarge',
  profile_headline: '.text-body-medium',
};

// Override via environment variable
const SELECTOR_OVERRIDE_PATH = process.env.LINKEDIN_SELECTORS_OVERRIDE;
```

Same override pattern as WhatsApp Watcher — users can update selectors via a JSON
file without code changes.

## 9. CLI Entry Point: `src/cli.ts`

For the Action Executor to call directly (bypassing MCP protocol):

```typescript
// Usage:
// npx tsx src/cli.ts create_post --content "Post text" --visibility public
// npx tsx src/cli.ts get_profile_info

import { parseArgs } from "node:util";
// Import tool implementations directly
```

This mirrors the Email MCP cli.ts pattern from Phase S2.

## 10. Fallback: Draft-to-Clipboard

If Playwright posting fails (selector changes, rate limit, detection):

```typescript
async function fallbackDraft(content: string): Promise<string> {
  /**
   * When automated posting fails:
   * 1. Save post content to /Plans/DRAFT_linkedin_{timestamp}.md
   * 2. Copy content to system clipboard (if available)
   * 3. Open LinkedIn in default browser: open https://www.linkedin.com/feed/
   * 4. Return instructions: "Post drafted. Content copied to clipboard.
   *    LinkedIn opened in your browser — paste and post manually."
   *
   * NEVER lose the drafted content. The draft file is the backup.
   */
}
```

## 11. Error Handling

```typescript
enum LinkedInError {
  SESSION_EXPIRED = "LinkedIn session expired — run setup_session to re-login",
  RATE_LIMITED = "Rate limit exceeded — maximum 3 posts per day",
  SELECTOR_CHANGED = "LinkedIn UI changed — selectors need updating",
  POST_FAILED = "Failed to submit post — check browser state",
  BROWSER_CRASH = "Browser crashed — restart MCP server",
  CONTENT_TOO_LONG = "Post content exceeds 3000 character limit",
  NETWORK_ERROR = "Network error — check internet connection",
}
```

## 12. Edge Cases

- **Session expired mid-post:** Detect login redirect → abort, save draft, error response
- **LinkedIn shows CAPTCHA:** Detect CAPTCHA element → abort, save draft, alert on Dashboard
- **Post modal doesn't appear:** Try fallback selector, then abort with draft
- **Content contains special characters:** Playwright handles Unicode natively. No escaping needed.
- **Content contains URLs:** LinkedIn auto-generates previews. Wait for preview to load before posting.
- **Content exactly 3000 chars:** Accept. 3001+ chars → truncate with warning.
- **Network drop during posting:** Catch timeout → check if post appeared → report ambiguous result
- **Multiple rapid post requests:** Rate limiter blocks. Queue not implemented (use HITL for pacing).
- **LinkedIn A/B tests different UI:** Selector fallbacks mitigate. Override file for edge cases.
- **Headless browser blocked:** Some LinkedIn features require visible browser. Fall back to `headless: false` with `xvfb` on Linux.

## 13. Validation Criteria

- [ ] MCP server starts and connects via stdio transport
- [ ] 2 tools registered: create_post, get_profile_info
- [ ] DRY_RUN=true by default (no browser launched, no posts)
- [ ] DRY_RUN response shows full preview of post content
- [ ] Session persistence: login once, headless thereafter
- [ ] setup_session.ts works for initial login
- [ ] Rate limiter: max 3 posts/day, 1 post/hour, 30min between posts
- [ ] Human-like delays on all interactions
- [ ] Fallback draft mechanism when posting fails
- [ ] Selector override via environment variable
- [ ] CLI entry point for Action Executor
- [ ] All logging to stderr
- [ ] Registered in .claude/settings.json
- [ ] No modification to existing components
