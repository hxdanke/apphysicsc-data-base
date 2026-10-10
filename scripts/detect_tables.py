"""Extract the cell text of every table-style question.

Detection (see the module docstring history): a table-style question prints its
four options as BARE letters A/B/C/D (never "(A)"), one option per row, with a
header row above.  This module re-reads those rows and splits every row into
columns by x-gaps so multi-line cells survive.

Output: scripts/table_plan.json
  [{id, page, headers:[...], rows:[{label, cells:[...]}]}]
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "data", "bank.json")
OUT = os.path.join(ROOT, "scripts", "table_plan.json")
PDF = ("D:/OneDrive/WHBC/AP/APPCM/Exercises/2026-2027/Exercise Book 2026-2027/"
       "AP Physics C Mechanics Exercise Book 3 Topic Questions 2026-2027.pdf")

NUM_RE = re.compile(r"^(\d{1,2})\.$")
BARE_RE = re.compile(r"^([A-D])$")
WS = re.compile(r"\s+")


def norm(s):
    return WS.sub(" ", (s or "")).strip()


def page_lines(page):
    d = page.get_text("dict")
    out = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            t = norm("".join(sp["text"] for sp in l["spans"]))
            if t:
                out.append({"y": round(l["bbox"][1], 1), "x": round(l["bbox"][0], 1),
                            "x1": round(l["bbox"][2], 1), "t": t})
    out.sort(key=lambda z: (z["y"], z["x"]))
    return out


def split_columns(items, gap=18.0):
    """Split a row's text lines into columns by the largest x gaps.

    ``items`` = list of (x, x1, text) sorted by x.  A new column starts when the
    horizontal gap to the previous line exceeds ``gap``.
    """
    cols = []
    for x, x1, t in sorted(items):
        if not cols or x - cols[-1]["x1"] > gap:
            cols.append({"x": x, "x1": x1, "parts": [(x, t)]})
        else:
            # same column: append its text (a wrapped line)
            cols[-1]["parts"].append((x, t))
            cols[-1]["x1"] = max(cols[-1]["x1"], x1)
    return [" ".join(p[1] for p in sorted(c["parts"])) for c in cols]


def band_cols(lines, y0, y1, xmin=100, gap=18.0):
    items = [(l["x"], l["x1"], l["t"]) for l in lines
             if y0 - 1 <= l["y"] < y1 and l["x"] >= xmin]
    if not items:
        return []
    return split_columns(items, gap)


def main():
    bank = json.load(open(BANK, encoding="utf-8"))
    qs = bank["questions"]
    doc = pymupdf.open(PDF)

    by_page = defaultdict(list)
    for q in qs:
        by_page[q["source"]["pdf_page"]].append(q)

    results = {}
    for pno, page_qs in by_page.items():
        page = doc[pno - 1]
        H = page.rect.height
        lines = page_lines(page)
        labs = [l["y"] for l in lines if NUM_RE.match(l["t"]) and l["x"] < 70]
        ordered = sorted(page_qs, key=lambda q: (str(q.get("topic") or ""),
                                                 q.get("number", 0)))
        pairs = sorted(zip(ordered, labs), key=lambda z: z[1])
        for i, (q, anchor) in enumerate(pairs):
            end = pairs[i + 1][1] if i + 1 < len(pairs) else H
            body = [l for l in lines if anchor - 1 <= l["y"] < end]
            bare = [(l["t"], l["y"], l["x"]) for l in body
                    if BARE_RE.match(l["t"]) and 70 <= l["x"] <= 115]
            letters = [b[0] for b in bare]
            if letters != ["A", "B", "C", "D"]:
                continue
            ys = sorted(b[1] for b in bare)
            if len({round(y) for y in ys}) != 4:
                continue
            first = min(ys)
            # header band: the line(s) above the first option row, bounded by the
            # stem above it (there is always a blank-ish gap before the header)
            head_items = [(l["x"], l["x1"], l["t"]) for l in body
                          if first - 26 <= l["y"] < first - 3 and l["x"] >= 100]
            if not head_items:
                continue
            headers = split_columns(head_items, gap=18.0)
            rows = []
            for k, (lab, ly, lx) in enumerate(bare):
                ny = ys[k + 1] if k + 1 < len(ys) else ly + 30
                cells = band_cols(body, ly - 2, ny - 2)
                rows.append({"label": lab, "cells": cells})
            ncol = max((len(r["cells"]) for r in rows), default=0)
            if ncol < 2:
                continue
            results[q["id"]] = {"id": q["id"], "page": pno,
                                "headers": headers, "rows": rows}

    json.dump(list(results.values()), open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("table questions:", len(results))
    for k, v in results.items():
        print("=" * 66)
        print(k, "| head:", v["headers"])
        for r in v["rows"]:
            print("   ", r["label"], "->", r["cells"])


if __name__ == "__main__":
    main()
