"""Click through the whole app in a real browser (Chromium via Playwright).

Start the app in demo mode first (invented data, no GPU needed):
    uv run triagesim ui --demo --no-browser
Then, with Playwright installed (pip install playwright && playwright install chromium):
    python scripts/browser_test.py http://127.0.0.1:8765 [screenshot-folder]

It builds a cohort and its cases, reviews cases, starts an experiment with the demo
model, waits for it to finish, opens the results and a transcript, and fails on any
browser error. Screenshots of every step go to the screenshot folder (default: shots/).
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
shots = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
shots.mkdir(exist_ok=True)
errors: list[str] = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Behave like newer Chrome, where scrollIntoView returns a Promise (this once broke the run page).
    page.add_init_script("const s = Element.prototype.scrollIntoView;"
                         "Element.prototype.scrollIntoView = function (...a) { s.apply(this, a); return Promise.resolve(); };")
    page.add_init_script("window.addEventListener('error', e => console.error(e.message));")

    def shot(name):
        page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
        print("ok:", name)

    def link(name):
        page.get_by_role("link", name=name, exact=True).click()

    def button(name):
        page.get_by_role("button", name=name, exact=True).click()

    page.goto(base); page.wait_for_selector("text=Getting started"); shot("01_home")
    link("1 Data"); page.wait_for_selector("text=Expected layout"); shot("02_data")
    link("2 Cohorts & cases"); button("New cohort"); page.wait_for_selector("text=Start from a preset"); shot("03_filters")
    button("Next: review"); shot("04_review")
    button("Build cohort"); page.wait_for_selector("text=Cohort flow", timeout=60000); shot("05_cohort")
    button("Build case files"); page.wait_for_selector("text=HPIs changed by redaction", timeout=120000); shot("06_cases")
    button("Case files"); page.wait_for_selector("text=Nurse sees at arrival"); shot("07_case_files")
    button("Case review"); page.wait_for_selector("text=cases in this group", timeout=60000); shot("08_case_review")
    link("4 New experiment"); page.click("text=interview personas"); page.wait_for_selector("text=Nurse agent")
    for select in page.locator("select").all():
        if select.locator("option[value=__demo]").count():
            select.select_option("__demo")
    page.fill("input[type=number] >> nth=0", "4"); time.sleep(1); shot("09_experiment")
    button("Start run"); page.wait_for_selector("text=Conversation", timeout=30000); time.sleep(1.5); shot("10_live")
    page.wait_for_selector("text=completed", timeout=120000)
    button("Results"); page.wait_for_selector("text=Agreement with nurse"); shot("11_results")
    if page.locator("text=This page ran into a problem").count():
        errors.append("error page shown after leaving the Live tab")
    button("Cases"); page.get_by_role("button", name="Transcript").first.click()
    page.wait_for_selector("text=Transcript ·"); shot("12_transcript")
    link("3 Models"); page.wait_for_selector("text=Model catalog"); shot("13_models")
    browser.close()

if errors:
    print("Browser errors:", *errors, sep="\n  ")
    sys.exit(1)
print("All steps passed, no browser errors.")
