import { writeFileSync } from "node:fs";
import { mkdirSync } from "node:fs";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { gateWriteOperation } from "../utils/dry_run.js";
import { log } from "../utils/logger.js";
import { rateLimiter } from "../utils/rate_limiter.js";
import { browserSession, SELECTORS, humanDelay } from "../utils/browser_session.js";
import { SessionExpiredError } from "../utils/browser_session.js";

type ToolResponse = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

const MAX_CONTENT_LENGTH = 3000;

export function registerCreatePost(server: McpServer): void {
  server.tool(
    "create_post",
    "Publish a text post to LinkedIn. Requires DRY_RUN=false and a valid session.",
    {
      content: z
        .string()
        .min(1)
        .max(MAX_CONTENT_LENGTH)
        .describe("Post text content (LinkedIn max ~3000 chars)"),
      visibility: z
        .enum(["public", "connections"])
        .default("public")
        .describe("Post visibility: public or connections only"),
    },
    async ({ content, visibility }): Promise<ToolResponse> => {
      // Truncate if needed (edge case: content exactly at limit is fine)
      let postContent = content;
      let truncationWarning = "";
      if (postContent.length > MAX_CONTENT_LENGTH) {
        postContent = postContent.slice(0, MAX_CONTENT_LENGTH);
        truncationWarning = `\n  WARNING: Content truncated to ${MAX_CONTENT_LENGTH} chars.`;
        log("warn", "create_post_truncated", {
          original_length: content.length,
        });
      }

      log("info", "create_post_request", {
        content_length: postContent.length,
        visibility,
      });

      return gateWriteOperation(
        "post to LinkedIn",
        {
          Visibility: visibility,
          "Content length": `${postContent.length} chars`,
          "Content preview": postContent.slice(0, 100) + (postContent.length > 100 ? "..." : ""),
        },
        async (): Promise<ToolResponse> => {
          // Check rate limiter
          const rateCheck = rateLimiter.canPost();
          if (!rateCheck.allowed) {
            const retryMin = rateCheck.retryAfterMs
              ? Math.ceil(rateCheck.retryAfterMs / 60000)
              : null;
            const retryMsg = retryMin
              ? ` Retry in ~${retryMin} minutes.`
              : "";
            return {
              content: [
                {
                  type: "text",
                  text: `Rate limit exceeded: ${rateCheck.reason ?? "limit reached"}.${retryMsg}`,
                },
              ],
              isError: true,
            };
          }

          try {
            const page = await browserSession.getPage();

            // Navigate to feed
            log("info", "create_post_navigate", { url: "https://www.linkedin.com/feed/" });
            await page.goto("https://www.linkedin.com/feed/", {
              waitUntil: "domcontentloaded",
              timeout: 30000,
            });
            await humanDelay("PAGE_LOAD");

            // Click "Start a post" button
            await humanDelay("BEFORE_CLICK");
            let startPostBtn = page.locator(SELECTORS.start_post_button).first();
            const startPostVisible = await startPostBtn.isVisible({ timeout: 5000 }).catch(() => false);
            if (!startPostVisible) {
              startPostBtn = page.locator(SELECTORS.start_post_fallback).first();
            }
            await startPostBtn.click({ timeout: 10000 });
            log("info", "create_post_modal_opening", {});

            // Wait for post modal
            await page.waitForSelector(SELECTORS.post_modal, {
              timeout: 15000,
              state: "visible",
            });
            await humanDelay("PAGE_LOAD");

            // Find text area
            let textArea = page.locator(SELECTORS.post_text_area).first();
            const textAreaVisible = await textArea.isVisible({ timeout: 5000 }).catch(() => false);
            if (!textAreaVisible) {
              textArea = page.locator(SELECTORS.post_text_fallback).first();
            }
            await textArea.click({ timeout: 10000 });

            // Type content character by character with human-like delays
            log("info", "create_post_typing", { chars: postContent.length });
            for (const char of postContent) {
              await page.keyboard.type(char);
              await humanDelay("BETWEEN_KEYSTROKES");
            }
            await humanDelay("AFTER_TYPING");

            // Set visibility if "connections"
            if (visibility === "connections") {
              await humanDelay("BEFORE_CLICK");
              const visBtn = page.locator(SELECTORS.visibility_button).first();
              if (await visBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
                await visBtn.click();
                // Try to find and click connections option
                const connectionsOption = page
                  .locator('[aria-label*="connections"]', { hasText: /connections only/i })
                  .first();
                if (await connectionsOption.isVisible({ timeout: 5000 }).catch(() => false)) {
                  await connectionsOption.click();
                  await humanDelay("BEFORE_CLICK");
                }
              }
            }

            // Click Post button
            await humanDelay("BEFORE_POST");
            let postBtn = page.locator(SELECTORS.post_button).first();
            const postBtnVisible = await postBtn.isVisible({ timeout: 5000 }).catch(() => false);
            if (!postBtnVisible) {
              postBtn = page.locator(SELECTORS.post_button_fallback).first();
            }
            await postBtn.click({ timeout: 10000 });
            log("info", "create_post_submitted", {});

            // Wait for confirmation
            await humanDelay("AFTER_POST");
            await page.waitForSelector(SELECTORS.post_success, {
              timeout: 20000,
              state: "visible",
            }).catch(() => {
              log("warn", "create_post_success_selector_timeout", {});
            });

            // Record successful post
            rateLimiter.recordPost();

            const timestamp = new Date().toISOString();
            log("info", "create_post_success", {
              content_length: postContent.length,
              visibility,
              timestamp,
            });

            return {
              content: [
                {
                  type: "text",
                  text: [
                    "Posted to LinkedIn successfully.",
                    `  Visibility: ${visibility}`,
                    `  Content: (${postContent.length} chars)`,
                    `  Time: ${timestamp}`,
                    truncationWarning,
                  ]
                    .filter(Boolean)
                    .join("\n"),
                },
              ],
            };
          } catch (err) {
            if (err instanceof SessionExpiredError) {
              return {
                content: [
                  {
                    type: "text",
                    text: `Failed to post to LinkedIn: ${err.message}`,
                  },
                ],
                isError: true,
              };
            }

            // Fallback: save draft on failure
            const errMsg =
              err instanceof Error ? err.message : String(err);
            log("error", "create_post_failed", { error: errMsg });

            const draftResult = await saveDraft(postContent);
            return {
              content: [
                {
                  type: "text",
                  text: [
                    `Failed to post to LinkedIn: ${errMsg}`,
                    draftResult,
                  ].join("\n"),
                },
              ],
              isError: true,
            };
          }
        },
      ) as Promise<ToolResponse>;
    },
  );
}

// ---------------------------------------------------------------------------
// Fallback: Draft-to-file
// ---------------------------------------------------------------------------

async function saveDraft(content: string): Promise<string> {
  try {
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const planDir = "Plans";
    const filename = `DRAFT_linkedin_${timestamp}.md`;
    const filepath = `${planDir}/${filename}`;

    mkdirSync(planDir, { recursive: true });
    const draftContent = [
      `# LinkedIn Post Draft — ${new Date().toISOString()}`,
      "",
      "**Status:** Draft (automated posting failed)",
      "",
      "## Content",
      "",
      content,
      "",
      "---",
      "_Post this manually at https://www.linkedin.com/feed/_",
    ].join("\n");

    writeFileSync(filepath, draftContent, "utf-8");
    log("info", "create_post_draft_saved", { path: filepath });

    return `Draft saved to ${filepath}. Post manually at https://www.linkedin.com/feed/`;
  } catch (saveErr) {
    const msg =
      saveErr instanceof Error ? saveErr.message : String(saveErr);
    log("error", "create_post_draft_save_failed", { error: msg });
    return `WARNING: Could not save draft file: ${msg}`;
  }
}
