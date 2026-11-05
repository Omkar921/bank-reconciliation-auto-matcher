"""Capture README screenshots of the running Streamlit app with Playwright.

    streamlit run app.py --server.headless true --server.port 8599 &
    python scripts/screenshot_dashboard.py
"""
from playwright.sync_api import sync_playwright

URL = "http://localhost:8599"
SHOTS = [("📊 Overview", "dashboard_overview.png"), ("🟡 Suggested matches", "dashboard_review_queue.png"),
         ("🔴 Unmatched bank", "dashboard_exceptions.png"), ("⚪ Unmatched GL", "dashboard_unmatched_gl.png")]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 1050}, device_scale_factor=1.5)
    page.goto(URL)
    page.wait_for_selector("text=Bank Reconciliation Auto-Matcher", timeout=60000)
    page.wait_for_timeout(5000)
    for tab, fname in SHOTS:
        page.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(3500)
        page.screenshot(path=f"docs/images/{fname}", full_page=False)
        print("saved", fname)
    browser.close()
