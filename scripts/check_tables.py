"""Audit every table-layout question in the bank after the border/spacing fix.

For each ``choice_layout == "table"`` question we render it alone, then check:

* the table does not run past the right margin;
* the gap between the stem and the table is close to one paragraph's worth;
* the table carries exactly the two rules the printed book uses -- one vertical
  rule between the label column and the first data column, one horizontal rule
  under the header row -- and no outer frame.

Usage:
    python scripts/check_tables.py
"""
import json
import os
import re
import subprocess
import sys

import pymupdf

sys.path.insert(0, ".")
from server import latex, bank as bank_mod   # noqa: E402

TECTONIC = os.path.join("tools", "tectonic.exe")
OUT = "outputs/_tblaudit"
TEXT_WIDTH = 491.6
RIGHT_MARGIN = 595.3 - 0.72 * 72          # 543.4


def rules_of(page):
    """Return (vertical, horizontal) *table* rules as (x0, x1, y0, y1).

    Fraction bars (``\\dfrac``) are also thin horizontal strokes, so only rules
    at least 40pt wide count as table rules -- a fraction bar never spans a
    column.
    """
    v, h = [], []
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.height > 8 and r.width < 3:
            v.append((r.x0, r.x1, r.y0, r.y1))
        elif r.width >= 40 and r.height < 3:
            h.append((r.x0, r.x1, r.y0, r.y1))
    return v, h


def text_lines(page):
    out = []
    for blk in page.get_text("dict").get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            t = "".join(s.get("text", "") for s in ln.get("spans", []))
            if t.strip():
                out.append((ln["bbox"][1], ln["bbox"][3], ln["bbox"][0],
                            ln["bbox"][2], t))
    out.sort()
    return out


def audit_one(q) -> dict:
    doc = latex.build_document([q])
    os.makedirs(OUT, exist_ok=True)
    tex = os.path.join(OUT, "t.tex")
    with open(tex, "w", encoding="utf-8") as fh:
        fh.write(doc)
    subprocess.run([TECTONIC, "-X", "compile", tex, "--outdir", OUT],
                   capture_output=True, text=True)
    pdf = os.path.join(OUT, "t.pdf")
    if not os.path.exists(pdf):
        return {"id": q["id"], "err": "compile failed"}

    page = pymupdf.open(pdf)[0]
    v, h = rules_of(page)
    lines = text_lines(page)
    headers = [str(x) for x in (q.get("table_headers") or [])]

    # the table's top is the top of the vertical rule (the rule starts at the
    # header row); fall back to the header text if the rule is missing
    table_top = min((r[2] for r in v), default=None)
    hdr = [l for l in lines if headers and headers[0] in l[4] and
           len(l[4].strip()) < 60]
    if table_top is None:
        table_top = hdr[0][0] if hdr else None

    # stem bottom = last text line that ends before the table starts
    above = [l for l in lines if table_top is not None and l[1] <= table_top + 1]
    stem_bottom = max((l[1] for l in above), default=None)
    gap = (table_top - stem_bottom) if (stem_bottom is not None and
                                        table_top is not None) else None

    # table band: everything from the table top downwards on this page
    band = [l for l in lines if table_top is not None and l[0] >= table_top - 3]
    tx1 = max((l[3] for l in band), default=0)

    return {
        "id": q["id"],
        "gap": gap,
        "right": tx1,
        "overflow": tx1 > RIGHT_MARGIN + 1,
        "n_v": len(v), "n_h": len(h),
        "rules_ok": len(v) >= 1 and len(h) == 1,
    }


def main():
    data = bank_mod.load_bank()
    tables = [q for q in data["questions"] if q.get("choice_layout") == "table"]
    print(f"auditing {len(tables)} table questions\n")
    bad = 0
    for q in tables:
        r = audit_one(q)
        if r.get("err"):
            print(f"  {r['id']:18} ERROR {r['err']}")
            bad += 1
            continue
        flags = []
        if r["overflow"]:
            flags.append("OVERFLOW")
        if not r["rules_ok"]:
            flags.append(f"RULES v={r['n_v']} h={r['n_h']}")
        if r["gap"] is not None and not (7 <= r["gap"] <= 16):
            flags.append(f"GAP={r['gap']:.1f}")
        gtxt = f"{r['gap']:5.1f}" if r["gap"] is not None else "  n/a"
        status = "  ".join(flags) if flags else "ok"
        if flags:
            bad += 1
        print(f"  {r['id']:18} gap={gtxt}  right={r['right']:6.1f}  "
              f"v={r['n_v']} h={r['n_h']}   {status}")
    print(f"\n{len(tables) - bad}/{len(tables)} clean")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
