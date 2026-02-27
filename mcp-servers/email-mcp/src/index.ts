import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerSendEmail } from "./tools/send_email.js";
import { registerDraftEmail } from "./tools/draft_email.js";
import { registerSearchEmails } from "./tools/search_emails.js";
import { registerReplyToThread } from "./tools/reply_to_thread.js";
import { log } from "./utils/logger.js";

const server = new McpServer({
  name: "email-mcp",
  version: "0.2.0",
  description:
    "Gmail integration for the AI Employee. Send, draft, search, and reply to emails.",
});

// Register all 4 tools
registerSendEmail(server);
registerDraftEmail(server);
registerSearchEmails(server);
registerReplyToThread(server);

async function main() {
  log("info", "server_start", {
    dry_run: process.env["DRY_RUN"] ?? "true (default)",
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Fatal error: ${message}`);
  process.exit(1);
});
