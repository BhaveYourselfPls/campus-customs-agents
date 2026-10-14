"""Screenshot the live React board, one image per resolved ticket.

Run with both servers up (API on 8000, Vite on 5173):

    .venv/Scripts/python.exe frontend/shoot_board.py

Writes output/shots/<ticket_id>.png and prints what it captured.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "output" / "shots"
BOARD = "http://localhost:5173/"

TICKETS = ["T1-gym-shorts", "T2-handsome-dan", "T3-emerald-green-hoodie"]


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000},
                                device_scale_factor=2)
        page.goto(BOARD, wait_until="networkidle")
        page.wait_for_selector(".tcard", timeout=15000)

        # Overview first: the rail with all three tickets and the balance.
        page.screenshot(path=str(SHOTS / "board-overview.png"))
        captured.append("board-overview.png")

        for ticket in TICKETS:
            # Click the ticket card whose id label matches.
            card = page.locator(".tcard", has=page.locator(f".id:text-is('{ticket}')"))
            card.first.click()
            page.wait_for_timeout(700)

            # Full page so the decision and agent sections are included, not
            # just what happens to fit in the viewport.
            page.screenshot(path=str(SHOTS / f"{ticket}.png"), full_page=True)
            captured.append(f"{ticket}.png")
            print(f"captured {ticket}")

        browser.close()

    print(f"\n{len(captured)} image(s) in {SHOTS}")
    for c in captured:
        size = (SHOTS / c).stat().st_size
        print(f"  {c}  ({size // 1024} KB)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Screenshot run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
