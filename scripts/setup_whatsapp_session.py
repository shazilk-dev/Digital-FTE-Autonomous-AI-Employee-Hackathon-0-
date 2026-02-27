"""
One-time script to log in to WhatsApp Web and save the Playwright session.

Run this ONCE from the vault root:
    PYTHONPATH=. uv run python scripts/setup_whatsapp_session.py

After scanning the QR code, come back here and press Enter.
The session is then saved and the watcher can run headlessly from that point on.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

SESSION_PATH = Path(os.getenv("WHATSAPP_SESSION_PATH", "./sessions/whatsapp"))
SESSION_PATH.mkdir(parents=True, exist_ok=True)

print(f"Session will be saved to: {SESSION_PATH.resolve()}")
print("Opening WhatsApp Web — DO NOT close this script until told to.")
print("─" * 50)

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_PATH),
        headless=False,
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )

    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

    print()
    print("Browser is open.")
    print()
    print("Steps:")
    print("  1. Wait for the QR code to appear in the browser")
    print("  2. On your phone: WhatsApp → three dots (⋮) → Linked Devices → Link a Device")
    print("  3. Scan the QR code")
    print("  4. Wait until your chats appear in the browser")
    print("  5. Come back here and press Enter")
    print()
    input("Press Enter AFTER your chats are visible in the browser... ")

    print()
    print("Saving session and closing browser...")
    browser.close()

print()
print("Session saved successfully.")
print(f"Location: {SESSION_PATH.resolve()}")
print()
print("You can now run the watcher:")
print("  PYTHONPATH=. DRY_RUN=true uv run python scripts/watchers/whatsapp_watcher.py --once")
