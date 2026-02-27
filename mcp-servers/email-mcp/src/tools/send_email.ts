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
} from "../utils/errors.js";
import {
  validateEmailAddress,
  validateRecipientList,
  validateSubject,
  validateBody,
} from "../utils/validation.js";

export function registerSendEmail(server: McpServer): void {
  server.tool(
    "send_email",
    "Send an email via Gmail. Requires DRY_RUN=false or returns a dry-run preview.",
    {
      to: z.string().email().describe("Recipient email address"),
      subject: z.string().min(1).max(500).describe("Email subject line"),
      body: z
        .string()
        .min(1)
        .max(50000)
        .describe("Email body (plain text)"),
      cc: z
        .string()
        .optional()
        .describe("CC recipients (comma-separated emails)"),
      bcc: z
        .string()
        .optional()
        .describe("BCC recipients (comma-separated emails)"),
      html_body: z
        .string()
        .optional()
        .describe("Optional HTML version of the email body"),
      reply_to: z
        .string()
        .email()
        .optional()
        .describe("Reply-To header email address"),
    },
    async ({ to, subject, body, cc, bcc, html_body, reply_to }) => {
      try {
        // Validate addresses
        if (!validateEmailAddress(to)) {
          return {
            content: [
              {
                type: "text" as const,
                text: `Error: Invalid recipient address: "${to}"`,
              },
            ],
            isError: true,
          };
        }

        const validatedSubject = validateSubject(subject);
        const validatedBody = validateBody(body);
        const ccList = cc ? validateRecipientList(cc).join(", ") : undefined;
        const bccList = bcc
          ? validateRecipientList(bcc).join(", ")
          : undefined;

        const dryRunDetails: Record<string, string> = {
          To: to,
          Subject: validatedSubject,
          Body: `(${validatedBody.length} chars)`,
          CC: ccList ?? "none",
          BCC: bccList ?? "none",
        };

        log("info", "send_email", { to, subject: validatedSubject });

        return await gateWriteOperation(
          "send email",
          dryRunDetails,
          async () => {
            await sendLimiter.waitIfNeeded();
            const gmail = await getGmailService();

            const mimeOptions: Parameters<typeof buildMimeMessage>[0] = {
              to,
              subject: validatedSubject,
              body: validatedBody,
            };
            if (ccList !== undefined) mimeOptions.cc = ccList;
            if (bccList !== undefined) mimeOptions.bcc = bccList;
            if (html_body !== undefined) mimeOptions.htmlBody = html_body;
            if (reply_to !== undefined) mimeOptions.replyTo = reply_to;

            const raw = buildMimeMessage(mimeOptions);

            try {
              const result = await gmail.users.messages.send({
                userId: "me",
                requestBody: { raw },
              });

              const msgId = result.data.id ?? "unknown";
              const threadId = result.data.threadId ?? "unknown";

              log("info", "send_email_success", {
                message_id: msgId,
                thread_id: threadId,
              });

              return {
                content: [
                  {
                    type: "text" as const,
                    text: [
                      "Email sent successfully.",
                      `  Message ID: ${msgId}`,
                      `  To: ${to}`,
                      `  Subject: ${validatedSubject}`,
                      `  Thread ID: ${threadId}`,
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
        log("error", "send_email_error", {
          error: err instanceof Error ? err.message : String(err),
        });
        return catchToErrorResponse(err);
      }
    },
  );
}
