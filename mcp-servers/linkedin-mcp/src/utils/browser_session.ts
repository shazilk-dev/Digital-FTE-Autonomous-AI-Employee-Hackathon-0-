import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import type { BrowserContext, Page } from "playwright";
import { log } from "./logger.js";

export class SessionExpiredError extends Error {
  constructor() {
    super("LinkedIn session expired — run setup_session to re-login");
    this.name = "SessionExpiredError";
  }
}

export class BrowserSession {
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private readonly sessionPath: string;
  private readonly headless: boolean;

  constructor(sessionPath?: string, headless?: boolean) {
    this.sessionPath =
      sessionPath ??
      process.env["LINKEDIN_SESSION_PATH"] ??
      "./sessions/linkedin";
    this.headless = headless ?? process.env["LINKEDIN_HEADLESS"] !== "false";
  }

  async getPage(): Promise<Page> {
    // Return existing responsive page
    if (this.page !== null && !this.page.isClosed()) {
      return this.page;
    }

    log("info", "browser_session_init", {
      session_path: this.sessionPath,
      headless: this.headless,
    });

    // Launch persistent context (saves/loads session from disk)
    this.context = await chromium.launchPersistentContext(this.sessionPath, {
      headless: this.headless,
      viewport: { width: 1280, height: 720 },
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
      locale: "en-US",
      timezoneId: "America/New_York",
    });

    const pages = this.context.pages();
    this.page = pages[0] ?? (await this.context.newPage());

    // Navigate to LinkedIn to trigger session check
    await this.page.goto("https://www.linkedin.com/feed/", {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });

    const loggedIn = await this.isLoggedIn(this.page);
    if (!loggedIn) {
      await this.close();
      throw new SessionExpiredError();
    }

    log("info", "browser_session_ready", {});
    return this.page;
  }

  async close(): Promise<void> {
    try {
      if (this.context !== null) {
        await this.context.close();
        log("info", "browser_session_closed", {});
      }
    } catch (err) {
      log("warn", "browser_session_close_error", {
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      this.context = null;
      this.page = null;
    }
  }

  async isLoggedIn(page: Page): Promise<boolean> {
    try {
      await page.waitForSelector(SELECTORS.logged_in_indicator, {
        timeout: 15000,
        state: "visible",
      });
      return true;
    } catch {
      try {
        const onLoginPage = await page
          .locator(SELECTORS.login_page)
          .isVisible({ timeout: 3000 });
        if (onLoginPage) {
          log("warn", "browser_session_not_logged_in", {
            reason: "login page detected",
          });
        }
      } catch {
        // ignore secondary check errors
      }
      return false;
    }
  }
}

// Singleton instance for MCP server lifecycle
export const browserSession = new BrowserSession();

// ---------------------------------------------------------------------------
// Selectors — current as of Feb 2026
// ---------------------------------------------------------------------------

export interface LinkedInSelectors {
  feed_loaded: string;
  start_post_button: string;
  start_post_fallback: string;
  post_modal: string;
  post_text_area: string;
  post_text_fallback: string;
  visibility_button: string;
  post_button: string;
  post_button_fallback: string;
  post_success: string;
  logged_in_indicator: string;
  login_page: string;
  profile_name: string;
  profile_headline: string;
  profile_about: string;
}

const DEFAULT_SELECTORS: LinkedInSelectors = {
  feed_loaded: '[data-test-id="feed-page"]',
  start_post_button: ".share-box-feed-entry__trigger",
  start_post_fallback: '[aria-label*="Start a post"]',
  post_modal: ".share-creation-state__text-editor",
  post_text_area: '[role="textbox"][aria-label*="Text editor"]',
  post_text_fallback: ".ql-editor",
  visibility_button: ".share-creation-state__visibility-button",
  post_button: ".share-actions__primary-action",
  post_button_fallback: 'button[aria-label*="Post"]',
  post_success: ".feed-shared-update-v2",
  logged_in_indicator: ".global-nav__me",
  login_page: "#username",
  profile_name: ".text-heading-xlarge",
  profile_headline: ".text-body-medium",
  profile_about: ".display-flex.ph5.pv3 .full-width",
};

function loadSelectors(): LinkedInSelectors {
  const overridePath = process.env["LINKEDIN_SELECTORS_OVERRIDE"];
  if (overridePath) {
    try {
      const raw = readFileSync(overridePath, "utf-8");
      const overrides = JSON.parse(raw) as Partial<LinkedInSelectors>;
      return { ...DEFAULT_SELECTORS, ...overrides };
    } catch (err) {
      log("warn", "selectors_override_failed", {
        path: overridePath,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }
  return DEFAULT_SELECTORS;
}

export const SELECTORS: LinkedInSelectors = loadSelectors();

// ---------------------------------------------------------------------------
// Human-like delays
// ---------------------------------------------------------------------------

function randomDelay(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

type DelayType =
  | "PAGE_LOAD"
  | "BEFORE_CLICK"
  | "BETWEEN_KEYSTROKES"
  | "AFTER_TYPING"
  | "BEFORE_POST"
  | "AFTER_POST";

const DELAY_RANGES: Record<DelayType, () => number> = {
  PAGE_LOAD: () => 3000,
  BEFORE_CLICK: () => randomDelay(500, 1500),
  BETWEEN_KEYSTROKES: () => randomDelay(30, 80),
  AFTER_TYPING: () => randomDelay(1000, 3000),
  BEFORE_POST: () => randomDelay(2000, 5000),
  AFTER_POST: () => randomDelay(3000, 6000),
};

export async function humanDelay(type: DelayType): Promise<void> {
  const ms = DELAY_RANGES[type]();
  await new Promise<void>((resolve) => setTimeout(resolve, ms));
}
