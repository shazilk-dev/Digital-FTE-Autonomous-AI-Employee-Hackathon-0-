import { log } from "./logger.js";

interface CanPostResult {
  allowed: boolean;
  reason?: string;
  retryAfterMs?: number;
}

class LinkedInRateLimiter {
  private postTimestamps: number[] = [];

  // Hard limits — conservative to avoid LinkedIn detection
  private readonly MAX_POSTS_PER_DAY = 3;
  private readonly MAX_POSTS_PER_HOUR = 1;
  private readonly MIN_DELAY_BETWEEN_POSTS_MS = 30 * 60 * 1000; // 30 minutes

  canPost(): CanPostResult {
    const now = Date.now();
    const oneHourAgo = now - 60 * 60 * 1000;
    const oneDayAgo = now - 24 * 60 * 60 * 1000;

    // Purge timestamps older than 24h
    this.postTimestamps = this.postTimestamps.filter((t) => t > oneDayAgo);

    // Check daily limit
    if (this.postTimestamps.length >= this.MAX_POSTS_PER_DAY) {
      const oldest = this.postTimestamps[0];
      const retryAfterMs = oldest !== undefined ? oldest + 24 * 60 * 60 * 1000 - now : 0;
      return {
        allowed: false,
        reason: `Daily limit reached (max ${this.MAX_POSTS_PER_DAY} posts/day)`,
        retryAfterMs: Math.max(0, retryAfterMs),
      };
    }

    // Check hourly limit
    const postsInLastHour = this.postTimestamps.filter((t) => t > oneHourAgo);
    if (postsInLastHour.length >= this.MAX_POSTS_PER_HOUR) {
      const oldest = postsInLastHour[0];
      const retryAfterMs = oldest !== undefined ? oldest + 60 * 60 * 1000 - now : 0;
      return {
        allowed: false,
        reason: `Hourly limit reached (max ${this.MAX_POSTS_PER_HOUR} post/hour)`,
        retryAfterMs: Math.max(0, retryAfterMs),
      };
    }

    // Check minimum delay between posts
    const lastPost = this.postTimestamps[this.postTimestamps.length - 1];
    if (lastPost !== undefined) {
      const elapsed = now - lastPost;
      if (elapsed < this.MIN_DELAY_BETWEEN_POSTS_MS) {
        const retryAfterMs = this.MIN_DELAY_BETWEEN_POSTS_MS - elapsed;
        return {
          allowed: false,
          reason: `Minimum 30 minutes between posts required`,
          retryAfterMs,
        };
      }
    }

    return { allowed: true };
  }

  recordPost(): void {
    this.postTimestamps.push(Date.now());
    log("info", "rate_limiter_record", {
      total_today: this.postTimestamps.length,
    });
  }
}

export const rateLimiter = new LinkedInRateLimiter();
