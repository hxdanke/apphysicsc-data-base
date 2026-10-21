"""Drop the source-file tag from every question, and flag the bank for review.

The `source` field ({"doc": "EB3", "pdf_page": …, "book_page": …}) only existed to
say where a question was imported from, which is not something a teacher needs to
see on the card.  It is being removed for good, so nothing records it any more.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# How many leading questions of the bank are left unflagged.
UNFLAGGED_HEAD = 7


def main() -> int:
    if "--apply" not in sys.argv:
        print("dry run — pass --apply")
        return 0

    banks = {
        "apc-mech": ROOT / "data" / "bank.json",
        "apc-em": ROOT / "data" / "banks" / "apc-em" / "bank.json",
        "ap1": ROOT / "data" / "banks" / "ap1" / "bank.json",
        "ap2": ROOT / "data" / "banks" / "ap2" / "bank.json",
    }

    for course, path in banks.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = data["questions"]
        dropped = 0
        for q in questions:
            if "source" in q:
                del q["source"]
                dropped += 1
        if course == "apc-mech":
            for i, q in enumerate(questions):
                if i >= UNFLAGGED_HEAD:
                    q["needs_review"] = True
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        flagged = sum(1 for q in questions if q.get("needs_review"))
        print(f"{course:9} {len(questions):3} questions | source removed: {dropped} | flagged: {flagged}")

    mech = json.loads(banks["apc-mech"].read_text(encoding="utf-8"))
    print("\nleft unflagged (the first %d):" % UNFLAGGED_HEAD)
    for q in mech["questions"][:UNFLAGGED_HEAD]:
        print(f"  {q['id']}  needs_review={q.get('needs_review')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
