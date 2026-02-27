import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getGmailService } from "../auth/gmail_auth.js";
import { buildMimeMessage } from "../utils/email_builder.js";
import { gateWriteOperation } from "../utils/dry_run.js";
import { log } from "../utils/logger.js";
import { sendLimiter } from "../utils/rate_limiter.js";
import {
  handleGmailError,
  catchToErrorResponse,
  EmailError,
} from "../utils/errors.js";
import { validateBody } from "../utils/validation.js";

function extractHeader(
  headers: Array<{ name?: string | null; value?: string | null }>,
  name: string,
): string {
  const header = headers.find(
    (h) => h.name?.toLowerCase() === name.toLowerCase(),
  );
  return header?.value ?? "";
}

export function registerReplyToThread(server: McpServer): void {
  server.tool(
    "reply_to_thread",
    "Reply to an existing Gmail thread. Maintains conversation threading. Requires DRY_RUN=false or returns a dry-run preview.",
    {
      thread_id: z
        .string()
        .min(1)
        .describe("Gmail thread ID to reply to"),
      body: z
        .string()
        .min(1)
        .max(50000)
        .describe("Reply body (plain text)"),
      reply_all: z
        .boolean()
        .default(false)
        .describe("Reply to all recipients (To + CC)"),
      html_body: z
        .string()
        .optional()
        .describe("Optional HTML version of the reply body"),
    },
    async ({ thread_id, body, reply_all, html_body }) => {
      try {
        const validatedBody = validateBody(body);

        log("info", "reply_to_thread", { thread_id, reply_all });

        const dryRunDetails: Record<string, string> = {
          "Thread ID": thread_id,
          "Reply All": String(reply_all),
          Body: `(${validatedBody.length} chars)`,
        };

        return await gateWriteOperation(
          "reply to thread",
          dryRunDetails,
          async () => {
            await sendLimiter.waitIfNeeded();
            const gmail = await getGmailService();

            // Fetch the thread to get threading metadata
            let threadData;
            try {
              threadData = await gmail.users.threads.get({
                userId: "me",
                id: thread_id,
                format: "metadata",
                metadataHeaders: [
                  "From",
                  "To",
                  "Cc",
                  "Subject",
                  "Message-ID",
                  "References",
                ],
              });
            } catch (err) {
              const errObj = err as { response?: { status?: number } };
              if (errObj?.response?.status === 404) {
                return {
                  content: [
                    {
                      type: "text" as const,
                      text: `Error: ${EmailError.THREAD_NOT_FOUND}`,
                    },
                  ],
                  isError: true,
                };
              }
              handleGmailError(err);
            }

            const messages = threadData.data.messages ?? [];
            if (messages.length === 0) {
              return {
                content: [
                  {
                    type: "text" as const,
                    text: `Error: Thread ${thread_id} has no messages.`,
                  },
                ],
                isError: true,
              };
            }

            // Get the latest message for threading headers
            const lastMessage = messages[messages.length - 1];
            if (!lastMessage) {
              return {
                content: [
                  {
                    type: "text" as const,
                    text: `Error: Could not retrieve last message in thread.`,
                  },
                ],
                isError: true,
              };
            }

            const headers = lastMessage.payload?.headers ?? [];
            const originalFrom = extractHeader(headers, "From");
            const originalTo = extractHeader(headers, "To");
            const originalCc = extractHeader(headers, "Cc");
            const originalSubject = extractHeader(headers, "Subject");
            const originalMessageId = extractHeader(headers, "Message-ID");
            const originalReferences = extractHeader(headers, "References");

            // Build reply subject
            const replySubject = originalSubject.startsWith("Re:")
              ? originalSubject
              : `Re: ${originalSubject}`;

            // Determine recipients
            const replyTo = originalFrom || originalTo;

            // Collect all CC for reply-all
            let ccRecipients: string | undefined;
            if (reply_all) {
              const ccParts = [originalTo, originalCc].filter(
                (s) => s.length > 0,
              );
              if (ccParts.length > 0) ccRecipients = ccParts.join(", ");
            }

            // Build threading references
            const newReferences = originalReferences
              ? `${originalReferences} ${originalMessageId}`
              : originalMessageId;

            const mimeOptions: Parameters<typeof buildMimeMessage>[0] = {
              to: replyTo,
              subject: replySubject,
              body: validatedBody,
              inReplyTo: originalMessageId,
              references: newReferences,
            };
            if (ccRecipients !== undefined) mimeOptions.cc = ccRecipients;
            if (html_body !== undefined) mimeOptions.htmlBody = html_body;

            const raw = buildMimeMessage(mimeOptions);

            try {
              const result = await gmail.users.messages.send({
                userId: "me",
                requestBody: { raw, threadId: thread_id },
              });

              const msgId = result.data.id ?? "unknown";

              log("info", "reply_to_thread_success", {
                thread_id,
                message_id: msgId,
              });

              return {
                content: [
                  {
                    type: "text" as const,
                    text: [
                      "Reply sent successfully.",
                      `  Message ID: ${msgId}`,
                      `  Thread ID: ${thread_id}`,
                      `  To: ${replyTo}`,
                      `  Subject: ${replySubject}`,
                    ].join("\n"),
                  },
                ],
              };
            } catch (err) {
              handleGmailError(err);
            }
          },
        );
      } catch (err) {
        log("error", "reply_to_thread_error", {
          error: err instanceof Error ? err.message : String(err),
        });
        return catchToErrorResponse(err);
      }
    },
  );
}
