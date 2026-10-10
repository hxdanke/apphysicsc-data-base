#!/usr/bin/env python
"""Flag LaTeX macros that ended up outside every $...$ run.

Those are the ones that make the compiled paper fail: "\\pi" printed in prose is
either an error or literal backslash-pi.  ``convert_unicode`` produces macros
from Greek and symbols, so a run holding one should have been judged maths.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_new_extract.json")
MATH_RUN = re.compile(r"\$[^$]*\$")
MACRO = re.compile(r"\\([A-Za-z]+)")
# deliberately written by the converter as plain text
ALLOWED = {"includegraphics", "linewidth", "textwidth", "textbackslash", "textbf",
           "textit", "emph", "texttt", "textsc", "underline", "LaTeX"}

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)
qs = data["questions"] if isinstance(data, dict) else data

hits: dict[str, set] = {}
checked = 0
for q in qs:
    parts = [(q.get("stem") or "", "stem")]
    for c in q.get("choices") or []:
        parts.append((c.get("text") or "", "choice " + str(c.get("label"))))
    for text, where in parts:
        checked += 1
        prose = MATH_RUN.sub(" ", text)
        for name in MACRO.findall(prose):
            if name in ALLOWED:
                continue
            hits.setdefault(name, set()).add(f"{q['id']} / {where}")

for name, ids in sorted(hits.items(), key=lambda kv: -len(kv[1])):
    print(f"\\{name:12s} x{len(ids):3d}  {sorted(ids)[:5]}")
print(f"\n{checked} parts checked, {len(hits)} macro kinds stray outside maths")
