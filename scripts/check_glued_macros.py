#!/usr/bin/env python
"""Find maths macros glued to a following letter: "\\pif", "\\thetaA", ...

LaTeX reads "\\pif_{0}" as one undefined control sequence, so the compiled paper
fails.  Every one of these has to be split ("\\pi f_{0}").
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_new_extract.json")

GLUED = re.compile(r"\\([A-Za-z]+)(?=[A-Za-z])")
SYMBOLS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu",
    "pi", "rho", "sigma", "tau", "varphi", "phi", "omega", "Delta", "Omega",
    "Sigma", "ell", "degree", "times", "cdot", "circ", "perp", "int",
    "leq", "geq", "neq", "approx", "propto", "ll", "gg", "infty", "partial",
}

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)
qs = data["questions"] if isinstance(data, dict) else data

hits: collections.Counter = collections.Counter()
where: dict[str, set] = {}
total = 0
for q in qs:
    parts = [(q.get("stem") or "", "stem")]
    for c in q.get("choices") or []:
        parts.append((c.get("text") or "", "choice " + str(c.get("label"))))
    for text, tag in parts:
        for m in GLUED.finditer(text):
            name = m.group(1)
            if name not in SYMBOLS:
                continue
            total += 1
            hits[name] += 1
            where.setdefault(name, set()).add(f"{q['id']} / {tag}: "
                                              f"{text[max(0, m.start() - 10):m.end() + 10]}")

for name, n in hits.most_common():
    print(f"\\{name:9s} x{n:3d}  {sorted(where[name])[:2]}")
print(f"\n{total} glued symbol macro(s)")
