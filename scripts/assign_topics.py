"""Fill in additional_topics for questions that genuinely span knowledge blocks.

An entry is added only where solving the question *requires* the other block --
not where it merely mentions a related idea.  A kinematics question that asks for
a position-time graph needs 1.3; a vector question that happens to be about
velocity does not need 1.2.

Lists are written in chapter order by :func:`sort_key`, not in the order typed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "data" / "bank.json"

# id -> extra knowledge blocks, besides the primary topic
EXTRA = {
    # --- Unit 1: vectors that are really kinematics, kinematics that needs graphs
    "EB3-U1-1.1-Q1": ["1.2"],
    "EB3-U1-1.1-Q2": ["1.2"],
    "EB3-U1-1.1-Q6": ["1.2"],
    "EB3-U1-1.1-Q8": ["1.2"],
    "EB3-U1-1.1-Q9": ["1.2"],
    "EB3-U1-1.2-Q2": ["1.3"],
    "EB3-U1-1.2-Q4": ["1.3"],
    "EB3-U1-1.2-Q7": ["1.1"],
    "EB3-U1-1.3-Q1": ["1.2"],
    "EB3-U1-1.3-Q2": ["1.2"],
    "EB3-U1-1.3-Q7": ["1.2"],
    "EB3-U1-1.3-Q8": ["1.2"],
    "EB3-U1-1.3-Q9": ["1.2"],
    "EB3-U1-1.3-Q10": ["1.2"],
    # relative motion in two dimensions
    "EB3-U1-1.4-Q1": ["1.5"],
    "EB3-U1-1.4-Q2": ["1.5"],
    "EB3-U1-1.4-Q4": ["1.5"],
    "EB3-U1-1.4-Q5": ["1.3"],
    "EB3-U1-1.4-Q6": ["1.5"],
    "EB3-U1-1.4-Q8": ["1.5"],
    "EB3-U1-1.4-Q9": ["1.5"],
    # river / boat problems are relative velocity as much as projectiles
    "EB3-U1-1.5-Q1": ["1.4"],
    "EB3-U1-1.5-Q2": ["1.1"],
    "EB3-U1-1.5-Q4": ["1.4"],
    "EB3-U1-1.5-Q8": ["1.1"],

    # --- Unit 2: centre of mass in flight and in hanging equilibrium
    "EB3-U2-2.1-Q2": ["1.5"],
    "EB3-U2-2.1-Q6": ["5.5"],
    "EB3-U2-2.1-Q8": ["5.5"],
    # free-body work that still needs Newton's second law to finish
    "EB3-U2-2.2-Q2": ["2.5"],
    "EB3-U2-2.2-Q3": ["2.5", "2.7"],
    "EB3-U2-2.2-Q4": ["2.5"],
    "EB3-U2-2.2-Q6": ["2.4", "2.7"],
    "EB3-U2-2.2-Q7": ["2.5"],
    "EB3-U2-2.2-Q9": ["2.5"],
    # third-law pairs resolved through second law
    "EB3-U2-2.3-Q3": ["2.4"],
    "EB3-U2-2.3-Q4": ["2.7"],
    "EB3-U2-2.3-Q7": ["2.4", "2.7"],
    "EB3-U2-2.3-Q8": ["2.5", "2.7"],
    "EB3-U2-2.3-Q9": ["2.5"],
    "EB3-U2-2.4-Q1": ["2.7"],
    "EB3-U2-2.4-Q3": ["2.7"],
    "EB3-U2-2.4-Q9": ["2.5"],
    "EB3-U2-2.5-Q2": ["2.3"],
    "EB3-U2-2.5-Q4": ["2.2"],
    "EB3-U2-2.5-Q8": ["2.2"],
    "EB3-U2-2.5-Q9": ["2.2"],
    "EB3-U2-2.6-Q7": ["2.10"],
    "EB3-U2-2.7-Q2": ["2.5"],
    "EB3-U2-2.7-Q6": ["2.2"],
    "EB3-U2-2.7-Q8": ["2.5"],
    "EB3-U2-2.7-Q9": ["2.5"],
    "EB3-U2-2.8-Q2": ["2.5"],
    "EB3-U2-2.8-Q4": ["2.5"],
    "EB3-U2-2.8-Q5": ["2.5"],
    "EB3-U2-2.8-Q9": ["2.5"],
    "EB3-U2-2.9-Q1": ["2.5"],
    "EB3-U2-2.9-Q2": ["2.5"],
    "EB3-U2-2.9-Q4": ["2.5"],
    "EB3-U2-2.9-Q7": ["2.5"],
    "EB3-U2-2.10-Q1": ["2.5"],
    "EB3-U2-2.10-Q2": ["2.7"],
    "EB3-U2-2.10-Q3": ["2.7"],
    "EB3-U2-2.10-Q4": ["2.5"],
    "EB3-U2-2.10-Q5": ["2.5"],
    "EB3-U2-2.10-Q6": ["2.5"],
    "EB3-U2-2.10-Q8": ["2.5"],

    # --- Unit 3: work and energy
    "EB3-U3-3.1-Q9": ["3.4", "4.3"],
    "EB3-U3-3.2-Q3": ["3.1"],
    "EB3-U3-3.2-Q5": ["2.8"],
    "EB3-U3-3.2-Q6": ["2.7"],
    "EB3-U3-3.2-Q7": ["2.7"],
    "EB3-U3-3.3-Q4": ["2.8"],
    "EB3-U3-3.3-Q5": ["2.8", "3.4"],
    "EB3-U3-3.3-Q6": ["2.8"],
    "EB3-U3-3.3-Q8": ["3.4"],
    "EB3-U3-3.4-Q1": ["1.5"],
    "EB3-U3-3.4-Q2": ["2.7"],
    "EB3-U3-3.4-Q6": ["2.7"],
    "EB3-U3-3.4-Q9": ["2.5"],
    "EB3-U3-3.5-Q2": ["2.5"],
    "EB3-U3-3.5-Q4": ["2.5", "2.7"],
    "EB3-U3-3.5-Q5": ["2.5"],
    "EB3-U3-3.5-Q7": ["2.4", "2.7"],

    # --- Unit 4: momentum
    "EB3-U4-4.1-Q1": ["1.1"],
    "EB3-U4-4.1-Q4": ["2.5"],
    "EB3-U4-4.1-Q5": ["3.1"],
    "EB3-U4-4.1-Q8": ["4.2"],
    "EB3-U4-4.2-Q1": ["4.1"],
    "EB3-U4-4.2-Q3": ["4.3"],
    "EB3-U4-4.2-Q5": ["4.1"],
    "EB3-U4-4.2-Q8": ["2.5", "4.1"],
    "EB3-U4-4.3-Q4": ["4.2"],
    "EB3-U4-4.3-Q5": ["2.5"],
    "EB3-U4-4.3-Q9": ["4.4"],
    "EB3-U4-4.4-Q3": ["3.3", "3.4"],
    "EB3-U4-4.4-Q5": ["3.1"],
    "EB3-U4-4.4-Q8": ["4.1"],

    # --- Unit 5: rotation
    "EB3-U5-5.1-Q5": ["5.2"],
    "EB3-U5-5.1-Q7": ["5.2"],
    "EB3-U5-5.2-Q2": ["5.1"],
    "EB3-U5-5.2-Q6": ["5.1"],
    "EB3-U5-5.2-Q9": ["5.1"],
    "EB3-U5-5.3-Q1": ["5.6"],
    "EB3-U5-5.3-Q4": ["5.6"],
    "EB3-U5-5.3-Q9": ["5.6"],
    "EB3-U5-5.4-Q4": ["5.3"],
    "EB3-U5-5.4-Q5": ["5.3"],
    "EB3-U5-5.5-Q1": ["5.3"],
    "EB3-U5-5.5-Q2": ["5.3"],
    "EB3-U5-5.5-Q4": ["5.3", "5.4"],
    "EB3-U5-5.5-Q8": ["5.3"],
    "EB3-U5-5.5-Q9": ["5.3"],
    "EB3-U5-5.6-Q4": ["5.3"],
    "EB3-U5-5.6-Q5": ["5.3", "5.4"],
    "EB3-U5-5.6-Q7": ["5.2"],
    "EB3-U5-5.6-Q8": ["5.3"],

    # --- Unit 6: rotation continued
    "EB3-U6-6.1-Q4": ["6.5", "3.4"],
    "EB3-U6-6.1-Q5": ["5.4", "6.2"],
    "EB3-U6-6.1-Q7": ["6.5"],
    "EB3-U6-6.1-Q8": ["6.5"],
    "EB3-U6-6.2-Q1": ["5.1"],
    "EB3-U6-6.2-Q3": ["5.4"],
    "EB3-U6-6.2-Q5": ["5.4"],
    "EB3-U6-6.2-Q8": ["5.1"],
    "EB3-U6-6.3-Q2": ["6.4"],
    "EB3-U6-6.3-Q5": ["5.4"],
    "EB3-U6-6.3-Q7": ["5.4"],
    "EB3-U6-6.4-Q2": ["5.4"],
    "EB3-U6-6.4-Q4": ["6.5"],
    "EB3-U6-6.4-Q5": ["6.3"],
    "EB3-U6-6.4-Q8": ["5.3"],
    "EB3-U6-6.5-Q1": ["5.4"],
    "EB3-U6-6.5-Q3": ["2.7", "5.6"],
    "EB3-U6-6.5-Q4": ["5.4"],
    "EB3-U6-6.5-Q8": ["2.7"],
    "EB3-U6-6.6-Q1": ["2.6"],
    "EB3-U6-6.6-Q2": ["2.6", "6.4"],
    "EB3-U6-6.6-Q3": ["2.6", "3.4"],
    "EB3-U6-6.6-Q4": ["2.6"],
    "EB3-U6-6.6-Q5": ["2.6"],
    "EB3-U6-6.6-Q6": ["2.6"],
    "EB3-U6-6.6-Q7": ["2.6", "6.4"],
    "EB3-U6-6.6-Q8": ["2.6", "6.4"],
    "EB3-U6-6.6-Q9": ["2.6", "6.4"],

    # --- Unit 7: oscillations
    "EB3-U7-7.1-Q1": ["2.8"],
    "EB3-U7-7.1-Q2": ["2.8"],
    "EB3-U7-7.1-Q3": ["2.8"],
    "EB3-U7-7.1-Q5": ["2.6"],
    "EB3-U7-7.1-Q7": ["2.8", "3.4"],
    "EB3-U7-7.1-Q9": ["2.4", "2.8"],
    "EB3-U7-7.2-Q2": ["2.8"],
    "EB3-U7-7.2-Q3": ["2.8"],
    "EB3-U7-7.2-Q5": ["2.8"],
    "EB3-U7-7.2-Q7": ["2.8"],
    "EB3-U7-7.2-Q9": ["2.8"],
    "EB3-U7-7.3-Q1": ["2.8"],
    "EB3-U7-7.3-Q3": ["2.8"],
    "EB3-U7-7.3-Q4": ["2.8"],
    "EB3-U7-7.3-Q6": ["2.8"],
    "EB3-U7-7.3-Q9": ["2.8"],
    "EB3-U7-7.4-Q1": ["4.3"],
    "EB3-U7-7.4-Q2": ["3.4"],
    "EB3-U7-7.4-Q3": ["3.4"],
    "EB3-U7-7.4-Q4": ["3.1"],
    "EB3-U7-7.4-Q7": ["3.4"],
    "EB3-U7-7.4-Q8": ["2.6"],
    "EB3-U7-7.5-Q2": ["5.4"],
    "EB3-U7-7.5-Q3": ["5.4"],
    "EB3-U7-7.5-Q4": ["5.4"],
    "EB3-U7-7.5-Q5": ["5.4"],
    "EB3-U7-7.5-Q6": ["5.4", "5.6"],
    "EB3-U7-7.5-Q7": ["5.3", "5.4"],
    "EB3-U7-7.5-Q9": ["5.4"],
}


def sort_key(topic: str) -> tuple:
    """Chapter order: unit first, then numeric topic, so 2.10 follows 2.9."""
    major, _, minor = str(topic).partition(".")
    try:
        return (int(major), int(minor or 0))
    except ValueError:
        return (99, 99)


def main() -> int:
    data = json.loads(BANK.read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in data["questions"]}

    missing = [qid for qid in EXTRA if qid not in by_id]
    if missing:
        raise SystemExit(f"unknown ids: {missing[:5]}")

    touched = 0
    for qid, extras in EXTRA.items():
        q = by_id[qid]
        primary = q["topic"]
        cleaned = sorted({t for t in extras if t != primary}, key=sort_key)
        if q.get("additional_topics") != cleaned:
            q["additional_topics"] = cleaned
            touched += 1

    BANK.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(1 for q in data["questions"] if q.get("additional_topics"))
    print(f"assigned multi-block topics to {total} questions ({touched} changed)")
    multi = [q for q in data["questions"] if len(q.get("additional_topics") or []) > 1]
    print(f"questions with more than one extra block: {len(multi)}")
    for q in multi[:5]:
        print(f"  {q['id']}: {q['topic']} + {q['additional_topics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
