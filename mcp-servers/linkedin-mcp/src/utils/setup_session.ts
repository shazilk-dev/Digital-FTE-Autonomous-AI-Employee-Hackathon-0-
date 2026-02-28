#!/usr/bin/env node
// setup_session.ts — First-time LinkedIn login helper (standalone script)
//
// Usage:
//   npx tsx src/utils/setup_session.ts
//   npm run setup-session
//
// Opens a visible Chromium browser pointed at LinkedIn.
// Log in manually. Session is saved to disk.
// Subsequent MCP server launches use the saved session headlessly.

import "dotenv/config";
import { chromium } from "playwright";
import * as readline from "node:readline";

async function setup(): Promise<void> {
  const sessionPath =
    process.env["LINKEDIN_SESSION_PATH"] ?? "./sessions/linkedin";

  console.error(`[setup_session] Session will be saved to: ${sessionPath}`);
  console.error("[setup_session] Opening LinkedIn for login...");
  console.error(
    "[setup_session] Log in manually, then press Enter in this terminal to save and exit.",
  );

  const context = await chromium.launchPersistentContext(sessionPath, {
    headless: false,
    viewport: { width: 1280, height: 720 },
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    locale: "en-US",
  });

  const pages = context.pages();
  const page = pages[0] ?? (await context.newPage());
  await page.goto("https://www.linkedin.com/login");

  // Wait for user to log in and press Enter
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  await new Promise<void>((resolve) => {
    rl.question(
      "\nPress Enter after you have logged in to LinkedIn...",
      () => {
        rl.close();
        resolve();
      },
    );
  });

  // Verify login
  console.error("[setup_session] Verifying login...");
  await page.goto("https://www.linkedin.com/feed/", {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });

  try {
    await page.waitForSelector(".global-nav__me", {
      timeout: 15000,
      state: "visible",
    });
    console.error(
      "[setup_session] Login verified. Session saved successfully.",
    );
    console.error(
      "[setup_session] You can now run the MCP server in headless mode.",
    );
  } catch {
    console.error(
      "[setup_session] WARNING: Could not verify login. " +
        "Make sure you are logged into LinkedIn before pressing Enter.",
    );
  }

  await context.close();
}

setup().catch((err: unknown) => {
  console.error(
    "[setup_session] Fatal error:",
    err instanceof Error ? err.message : String(err),
  );
  process.exit(1);
});
