"""Drive the real founder console in a headless browser (not part of pytest; run it directly).

    python tests/browser_check.py

It serves the page with the scripted test model and goes through it the way a founder would: the welcome
page, the idea form, a whole run in the chat (buttons and typed messages), a STOP shown in the chat, and
laptop and phone sizes. Screenshots go to /tmp/shots.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from playwright.sync_api import sync_playwright   # noqa: E402

from fake_model import FakeModel, variant          # noqa: E402
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


def factory(brief, mode, overrides=None):
    logger = DecisionLogger(TMP / "decision_log.json")
    llm = LLM(mode=mode, model="qwen3:4b", logger=logger, replay_dir=TMP / "replay", transport=FakeModel(overrides))
    return Pipeline(brief, llm=llm, logger=logger, sources=SourceLibrary(TMP / "sources"), out_dir=TMP / "outputs",
                    state_dir=TMP / "state", gates_path=TMP / "gates.yaml")


demo = build_ui(ConsoleApp(factory))
demo.queue().launch(server_port=7861, prevent_thread_lock=True, allowed_paths=[str(TMP / "outputs")],
                    show_api=False, quiet=True)
# a second page where Steve's research rates the idea WEAK, to see the automatic STOP in the chat
WEAK = {"find_opportunities": [variant("find_opportunities", verdict="weak",
                                       verdict_reasons=["Many free chatbots already answer any question.",
                                                        "There is no clear group of customers."])]}
weak = build_ui(ConsoleApp(lambda brief, mode: factory(brief, mode, WEAK)))
weak.queue().launch(server_port=7862, prevent_thread_lock=True, allowed_paths=[str(TMP / "outputs")],
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


def answer_until(page, stop_text, limit=80):
    """Press the main quick-reply button (or answer a question) until stop_text appears in the chat."""
    for _ in range(limit):
        if page.locator("#vg-chat", has_text=stop_text).count():
            return True
        yes = page.locator("#vg-quick button").first
        box = page.locator("#vg-center textarea").first
        if yes.is_visible():
            yes.click()
        elif box.is_enabled():
            box.fill("Fresh graduates in Cairo and Alexandria")
            box.press("Enter")
        page.wait_for_timeout(500)
    return page.locator("#vg-chat", has_text=stop_text).count() > 0


def open_form(page, port):
    page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
    page.wait_for_selector("text=Meet Steve")
    page.get_by_role("button", name="Get started: tell Steve your idea").click()
    page.wait_for_selector("text=What do you want to build?")


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})   # a typical laptop screen
    page.route("**/fonts.googleapis.com/**", lambda route: route.abort())   # sandbox has no internet
    page.route("**/fonts.gstatic.com/**", lambda route: route.abort())

    # 1. welcome page
    page.goto("http://127.0.0.1:7861/", wait_until="domcontentloaded")
    page.wait_for_selector("text=Meet Steve")
    page.screenshot(path=str(SHOTS / "1-welcome.png"), full_page=True)
    check(page.locator(".vg-header").count() == 1, "header renders")
    for text in ("How it works", "The six phases", "When Steve says stop", "Labels you will see", "Steve will never"):
        check(page.locator(f"text={text}").count() == 1, f"welcome page explains: {text}")
    check(page.get_by_role("button", name="Weak idea: ends in STOP").count() == 0, "no weak-idea option on the page")

    # 2. the idea form
    page.get_by_role("button", name="Get started: tell Steve your idea").click()
    page.wait_for_selector("text=What do you want to build?")
    check(page.get_by_label("Your skills").count() == 0, "the form does not ask for skills")
    page.get_by_role("button", name="Fill in an example idea for me").click()
    page.wait_for_timeout(500)
    check("CV" in page.get_by_label("Your idea (a digital product)").input_value(), "the example fills the form")
    page.screenshot(path=str(SHOTS / "2-form.png"), full_page=True)

    # 3. the chat
    page.get_by_role("button", name="Start working with Steve").click()
    page.get_by_role("button", name="Yes, this is right. Continue").wait_for(timeout=15000)
    page.screenshot(path=str(SHOTS / "3-chat.png"))
    check(page.locator("#vg-chat", has_text="Digital product: yes").count() == 1,
          "the first report is written inside the chat")
    check(page.get_by_role("button", name="Stop working on this idea").is_visible(), "a stop button is offered")

    page.locator("#vg-center textarea").first.press("Enter")                     # empty message
    page.wait_for_selector("text=Type a message first", timeout=10000)
    check(page.locator("#vg-chat .user.message").count() == 0, "an empty message is not sent")

    page.get_by_role("button", name="Yes, this is right. Continue").click()
    page.get_by_role("button", name="Yes, this is right. Continue").wait_for(timeout=15000)
    page.wait_for_timeout(400)
    box = page.locator("#vg-center textarea").first
    box.fill("Focus on data analyst roles only.")
    box.press("Enter")
    page.wait_for_selector("text=Revising", timeout=15000)
    check(page.locator("#vg-chat .user.message", has_text="Focus on data analyst roles only.").count() == 1,
          "a typed message appears in the chat as the founder's message")
    page.get_by_role("button", name="Yes, this is right. Continue").wait_for(timeout=15000)
    check(page.locator("#vg-chat", has_text="Digital product: yes").count() == 1,
          "earlier messages stay visible in the chat history")

    reached = answer_until(page, "practice only (MOCKED)")
    label = page.locator("#vg-quick button").first.inner_text()
    page.screenshot(path=str(SHOTS / "4-mocked-approval.png"))
    check(reached and "practice only" in label, f"a MOCKED approval is explained and labelled ({label!r})")

    # laptop screens: the chat box and buttons are on screen without scrolling the page
    for width, height in ((1366, 768), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(300)
        box = page.locator("#vg-center textarea").first.bounding_box()
        if "--measure" in sys.argv:
            print(page.evaluate(MEASURE))
        page_height = page.evaluate("document.documentElement.scrollHeight")
        check(box is not None and box["y"] + box["height"] <= height and page_height <= height + 2,
              f"at {width}x{height} the message box is visible and the page itself does not scroll")
    page.set_viewport_size({"width": 1366, "height": 768})

    finished = answer_until(page, "All six phases are done")
    page.screenshot(path=str(SHOTS / "5-finished.png"))
    check(finished, "a run goes through all six phases in the chat")
    check(not page.locator("#vg-quick button").first.is_visible(), "no answer buttons after the run ends")
    new = page.get_by_role("button", name="Start over with a new idea").bounding_box()
    check(new is not None and new["y"] + new["height"] <= 768, "Start over is offered and on screen on a laptop")

    # 4. a STOP, shown plainly in the chat
    open_form(page, 7862)
    page.get_by_role("button", name="Fill in an example idea for me").click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Start working with Steve").click()
    page.get_by_role("button", name="Yes, this is right. Continue").wait_for(timeout=15000)
    stopped = answer_until(page, "I don't think this idea is ready")
    page.wait_for_timeout(500)
    page.screenshot(path=str(SHOTS / "6-stop.png"))
    check(stopped and page.locator("#vg-chat", has_text="Many free chatbots already answer").count() >= 1,
          "a weak idea stops by itself and the chat explains why")
    check(page.locator("#vg-chat", has_text="Lean Canvas").count() == 0, "no later steps run after the STOP")
    check(page.locator("#vg-chat", has_text="What could change my mind").count() == 1, "the STOP says what would help")

    # phone width
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "7-phone.png"), full_page=False)
    width = page.evaluate("document.documentElement.scrollWidth")
    check(width <= 400, f"no sideways scrolling at phone width (page is {width}px wide)")
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
