export function isDryRun(): boolean {
  const value = process.env["DRY_RUN"] ?? "true";
  return value.toLowerCase() === "true";
}

export function dryRunResponse(
  action: string,
  details: Record<string, string>,
): { content: Array<{ type: "text"; text: string }> } {
  const lines = [`[DRY RUN] Would ${action}:`];
  for (const [key, value] of Object.entries(details)) {
    lines.push(`  ${key}: ${value}`);
  }
  lines.push("", "Set DRY_RUN=false to execute for real.");

  return {
    content: [{ type: "text", text: lines.join("\n") }],
  };
}

export async function gateWriteOperation<T>(
  action: string,
  details: Record<string, string>,
  execute: () => Promise<T>,
): Promise<{ content: Array<{ type: "text"; text: string }> } | T> {
  if (isDryRun()) {
    return dryRunResponse(action, details);
  }
  return execute();
}
