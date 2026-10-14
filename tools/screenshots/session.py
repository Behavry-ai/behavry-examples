"""A signed-in dashboard session for capturing screenshots.

    python tools/screenshots/session.py login --plane https://demo.behavry.ai

Opens a Chrome window on the plane. Sign in as you normally would; the window
closes on its own once the dashboard has a session. The session is kept in a
browser profile outside this repository (default ``~/.behavry-examples/profile``,
override with ``BEHAVRY_SCREENSHOT_PROFILE``) so later captures run headless.
Nothing from the session is written into the repository.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

PROFILE = Path(os.environ.get("BEHAVRY_SCREENSHOT_PROFILE", Path.home() / ".behavry-examples" / "profile"))
TOKEN_KEY = "behavry_admin_token"


@contextmanager
def browser(headless: bool, *, width: int = 1440, height: int = 900):
    from playwright.sync_api import Error, sync_playwright

    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        kwargs = dict(user_data_dir=str(PROFILE), headless=headless,
                      viewport={"width": width, "height": height}, device_scale_factor=2)
        try:
            ctx = pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Error:
            ctx = pw.chromium.launch_persistent_context(**kwargs)
        try:
            yield ctx
        finally:
            ctx.close()


def signed_in(page) -> bool:
    return bool(page.evaluate(f"() => localStorage.getItem('{TOKEN_KEY}')"))


def login(plane: str, timeout_s: int) -> None:
    with browser(headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(plane.rstrip("/") + "/")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if signed_in(page):
                    page.wait_for_timeout(1500)
                    print("signed in")
                    return
            except Exception:
                pass  # mid-navigation
            time.sleep(1)
    sys.exit("timed out waiting for sign-in")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["login"])
    ap.add_argument("--plane", default="https://demo.behavry.ai")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    login(a.plane, a.timeout)
