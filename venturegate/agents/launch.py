"""Phase 5 Launch. Core steps: open the store; deliver automatically.

Steps
  1 store page     a draft. Opening the store needs the founder's approval (the orchestrator asks).
  2 launch posts   drafts. Publishing needs approval and is MOCKED: nothing is posted anywhere.
Automatic delivery is the MOCKED sale-to-cash flow in mock_flow.py.
"""
import html

from .. import costs as C
from ..schema import arr, obj, s
from .base import Agent, StepResult, unique, dedupe

LINK = "<STORE_LINK>"
STORE = obj({"title": s(3), "description": s(20), "bullets": arr(s(5), 3, 6),
             "faq": arr(obj({"q": s(5), "a": s(5)}), 2, 4), "button_label": s(2)})
POSTS = obj({"posts": arr(obj({"channel": s(2), "text": s(30)}), 2, 3)})


class LaunchAgent(Agent):
    name = "launch"

    def store_page(self, feedback=None) -> StepResult:
        price = self.ctx.state.get("price")
        if not price:
            raise ValueError("the price must be approved before the store page is written")
        task = ("Write the store page for the MVP. Describe exactly what the buyer gets. No testimonials, "
                "ratings, sales counts, urgency, scarcity or income promises.")

        def build(fb):
            d, _ = self.ask("store_page", task, STORE, feedback=fb)
            text = "\n".join([d["title"], d["description"], *d["bullets"],
                              *[f"{x['q']} {x['a']}" for x in d["faq"]], d["button_label"]])
            return text, d

        d = self.guarded(build, feedback)
        e = lambda value: html.escape(str(value), quote=True)        # noqa: E731
        lang = self.ctx.brief.language
        page = f"""<!DOCTYPE html>
<html lang="{lang}" dir="{'rtl' if lang == 'ar' else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(d['title'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:0 auto;padding:24px;line-height:1.5}}
.buy{{background:#f4f7ff;border-radius:12px;padding:16px}} button{{padding:10px 16px}}</style></head>
<body><h1>{e(d['title'])}</h1><p>{e(d['description'])}</p>
<ul>{''.join(f'<li>{e(b)}</li>' for b in d['bullets'])}</ul>
<div class="buy"><p><strong>{e(C.fmt_money(price['price'], self.ctx.brief.currency))}</strong></p>
<button type="button" onclick="this.nextElementSibling.hidden=false">{e(d['button_label'])}</button>
<p hidden>MOCKED store: no payment is taken. In the demo a simulated order triggers automatic delivery.</p></div>
<h2>Questions</h2>{''.join(f'<p><strong>{e(x["q"])}</strong><br>{e(x["a"])}</p>' for x in d['faq'])}
<p><small>Terms, privacy and refund policies: drafts, not legal advice.</small></p>
</body></html>"""
        path = self.ctx.writer.write(5, 1, "store-page", page, ext="html",
                                     labels=["MOCKED store", "opens only after founder approval"])
        return StepResult(f"Store page draft \"{d['title']}\" at {price['label']}.", [path], d)

    def launch_posts(self, feedback=None) -> StepResult:
        task = ("Write two or three short launch post drafts for channels where the target customers already "
                "are. Write honestly about the founder's own product. No urgency, scarcity, testimonials, "
                f"ratings, user counts or income promises. Put the link placeholder {LINK} in every post.")

        def check(d):
            dedupe(d["posts"], "channel", "channel")
            for p in d["posts"]:                   # the link placeholder is added, never a real link
                if LINK not in p["text"]:
                    p["text"] = p["text"].rstrip() + f" {LINK}"

        def build(fb):
            d, _ = self.ask("launch_posts", task, POSTS, feedback=fb, check=check)
            md = ["# Launch post drafts", "",
                  "> Drafts only. Publishing needs the founder's approval and is MOCKED here: nothing is posted.", ""]
            for post in d["posts"]:
                md += [f"## {post['channel']}", "", post["text"], ""]
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        path = self.ctx.writer.write(5, 2, "launch-posts", self.latest, labels=["DRAFT", "publishing MOCKED"])
        return StepResult(f"{len(d['posts'])} launch post drafts: {', '.join(p['channel'] for p in d['posts'])}.",
                          [path], d)
