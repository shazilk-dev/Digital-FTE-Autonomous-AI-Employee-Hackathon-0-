#!/usr/bin/env node
// cli.ts — Direct CLI for Action Executor
//
// Usage:
//   npx tsx src/cli.ts create_post --content "Post text" --visibility public
//   npx tsx src/cli.ts get_profile_info
//
// Output: strict JSON on stdout, exit 0 on success, exit 1 on error.
// Respects DRY_RUN env var (default: true).

import "dotenv/config";
import { parseArgs } from "node:util";
import { isDryRun } from "./utils/dry_run.js";
import { log } from "./utils/logger.js";
import { rateLimiter } from "./utils/rate_limiter.js";
import { browserSession, SELECTORS, humanDelay } from "./utils/browser_session.js";
import { SessionExpiredError } from "./utils/browser_session.js";
import { writeFileSync, mkdirSync } from "node:fs";

type CliResult =
  | { success: true; result: string; error: null }
  | { success: false; result: null; error: string };

function ok(result: string): CliResult {
  return { success: true, result, error: null };
}

function fail(error: string): CliResult {
  return { success: false, result: null, error };
}

const MAX_CONTENT_LENGTH = 3000;

// ---------------------------------------------------------------------------
// Command: create_post
// ---------------------------------------------------------------------------

async function cmdCreatePost(
  values: Record<string, string | boolean | string[] | undefined>,
): Promise<CliResult> {
  const content = String(values["content"] ?? "");
  const visibility = String(values["visibility"] ?? "public") as
    | "public"
    | "connections";

  if (!content) return fail("Missing required param: --content");
  if (content.length > MAX_CONTENT_LENGTH) {
    return fail(
      `Content exceeds ${MAX_CONTENT_LENGTH} character limit (got ${content.length} chars)`,
    );
  }

  if (isDryRun()) {
    return ok(
      [
        "[DRY RUN] Would post to LinkedIn:",
        `  Visibility: ${visibility}`,
        `  Content (${content.length} chars):`,
        "---",
        content.slice(0, 200) + (content.length > 200 ? "..." : ""),
        "---",
        "Set DRY_RUN=false to post for real.",
      ].join("\n"),
    );
  }

  // Check rate limiter
  const rateCheck = rateLimiter.canPost();
  if (!rateCheck.allowed) {
    const retryMin = rateCheck.retryAfterMs
      ? Math.ceil(rateCheck.retryAfterMs / 60000)
      : null;
    return fail(
      `Rate limit exceeded: ${rateCheck.reason ?? "limit reached"}.${retryMin ? ` Retry in ~${retryMin} minutes.` : ""}`,
    );
  }

  try {
    const page = await browserSession.getPage();

    // Navigate to feed
    await page.goto("https://www.linkedin.com/feed/", {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await humanDelay("PAGE_LOAD");

    // Click "Start a post"
    await humanDelay("BEFORE_CLICK");
    let startPostBtn = page.locator(SELECTORS.start_post_button).first();
    const visible = await startPostBtn.isVisible({ timeout: 5000 }).catch(() => false);
    if (!visible) {
      startPostBtn = page.locator(SELECTORS.start_post_fallback).first();
    }
    await startPostBtn.click({ timeout: 10000 });

    // Wait for modal
    await page.waitForSelector(SELECTORS.post_modal, {
      timeout: 15000,
      state: "visible",
    });
    await humanDelay("PAGE_LOAD");

    // Find text area and type content
    let textArea = page.locator(SELECTORS.post_text_area).first();
    const textAreaVisible = await textArea.isVisible({ timeout: 5000 }).catch(() => false);
    if (!textAreaVisible) {
      textArea = page.locator(SELECTORS.post_text_fallback).first();
    }
    await textArea.click({ timeout: 10000 });

    for (const char of content) {
      await page.keyboard.type(char);
      await humanDelay("BETWEEN_KEYSTROKES");
    }
    await humanDelay("AFTER_TYPING");

    // Set connections-only visibility if requested
    if (visibility === "connections") {
      await humanDelay("BEFORE_CLICK");
      const visBtn = page.locator(SELECTORS.visibility_button).first();
      if (await visBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await visBtn.click();
        const connectionsOption = page
          .locator('[aria-label*="connections"]', { hasText: /connections only/i })
          .first();
        if (await connectionsOption.isVisible({ timeout: 5000 }).catch(() => false)) {
          await connectionsOption.click();
          await humanDelay("BEFORE_CLICK");
        }
      }
    }

    // Click Post
    await humanDelay("BEFORE_POST");
    let postBtn = page.locator(SELECTORS.post_button).first();
    const postBtnVisible = await postBtn.isVisible({ timeout: 5000 }).catch(() => false);
    if (!postBtnVisible) {
      postBtn = page.locator(SELECTORS.post_button_fallback).first();
    }
    await postBtn.click({ timeout: 10000 });

    // Wait for confirmation
    await humanDelay("AFTER_POST");
    await page
      .waitForSelector(SELECTORS.post_success, {
        timeout: 20000,
        state: "visible",
      })
      .catch(() => {
        log("warn", "cli_create_post_success_selector_timeout", {});
      });

    rateLimiter.recordPost();
    await browserSession.close();

    const timestamp = new Date().toISOString();
    return ok(
      [
        "Posted to LinkedIn successfully.",
        `  Visibility: ${visibility}`,
        `  Content: (${content.length} chars)`,
        `  Time: ${timestamp}`,
      ].join("\n"),
    );
  } catch (err) {
    if (err instanceof SessionExpiredError) {
      return fail(err.message);
    }

    const errMsg = err instanceof Error ? err.message : String(err);
    log("error", "cli_create_post_failed", { error: errMsg });

    // Save draft as fallback
    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filepath = `Plans/DRAFT_linkedin_${timestamp}.md`;
      mkdirSync("Plans", { recursive: true });
      writeFileSync(
        filepath,
        [
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
        ].join("\n"),
        "utf-8",
      );
      return fail(
        `Failed to post to LinkedIn: ${errMsg}. Draft saved to ${filepath}.`,
      );
    } catch {
      return fail(`Failed to post to LinkedIn: ${errMsg}`);
    } finally {
      await browserSession.close().catch(() => undefined);
    }
  }
}

// ---------------------------------------------------------------------------
// Command: get_profile_info
// ---------------------------------------------------------------------------

async function cmdGetProfileInfo(): Promise<CliResult> {
  // DRY_RUN not gated — read-only
  try {
    const page = await browserSession.getPage();

    await page.goto("https://www.linkedin.com/in/me/", {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await page.waitForSelector(SELECTORS.profile_name, {
      timeout: 15000,
      state: "visible",
    });

    const name = await page
      .locator(SELECTORS.profile_name)
      .first()
      .innerText()
      .catch(() => "Unknown");
    const headline = await page
      .locator(SELECTORS.profile_headline)
      .first()
      .innerText()
      .catch(() => "");
    const about = await page
      .locator(SELECTORS.profile_about)
      .first()
      .innerText()
      .catch(() => "");

    await browserSession.close();

    return ok(
      [
        "LinkedIn Profile:",
        `  Name: ${name.trim()}`,
        `  Headline: ${headline.trim() || "(not set)"}`,
        about.trim()
          ? `  About: ${about.trim().slice(0, 500)}`
          : "  About: (not set)",
      ].join("\n"),
    );
  } catch (err) {
    if (err instanceof SessionExpiredError) {
      return fail(err.message);
    }
    const errMsg = err instanceof Error ? err.message : String(err);
    log("error", "cli_get_profile_info_failed", { error: errMsg });
    await browserSession.close().catch(() => undefined);
    return fail(`Failed to read LinkedIn profile: ${errMsg}`);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const { positionals, values } = parseArgs({
    args: process.argv.slice(2),
    allowPositionals: true,
    options: {
      content: { type: "string" },
      visibility: { type: "string", default: "public" },
    },
  });

  const command = positionals[0];
  let result: CliResult;

  switch (command) {
    case "create_post":
      result = await cmdCreatePost(values);
      break;
    case "get_profile_info":
      result = await cmdGetProfileInfo();
      break;
    default:
      result = fail(
        `Unknown command: "${command ?? ""}". Valid commands: create_post, get_profile_info`,
      );
  }

  // STRICT JSON output to stdout
  console.log(JSON.stringify(result));
  if (!result.success) {
    process.exit(1);
  }
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  console.log(JSON.stringify({ success: false, result: null, error: message }));
  process.exit(1);
});
