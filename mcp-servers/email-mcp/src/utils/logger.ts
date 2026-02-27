import { isDryRun } from "./dry_run.js";

export function log(
  level: "info" | "warn" | "error" | "debug",
  action: string,
  details: Record<string, unknown> = {},
): void {
  // CRITICAL: Always log to stderr — stdout is the MCP protocol transport channel
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    action,
    dry_run: isDryRun(),
    ...details,
  };
  console.error(JSON.stringify(entry));
}
