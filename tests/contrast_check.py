"""Measure text contrast on the real page (not part of pytest; run it directly).

    python tests/contrast_check.py            # report problems, exit 1 if any
    python tests/contrast_check.py --verbose  # also list every text element checked

Opens the founder console in a headless browser in light and dark colour scheme (Windows dark mode
makes Gradio switch its own components to dark colours), goes through the start screen, a step that
waits for a decision, and the weak run's STOP, and computes the WCAG contrast ratio of every visible
text element against its real background. Normal text needs 4.5:1; large text (24px, or 18.7px bold) 3:1.
"""
import shutil
import sys
import tempfile
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
(TMP / "sources").mkdir()
for i in range(1, 4):
    (TMP / "sources" / f"s{i}.md").write_text(
        f"URL: https://example.org/s{i}\nTitle: Source {i}\n\nCV templates competitors pricing graduates Egypt "
        f"engineering students hosting domain month cost trademark licence chatbot app market {i}", encoding="utf-8")
shutil.copy(ROOT / "gates.yaml", TMP / "gates.yaml")


def factory(brief, mode):
    brief.mock_scenario = "weak"           # so the audit also sees a STOP in the chat
    logger = DecisionLogger(TMP / "decision_log.json")
    llm = LLM(mode=mode, model="qwen3:4b", logger=logger, replay_dir=TMP / "replay", transport=FakeModel())
    return Pipeline(brief, llm=llm, logger=logger, sources=SourceLibrary(TMP / "sources"), out_dir=TMP / "outputs",
                    state_dir=TMP / "state", gates_path=TMP / "gates.yaml")


AUDIT = r"""() => {
  function rgba(s) { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x)); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  function lum(c) { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); }
  function blend(top, bottom) { const a = top[3]; return [top[0]*a + bottom[0]*(1-a), top[1]*a + bottom[1]*(1-a), top[2]*a + bottom[2]*(1-a), 1]; }
  function background(el) { const layers = [];
    for (let e = el; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let bg = [255, 255, 255, 1]; for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg); return bg; }
  const out = [], seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, text = node.textContent.trim();
    if (!text) continue;
    const el = node.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    let hidden = false; for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e); if (s.display === 'none' || s.visibility === 'hidden') { hidden = true; break; } }
    if (hidden) continue;
    const bg = background(el), fg = blend(rgba(cs.color) || [0,0,0,1], bg);
    const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    out.push({text: text.slice(0, 60), ratio: Math.round(ratio * 100) / 100, need, color: cs.color,
              bg: `rgb(${bg.slice(0,3).map(Math.round).join(',')})`, tag: el.tagName, cls: (el.className || '').toString().slice(0, 50)});
  }
  // placeholders
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    const r = el.getBoundingClientRect(); if (!r.width || el.value) continue;
    const cs = getComputedStyle(el, '::placeholder'), bg = background(el), fg = blend(rgba(cs.color) || [0,0,0,1], bg);
    const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    out.push({text: 'placeholder: ' + el.placeholder.slice(0, 40), ratio: Math.round(ratio * 100) / 100, need: 4.5,
              color: cs.color, bg: `rgb(${bg.slice(0,3).map(Math.round).join(',')})`, tag: el.tagName, cls: ''});
  }
  return out;
}"""

demo = build_ui(ConsoleApp(factory))
demo.queue().launch(server_port=7863, prevent_thread_lock=True, show_api=False, quiet=True)
problems = []


def audit(page, label):
    page.wait_for_timeout(500)
    results = page.evaluate(AUDIT)
    bad = [r for r in results if r["ratio"] < r["need"]]
    print(f"\n== {label}: {len(results)} text elements, {len(bad)} below the minimum")
    for r in (results if "--verbose" in sys.argv else bad):
        print(f"  {r['ratio']:>5} (need {r['need']})  {r['text']!r:62} color={r['color']} bg={r['bg']} <{r['tag']} {r['cls']}>")
    problems.extend((label, r) for r in bad)


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for scheme in ("light", "dark"):
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        page.route("**/fonts.g*/**", lambda route: route.abort())
        page.goto("http://127.0.0.1:7863/", wait_until="domcontentloaded")
        page.wait_for_selector("text=Meet Steve")
        if scheme == "dark":
            page.screenshot(path="/tmp/shots/dark-welcome.png")
        audit(page, f"{scheme} · welcome page")
        page.get_by_role("button", name="Get started: tell Steve your idea").click()
        page.wait_for_selector("text=What do you want to build?")
        audit(page, f"{scheme} · idea form")
        page.get_by_role("button", name="Fill in an example idea for me").click()
        page.wait_for_timeout(400)
        audit(page, f"{scheme} · idea form with the example loaded")
        page.get_by_role("button", name="Start working with Steve").click()
        page.locator("#vg-quick button").first.wait_for(state="visible", timeout=15000)
        page.wait_for_timeout(400)
        audit(page, f"{scheme} · the chat, waiting for an answer")
        if scheme == "dark":
            page.screenshot(path="/tmp/shots/dark-chat.png")
        box = page.locator("#vg-center textarea").first
        box.fill("Focus on data analyst roles only.")
        box.press("Enter")
        page.locator("#vg-quick button").first.wait_for(state="visible", timeout=15000)
        for _ in range(60):
            if page.locator("#vg-chat", has_text="I don't think this idea is ready").count():
                break
            if page.locator("#vg-quick button").first.is_visible():
                page.locator("#vg-quick button").first.click()
            else:
                box.fill("Fresh graduates in Cairo")
                box.press("Enter")
            page.wait_for_timeout(400)
        page.wait_for_timeout(400)
        audit(page, f"{scheme} · the STOP in the chat")
        page.close()
    browser.close()

print(f"\n{len(problems)} contrast problem(s)")
sys.exit(1 if problems else 0)
