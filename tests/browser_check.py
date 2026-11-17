"""Drive the real founder console in a headless browser (not part of pytest; run it directly).

    python tests/browser_check.py

It serves the page with the scripted test model, then clicks through the weak run to its STOP and
part of the strong run, the way a founder would, and saves screenshots to /tmp/shots.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from playwright.sync_api import sync_playwright   # noqa: E402

from fake_model import FakeModel                   # noqa: E402
from venturegate.app import ConsoleApp, build_ui   # noqa: E402
from venturegate.llm import LLM                    # noqa: E402
from venturegate.logger import DecisionLogger      # noqa: E402
from venturegate.orchestrator import Pipeline      # noqa: E402
from venturegate.sources import SourceLibrary      # noqa: E402

TMP = Path(tempfile.mkdtemp())
SHOTS = Path("/tmp/shots")
SHOTS.mkdir(exist_ok=True)
(TMP / "sources").mkdir()
for i in range(1, 4):
    (TMP / "sources" / f"s{i}.md").write_text(
        f"URL: https://example.org/s{i}\nTitle: Source {i}\n\nCV templates competitors pricing graduates Egypt "
        f"engineering students hosting domain month cost trademark licence chatbot app market {i}", encoding="utf-8")
shutil.copy(ROOT / "gates.yaml", TMP / "gates.yaml")


def factory(brief, mode):
    logger = DecisionLogger(TMP / "decision_log.json")
    llm = LLM(mode=mode, model="qwen3:4b", logger=logger, replay_dir=TMP / "replay", transport=FakeModel())
    return Pipeline(brief, llm=llm, logger=logger, sources=SourceLibrary(TMP / "sources"), out_dir=TMP / "outputs",
                    state_dir=TMP / "state", gates_path=TMP / "gates.yaml")


demo = build_ui(ConsoleApp(factory))
demo.queue().launch(server_port=7861, prevent_thread_lock=True, allowed_paths=[str(TMP / "outputs")],
                    show_api=False, quiet=True)
failures = []
MEASURE = """() => {
  const out = [];
  for (const sel of ['.gradio-container', '.vg-header', '.vg-message', '#vg-main', '#vg-left', '#vg-center', '#vg-run',
                     '#vg-timeline', '#vg-dock', '#vg-right']) {
    const el = document.querySelector(sel); if (!el) { out.push(sel + ' MISSING'); continue; }
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    out.push(`${sel}: y=${r.y|0} h=${r.height|0} pad=${cs.padding} margin=${cs.margin}`);
  }
  let el = document.querySelector('.vg-header'); const chain = [];
  while (el && el !== document.body) { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    chain.push(`${el.tagName}#${el.id}.${(el.className||'').toString().slice(0,50)} y=${r.y|0} h=${r.height|0} pad=${cs.padding} gap=${cs.gap}`); el = el.parentElement; }
  out.push('--- header chain'); out.push(...chain);
  out.push('scrollHeight=' + document.documentElement.scrollHeight);
  return out.join('\\n');
}"""


def check(cond, message):
    print(("PASS " if cond else "FAIL ") + message)
    if not cond:
        failures.append(message)


def click_primary_until(page, done_selector, limit=40, button_text=None):
    for _ in range(limit):
        if done_selector and page.locator(done_selector).count():
            return True
        if button_text and button_text in page.locator("#vg-dock button.vg-btn-primary").inner_text():
            return True
        button = page.locator("#vg-dock button.vg-btn-primary")
        button.wait_for(state="visible", timeout=15000)
        button.click()
        page.wait_for_timeout(400)
    return bool(done_selector) and page.locator(done_selector).count() > 0


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})   # a typical laptop screen
    page.route("**/fonts.googleapis.com/**", lambda route: route.abort())   # sandbox has no internet
    page.route("**/fonts.gstatic.com/**", lambda route: route.abort())
    page.goto("http://127.0.0.1:7861/", wait_until="domcontentloaded")
    page.wait_for_selector("text=What do you want to build?")
    page.screenshot(path=str(SHOTS / "1-start.png"), full_page=True)
    check(page.locator(".vg-header").count() == 1, "header renders")
    check(page.locator("text=Steve will not").count() == 1, "start side panel renders")

    # weak run
    page.get_by_role("button", name="Weak idea: ends in STOP").click()
    page.wait_for_timeout(500)
    idea = page.get_by_label("Your idea (a digital product)").input_value()
    check("chatbot" in idea, "loading the weak example fills the form")
    page.get_by_role("button", name="Start with Steve").click()
    page.wait_for_selector("text=Steve is waiting for your decision", timeout=15000)
    page.screenshot(path=str(SHOTS / "2-decision.png"), full_page=True)
    check(page.locator(".vg-step.current").count() == 1, "the step awaiting a decision is highlighted")
    check(page.locator("#vg-dock button", has_text="Request changes").is_visible(), "Request changes is offered")

    # empty "Request changes" is refused with a message, and nothing moves on
    page.locator("#vg-dock button.vg-btn-secondary").click()
    page.wait_for_selector("text=Write what should change", timeout=10000)
    check(page.locator(".vg-step").count() == 1, "an empty change request does not advance the run")

    stopped = click_primary_until(page, ".vg-stamp")
    page.wait_for_timeout(600)
    page.screenshot(path=str(SHOTS / "3-stop.png"), full_page=True)
    check(stopped, "the weak run reaches the STOP card")
    check(page.locator("text=12 of 100").count() >= 1, "STOP card quotes 12 of 100")
    check(page.locator(".vg-rail li.stop").count() == 1 and page.locator(".vg-rail li.skipped").count() == 4,
          "phase rail shows Gate 2 STOP and four phases not reached")
    check(not page.locator("#vg-dock").is_visible(), "no decision panel after the run ends")
    check(page.get_by_role("button", name="Start a new brief").is_visible(), "Start a new brief is offered")

    # a file link opens the real output
    href = page.locator(".vg-gate.stop a.vg-file").first.get_attribute("href")
    response = page.request.get("http://127.0.0.1:7861" + href)
    check(response.ok and "STOP" in response.text(), "the STOP report file link serves the real file")

    # strong run, as far as the first MOCKED approval
    page.get_by_role("button", name="Start a new brief").click()
    page.wait_for_selector("text=What do you want to build?")
    page.get_by_role("button", name="Strong idea: all six phases").click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Start with Steve").click()
    page.wait_for_selector("text=Steve is waiting for your decision", timeout=15000)
    reached = click_primary_until(page, None, limit=40, button_text="MOCKED")
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "4-mocked-approval.png"), full_page=True)
    check(reached, "the strong run reaches a MOCKED publish approval")
    label = page.locator("#vg-dock button.vg-btn-primary").inner_text()
    check("MOCKED" in label, f"the approve button says MOCKED ({label!r})")

    # laptop screens: the decision panel must be on screen without scrolling the page
    for width, height in ((1366, 768), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(300)
        box = page.locator("#vg-dock").bounding_box()
        if "--measure" in sys.argv:
            print(page.evaluate(MEASURE))
        page_height = page.evaluate("document.documentElement.scrollHeight")
        check(box is not None and box["y"] + box["height"] <= height and page_height <= height + 2,
              f"at {width}x{height} the decision panel is fully visible and the page itself does not scroll")
    page.set_viewport_size({"width": 1366, "height": 768})
    page.screenshot(path=str(SHOTS / "4b-laptop-1366.png"))

    # phone width
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "5-phone.png"), full_page=False)
    width = page.evaluate("document.documentElement.scrollWidth")
    check(width <= 400, f"no sideways scrolling at phone width (page is {width}px wide)")
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
