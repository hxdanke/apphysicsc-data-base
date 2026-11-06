"""Italicise physical quantities that were set upright.

A variable written ``$\\mathrm{m}$`` renders in the roman font, so "a block of
mass m" reads as a unit rather than a mass.  Physical quantities -- including
physical constants such as g -- are italic; units and descriptive subscripts are
upright; mathematical constants (e, pi) are upright too.

The distinction is positional rather than lexical: ``\\mathrm{L}`` is a label in
``$v_{\\mathrm{L}}$`` but a length in ``a distance $\\mathrm{L}$``, and
``\\mathrm{m}`` is a unit in ``$1\\ \\mathrm{m}$`` but a mass in ``mass
$\\mathrm{m}$``.
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

ROMAN = re.compile(r"\\(?:mathrm|text)\{([^{}]*)\}")


def italicise(inner: str, in_script: bool, before: str, after: str) -> bool:
    r"""Should this \mathrm{...} lose its upright wrapper?"""
    # descriptive subscript: v_{\mathrm{L}}, F_{\mathrm{W}\ 1}, T_{\mathrm{h}}
    if in_script:
        return False
    # multi-letter units, numbers, labels, and constants
    if not re.fullmatch(r"[A-Za-z]", inner):
        return False
    if inner == "e":            # natural constant stays upright
        return False

    b, a = before.rstrip(), after.lstrip()

    # A value in scientific notation is followed by a unit, whatever the letter:
    # "$8.0 \times 10^{4}\ \mathrm{J}$" is joules, not an impulse J.
    if "\\times" in b and re.search(r"10\^", b):
        return False

    # g, L, h and J are never units in this bank: they are gravitational field,
    # length/angular momentum, height and impulse.  They stay upright only when
    # they are the first half of a written-out compound unit, or carry an
    # exponent (m^{2}-style).
    if a.startswith("^"):                # m^{2}, s^{-1}
        return False
    if a.startswith("/") and re.match(r"/\s*\\(?:mathrm|text)\{", a):
        return False                     # W/s, N/m
    if inner in "gLhJ":
        return True
    # A subscripted letter is a variable too: a unit never carries an index.
    if a.startswith("_"):
        return True

    # What is left (m, s, N, W) may be a unit.  A number in a subscript is an
    # index, not a value, so it must not make a later symbol look like a unit.
    without_scripts = re.sub(r"[_^]\{[^{}]*\}", "", b)
    if re.search(r"\d", without_scripts):   # "1\ m", "(4i+3j)\ N"
        return False
    if b.endswith("/"):                  # second half of a compound unit
        return False
    if a.startswith("/"):                # first half of a compound unit
        return False
    if "\\mu" in b and inner == "s":     # a mangled \mu_s, neither unit nor variable
        return False
    return True


def fix_run(body: str) -> str:
    out, stack = [], []
    i = 0
    while i < len(body):
        if body[i] in "_^" and i + 1 < len(body) and body[i + 1] == "{":
            stack.append("script")
            out.append(body[i:i + 2])
            i += 2
            continue
        if body[i] == "{":
            stack.append("group")
            out.append("{")
            i += 1
            continue
        if body[i] == "}":
            if stack:
                stack.pop()
            out.append("}")
            i += 1
            continue
        m = ROMAN.match(body, i)
        if m:
            before = "".join(out)
            if italicise(m.group(1), "script" in stack, before, body[m.end():]):
                out.append(m.group(1))
            else:
                out.append(m.group(0))
            i = m.end()
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


def fix_text(text: str) -> str:
    if not text or ("\\mathrm" not in text and "\\text{" not in text):
        return text
    # _scan_math hands back bodies without their delimiters, so maths runs have
    # to be closed again here.
    return "".join(("$" + fix_run(b) + "$") if k == "math" else b
                   for k, b in _scan_math(text))


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
    if not args.apply:
        for qid, where, old, new in total[:40]:
            print(f"  {qid:18} {where:8}")
            print(f"      - {old[-100:]}")
            print(f"      + {new[-100:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
