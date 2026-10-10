#!/usr/bin/env python
"""Report every fraction rule the builder could NOT turn into structure.

A rule left ``used == False`` after the run either had no usable numerator /
denominator, or it was a radical rule whose radicand came out empty.  Both mean
content is being lost, so each one is listed with the text around it.
"""

from __future__ import annotations

import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.fractions import Builder, Span as FSpan, collect_bars  # noqa: E402

PDF = (r"D:\OneDrive\WHBC\AP\APPCM\Exercises\2026-2027\Exercise Book 2026-2027"
       r"\AP Physics C Mechanics Exercise Book 3 Topic Questions 2026-2027.pdf")


def main() -> int:
    doc = pymupdf.open(PDF)
    lost = 0
    for pno in range(len(doc)):
        page = doc[pno]
        layout = page.get_text("dict")
        fspans: list[FSpan] = []
        for blk in layout["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                for s in ln["spans"]:
                    if s["text"].strip():
                        fspans.append(FSpan(s["bbox"][0], s["bbox"][1], s["bbox"][2],
                                            s["bbox"][3], s["text"], s["flags"],
                                            s["size"]))
        bars = collect_bars(page)
        if not bars:
            continue
        Builder(fspans, bars).run()
        for b in bars:
            if b.used:
                continue
            lost += 1
            near = [s for s in fspans
                    if abs(s.y1 - b.y) < 26 and abs(s.cx - b.cx) < 90]
            near.sort(key=lambda s: (s.y1, s.x0))
            shown = " ".join(s.text for s in near)[:90]
            print(f"p{pno + 1:4d} unused rule x {b.x0:7.2f}..{b.x1:7.2f} y {b.y:7.2f}"
                  f" w {b.x1 - b.x0:6.2f}   near: {shown!r}")
    print(f"\n{lost} rules produced no structure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
