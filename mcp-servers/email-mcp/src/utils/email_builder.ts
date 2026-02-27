export function base64UrlEncode(str: string): string {
  // Gmail API requires base64url encoding (not standard base64).
  return Buffer.from(str)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function encodeSubject(subject: string): string {
  // Encode non-ASCII characters in subject using RFC 2047 encoded-word syntax
  const hasNonAscii = /[^\x00-\x7F]/.test(subject);
  if (!hasNonAscii) return subject;
  return `=?UTF-8?B?${Buffer.from(subject).toString("base64")}?=`;
}

export function buildMimeMessage(options: {
  to: string;
  from?: string;
  subject: string;
  body: string;
  htmlBody?: string;
  cc?: string;
  bcc?: string;
  replyTo?: string;
  inReplyTo?: string;
  references?: string;
}): string {
  const {
    to,
    from,
    subject,
    body,
    htmlBody,
    cc,
    bcc,
    replyTo,
    inReplyTo,
    references,
  } = options;

  const messageId = `<${Date.now()}.${Math.random().toString(36).slice(2)}@gmail.com>`;
  const date = new Date().toUTCString();

  const headerLines: string[] = [];
  if (from) headerLines.push(`From: ${from}`);
  headerLines.push(`To: ${to}`);
  if (cc) headerLines.push(`Cc: ${cc}`);
  if (bcc) headerLines.push(`Bcc: ${bcc}`);
  headerLines.push(`Subject: ${encodeSubject(subject)}`);
  if (replyTo) headerLines.push(`Reply-To: ${replyTo}`);
  if (inReplyTo) headerLines.push(`In-Reply-To: ${inReplyTo}`);
  if (references) headerLines.push(`References: ${references}`);
  headerLines.push(`MIME-Version: 1.0`);
  headerLines.push(`Date: ${date}`);
  headerLines.push(`Message-ID: ${messageId}`);

  let bodyContent: string;

  if (htmlBody) {
    const boundary = `boundary_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    headerLines.push(
      `Content-Type: multipart/alternative; boundary="${boundary}"`,
    );
    bodyContent = [
      `--${boundary}`,
      `Content-Type: text/plain; charset=utf-8`,
      ``,
      body,
      `--${boundary}`,
      `Content-Type: text/html; charset=utf-8`,
      ``,
      htmlBody,
      `--${boundary}--`,
    ].join("\r\n");
  } else {
    headerLines.push(`Content-Type: text/plain; charset=utf-8`);
    bodyContent = body;
  }

  const fullMessage = headerLines.join("\r\n") + "\r\n\r\n" + bodyContent;
  return base64UrlEncode(fullMessage);
}
