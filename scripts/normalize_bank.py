#!/usr/bin/env python
"""Run the LaTeX repairs from `texfix.py` over the whole question bank.

    python scripts/normalize_bank.py [--apply] [--report-only]

Without --apply it only prints what would change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from texfix import repair  # noqa: E402

BANK = ROOT / "data" / "bank.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the repaired bank")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    bank = json.loads(BANK.read_text(encoding="utf-8"))
    questions = bank.get("questions", bank)

    changed_fields = 0
    changed_questions = set()
    for q in questions:
        targets = [("stem", q)]
        for c in q.get("choices") or []:
            targets.append(("text", c))
        if q.get("solution"):
            targets.append(("solution", q))
        for key, holder in targets:
            before = holder.get(key) or ""
            if not before:
                continue
            after = repair(before)
            if after != before:
                changed_fields += 1
                changed_questions.add(q.get("id", "?"))
                holder[key] = after

    print(f"questions touched : {len(changed_questions)}")
    print(f"fields repaired   : {changed_fields}")
    if args.limit:
        for qid in list(changed_questions)[:args.limit]:
            print("  ", qid)

    if args.apply and changed_fields:
        backup = BANK.with_suffix(".json.bak")
        shutil.copy2(BANK, backup)
        BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"written: {BANK}  (backup at {backup.name})")
    elif args.apply:
        print("nothing to change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
