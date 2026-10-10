"""Compile-verify the whole bank.

Builds one LaTeX document from all 369 questions (answers + solutions on) and
runs it through the same engine the export endpoint uses.  Reports the tectonic
error lines, if any, so a broken table/figure shows up immediately.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from server import latex as L  # noqa: E402

BANK = os.path.join(ROOT, "data", "bank.json")
OUT_TEX = os.path.join(ROOT, "outputs", "fullbank_check.tex")
OUT_PDF = os.path.join(ROOT, "outputs", "fullbank_check.pdf")


def main():
    bank = json.load(open(BANK, encoding="utf-8"))
    qs = bank["questions"]
    tex = L.build_document(qs, title="Full Bank Verification",
                           show_answer=True, show_solution=True,
                           group_by_topic=True)
    open(OUT_TEX, "w", encoding="utf-8").write(tex)

    engine = L.find_engine()
    print("engine:", engine)
    res = L.compile_pdf(tex, workdir=os.path.join(ROOT, "outputs", "_fullbank"),
                        jobname="fullbank_check")
    print("ok:", res.get("ok"))
    print("pdf:", res.get("pdf"))
    log = res.get("log") or ""
    bad = [ln for ln in log.splitlines()
           if ln.startswith("error:") or ln.lstrip().startswith("! ")]
    if bad:
        print("--- engine errors ---")
        for ln in bad[:40]:
            print(" ", ln)
    else:
        print("no engine errors")


if __name__ == "__main__":
    main()
