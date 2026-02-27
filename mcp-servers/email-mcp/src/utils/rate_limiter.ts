import { log } from "./logger.js";

export class RateLimiter {
  private timestamps: number[] = [];
  private readonly maxPerMinute: number;

  constructor(maxPerMinute: number = 10) {
    this.maxPerMinute = maxPerMinute;
  }

  async waitIfNeeded(): Promise<void> {
    const now = Date.now();
    this.timestamps = this.timestamps.filter((t) => now - t < 60000);
    if (this.timestamps.length >= this.maxPerMinute) {
      const oldest = this.timestamps[0];
      if (oldest !== undefined) {
        const waitMs = 60000 - (now - oldest);
        log("warn", "rate_limit_wait", { wait_ms: waitMs });
        await new Promise<void>((resolve) => setTimeout(resolve, waitMs));
      }
    }
    this.timestamps.push(Date.now());
  }
}

export const sendLimiter = new RateLimiter(10);  // Max 10 sends per minute
export const searchLimiter = new RateLimiter(30); // Max 30 searches per minute
