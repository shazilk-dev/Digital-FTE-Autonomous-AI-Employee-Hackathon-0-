import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getGmailService } from "../auth/gmail_auth.js";
import { log } from "../utils/logger.js";
import { searchLimiter } from "../utils/rate_limiter.js";
import { handleGmailError, catchToErrorResponse } from "../utils/errors.js";

function extractHeader(
  headers: Array<{ name?: string | null; value?: string | null }>,
  name: string,
): string {
  const header = headers.find(
    (h) => h.name?.toLowerCase() === name.toLowerCase(),
  );
  return header?.value ?? "";
}

function extractPlainTextBody(
  payload: {
    mimeType?: string | null;
    body?: { data?: string | null } | null;
    parts?: Array<{
      mimeType?: string | null;
      body?: { data?: string | null } | null;
    }> | null;
  } | null | undefined,
): string {
  if (!payload) return "";

  // Single-part plain text
  if (payload.mimeType === "text/plain" && payload.body?.data) {
    return Buffer.from(payload.body.data, "base64").toString("utf-8").trim();
  }

  // Multipart — find the text/plain part
  if (payload.parts) {
    for (const part of payload.parts) {
      if (part.mimeType === "text/plain" && part.body?.data) {
        return Buffer.from(part.body.data, "base64").toString("utf-8").trim();
      }
    }
    // Fallback: first part with data
    for (const part of payload.parts) {
      if (part.body?.data) {
        return Buffer.from(part.body.data, "base64").toString("utf-8").trim();
      }
    }
  }

  return "";
}

export function registerSearchEmails(server: McpServer): void {
  server.tool(
    "search_emails",
    "Search emails using Gmail query syntax. Read-only — always safe regardless of DRY_RUN setting.",
    {
      query: z
        .string()
        .min(1)
        .describe(
          "Gmail search query (e.g., 'from:john subject:invoice after:2026/01/01')",
        ),
      max_results: z
        .number()
        .int()
        .min(1)
        .max(50)
        .default(10)
        .describe("Maximum number of results to return (1-50)"),
      include_body: z
        .boolean()
        .default(false)
        .describe("Include full email body in results"),
    },
    async ({ query, max_results, include_body }) => {
      try {
        // NOTE: search_emails is read-only — DRY_RUN check is skipped
        await searchLimiter.waitIfNeeded();
        log("info", "search_emails", { query, max_results });

        const gmail = await getGmailService();

        // List matching messages
        let listResult;
        try {
          listResult = await gmail.users.messages.list({
            userId: "me",
            q: query,
            maxResults: max_results,
          });
        } catch (err) {
          handleGmailError(err);
        }

        const messages = listResult.data.messages ?? [];

        if (messages.length === 0) {
          return {
            content: [
              {
                type: "text" as const,
                text: `No emails found matching '${query}'.`,
              },
            ],
          };
        }

        // Fetch details for each message
        const results: string[] = [
          `Found ${messages.length} email${messages.length === 1 ? "" : "s"} matching '${query}':`,
          "",
        ];

        for (let i = 0; i < messages.length; i++) {
          const msg = messages[i];
          if (!msg?.id) continue;

          let msgDetail;
          try {
            msgDetail = await gmail.users.messages.get({
              userId: "me",
              id: msg.id,
              format: include_body ? "full" : "metadata",
              metadataHeaders: ["From", "To", "Subject", "Date"],
            });
          } catch (err) {
            results.push(`${i + 1}. [Error fetching message ${msg.id}]`);
            continue;
          }

          const headers = msgDetail.data.payload?.headers ?? [];
          const from = extractHeader(headers, "From");
          const subject = extractHeader(headers, "Subject");
          const date = extractHeader(headers, "Date");
          const snippet = msgDetail.data.snippet ?? "";

          const entry: string[] = [
            `${i + 1}. From: ${from || "(unknown)"}`,
            `   Subject: ${subject || "(no subject)"}`,
            `   Date: ${date || "(unknown)"}`,
            `   Snippet: ${snippet.slice(0, 150)}${snippet.length > 150 ? "..." : ""}`,
          ];

          if (include_body) {
            const bodyText = extractPlainTextBody(msgDetail.data.payload);
            if (bodyText) {
              const preview = bodyText.slice(0, 500);
              entry.push(
                `   Body: ${preview}${bodyText.length > 500 ? "..." : ""}`,
              );
            }
          }

          results.push(entry.join("\n"));
        }

        log("info", "search_emails_success", {
          query,
          count: messages.length,
        });

        return {
          content: [{ type: "text" as const, text: results.join("\n") }],
        };
      } catch (err) {
        log("error", "search_emails_error", {
          error: err instanceof Error ? err.message : String(err),
        });
        return catchToErrorResponse(err);
      }
    },
  );
}
