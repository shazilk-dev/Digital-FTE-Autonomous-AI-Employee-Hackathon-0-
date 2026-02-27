#!/usr/bin/env node
// cli.ts — Direct CLI for Action Executor (Option C, hackathon scope)
//
// Usage:
//   npx tsx src/cli.ts send_email --to x@y.com --subject "S" --body "B"
//   npx tsx src/cli.ts draft_email --to x@y.com --subject "S" --body "B"
//   npx tsx src/cli.ts reply_to_thread --thread-id THREAD_ID --body "B"
//
// Output: JSON on stdout, exit 0 on success, exit 1 on error.
// Respects DRY_RUN env var (default: true).

import "dotenv/config";
import { parseArgs } from "node:util";
import { getGmailService } from "./auth/gmail_auth.js";
import { buildMimeMessage } from "./utils/email_builder.js";
import { isDryRun } from "./utils/dry_run.js";
import {
  validateEmailAddress,
  validateBody,
  validateSubject,
} from "./utils/validation.js";

type CliResult =
  | { success: true; result: string; error: null }
  | { success: false; result: null; error: string };

function ok(result: string): CliResult {
  return { success: true, result, error: null };
}

function fail(error: string): CliResult {
  return { success: false, result: null, error };
}

// ---------------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------------

async function cmdSendEmail(values: Record<string, string | boolean | string[] | undefined>): Promise<CliResult> {
  const to = String(values["to"] ?? "");
  const subject = String(values["subject"] ?? "");
  const body = String(values["body"] ?? "");
  const cc = values["cc"] ? String(values["cc"]) : undefined;
  const bcc = values["bcc"] ? String(values["bcc"]) : undefined;

  if (!to) return fail("Missing required param: --to");
  if (!subject) return fail("Missing required param: --subject");
  if (!body) return fail("Missing required param: --body");

  if (!validateEmailAddress(to)) return fail(`Invalid email address: "${to}"`);

  const validSubject = validateSubject(subject);
  const validBody = validateBody(body);

  if (isDryRun()) {
    return ok(
      `[DRY RUN] Would send email to ${to} | Subject: ${validSubject} | Body: (${validBody.length} chars)`
    );
  }

  try {
    const gmail = await getGmailService();
    const mimeOpts: Parameters<typeof buildMimeMessage>[0] = {
      to,
      subject: validSubject,
      body: validBody,
    };
    if (cc) mimeOpts.cc = cc;
    if (bcc) mimeOpts.bcc = bcc;

    const raw = buildMimeMessage(mimeOpts);
    const res = await gmail.users.messages.send({
      userId: "me",
      requestBody: { raw },
    });

    const msgId = res.data.id ?? "unknown";
    const threadId = res.data.threadId ?? "unknown";
    return ok(`Email sent. Message ID: ${msgId} | Thread ID: ${threadId} | To: ${to}`);
  } catch (err) {
    return fail(`Gmail API error: ${err instanceof Error ? err.message : String(err)}`);
  }
}

async function cmdDraftEmail(values: Record<string, string | boolean | string[] | undefined>): Promise<CliResult> {
  const to = String(values["to"] ?? "");
  const subject = String(values["subject"] ?? "");
  const body = String(values["body"] ?? "");
  const cc = values["cc"] ? String(values["cc"]) : undefined;
  const bcc = values["bcc"] ? String(values["bcc"]) : undefined;

  if (!to) return fail("Missing required param: --to");
  if (!subject) return fail("Missing required param: --subject");
  if (!body) return fail("Missing required param: --body");

  if (!validateEmailAddress(to)) return fail(`Invalid email address: "${to}"`);

  const validSubject = validateSubject(subject);
  const validBody = validateBody(body);

  if (isDryRun()) {
    return ok(
      `[DRY RUN] Would create draft to ${to} | Subject: ${validSubject} | Body: (${validBody.length} chars)`
    );
  }

  try {
    const gmail = await getGmailService();
    const mimeOpts: Parameters<typeof buildMimeMessage>[0] = {
      to,
      subject: validSubject,
      body: validBody,
    };
    if (cc) mimeOpts.cc = cc;
    if (bcc) mimeOpts.bcc = bcc;

    const raw = buildMimeMessage(mimeOpts);
    const res = await gmail.users.drafts.create({
      userId: "me",
      requestBody: { message: { raw } },
    });

    const draftId = res.data.id ?? "unknown";
    return ok(`Draft created. Draft ID: ${draftId} | To: ${to} | Subject: ${validSubject}`);
  } catch (err) {
    return fail(`Gmail API error: ${err instanceof Error ? err.message : String(err)}`);
  }
}

async function cmdReplyToThread(values: Record<string, string | boolean | string[] | undefined>): Promise<CliResult> {
  const threadId = String(values["thread-id"] ?? "");
  const body = String(values["body"] ?? "");
  const replyAll = Boolean(values["reply-all"]);

  if (!threadId) return fail("Missing required param: --thread-id");
  if (!body) return fail("Missing required param: --body");

  const validBody = validateBody(body);

  if (isDryRun()) {
    return ok(
      `[DRY RUN] Would reply to thread ${threadId} | Reply-All: ${replyAll} | Body: (${validBody.length} chars)`
    );
  }

  try {
    const gmail = await getGmailService();

    // Fetch the thread to get threading metadata
    const threadData = await gmail.users.threads.get({
      userId: "me",
      id: threadId,
      format: "metadata",
      metadataHeaders: ["From", "To", "Cc", "Subject", "Message-ID", "References"],
    });

    const messages = threadData.data.messages ?? [];
    if (messages.length === 0) {
      return fail(`Thread ${threadId} has no messages`);
    }

    const lastMessage = messages[messages.length - 1];
    if (!lastMessage) {
      return fail("Could not retrieve last message in thread");
    }

    const headers = lastMessage.payload?.headers ?? [];
    const getHeader = (name: string): string =>
      headers.find((h) => h.name?.toLowerCase() === name.toLowerCase())?.value ?? "";

    const originalFrom = getHeader("From");
    const originalTo = getHeader("To");
    const originalCc = getHeader("Cc");
    const originalSubject = getHeader("Subject");
    const originalMessageId = getHeader("Message-ID");
    const originalReferences = getHeader("References");

    const replySubject = originalSubject.startsWith("Re:")
      ? originalSubject
      : `Re: ${originalSubject}`;
    const replyTo = originalFrom || originalTo;

    let ccRecipients: string | undefined;
    if (replyAll) {
      const ccParts = [originalTo, originalCc].filter((s) => s.length > 0);
      if (ccParts.length > 0) ccRecipients = ccParts.join(", ");
    }

    const newReferences = originalReferences
      ? `${originalReferences} ${originalMessageId}`
      : originalMessageId;

    const mimeOpts: Parameters<typeof buildMimeMessage>[0] = {
      to: replyTo,
      subject: replySubject,
      body: validBody,
      inReplyTo: originalMessageId,
      references: newReferences,
    };
    if (ccRecipients) mimeOpts.cc = ccRecipients;

    const raw = buildMimeMessage(mimeOpts);
    const res = await gmail.users.messages.send({
      userId: "me",
      requestBody: { raw, threadId },
    });

    const msgId = res.data.id ?? "unknown";
    return ok(`Reply sent. Message ID: ${msgId} | Thread ID: ${threadId} | To: ${replyTo}`);
  } catch (err) {
    return fail(`Gmail API error: ${err instanceof Error ? err.message : String(err)}`);
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
      to: { type: "string" },
      subject: { type: "string" },
      body: { type: "string" },
      cc: { type: "string" },
      bcc: { type: "string" },
      "thread-id": { type: "string" },
      "reply-all": { type: "boolean", default: false },
    },
  });

  const command = positionals[0];
  let result: CliResult;

  switch (command) {
    case "send_email":
      result = await cmdSendEmail(values);
      break;
    case "draft_email":
      result = await cmdDraftEmail(values);
      break;
    case "reply_to_thread":
      result = await cmdReplyToThread(values);
      break;
    default:
      result = fail(
        `Unknown command: "${command}". Valid commands: send_email, draft_email, reply_to_thread`
      );
  }

  console.log(JSON.stringify(result, null, 2));
  if (!result.success) {
    process.exit(1);
  }
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  console.log(JSON.stringify({ success: false, result: null, error: message }));
  process.exit(1);
});
