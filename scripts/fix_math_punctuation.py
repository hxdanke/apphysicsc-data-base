"""Move prose punctuation out of the maths runs it had slipped into.

The scan uses the delimiter-aware splitter rather than a regex, because a comma
*between* two runs (``$a$, $b$``) is correct prose and must be left alone.  What
gets moved is punctuation sitting at the end of a run, or punctuation that has
swallowed the start of the next sentence.
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

END = re.compile(r"([.,;:!?])\s*$")
MID = re.compile(r"([.,;:!?])(\s+)(?=[A-Za-z\\])")


def fix_run(body: str) -> str:
    """One maths body, with any prose punctuation handed back to the text."""
    # \, \; \: \! are spacing commands; a comma after a backslash is one of
    # those, not prose, so it stays where it is.
    def escaped(at: int) -> bool:
        return body[:at].rstrip().endswith("\\")

    m = END.search(body)
    if m and not escaped(m.start(1)):
        head = body[:m.start()].rstrip()
        return "$" + head + "$" + m.group(1)

    m = MID.search(body)
    if m and not escaped(m.start(1)):
        return ("$" + body[:m.start(1)].rstrip() + "$" + m.group(1)
                + " $" + body[m.end():].lstrip() + "$")

    return "$" + body + "$"


def fix_text(text: str) -> str:
    if not text or "$" not in text:
        return text
    out = []
    for kind, body in _scan_math(text):
        out.append(fix_run(body) if kind == "math" else body)
    return "".join(out)


def walk(q: dict, apply: bool):
    """Yield (setter, label) for every text field that can carry maths."""
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
    heads = q.get("table_headers") or []
    for i, head in enumerate(heads):
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
                    record(f"stem_table.rows[{r}][{c}]", cell,
                           lambda v, r=r, c=c: spec["rows"][r].__setitem__(c, v))
    if q.get("solution"):
        record("solution", q["solution"], lambda v: q.__setitem__("solution", v))
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

    print(f"{'fixed' if args.apply else 'would fix'}: {len(total)}")
    for qid, where, old, new in total:
        if not args.apply:
            print(f"  {qid:20} {where:12} {old[-58:]!r}")
            print(f"  {'':20} {'':12} {new[-58:]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
