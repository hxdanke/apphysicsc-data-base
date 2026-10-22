"""Turn item labels back into plain text.

"Object 1", "Car 1", "Block A" name things; the 1 and the A are not quantities.
Set as maths they come out in the maths font and spaced like a formula, so the
label has to go back into the prose.

Only a capitalised noun from the list below counts, and only when what follows is
a bare digit or a single capital letter.  "After $3$ seconds" and "Between $1$
and $3$ seconds" are quantities and are left alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# nouns that introduce a label in this bank, both cases
NOUNS = [
    "Object", "Objects", "Block", "Blocks", "Figure", "Collision", "Scenario",
    "Trial", "Ball", "Car", "Disk", "Boat", "Spring", "Student", "Location",
    "Group", "Cart", "Asteroid", "Satellite", "Hoop", "Point", "Pulley",
    "System", "Systems",
    "objects", "blocks", "figures", "collisions", "scenarios", "trials",
    "balls", "cars", "disks", "boats", "springs", "students", "locations",
    "groups", "carts", "asteroids", "satellites", "hoops", "points", "pulleys",
    "systems",
]
TOKEN = r"(?:\\mathrm\{)?(\d{1,3}|[A-Z])\}?"
PAT = re.compile(r"\b(" + "|".join(NOUNS) + r")\s+\$" + TOKEN + r"\$")
# a label carried on: "Blocks 2 and $3$", "trials 1 and $2$"
PAT_JOIN = re.compile(r"\b(and|or)\s+\$" + TOKEN + r"\$")
# a whole list in one run: "points, $1,\ 2$, and $3$"
PAT_LIST = re.compile(r"\$(\d{1,3}(?:,\s*\\\s*\d{1,3})+)\$")
NEAR = re.compile(r"\b(" + "|".join(NOUNS) + r")\b", re.IGNORECASE)


def _labelled_near(text: str, at: int, back: int = 60) -> bool:
    """True when a label noun sits just before this point."""
    return NEAR.search(text[max(0, at - back):at]) is not None


def fix_text(text: str) -> str:
    if not text or "$" not in text:
        return text

    def unwrap(inner: str) -> str:
        s = inner.replace("\\,", ",").replace("\\ ", " ").strip()
        return re.sub(r",\s*", ", ", s)

    # "After $3$ seconds" and "Between $1$ and $3$ seconds" never reach this:
    # those words are not in the noun list above.
    out = PAT.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)

    def join_sub(m: re.Match) -> str:
        if not _labelled_near(out, m.start()):
            return m.group(0)
        return f"{m.group(1)} {m.group(2)}"

    out = PAT_JOIN.sub(join_sub, out)

    def list_sub(m: re.Match) -> str:
        if not _labelled_near(out, m.start()):
            return m.group(0)
        return unwrap(m.group(1))

    return PAT_LIST.sub(list_sub, out)


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
            print(f"  {qid:20} {where:10} {old[:96]}")
            print(f"  {'':20} {'':10} {new[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
