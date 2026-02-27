import { google } from "googleapis";
import type { gmail_v1 } from "googleapis";
import { readFileSync, writeFileSync, existsSync } from "fs";
import { log } from "../utils/logger.js";

const CREDENTIALS_PATH =
  process.env["GMAIL_CREDENTIALS_PATH"] ?? "./credentials.json";
const TOKEN_PATH = process.env["GMAIL_TOKEN_PATH"] ?? "./token.json";

type OAuth2Client = InstanceType<typeof google.auth.OAuth2>;

interface CredentialConfig {
  client_id: string;
  client_secret: string;
  redirect_uris: string[];
}

interface CredentialsFile {
  installed?: CredentialConfig;
  web?: CredentialConfig;
}

// Lazy singleton
let gmailService: gmail_v1.Gmail | null = null;

export async function getGmailService(): Promise<gmail_v1.Gmail> {
  if (gmailService) return gmailService;

  // 1. Read credentials.json
  if (!existsSync(CREDENTIALS_PATH)) {
    throw new Error(
      `credentials.json not found at ${CREDENTIALS_PATH}.\n` +
        `Download it from Google Cloud Console > APIs & Services > Credentials.`,
    );
  }

  const credentialsRaw = readFileSync(CREDENTIALS_PATH, "utf-8");
  const credentials = JSON.parse(credentialsRaw) as CredentialsFile;

  const clientConfig = credentials.installed ?? credentials.web;
  if (!clientConfig) {
    throw new Error(
      `Invalid credentials.json — missing 'installed' or 'web' key.`,
    );
  }

  const { client_id, client_secret, redirect_uris } = clientConfig;
  const redirectUri = redirect_uris[0] ?? "urn:ietf:wg:oauth:2.0:oob";
  const auth = new google.auth.OAuth2(client_id, client_secret, redirectUri);

  // 2. Check for existing token.json
  if (!existsSync(TOKEN_PATH)) {
    throw new Error(
      `No token found at ${TOKEN_PATH}. Run the Gmail Watcher first to complete OAuth:\n` +
        `  DRY_RUN=false uv run python scripts/watchers/gmail_watcher.py --once`,
    );
  }

  // 3. Read token.json and apply Python adapter
  const tokenRaw = readFileSync(TOKEN_PATH, "utf-8");
  const tokenData = JSON.parse(tokenRaw) as Record<string, unknown>;

  // Python's google-auth saves the access token as "token".
  // Node's googleapis expects it as "access_token".
  if (tokenData["token"] !== undefined && tokenData["access_token"] === undefined) {
    tokenData["access_token"] = tokenData["token"];
  }

  // 4. Set credentials and refresh if needed
  auth.setCredentials(tokenData);

  try {
    await refreshTokenIfNeeded(auth);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log("error", "token_refresh_failed", { error: message });
    throw new Error(
      `Token refresh failed: ${message}\n` +
        `Delete ${TOKEN_PATH} and re-run the Gmail Watcher to re-authenticate.`,
    );
  }

  // 5. Return authenticated Gmail service
  gmailService = google.gmail({ version: "v1", auth });
  log("info", "gmail_service_initialized", {});
  return gmailService;
}

export async function refreshTokenIfNeeded(auth: OAuth2Client): Promise<void> {
  const credentials = auth.credentials;
  const expiryDate = credentials.expiry_date;

  if (expiryDate !== null && expiryDate !== undefined && Date.now() > expiryDate - 60000) {
    log("info", "token_refresh_start", { expiry: new Date(expiryDate).toISOString() });
    const { credentials: newCreds } = await auth.refreshAccessToken();
    auth.setCredentials(newCreds);
    writeFileSync(TOKEN_PATH, JSON.stringify(newCreds, null, 2), "utf-8");
    log("info", "token_refresh_complete", {});
  }
}
