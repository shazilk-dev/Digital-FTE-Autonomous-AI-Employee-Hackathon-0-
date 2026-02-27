import { EmailError } from "./errors.js";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmailAddress(email: string): boolean {
  if (email.length >= 254) return false;
  const [local, domain] = email.split("@");
  if (!local || !domain) return false;
  if (local.length >= 64) return false;
  if (!domain.includes(".")) return false;
  // Reject localhost and IP addresses
  if (domain === "localhost") return false;
  if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(domain)) return false;
  return EMAIL_REGEX.test(email);
}

export function validateRecipientList(csv: string): string[] {
  const addresses = csv
    .split(",")
    .map((addr) => addr.trim())
    .filter((addr) => addr.length > 0);

  for (const addr of addresses) {
    if (!validateEmailAddress(addr)) {
      throw new Error(`${EmailError.INVALID_RECIPIENT}: "${addr}"`);
    }
  }
  return addresses;
}

export function validateSubject(subject: string): string {
  // Strip null bytes and trim
  let cleaned = subject.replace(/\0/g, "").trim();
  if (cleaned.length > 500) {
    cleaned = cleaned.slice(0, 497) + "...";
  }
  return cleaned;
}

export function validateBody(body: string): string {
  // Strip null bytes
  let cleaned = body.replace(/\0/g, "");
  if (cleaned.length > 50000) {
    cleaned =
      cleaned.slice(0, 49950) +
      "\n\n[Message truncated at 50,000 characters]";
  }
  return cleaned;
}
