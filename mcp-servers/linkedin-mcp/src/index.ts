import "dotenv/config";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerCreatePost } from "./tools/create_post.js";
import { registerGetProfileInfo } from "./tools/get_profile_info.js";
import { log } from "./utils/logger.js";
import { browserSession } from "./utils/browser_session.js";

const server = new McpServer({
  name: "linkedin-mcp",
  version: "0.2.0",
  description:
    "LinkedIn integration for the AI Employee. Create posts and read profile info.",
});

// Register tools
registerCreatePost(server);
registerGetProfileInfo(server);

async function main(): Promise<void> {
  log("info", "server_start", {
    dry_run: process.env["DRY_RUN"] ?? "true (default)",
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);

  log("info", "server_connected", {});
}

async function shutdown(): Promise<void> {
  log("info", "server_shutdown", {});
  await browserSession.close();
  process.exit(0);
}

process.on("SIGINT", () => void shutdown());
process.on("SIGTERM", () => void shutdown());

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Fatal error: ${message}`);
  process.exit(1);
});
