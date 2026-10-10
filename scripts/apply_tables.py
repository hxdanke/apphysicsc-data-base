"""Mark every table-style question and store its options as table cells.

Two inputs:

  * ``scripts/table_plan.json`` (from ``detect_tables.py``) tells us WHICH
    questions the printer set as tables (bare A/B/C/D labels, 2x2 grid, header
    row above);
  * ``scripts/table_data.py`` is the hand-transcribed CONTENT of those tables
    (the geometry pass misreads stacked fractions and long multi-line cells).

The script asserts the two agree on the set of questions, then writes into the
bank:

    choice_layout : "table"
    table_headers : [col1, col2, ...]
    choices[i].text, .text2, .text3 : the row's cells
"""

from __future__ import annotations

import json
import os
import re

from table_data import TABLES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "data", "bank.json")
PLAN = os.path.join(ROOT, "scripts", "table_plan.json")


def main():
    bank = json.load(open(BANK, encoding="utf-8"))
    byid = {q["id"]: q for q in bank["questions"]}
    detected = {p["id"] for p in json.load(open(PLAN, encoding="utf-8"))}
    typed = set(TABLES)

    if detected != typed:
        print("!! detected vs transcribed mismatch")
        print("   only detected :", sorted(detected - typed))
        print("   only transcribed:", sorted(typed - detected))

    n = 0
    for qid, rec in TABLES.items():
        q = byid.get(qid)
        if q is None:
            print("  missing question:", qid)
            continue
        q["choice_layout"] = "table"
        q["table_headers"] = list(rec["headers"])
        rows = rec["rows"]
        for i, ch in enumerate(q.get("choices") or []):
            if i >= len(rows):
                break
            cells = rows[i]
            ch["text"] = cells[0] if cells else ""
            for j, c in enumerate(cells[1:], start=2):
                ch[f"text{j}"] = c
        # drop any stale extra cells from an earlier pass
        ncell = max(len(r) for r in rows)          # cells excluding the label
        for ch in q["choices"]:
            for k in (2, 3, 4, 5, 6):
                if f"text{k}" in ch and k > ncell:
                    del ch[f"text{k}"]
        n += 1

    json.dump(bank, open(BANK, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"marked {n} table questions")


if __name__ == "__main__":
    main()
