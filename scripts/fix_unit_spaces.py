"""Remove the spurious thin space the extractor put before implicit products.

The old ``_space_num_unit`` inserted ``\\ `` between a digit and a following bare
single letter, intending to restore the unit space in ``2s``/``5m``.  But every
real unit is already ``\\mathrm{...}``, so the rule only ever fired on implicit
products -- ``5t``, ``2F_0``, ``3R``, ``4K_0``, ``v_{1\\ f}`` -- which then
rendered with a visible gap (``5 t``).

This script strips exactly that pattern from the stored bank.  It is idempotent
and only touches a ``\\ `` that sits directly between a digit and a single
letter (optionally followed by a script or a non-letter).
"""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "data", "bank.json")

# digit  +  "\ "  +  single letter (not part of a longer word)
BAD = re.compile(r"(?<=[0-9])\\\s(?=[a-zA-Z](?![a-zA-Z]))")

FIELDS = ("stem", "answer", "solution")


def clean(s: str) -> tuple[str, int]:
    if not s:
        return s, 0
    n = len(BAD.findall(s))
    return BAD.sub("", s), n


def main():
    bank = json.load(open(BANK, encoding="utf-8"))
    total = 0
    touched = 0
    for q in bank["questions"]:
        before = json.dumps(q, ensure_ascii=False, sort_keys=True)
        for f in FIELDS:
            if f in q and isinstance(q[f], str):
                q[f], k = clean(q[f])
                total += k
        for c in q.get("choices") or []:
            for k in ("text", "text2", "text3", "text4"):
                if k in c and isinstance(c[k], str):
                    c[k], n = clean(c[k])
                    total += n
        if json.dumps(q, ensure_ascii=False, sort_keys=True) != before:
            touched += 1

    json.dump(bank, open(BANK, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"removed {total} spurious spaces across {touched} questions")


if __name__ == "__main__":
    main()
