"""Take plain quantities out of maths mode.

A quantity that is only a number and a unit -- "3.0 m/s", "0.50 m", "$6$ N" --
has nothing mathematical about it: no subscript, no superscript, no algebra. Set
as maths it comes out in the maths font and spaced like a formula.

What stays in maths is anything that is actually mathematical: a superscript or
subscript ("$9.8\\ \\mathrm{m/s}^{2}$", "$\\theta_{0}$"), and an expression with
algebra in it ("$A = 3.0\\ \\mathrm{m}$").
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.latex import _scan_math  # noqa: E402

# number, then a \mathrm/\text unit, and nothing else
PURE = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?)\s*(?:\\\s+|\s+)?(?:\\mathrm|\\text)\{([^}]*)\}\s*$")
# just a number, with the unit left in the prose ("$6$ N")
BARE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*$")


def fix_run(body: str) -> str:
    m = PURE.match(body)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = BARE.match(body)
    if m:
        return m.group(1)
    return "$" + body + "$"


def fix_text(text: str) -> str:
    if not text or "$" not in text:
        return text
    return "".join(fix_run(b) if k == "math" else b for k, b in _scan_math(text))


def walk(q: dict, apply: bool):
    changes = []

    def record(where, old, set_fn):
        new = fix_text(old)
        if new != old:
            changes.append((q["id"], where, old, new))
            if apply:
                set_fn(new)

    if q.get("stem"):
        record("stem", q["stem"], lambda v: q.__setitem__("stem", v))
    for c in q.get("choices") or []:
        for key in ("text", "text2", "text3", "text4"):
            if c.get(key):
                record(f"choice {c.get('label','')}.{key}", c[key],
                       lambda v, c=c, key=key: c.__setitem__(key, v))
    for i, head in enumerate(q.get("table_headers") or []):
        record(f"table_headers[{i}]", head,
               lambda v, i=i: q["table_headers"].__setitem__(i, v))
    spec = q.get("stem_table")
    if spec:
        for i, head in enumerate(spec.get("headers") or []):
            record(f"stem_table.headers[{i}]", head,
                   lambda v, i=i: spec["headers"].__setitem__(i, v))
        for r, row in enumerate(spec.get("rows") or []):
            for c, cell in enumerate(row):
                if cell:
                    record(f"stem_table.rows[{r}][{c}]", str(cell),
                           lambda v, r=r, c=c: spec["rows"][r].__setitem__(c, v))
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    banks = [ROOT / "data" / "bank.json"] + sorted(
        (ROOT / "data" / "banks").glob("*/bank.json"))
    total = []
    for path in banks:
        data = json.loads(path.read_text(encoding="utf-8"))
        for q in data["questions"]:
            total += walk(q, args.apply)
        if args.apply:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    print(f"{'fixed' if args.apply else 'would fix'}: {len(total)} fields")
    for qid, where, old, new in total:
        if not args.apply:
            print(f"  {qid:20} {where:10} {old[:88]}")
            print(f"  {'':20} {'':10} {new[:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
