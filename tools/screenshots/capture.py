"""Capture dashboard screenshots for an example, from a JSON shot list.

    python tools/screenshots/session.py login --plane https://demo.behavry.ai   # once
    python tools/screenshots/capture.py examples/meraki-alert-triage/screenshots.json
    python tools/screenshots/capture.py examples/meraki-alert-triage/screenshots.json --only 02

Shot list format::

    {
      "plane": "https://demo.behavry.ai",
      "shots": [
        {
          "id": "02",
          "file": "screenshots/02-gateway-mapping.png",
          "caption": "Map each downstream system the gateway fronts",
          "path": "/provisioning",
          "steps": [
            {"scroll_to": "text=example-msp-gateway"},
            {"click": "tr:has-text('example-msp-gateway') [title='Configure downstream systems']"},
            {"wait_for": "text=Downstream systems"},
            {"wait_ms": 800}
          ],
          "clip_to": "[role=dialog]",
          "mask": ["[data-sensitive]"]
        }
      ]
    }

``steps`` run in order: ``click``, ``fill`` (with ``value``), ``scroll_to``,
``wait_for`` and ``wait_ms``. ``clip_to`` captures one element instead of the
viewport, ``crop_left`` (a fraction of the width, for side drawers) trims the
blurred page behind a drawer, ``hide`` removes floating widgets, and ``mask``
blacks out anything that must not be published (account names, tokens, ids).
Files are written relative to the shot list's folder.
Review every image before committing it: the examples are public.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session import browser, signed_in  # noqa: E402

# Always hidden, whatever the shot list says: the signed-in account and anything
# the dashboard marks as a secret.
ALWAYS_MASK = ["[data-testid='user-menu']", "[data-sensitive]", "[data-secret]"]
# Floating widgets that sit over content; hidden in every capture.
ALWAYS_HIDE = ["[aria-label='Onboarding assistant']"]


def run_steps(page, steps: list[dict]) -> None:
    for step in steps:
        if "click" in step:
            page.locator(step["click"]).first.click()
        elif "fill" in step:
            page.locator(step["fill"]).first.fill(step.get("value", ""))
        elif "scroll_to" in step:
            page.locator(step["scroll_to"]).first.scroll_into_view_if_needed()
        elif "wait_for" in step:
            page.locator(step["wait_for"]).first.wait_for(timeout=step.get("timeout", 15000))
        elif "wait_ms" in step:
            page.wait_for_timeout(step["wait_ms"])
        else:
            raise ValueError(f"unknown step: {step}")


def capture(spec_path: Path, only: set[str] | None) -> None:
    spec = json.loads(spec_path.read_text())
    plane = spec["plane"].rstrip("/")
    base = spec_path.parent
    with browser(headless=True) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(plane + "/")
        page.wait_for_timeout(1500)
        if not signed_in(page):
            sys.exit("Not signed in. Run: python tools/screenshots/session.py login --plane " + plane)
        for shot in spec["shots"]:
            if only and shot["id"] not in only:
                continue
            page.goto(plane + shot["path"])
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(shot.get("settle_ms", 1500))
            hide = ALWAYS_HIDE + shot.get("hide", [])
            page.add_style_tag(content=",".join(hide) + "{display:none !important}")
            run_steps(page, shot.get("steps", []))
            out = base / shot["file"]
            out.parent.mkdir(parents=True, exist_ok=True)
            masks = [page.locator(s) for s in ALWAYS_MASK + shot.get("mask", [])]
            target = page.locator(shot["clip_to"]).first if shot.get("clip_to") else page
            target.screenshot(path=str(out), mask=masks, mask_color="#0A1628", animations="disabled")
            if shot.get("crop_left"):
                crop_left(out, shot["crop_left"])
            print(out.relative_to(base))


def crop_left(path: Path, fraction: float) -> None:
    """Keep the right-hand part of an image, from ``fraction`` of its width."""
    from PIL import Image

    with Image.open(path) as im:
        im.crop((int(im.width * fraction), 0, im.width, im.height)).save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", type=Path)
    ap.add_argument("--only", nargs="*", help="shot ids to capture")
    a = ap.parse_args()
    capture(a.spec.resolve(), set(a.only) if a.only else None)
