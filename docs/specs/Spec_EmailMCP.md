# Spec: Email MCP Server — Gmail Integration via MCP

> **Component:** `mcp-servers/email-mcp/` (Node.js/TypeScript)
> **Protocol:** Model Context Protocol (MCP) over stdio
> **Priority:** P0 — First external action capability for the AI Employee
> **External Dependency:** Gmail API (OAuth 2.0), `@modelcontextprotocol/sdk`
> **Shares Credentials With:** Gmail Watcher (Bronze B2)

## 1. Objective

Build an MCP server that exposes Gmail operations as tools Claude Code can invoke.
This gives Claude the ability to send, draft, search, and reply to emails — transforming
it from a read-only observer into an actor.

**Safety-first design:** Every write operation (send, draft, reply) is gated by:

1. `DRY_RUN` environment variable (default: `"true"`)
2. HITL approval workflow (Phase S3 — wired later)

The MCP server itself has NO awareness of the HITL workflow. It simply checks DRY_RUN.
The HITL layer (S3) sets `DRY_RUN=false` only for approved actions.

## 2. File Structure

```
mcp-servers/email-mcp/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts                  # MCP server entry point
│   ├── tools/
│   │   ├── send_email.ts         # Send an email
│   │   ├── draft_email.ts        # Create a Gmail draft
│   │   ├── search_emails.ts      # Search emails with Gmail query syntax
│   │   └── reply_to_thread.ts    # Reply to an existing thread
│   ├── auth/
│   │   └── gmail_auth.ts         # OAuth 2.0 credential management
│   └── utils/
│       ├── dry_run.ts            # DRY_RUN gate utility
│       ├── email_builder.ts      # MIME message construction
│       └── logger.ts             # Structured logging
└── tests/                        # Future: Jest tests (optional for hackathon)
```

## 3. MCP Server Entry Point: `src/index.ts`

```typescript
// Responsibilities:
// 1. Initialize MCP server with server info
// 2. Register all 4 tools with schemas
// 3. Initialize Gmail auth (lazy — on first tool call)
// 4. Handle MCP protocol lifecycle (stdio transport)

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
```

### 3A. Server Initialization

```typescript
const server = new McpServer({
  name: "email-mcp",
  version: "0.2.0",
  description:
    "Gmail integration for the AI Employee. Send, draft, search, and reply to emails.",
});
```

### 3B. Tool Registration Pattern

Each tool is registered with:

- **Name:** Snake_case identifier
- **Description:** What it does (Claude reads this to decide when to use it)
- **Input schema:** Zod schema for type-safe parameter validation
- **Handler:** Async function that executes the operation

```typescript
import { z } from "zod";

server.tool(
  "send_email",
  "Send an email via Gmail. Requires DRY_RUN=false or returns a dry-run preview.",
  {
    to: z.string().email().describe("Recipient email address"),
    subject: z.string().min(1).describe("Email subject line"),
    body: z.string().min(1).describe("Email body (plain text)"),
    cc: z.string().optional().describe("CC recipients (comma-separated)"),
    bcc: z.string().optional().describe("BCC recipients (comma-separated)"),
  },
  async ({ to, subject, body, cc, bcc }) => {
    // Handler implementation
  },
);
```

### 3C. Startup

```typescript
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
```

## 4. Tool Specifications

### 4A. `send_email`

**Purpose:** Send an email via Gmail API.

**Input Schema:**

```typescript
{
  to: z.string().email(),                          // Required
  subject: z.string().min(1).max(500),             // Required
  body: z.string().min(1).max(50000),              // Required (plain text)
  cc: z.string().optional(),                       // Comma-separated emails
  bcc: z.string().optional(),                      // Comma-separated emails
  html_body: z.string().optional(),                // Optional HTML version
  reply_to: z.string().email().optional(),         // Reply-To header
}
```

**Handler Logic:**

1. Check DRY_RUN → if true, return dry-run preview (no API call)
2. Validate all email addresses (to, cc, bcc)
3. Build MIME message using `email_builder.ts`
4. Call Gmail API: `gmail.users.messages.send({ userId: 'me', requestBody: { raw: base64EncodedMessage } })`
5. Return result with message ID and status

**DRY_RUN Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "[DRY RUN] Would send email:\n  To: recipient@example.com\n  Subject: Test\n  Body: (53 chars)\n  CC: none\n  BCC: none\n\nSet DRY_RUN=false to send for real."
    }
  ]
}
```

**Live Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Email sent successfully.\n  Message ID: 18d1234abcd\n  To: recipient@example.com\n  Subject: Test\n  Thread ID: 18d1234abcd"
    }
  ]
}
```

**Error Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Failed to send email: Invalid recipient address"
    }
  ],
  "isError": true
}
```

### 4B. `draft_email`

**Purpose:** Create a draft in Gmail (doesn't send). Useful for HITL review.

**Input Schema:**

```typescript
{
  to: z.string().email(),
  subject: z.string().min(1).max(500),
  body: z.string().min(1).max(50000),
  cc: z.string().optional(),
  bcc: z.string().optional(),
  html_body: z.string().optional(),
}
```

**Handler Logic:**

1. Check DRY_RUN → if true, return preview
2. Build MIME message
3. Call Gmail API: `gmail.users.drafts.create({ userId: 'me', requestBody: { message: { raw: base64EncodedMessage } } })`
4. Return draft ID and preview link

**DRY_RUN Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "[DRY RUN] Would create draft:\n  To: recipient@example.com\n  Subject: Test\n  Body: (53 chars)"
    }
  ]
}
```

**Live Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Draft created successfully.\n  Draft ID: r1234567890\n  To: recipient@example.com\n  Subject: Test\n  View in Gmail: https://mail.google.com/mail/#drafts"
    }
  ]
}
```

### 4C. `search_emails`

**Purpose:** Search emails using Gmail query syntax. Read-only — always safe.

**Input Schema:**

```typescript
{
  query: z.string().min(1).describe("Gmail search query (e.g., 'from:john subject:invoice after:2026/01/01')"),
  max_results: z.number().int().min(1).max(50).default(10),
  include_body: z.boolean().default(false).describe("Include full email body in results"),
}
```

**Handler Logic:**

1. NOTE: This is read-only. DRY_RUN check is skipped (search is always safe).
2. Call Gmail API: `gmail.users.messages.list({ userId: 'me', q: query, maxResults: max_results })`
3. For each message: `gmail.users.messages.get({ userId: 'me', id: messageId })`
4. Parse headers: From, To, Subject, Date
5. If `include_body`: extract plain text body (same logic as Gmail Watcher)
6. Return formatted results

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Found 3 emails matching 'from:john subject:invoice':\n\n1. From: John Smith <john@example.com>\n   Subject: January Invoice\n   Date: 2026-02-25\n   Snippet: Please find attached...\n\n2. From: John Smith <john@example.com>\n   Subject: Invoice Reminder\n   Date: 2026-02-20\n   Snippet: Following up on..."
    }
  ]
}
```

### 4D. `reply_to_thread`

**Purpose:** Reply to an existing email thread. Maintains conversation threading.

**Input Schema:**

```typescript
{
  thread_id: z.string().min(1).describe("Gmail thread ID to reply to"),
  body: z.string().min(1).max(50000),
  reply_all: z.boolean().default(false).describe("Reply to all recipients"),
  html_body: z.string().optional(),
}
```

**Handler Logic:**

1. Check DRY_RUN → if true, return preview
2. Fetch the thread to get the latest message: `gmail.users.threads.get({ userId: 'me', id: thread_id })`
3. Extract: original sender (To), subject (prepend "Re:" if not present), In-Reply-To header, References header
4. If `reply_all`: gather all To and CC recipients from original
5. Build MIME reply with proper threading headers
6. Call Gmail API: `gmail.users.messages.send({ userId: 'me', requestBody: { raw: base64, threadId: thread_id } })`
7. Return result

**Threading headers:**

```
In-Reply-To: <original_message_id@mail.gmail.com>
References: <original_message_id@mail.gmail.com>
Subject: Re: Original Subject
```

## 5. Gmail Authentication: `src/auth/gmail_auth.ts`

### 5A. Shared Credentials

The MCP server uses the SAME OAuth credentials as the Gmail Watcher:

- `credentials.json` — OAuth client config (from Google Cloud Console)
- `token.json` — Stored refresh/access token

Paths from env vars:

```typescript
const CREDENTIALS_PATH =
  process.env.GMAIL_CREDENTIALS_PATH || "./credentials.json";
const TOKEN_PATH = process.env.GMAIL_TOKEN_PATH || "./token.json";
```

### 5B. Required Scopes

```typescript
const SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly", // search
  "https://www.googleapis.com/auth/gmail.send", // send, reply
  "https://www.googleapis.com/auth/gmail.compose", // draft
  "https://www.googleapis.com/auth/gmail.modify", // mark as read
];
```

### 5C. Auth Functions

```typescript
export async function getGmailService(): Promise<gmail_v1.Gmail> {
  /**
   * 1. Read credentials.json
   * 2. Check for existing token.json
   * 3. Read token.json and apply PYTHON ADAPTER:
   * Python's google-auth saves the access token as "token".
   * Node's googleapis expects it as "access_token".
   * Map it before setting credentials:
   * if (tokenData.token && !tokenData.access_token) {
   * tokenData.access_token = tokenData.token;
   * }
   * 4. If token is valid → use it
   * 5. If token exists but expired → refresh it
   * 6. If no token → throw error with instructions:
   *    "No token found. Run the Gmail Watcher first to complete OAuth:
   *     DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once"
   * 6. Return authenticated Gmail service instance
   *
   * NOTE: The MCP server does NOT run the OAuth browser flow itself.
   * The Python Gmail Watcher handles the initial OAuth. The MCP server
   * reuses the resulting token.json.
   */
}

export async function refreshTokenIfNeeded(auth: OAuth2Client): Promise<void> {
  /**
   * Check token expiry. If expired, refresh using the refresh_token.
   * Write updated token.json.
   */
}
```

**Why no browser flow in the MCP server?** The MCP server runs as a subprocess of Claude Code
(stdio transport). It can't open a browser for OAuth. The initial auth is done via the Python
Gmail Watcher, which saves `token.json`. The MCP server just reads and refreshes that token.

## 6. DRY_RUN Gate: `src/utils/dry_run.ts`

```typescript
export function isDryRun(): boolean {
  const value = process.env.DRY_RUN ?? "true";
  return value.toLowerCase() === "true";
}

export function dryRunResponse(
  action: string,
  details: Record<string, string>,
): { content: Array<{ type: "text"; text: string }> } {
  /**
   * Format a standardized dry-run response.
   *
   * Example output:
   * [DRY RUN] Would {action}:
   *   To: recipient@example.com
   *   Subject: Test Email
   *   Body: (142 chars)
   *
   * Set DRY_RUN=false to execute for real.
   */
  const lines = [`[DRY RUN] Would ${action}:`];
  for (const [key, value] of Object.entries(details)) {
    lines.push(`  ${key}: ${value}`);
  }
  lines.push("", "Set DRY_RUN=false to execute for real.");

  return {
    content: [{ type: "text", text: lines.join("\n") }],
  };
}

export function gateWriteOperation<T>(
  action: string,
  details: Record<string, string>,
  execute: () => Promise<T>,
): Promise<{ content: Array<{ type: "text"; text: string }> } | T> {
  /**
   * Universal gate for write operations.
   * If DRY_RUN: return preview response
   * If not: execute the operation
   */
  if (isDryRun()) {
    return Promise.resolve(dryRunResponse(action, details));
  }
  return execute();
}
```

## 7. Email Builder: `src/utils/email_builder.ts`

```typescript
export function buildMimeMessage(options: {
  to: string;
  from?: string; // Defaults to authenticated user
  subject: string;
  body: string; // Plain text
  htmlBody?: string; // Optional HTML
  cc?: string;
  bcc?: string;
  replyTo?: string;
  inReplyTo?: string; // For threading
  references?: string; // For threading
}): string {
  /**
   * Build a RFC 2822 compliant MIME message.
   *
   * If htmlBody provided: multipart/alternative with text + HTML
   * Otherwise: text/plain only
   *
   * Returns base64url encoded string ready for Gmail API.
   *
   * Headers:
   * - From: (authenticated user or specified)
   * - To: recipient
   * - Cc: (if provided)
   * - Bcc: (if provided)
   * - Subject: subject
   * - Reply-To: (if provided)
   * - In-Reply-To: (if threading)
   * - References: (if threading)
   * - MIME-Version: 1.0
   * - Content-Type: text/plain; charset=utf-8 (or multipart/alternative)
   * - Date: current UTC
   * - Message-ID: generated
   */
}

export function base64UrlEncode(str: string): string {
  /**
   * Gmail API requires base64url encoding (not standard base64).
   * Replace +/ with -_, remove =
   */
  return Buffer.from(str)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
```

## 8. Logger: `src/utils/logger.ts`

```typescript
export function log(
  level: "info" | "warn" | "error" | "debug",
  action: string,
  details: Record<string, unknown> = {},
): void {
  /**
   * Structured JSON logging to stderr (MCP uses stdout for protocol).
   *
   * Format:
   * {"timestamp":"2026-02-27T10:30:00Z","level":"info","action":"send_email","dry_run":true,...}
   *
   * CRITICAL: Never log to stdout — that's the MCP transport channel.
   * Always use console.error() or write to stderr.
   */
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    action,
    dry_run: isDryRun(),
    ...details,
  };
  console.error(JSON.stringify(entry));
}
```

## 9. Error Handling

### 9A. Error Categories

```typescript
enum EmailError {
  AUTH_FAILED = "Authentication failed — check credentials.json and token.json",
  TOKEN_EXPIRED = "Token expired — re-run Gmail Watcher to refresh",
  INVALID_RECIPIENT = "Invalid recipient email address",
  QUOTA_EXCEEDED = "Gmail API quota exceeded — retry later",
  RATE_LIMITED = "Rate limited by Gmail API — wait 60 seconds",
  THREAD_NOT_FOUND = "Thread ID not found — it may have been deleted",
  NETWORK_ERROR = "Network error — check internet connection",
  UNKNOWN = "Unexpected error",
}
```

### 9B. Error Response Format

All errors return MCP-compliant error responses:

```typescript
function errorResponse(error: EmailError, detail?: string) {
  return {
    content: [
      {
        type: "text" as const,
        text: `Error: ${error}${detail ? `\nDetail: ${detail}` : ""}`,
      },
    ],
    isError: true,
  };
}
```

### 9C. Gmail API Error Mapping

```typescript
function handleGmailError(error: any): never {
  const status = error?.response?.status || error?.code;

  switch (status) {
    case 401:
      throw new Error(EmailError.AUTH_FAILED);
    case 403:
      throw new Error(EmailError.QUOTA_EXCEEDED);
    case 429:
      throw new Error(EmailError.RATE_LIMITED);
    case 404:
      throw new Error(EmailError.THREAD_NOT_FOUND);
    default:
      if (
        error.message?.includes("ENOTFOUND") ||
        error.message?.includes("ETIMEDOUT")
      ) {
        throw new Error(EmailError.NETWORK_ERROR);
      }
      throw new Error(`${EmailError.UNKNOWN}: ${error.message}`);
  }
}
```

## 10. Rate Limiting

Built-in rate limiting to avoid Gmail API quota issues:

```typescript
class RateLimiter {
  private timestamps: number[] = [];
  private readonly maxPerMinute: number;

  constructor(maxPerMinute: number = 10) {
    this.maxPerMinute = maxPerMinute;
  }

  async waitIfNeeded(): Promise<void> {
    const now = Date.now();
    this.timestamps = this.timestamps.filter((t) => now - t < 60000);
    if (this.timestamps.length >= this.maxPerMinute) {
      const waitMs = 60000 - (now - this.timestamps[0]);
      log("warn", "rate_limit_wait", { wait_ms: waitMs });
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
    this.timestamps.push(Date.now());
  }
}

// Global rate limiters
const sendLimiter = new RateLimiter(10); // Max 10 sends per minute
const searchLimiter = new RateLimiter(30); // Max 30 searches per minute
```

## 11. Validation Rules

### 11A. Email Address Validation

Beyond Zod's `.email()`:

```typescript
function validateEmailAddress(email: string): boolean {
  // 1. Zod schema validates format
  // 2. Additional checks:
  //    - No localhost or IP addresses
  //    - Domain has at least one dot
  //    - Total length < 254 chars
  //    - Local part < 64 chars
}

function validateRecipientList(csv: string): string[] {
  // Split by comma, trim each, validate each, return clean list
  // Throw on any invalid address
}
```

### 11B. Content Validation

```typescript
function validateSubject(subject: string): string {
  // - Trim whitespace
  // - Max 500 chars (truncate with ...)
  // - Strip null bytes
  // Return cleaned subject
}

function validateBody(body: string): string {
  // - Max 50,000 chars (Gmail limit is higher, but reasonable cap)
  // - Strip null bytes
  // Return cleaned body
}
```

## 12. Testing Strategy

### 12A. Manual Testing Protocol (Required for Hackathon)

Since this is a hackathon project, automated MCP tests are optional. The required tests are:

```
1. Start Claude Code with Email MCP registered
2. Verify MCP connects: Claude should list email tools when asked
3. Test search_emails with a real query
4. Test draft_email in DRY_RUN mode
5. Test send_email in DRY_RUN mode
6. Test reply_to_thread in DRY_RUN mode (use thread_id from search results)
7. Set DRY_RUN=false, send one real test email to yourself
8. Verify email arrives
9. Set DRY_RUN back to true
```

### 12B. Optional Automated Tests (Jest)

If time permits, add Jest tests for:

- `email_builder.ts` — MIME construction
- `dry_run.ts` — gate logic
- `gmail_auth.ts` — token reading (mocked filesystem)
- Tool handlers with mocked Gmail API

## 13. Edge Cases

- **No token.json:** Clear error message pointing to Gmail Watcher for OAuth
- **Token expired and refresh fails:** Delete token, instruct re-auth via watcher
- **Empty search results:** Return friendly "No emails found matching query"
- **Thread has been deleted:** 404 → clear error on reply_to_thread
- **Very long email body:** Truncate at 50,000 chars with warning
- **HTML in body field:** Escape HTML if in plain text body. Use `html_body` for intentional HTML.
- **CC/BCC with invalid addresses:** Validate each, reject entire send if any invalid
- **Send to self:** Allowed (useful for testing and notes)
- **Unicode in subject/body:** UTF-8 encoding handled by MIME builder
- **Concurrent MCP calls:** Gmail API handles concurrent requests fine. Rate limiter prevents overload.
- **MCP server crashes:** Claude Code shows error. PM2 (S6) will auto-restart.

## 14. Validation Criteria

- [ ] MCP server starts and connects via stdio transport
- [ ] 4 tools registered: send_email, draft_email, search_emails, reply_to_thread
- [ ] All tools have Zod input validation
- [ ] DRY_RUN=true by default (no accidental sends)
- [ ] DRY_RUN responses include full preview of what would happen
- [ ] search_emails works in both DRY_RUN and live mode (read-only is safe)
- [ ] Gmail auth reuses credentials.json and token.json from vault root
- [ ] No browser-based OAuth flow in the MCP server
- [ ] Structured error responses with isError flag
- [ ] Rate limiting on send and search operations
- [ ] All logging to stderr (never stdout — that's the MCP channel)
- [ ] TypeScript compiles without errors
- [ ] Registered in .claude/settings.json with DRY_RUN=true
- [ ] No modification to Bronze or S1 files
