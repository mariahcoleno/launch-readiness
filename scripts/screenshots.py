"""Regenerate the README screenshots.

Runs the app on a temporary database loaded with the sample data (your own
database is never touched), walks through the pages with a headless browser,
and saves PNGs to docs/screenshots/.

Setup (once; the browser install can be skipped if Google Chrome is installed):
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/playwright install chromium
Run:
    .venv/bin/python scripts/screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launch_readiness.app import create_app  # noqa: E402
from launch_readiness.db import get_connection  # noqa: E402
from launch_readiness.seed import seed_database  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1280, "height": 900}

SCOPE_CHANGE = {
    "decided_by": "Morgan T. (VP, Product)",
    "rationale": "Tool-use eval won't pass before the trusted-tester date; launch the rest on time.",
    "follow_up": "Re-enable tool use for v2.1.1 once the tool-use safety eval passes.",
}


def start_app(db_path: Path):
    app = create_app({"DATABASE": str(db_path)})
    conn = get_connection(db_path)
    seed_database(conn)
    conn.close()
    server = make_server("127.0.0.1", 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def launch_browser(p):
    """Playwright's own Chromium if installed, otherwise an installed Google Chrome.

    Either way it's a separate headless browser with a temporary profile.
    """
    try:
        return p.chromium.launch()
    except Exception as bundled_error:  # bundled browser not downloaded
        try:
            return p.chromium.launch(channel="chrome")
        except Exception:
            raise SystemExit(
                "No browser found. Run `playwright install chromium`, or install Google Chrome."
            ) from bundled_error


def shot_until(page, path: Path, last_selector: str, padding: int = 24) -> None:
    """Screenshot from the top of the page down to the end of `last_selector`."""
    box = page.locator(last_selector).bounding_box()
    height = int(box["y"] + box["height"] + padding)
    page.screenshot(path=str(path), full_page=True,
                    clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": height})
    print(f"  saved {path.relative_to(ROOT)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        server, base = start_app(Path(tmp) / "screenshots.db")
        try:
            with sync_playwright() as p:
                browser = launch_browser(p)
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

                # 1. Go/no-go review for v2.1: verdict, blocker, "launch without" preview.
                page.goto(f"{base}/launches/1/go-no-go")
                shot_until(page, OUT / "01-go-no-go.png",
                           "section[aria-labelledby='blockers-heading']")

                # 2. Dashboard for v2.1.
                page.goto(f"{base}/launches/1")
                shot_until(page, OUT / "02-dashboard.png", "section.team >> nth=-1")

                # 3. Launch without tool use: the impact before confirming the scope change.
                page.goto(f"{base}/launches/1/disable/tool_use")
                for field, value in SCOPE_CHANGE.items():
                    page.fill(f"#{field}", value)
                page.locator("#follow_up").blur()  # no focus outline in the image
                shot_until(page, OUT / "03-launch-without.png", "form")

                # 4. Delta review: adding code execution to v2.2 shows only the new gate.
                page.goto(f"{base}/launches/2/enable/code_execution")
                shot_until(page, OUT / "04-delta-review.png", "section.impact", padding=4)

                # 5. Decision log for v2.1 after confirming the scope change from step 3.
                page.goto(f"{base}/launches/1/disable/tool_use")
                for field, value in SCOPE_CHANGE.items():
                    page.fill(f"#{field}", value)
                page.click("button[type=submit]")
                page.wait_for_url(f"{base}/launches/1/go-no-go")
                page.goto(f"{base}/launches/1/decisions")
                shot_until(page, OUT / "05-decision-log.png", "ul.decision-list")

                browser.close()
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
