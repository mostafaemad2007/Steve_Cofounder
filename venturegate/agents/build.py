"""Phase 3 Build. Core step: build the product.

The agent writes the product content. mvp.py renders it into a working self-contained page with a
download bundle, writes the user docs, and runs the automatic MVP tests that Gate 3 checks.
"""
from .. import mvp
from ..schema import arr, obj, s
from .base import Agent, StepResult

SPEC = obj({
    "product_name": s(3), "tagline": s(10), "audience": s(5),
    "items": arr(obj({"title": s(3), "description": s(10), "content": s(150)}), 3, 6),
    "user_docs": obj({"quick_start": arr(s(5), 3, 6), "faq": arr(obj({"q": s(5), "a": s(10)}), 2, 5)}),
})


class BuildAgent(Agent):
    name = "build"

    def mvp(self, feedback=None) -> StepResult:
        task = ("Build the smallest version of the product that is genuinely useful: three to six items of "
                "real, complete content (templates, checklists, guides or worked examples), each 80 to 250 "
                "words of Markdown with no placeholders such as [insert ...] or TODO. Write fields the buyer fills in as labels in curly "
                "braces, such as {FULL NAME}. In example bullets use percentages or counts, never money amounts. "
                "Add user docs: a quick "
                "start and an FAQ. No testimonials, ratings, urgency or income promises.")

        def build(fb):
            spec, _ = self.ask("build_mvp", task, SPEC, feedback=fb)
            return mvp.bundle_markdown(spec), spec

        spec = self.guarded(build, feedback)
        page = mvp.render_mvp_html(spec, self.ctx.brief.language)
        docs = mvp.render_user_docs(spec)
        checks = mvp.verify_mvp(page, spec, docs, self.ctx.guard)
        passed = sum(c["passed"] for c in checks)
        failing = [c["name"] for c in checks if not c["passed"]]

        writer = self.ctx.writer
        page_path = writer.write(3, 1, "mvp", page, ext="html", labels=["MVP built by VentureGate", "not published"])
        docs_path = writer.write(3, 2, "user-docs", docs)
        report = ["# MVP automatic tests", "",
                  f"**Result: {'ALL PASS' if not failing else 'FAILURES'}** ({passed}/{len(checks)})", "",
                  "| Test | Result | Detail |", "|---|---|---|"]
        report += [f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |" for c in checks]
        report_path = writer.write(3, 3, "mvp-tests", "\n".join(report))
        self.ctx.logger.log(self.name, "run_mvp_tests", passed=passed, total=len(checks), failing=failing or None)

        self.ctx.state.update(product_name=spec["product_name"], product_tagline=spec["tagline"])
        summary = (f"MVP \"{spec['product_name']}\": {len(spec['items'])} items, "
                   + ("all tests pass." if not failing else f"tests FAILING: {', '.join(failing)}."))
        return StepResult(summary, [page_path, docs_path, report_path],
                          {"tests_passed": not failing, "user_docs_exist": bool(docs.strip()),
                           "failing": failing, "checks": checks,
                           "failing_details": [f"{c['name']} ({c['detail']})" if c["detail"] else c["name"]
                                               for c in checks if not c["passed"]]})
