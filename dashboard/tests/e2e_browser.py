"""E2E browser verification: loads every page, captures console errors and
screenshots. Requires playwright + a running server on TA_DASH_PORT.
Run: python3 dashboard/tests/e2e_browser.py
"""
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TA_DASH_URL", "http://127.0.0.1:8420")
OUT = Path(__file__).resolve().parents[2] / "artifacts" / "dashboard_review"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = {
    "overview": "#/overview",
    "funnel": "#/funnel",
    "research": "#/research",
    "research_PBF": "#/research/PBF",
    "positions": "#/positions",
    "position_PBF": "#/positions/PBF",
    "management": "#/management",
    "executions": "#/executions",
    "performance": "#/performance",
    "providers": "#/providers",
    "health": "#/health",
    "capabilities": "#/capabilities",
    "tracks": "#/tracks",
    "controls": "#/controls",
}

report = {"base": BASE, "pages": {}, "api_5xx": [], "console_errors": []}

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    errors = []
    api5xx = []

    def on_console(msg):
        if msg.type == "error":
            errors.append(msg.text[:300])

    def on_response(resp):
        if "/api/" in resp.url and resp.status >= 500:
            api5xx.append({"url": resp.url, "status": resp.status})

    page.on("console", on_console)
    page.on("response", on_response)

    for name, route in PAGES.items():
        errors.clear()
        try:
            page.goto(f"{BASE}/{route}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1200)
            shot = OUT / f"{name}.png"
            page.screenshot(path=str(shot), full_page=False)
            report["pages"][name] = {"ok": True, "console_errors": list(errors),
                                     "screenshot": shot.name}
        except Exception as e:
            report["pages"][name] = {"ok": False, "error": str(e)[:300],
                                     "console_errors": list(errors)}
    report["console_errors"] = errors
    report["api_5xx"] = api5xx

    # interaction smoke: search a ticker, toggle a sort, open a collapsible
    try:
        page.goto(f"{BASE}/#/research", wait_until="networkidle")
        page.wait_for_timeout(800)
        inp = page.query_selector("input[type=search], input[placeholder*=ilter], input[placeholder*=earch]")
        if inp:
            inp.fill("PBF")
            page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "interaction_research_filter.png"))
    except Exception as e:
        report["interaction"] = {"error": str(e)[:300]}

    # responsive checks on overview
    report["viewports"] = {}
    for w, h in [(1440, 900), (1366, 768)]:
        try:
            page.set_viewport_size({"width": w, "height": h})
            page.goto(f"{BASE}/#/overview", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(800)
            shot = OUT / f"overview_{w}x{h}.png"
            page.screenshot(path=str(shot))
            report["viewports"][f"{w}x{h}"] = {"ok": True}
        except Exception as e:
            report["viewports"][f"{w}x{h}"] = {"ok": False, "error": str(e)[:200]}
    b.close()

(OUT / "e2e_report.json").write_text(json.dumps(report, indent=1))
fails = [k for k, v in report["pages"].items() if not v["ok"]]
allerr = [e for v in report["pages"].values() for e in v.get("console_errors", [])]
print("pages failed:", fails or "none")
print("api 5xx:", report["api_5xx"] or "none")
print("console errors:", allerr or "none")
sys.exit(1 if fails or report["api_5xx"] else 0)
