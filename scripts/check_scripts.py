#!/usr/bin/env python
"""Flag every superscript / subscript group that cannot possibly be one.

The printed page never raises more than a couple of glyphs: exponents are
"2", "-1", "T", "n".  So a group such as

    ^{at}^{t}^{= 2. Multiply the result by}^{\\Delta t}
    ^{-}^{\\theta}^{f}^{/}^{k}

is the converter mistaking body text for scripts, not mathematics.
``audit_pages.py`` is blind to that class of damage because it compares bags of
letters and the letters survive inside the braces -- this checker looks at the
wrapper instead.

Multi-glyph *subscripts* are legitimate and common on their own, however --
"K_{\\mathrm{Disk 1}}", "P_{\\mathrm{norm}}" -- so only English prose or sentence
punctuation inside a subscript is reported.

    python scripts/check_scripts.py [BANK.json]
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_new_extract.json")

SCRIPT = re.compile(r"(?<!\\)([\^_])(\{)")
# words that can only be English, never a subscript label
PROSE = {"and", "or", "the", "is", "are", "was", "that", "which", "when",
         "where", "then", "with", "than", "given", "between", "multiply",
         "result", "interval", "position", "distance", "planet", "earth"}
CHAIN_MIN = 3          # three scripts in a row is always a mis-split
SUP_MAX = 16           # longest exponent the book prints ("-\theta_{f}/k")


def _match(text: str, start: int) -> str | None:
    """Body of the brace group opening at ``start`` (which points at '{')."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return None


def _plain(body: str) -> list[str]:
    """Words inside a group, with \\mathrm{..} wrappers taken off."""
    body = re.sub(r"\\(?:mathrm|mathbf|text|textrm|texttt)\{([^{}]*)\}", r"\1", body)
    return [w.lower() for w in re.findall(r"[A-Za-z]+", body)]


def scan(text: str) -> list[tuple[str, str]]:
    """(reason, body) of every script group that looks wrong."""
    hits: list[tuple[str, str]] = []
    marks: list[tuple[int, int, int, str]] = []   # (start, end, kind_is_sup, body)
    for m in SCRIPT.finditer(text):
        body = _match(text, m.end(2) - 1)
        if body is None:
            continue
        # index just past the closing brace
        end = m.end(2) + len(body) + 1
        marks.append((m.start(1), end, 1 if m.group(1) == "^" else 0, body))

    # a run of scripts with nothing real between them
    run: list[int] = []
    for i, mk in enumerate(marks):
        gap = "" if not run else text[marks[run[-1]][1]:mk[0]]
        if run and not gap.strip("$ "):
            run.append(i)
        else:
            if len(run) >= CHAIN_MIN:
                hits.append(("chain", " ".join(marks[j][3] for j in run)))
            run = [i]
    if len(run) >= CHAIN_MIN:
        hits.append(("chain", " ".join(marks[j][3] for j in run)))

    for _s, _e, sup, body in marks:
        # only feast the word test on real words: "_{a}" and "_{max,1}" are
        # honest labels, and the comma is a separator, not sentence punctuation
        words = [w for w in _plain(body) if len(w) >= 3]
        if any(w in PROSE for w in words):
            hits.append(("superscript" if sup else "subscript", body))
        elif sup and len(body.strip()) > SUP_MAX:
            hits.append(("superscript", body))
        elif len(body.strip()) > 24:
            hits.append(("subscript", body))
    return hits


def render(q: dict) -> list[tuple[str, str]]:
    parts = [("stem", q.get("stem") or "")]
    for c in q.get("choices") or []:
        parts.append((f"choice {c.get('label', '')}".strip(), c.get("text") or ""))
    return parts


def main() -> int:
    with open(BANK, encoding="utf-8") as fh:
        blob = json.load(fh)
    qs = blob["questions"] if isinstance(blob, dict) else blob
    bad = 0
    bodies: collections.Counter = collections.Counter()
    for q in qs:
        hits = [(name, why, b) for name, txt in render(q)
                for why, b in scan(txt or "")]
        if not hits:
            continue
        bad += 1
        print(f"=== {q['id']}  (pdf p.{q.get('source', {}).get('pdf_page')})")
        for name, why, body in hits:
            bodies[(why, body)] += 1
            print(f"    {name} [{why}]: ...{body[:90]}...")
    print(f"\n{bad} question(s) carry an impossible script group")
    for (why, body), n in bodies.most_common(12):
        print(f"    {n:3d} x  [{why}] {body[:70]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
