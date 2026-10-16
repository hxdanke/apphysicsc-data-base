"""Add (or remove) one tag on every question in a course.

Bulk edits to the bank are the easiest way to lose an afternoon, so this runs
dry by default: it prints what would change and touches nothing until you pass
``--apply``, and even then it leaves a ``.bak`` beside the bank.

Examples
    python scripts/tag_all.py --course apc-mech --tag "Topic Questions"
    python scripts/tag_all.py --course apc-mech --tag "Topic Questions" --apply
    python scripts/tag_all.py --course apc-mech --tag "Topic Questions" --remove --apply
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import bank as bank_mod  # noqa: E402
from server import courses as courses_mod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", default=courses_mod.DEFAULT_COURSE_ID,
                        help="course id, e.g. apc-mech / apc-em / ap1 / ap2")
    parser.add_argument("--tag", required=True, help="the tag to add or remove")
    parser.add_argument("--remove", action="store_true",
                        help="remove the tag instead of adding it")
    parser.add_argument("--apply", action="store_true",
                        help="write the bank (default is a dry run)")
    args = parser.parse_args()

    course = courses_mod.get(args.course)
    tag = args.tag.strip()
    if not tag:
        raise SystemExit("--tag cannot be empty")

    data = bank_mod.load_bank(course.id)
    questions = data.get("questions") or []
    print(f"course : {course.id} ({course.title})")
    print(f"bank   : {course.bank}")
    print(f"tag    : {tag!r} ({'remove' if args.remove else 'add'})")
    print(f"questions: {len(questions)}")

    changed = 0
    for question in questions:
        tags = bank_mod.clean_tags(question.get("tags"))
        has = any(existing.casefold() == tag.casefold() for existing in tags)
        if args.remove:
            if not has:
                continue
            kept = [t for t in tags if t.casefold() != tag.casefold()]
        else:
            if has:
                continue
            kept = [*tags, tag]
        question["tags"] = bank_mod.clean_tags(kept)
        changed += 1

    print(f"would change: {changed} question(s)")
    print(f"already correct: {len(questions) - changed}")

    if not args.apply:
        print("\nDry run — nothing was written. Re-run with --apply.")
        return 0

    path = course.path(course.bank)
    shutil.copy(path, path + ".bak")
    bank_mod.save_bank(data, course.id)
    print(f"\nApplied. Backup: {path}.bak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
