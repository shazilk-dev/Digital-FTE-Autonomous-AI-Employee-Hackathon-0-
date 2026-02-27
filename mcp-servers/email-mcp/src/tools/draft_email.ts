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

export function registerDraftEmail(server: McpServer): void {
  server.tool(
    "draft_email",
    "Create a draft email in Gmail (doesn't send). Useful for HITL review before sending.",
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
    },
    async ({ to, subject, body, cc, bcc, html_body }) => {
      try {
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
        };
        if (ccList) dryRunDetails["CC"] = ccList;
        if (bccList) dryRunDetails["BCC"] = bccList;

        log("info", "draft_email", { to, subject: validatedSubject });

        return await gateWriteOperation(
          "create draft",
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

            const raw = buildMimeMessage(mimeOptions);

            try {
              const result = await gmail.users.drafts.create({
                userId: "me",
                requestBody: {
                  message: { raw },
                },
              });

              const draftId = result.data.id ?? "unknown";

              log("info", "draft_email_success", { draft_id: draftId });

              return {
                content: [
                  {
                    type: "text" as const,
                    text: [
                      "Draft created successfully.",
                      `  Draft ID: ${draftId}`,
                      `  To: ${to}`,
                      `  Subject: ${validatedSubject}`,
                      `  View in Gmail: https://mail.google.com/mail/#drafts`,
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
        log("error", "draft_email_error", {
          error: err instanceof Error ? err.message : String(err),
        });
        return catchToErrorResponse(err);
      }
    },
  );
}
