import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { log } from "../utils/logger.js";
import { browserSession, SELECTORS } from "../utils/browser_session.js";
import { SessionExpiredError } from "../utils/browser_session.js";

type ToolResponse = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

export function registerGetProfileInfo(server: McpServer): void {
  server.tool(
    "get_profile_info",
    "Read the authenticated user's LinkedIn profile. No DRY_RUN gate — read-only operation.",
    {},
    async (): Promise<ToolResponse> => {
      log("info", "get_profile_info_request", {});

      try {
        const page = await browserSession.getPage();

        // Navigate to own profile
        await page.goto("https://www.linkedin.com/in/me/", {
          waitUntil: "domcontentloaded",
          timeout: 30000,
        });

        // Wait for profile to load
        await page.waitForSelector(SELECTORS.profile_name, {
          timeout: 15000,
          state: "visible",
        });

        // Extract name
        const name = await page
          .locator(SELECTORS.profile_name)
          .first()
          .innerText()
          .catch(() => "Unknown");

        // Extract headline
        const headline = await page
          .locator(SELECTORS.profile_headline)
          .first()
          .innerText()
          .catch(() => "");

        // Extract about (best-effort)
        const about = await page
          .locator(SELECTORS.profile_about)
          .first()
          .innerText()
          .catch(() => "");

        // Count recent posts (best-effort via activity section)
        const recentPostCount = await getRecentPostCount(page);

        log("info", "get_profile_info_success", {
          name: name.trim(),
          has_headline: headline.length > 0,
        });

        return {
          content: [
            {
              type: "text",
              text: [
                "LinkedIn Profile:",
                `  Name: ${name.trim()}`,
                `  Headline: ${headline.trim() || "(not set)"}`,
                about.trim()
                  ? `  About: ${about.trim().slice(0, 500)}${about.length > 500 ? "..." : ""}`
                  : "  About: (not set)",
                `  Recent posts: ${recentPostCount}`,
              ].join("\n"),
            },
          ],
        };
      } catch (err) {
        if (err instanceof SessionExpiredError) {
          return {
            content: [
              {
                type: "text",
                text: `Failed to read profile: ${err.message}`,
              },
            ],
            isError: true,
          };
        }

        const errMsg = err instanceof Error ? err.message : String(err);
        log("error", "get_profile_info_failed", { error: errMsg });
        return {
          content: [
            {
              type: "text",
              text: `Failed to read LinkedIn profile: ${errMsg}`,
            },
          ],
          isError: true,
        };
      }
    },
  );
}

async function getRecentPostCount(
  page: import("playwright").Page,
): Promise<string> {
  try {
    // Navigate to activity posts tab
    await page.goto(
      "https://www.linkedin.com/in/me/recent-activity/all/",
      { waitUntil: "domcontentloaded", timeout: 15000 },
    );

    // Count post elements visible (best-effort)
    const posts = await page
      .locator('.profile-creator-shared-feed-update__container')
      .count()
      .catch(() => 0);

    return posts > 0 ? `~${posts} visible` : "unknown";
  } catch {
    return "unknown";
  }
}
