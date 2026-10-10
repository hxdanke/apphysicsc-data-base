#!/usr/bin/env python
"""Seed data/bank.json from an exercise-book PDF (offline equivalent of the import UI).

    python scripts/seed_from_pdf.py path/to/book.pdf --doc-id EB3 [--dpi 300]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from server import bank as bank_mod          # noqa: E402
from server import extract as extract_mod    # noqa: E402
from texfix import repair                    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("--doc-id", default=None, help="short document id, e.g. EB3")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--replace", action="store_true",
                    help="drop existing questions coming from the same document first")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        print("no such file:", args.pdf)
        return 2

    doc_id = args.doc_id or os.path.splitext(os.path.basename(args.pdf))[0][:24]
    print(f"extracting {args.pdf} as {doc_id} @ {args.dpi} dpi")
    questions = extract_mod.extract_pdf(
        args.pdf, bank_mod.MEDIA_DIR, doc_id, dpi=args.dpi,
        progress=lambda i, n: print(f"  page {i}/{n}", end="\r", flush=True))
    print(f"\n  {len(questions)} questions, "
          f"{sum(len(q['images']) for q in questions)} figures")

    # figures live directly in data/media, make sure the LaTeX points there
    for q in questions:
        for im in q["images"]:
            im["rel"] = "media/" + im["file"]
        # same repairs the web UI applies after an upload: split glued macros,
        # rebuild stacked fractions, keep quantities italic and units upright
        q["stem"] = repair(q.get("stem") or "")
        for c in q.get("choices") or []:
            c["text"] = repair(c.get("text") or "")

    if args.dry_run:
        for q in questions[:3]:
            print("\n---", q["id"], q["topic"], q["topic_title"])
            print(q["stem"][:400])
        return 0

    if args.replace:
        bank = bank_mod.load_bank()
        bank["questions"] = [q for q in bank["questions"]
                             if (q.get("source") or {}).get("doc") != doc_id]
        bank_mod.save_bank(bank)

    bank = bank_mod.load_bank()
    written = bank_mod.upsert(bank, questions)
    tax = bank_mod.load_taxonomy()
    bank_mod.save_taxonomy(tax)
    print(f"wrote {written} questions to {bank_mod.BANK_PATH}")
    print(json.dumps(bank_mod.stats(bank), indent=2)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
