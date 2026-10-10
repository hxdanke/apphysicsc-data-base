"""Build a geometry-driven figure plan for the whole bank.

Ground truth = the original PDF.

Anchoring.  The bank records each question's physical page.  On every page the
questions appear in reading order, and the page carries exactly one bare number
label ("3.") per question -- verified: question count == label count on every
page.  So we simply zip the page's questions (ordered by unit/topic/number) with
the page's number-label lines (ordered by y).  This is exact and needs no text
matching.

Attribution of images (pre-sorted by y):

  prev = the last anchored question at or above the image
  next = the first anchored question strictly below the image

  * prev is None                         -> header of `next`
  * gap figure (below prev's last option / stem, above next's label):
        - next's stem mentions a figure   -> header of next
        * else                            -> trailing of prev
  * inside prev: within an option band   -> option (letter)
                 otherwise               -> trailing

The gap rule is the fix for the reported bug (a figure printed between Q2 and Q3
belongs above Q3's stem, not under Q2).
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "data", "bank.json")
PDF = ("D:/OneDrive/WHBC/AP/APPCM/Exercises/2026-2027/Exercise Book 2026-2027/"
       "AP Physics C Mechanics Exercise Book 3 Topic Questions 2026-2027.pdf")
OUT = os.path.join(ROOT, "scripts", "figure_plan.json")

NUM_RE = re.compile(r"^(\d{1,2})\.$")
OPT_RE = re.compile(r"^\(([A-D])\)$")
OPT_GLUE_RE = re.compile(r"^\(([A-D])\)\s+\S")
WANTS_FIG = re.compile(r"\b(figure|graph|diagram|shown)\b", re.I)
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
                out.append((l["bbox"][1], l["bbox"][0], t))
    out.sort(key=lambda z: (z[0], z[1]))
    return out


def page_images(page):
    d = page.get_text("dict")
    imgs = [fitz.Rect(b["bbox"]) for b in d["blocks"] if b["type"] == 1]
    imgs = [r for r in imgs if r.width > 25 and r.height > 25]
    imgs.sort(key=lambda r: (r.y0, r.x0))
    return imgs


def number_labels(lines):
    return [y for y, x, t in lines if NUM_RE.match(t) and x < 70]


def option_labels(lines, anchor, end):
    """Ordered list of (letter, y, x) for the option labels in [anchor, end).

    In the book the labels sit in a two-column grid: (A) (C) on the left,
    (B) (D) on the right, each on its own row.  We keep, for every letter, the
    occurrence nearest the question (first in reading order)."""
    found = {}
    for y, x, t in lines:
        if y < anchor - 1 or y >= end:
            continue
        m = OPT_RE.match(t)
        if not m and x < 130:
            m = OPT_GLUE_RE.match(t)
        if m and m.group(1) not in found:
            found[m.group(1)] = (y, x)
    return sorted(((k, v[0], v[1]) for k, v in found.items()), key=lambda z: (z[1], z[2]))


def rec_of(r, kind, opt):
    return {"y": round(r.y0, 1), "x0": round(r.x0, 1), "x1": round(r.x1, 1),
            "kind": kind, "opt": opt}


def main():
    bank = json.load(open(BANK, encoding="utf-8"))
    qs = bank["questions"]
    doc = fitz.open(PDF)

    by_page = defaultdict(list)
    for q in qs:
        by_page[q["source"]["pdf_page"]].append(q)

    plan = {q["id"]: {"id": q["id"], "number": q.get("number"),
                      "topic": q.get("topic"),
                      "page": q["source"]["pdf_page"], "figures": []}
            for q in qs}

    problems = []
    for pno, page_qs in by_page.items():
        page = doc[pno - 1]
        H = page.rect.height
        lines = page_lines(page)
        imgs = page_images(page)
        labs = number_labels(lines)

        ordered_qs = sorted(page_qs, key=lambda q: (
            str(q.get("topic") or ""), q.get("number", 0)))
        if len(labs) != len(ordered_qs):
            problems.append((pno, len(ordered_qs), len(labs)))
        # zip; if counts differ, pair by nearest available
        pairs = list(zip(ordered_qs, labs))
        if len(labs) > len(ordered_qs):
            # extra labels: ignore beyond
            pass
        if not pairs or not imgs:
            continue
        valid = sorted(pairs, key=lambda p: p[1])  # by anchor y
        anchors = {q["id"]: y for q, y in valid}

        opts_by_q = {}
        for i, (q, a) in enumerate(valid):
            end = valid[i + 1][1] if i + 1 < len(valid) else H
            opts_by_q[q["id"]] = option_labels(lines, a, end)

        for r in imgs:
            prev = None
            nxt = None
            for q, a in valid:
                if a <= r.y0 + 1:
                    prev = (q, a)
                elif nxt is None:
                    nxt = (q, a)

            if prev is None:
                plan[nxt[0]["id"]]["figures"].append(rec_of(r, "header", None))
                continue

            pq, pa = prev
            labs_prev = opts_by_q[pq["id"]]
            # Everything below prev's LAST option label (or below its stem when
            # it has no options) is figure territory -- text there is just the
            # figure's own annotations -- so the option bottom is the boundary.
            gap_bottom = labs_prev[-1][1] if labs_prev else pa + 6

            if nxt is not None and r.y0 > gap_bottom + 6 and r.y0 < nxt[1] - 4:
                nq = nxt[0]
                # A figure sitting in the gap below question N is printed above
                # the stem of the next question that actually refers to a
                # figure.  The book sometimes has an intervening question with
                # no artwork of its own (e.g. a pure-computation item), so we
                # look forward to the first following question whose stem
                # mentions a figure and attach it there as a header.
                target = None
                for cand, cy in valid:
                    if cy <= r.y0 + 1:
                        continue
                    if cy > nxt[1] + 200:      # do not reach across a page's worth
                        break
                    if WANTS_FIG.search(cand.get("stem") or ""):
                        target = cand
                        break
                    if target is None:
                        target = cand
                if WANTS_FIG.search(pq.get("stem") or "") and not any(
                        f["kind"] in ("header", "trailing")
                        for f in plan[pq["id"]]["figures"]):
                    plan[pq["id"]]["figures"].append(rec_of(r, "trailing", None))
                elif target is not None:
                    plan[target["id"]]["figures"].append(rec_of(r, "header", None))
                else:
                    plan[nq["id"]]["figures"].append(rec_of(r, "header", None))
                continue

            opt = None
            if labs_prev:
                # Option figures sit in the same two-column grid as the labels:
                # (A) (C) on the left, (B) (D) on the right, each on its row.
                # Match an image to the label nearest in both y (its row) and
                # x (its column).
                rc = (r.y0 + r.y1) / 2.0
                best = None
                for letter, oy, lx in labs_prev:
                    dy = abs(oy - rc)
                    dx = abs(lx - r.x0)
                    if dy < 55 and dx < 170:
                        score = dy + dx * 0.25
                        if best is None or score < best[0]:
                            best = (score, letter)
                if best:
                    opt = best[1]
            plan[pq["id"]]["figures"].append(
                rec_of(r, "option" if opt else "trailing", opt))

    for rec in plan.values():
        rec["figures"].sort(key=lambda f: (f["y"], f["x0"]))

    json.dump(list(plan.values()), open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    tally = defaultdict(int)
    nofig = 0
    for rec in plan.values():
        if not rec["figures"]:
            nofig += 1
        for f in rec["figures"]:
            tally[f["kind"]] += 1
    print("questions:", len(plan), "| no figure:", nofig)
    print("kind tally:", dict(tally))
    if problems:
        print("pages with count mismatch (start page, nq, nlabels):", problems[:20])
        print("  total mismatched pages:", len(problems))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
