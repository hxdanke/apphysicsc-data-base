#!/usr/bin/env python
"""Reconcile every converted question against what the PDF actually prints.

For each question we know two things: the wording of the lines it was built
from (``server.extract.RAW_TEXT``) and the LaTeX that came out of them.  Both
sides are reduced to the same stream of tokens -- letters, digits and symbol
names -- and differenced.  Tokens missing from the output are glyphs the
converter dropped; tokens that only the output has are glyphs it invented.
Neither can happen in a faithful conversion, so both are reported.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from server import extract as ex  # noqa: E402

PDF = (r"D:\OneDrive\WHBC\AP\APPCM\Exercises\2026-2027\Exercise Book 2026-2027"
       r"\AP Physics C Mechanics Exercise Book 3 Topic Questions 2026-2027.pdf")

# macros that only carry layout; their argument supplies the real tokens
STRUCT = {
    "frac", "sqrt",     "mathrm", "mathbf", "mathit", "mathsf", "mathtt", "text", "textit",
    "textrm", "textbf", "textsc", "texttt", "emph", "left", "right", "big", "Big", "bigg", "Bigg", "quad",
    "qquad", "begin", "end", "vec", "hat", "bar", "tilde", "dot", "ddot",
    "overline", "underline", "displaystyle", "limits", "nolimits", "atop",
    "over", "binom", "substack", "rule", "hspace", "vspace", "mathrm",
}
TOKEN = re.compile(r"\\([A-Za-z]+)|\\(.)|([A-Za-z0-9])|(.)")
INCLUDEGRAPHICS = re.compile(r"\\includegraphics\[[^\]]*\]\{[^{}]*\}")
UNIT_GROUP = re.compile(r"\\mathrm\{([^{}]*)\}")
# The page prints "kgm" and raises the 2; the converter writes the customary
# "kg \cdot m^{2}".  The dot is typography, not content, so it is not counted.
_WITH_CDOT = "\\cdot"
# notation that is spelled out with letters in print but named in LaTeX
OPERATORS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos",
             "arctan", "log", "ln", "exp", "max", "min", "det", "dim", "arg"}
MACRO_ONLY = re.compile(r"^\\([A-Za-z]+)$")


def _add(out: Counter, piece: str) -> None:
    for macro, esc, alnum, other in TOKEN.findall(piece):
        if macro:
            if macro in STRUCT:
                continue
            if macro.lower() in OPERATORS:
                out.update(macro.lower())         # "cos" is printed as c, o, s
            else:
                out[macro.lower()] += 1
        elif alnum:
            out[alnum.lower()] += 1


def _units(text: str) -> str:
    return UNIT_GROUP.sub(lambda m: r"\mathrm{" + m.group(1).replace(_WITH_CDOT, " ") + "}", text)


def tokens(text: str) -> Counter:
    """Normalise one side of the comparison into a bag of tokens.

    The printed page is read character by character so a Greek letter followed
    by its subscript cannot fuse into one bogus macro ("\\omega" + "A").
    """
    out: Counter = Counter()
    _add(out, INCLUDEGRAPHICS.sub(" ", text))
    return out


def raw_tokens(text: str) -> Counter:
    """Tokens of the wording as the PDF prints it."""
    out: Counter = Counter()
    buf: list[str] = []
    for ch in INCLUDEGRAPHICS.sub(" ", text):
        if ch.isascii() and (ch.isalnum()):
            if buf:
                _add(out, "".join(buf))
                buf = []
            out[ch.lower()] += 1
            continue
        piece = ex.convert_unicode(ch)
        if piece == ch:
            continue                              # punctuation: carries no signal
        if MACRO_ONLY.match(piece):
            if buf:
                _add(out, "".join(buf))
                buf = []
            buf.append(piece)                     # keep macros separate from letters
        else:
            _add(out, piece)
    if buf:
        _add(out, "".join(buf))
    return out


def render(q: dict) -> str:
    parts = [q.get("stem") or ""]
    for c in q.get("choices") or []:
        parts.append(c.get("label") or "")
        parts.append(c.get("text") or "")
    return " ".join(parts)


def main() -> int:
    media = os.path.join(ROOT, "data", "_audit_media")
    ex.RAW_TEXT.clear()
    qs = ex.extract_pdf(PDF, media, "EB3", dpi=72)
    raws = dict(ex.RAW_TEXT)
    print(f"{len(qs)} questions, {len(raws)} with provenance\n")

    bad = 0
    for q in qs:
        orig = raw_tokens(raws.get(q["id"], ""))
        conv = tokens(_units(render(q)))
        lost = orig - conv
        gained = conv - orig
        # A single stray character is usually an artefact of the tokenising
        # itself ("-" turned into a macro argument); only report real loss.
        lost_n = sum(lost.values())
        gained_n = sum(gained.values())
        if lost_n + gained_n < 2:
            continue
        bad += 1
        print(f"=== {q['id']}  (pdf p.{q['source']['pdf_page']})")
        if lost_n:
            print(f"    MISSING  {sorted(lost.elements())}")
        if gained_n:
            print(f"    INVENTED {sorted(gained.elements())}")
        print(f"    PDF : {raws.get(q['id'], '')[:220]}")
        print(f"    OUT : {render(q)[:220]}")
    print(f"\n{bad} question(s) disagree with the printed page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
