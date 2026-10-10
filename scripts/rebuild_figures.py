"""Re-attribute every figure in the bank from the geometry plan.

The plan (``scripts/figure_plan.json``, produced by ``plan_figures.py``) records,
for each question and each figure in the original PDF, where that figure belongs:

    header   -> above the stem, on its own line (number stays on the stem line)
    trailing -> below the stem (rare: an unlabelled illustration at the end)
    option   -> inside one specific choice (letter in ``opt``)

This script:

  1. strips every pre-existing ``\\includegraphics`` token from stem / choices /
     solution (the old tokens were mis-attributed, some duplicated);
  2. re-crops each figure straight from the PDF at the plan's bbox, so the file
     is named for its true owner and its content is guaranteed correct;
  3. re-inserts the tokens: header -> top of stem, trailing -> bottom of stem,
     option -> the matching choice's text;
  4. keeps ``images`` (the sidebar metadata) in sync.

The crop resolution is 3x (~216 dpi) so the figures stay legible in print.
"""

from __future__ import annotations

import json
import os
import re
import shutil

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "data", "bank.json")
MEDIA = os.path.join(ROOT, "data", "media")
PLAN = os.path.join(ROOT, "scripts", "figure_plan.json")
PDF = ("D:/OneDrive/WHBC/AP/APPCM/Exercises/2026-2027/Exercise Book 2026-2027/"
       "AP Physics C Mechanics Exercise Book 3 Topic Questions 2026-2027.pdf")

TEXT_W = 491.6          # A4 minus the 0.72in margins in latex.py
ZOOM = 3.0              # crop resolution (~216 dpi)

RE_IMG_TOKEN = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")


def topic_tag(topic: str) -> str:
    """'1.1' -> '11', '2.10' -> '210'."""
    return re.sub(r"[^0-9]", "", str(topic))


def width_frac(bbox) -> float:
    w = (bbox[2] - bbox[0]) / TEXT_W
    # keep the printed proportions but never let a figure exceed the text block
    return max(0.20, min(0.92, round(w, 2)))


def crop(doc, page_no, rec, out_path):
    pg = doc[page_no - 1]
    r = pymupdf.Rect(rec["x0"], rec["y"], rec["x1"], rec["y"] + (rec.get("h") or 0))
    if not rec.get("h"):
        # older plans carry no height: recover it from the page image that holds
        # this bbox (vector figures are cropped by the same rect either way)
        r = pymupdf.Rect(rec["x0"], rec["y"], rec["x1"], rec["y"] + 1)
        for info in pg.get_image_info():
            bb = pymupdf.Rect(info["bbox"])
            if abs(bb.y0 - rec["y"]) < 2 and abs(bb.x0 - rec["x0"]) < 2:
                r = bb
                break
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=r)
    pix.save(out_path)
    return pix.width, pix.height


def main():
    import sys
    topic_filter = None
    dry = False
    out_media = MEDIA
    for a in sys.argv[1:]:
        if a.startswith("--topic="):
            topic_filter = a.split("=", 1)[1]
        elif a == "--dry":
            dry = True

    bank = json.load(open(BANK, encoding="utf-8"))
    qs = bank["questions"]
    if topic_filter:
        qs = [q for q in qs if q.get("topic") == topic_filter]
    plan = {p["id"]: p for p in json.load(open(PLAN, encoding="utf-8"))}
    doc = pymupdf.open(PDF)

    if dry:
        out_media = os.path.join(ROOT, "outputs", "_dryrun_media")
    if not os.path.isdir(out_media):
        os.makedirs(out_media)

    # the plan has no height; read each page's raster images once so we can crop
    # accurately (vector figures fall back to the tiny-rect path in crop())
    for p in plan.values():
        for f in p.get("figures", []):
            if "h" in f:
                continue
            pg = doc[p["page"] - 1]
            for info in pg.get_image_info():
                bb = pymupdf.Rect(info["bbox"])
                if abs(bb.y0 - f["y"]) < 2 and abs(bb.x0 - f["x0"]) < 2:
                    f["h"] = round(bb.height, 1)
                    break

    made = 0
    for q in qs:
        qid = q["id"]
        rec = plan.get(qid)
        figs = (rec or {}).get("figures", [])

        # 1. strip old tokens everywhere
        stem = RE_IMG_TOKEN.sub("", q.get("stem") or "").strip()
        choices = q.get("choices") or []
        for ch in choices:
            ch["text"] = RE_IMG_TOKEN.sub("", ch.get("text") or "").strip()

        ut = f"u{q.get('unit', 0)}_{topic_tag(q.get('topic', ''))}_q{q.get('number', 0)}"
        seq = 0
        images_meta = []

        headers, trails, opts = [], [], {}
        for f in figs:
            seq += 1
            fn = f"{ut}_{seq}.png"
            path = os.path.join(out_media, fn)
            crop(doc, rec["page"], f, path)
            made += 1
            wf = width_frac((f["x0"], f["y"], f["x1"], f["y"]))
            rel = f"media/{fn}"
            images_meta.append({"file": fn, "rel": rel, "width": wf})
            if f["kind"] == "header":
                headers.append((wf, rel))
            elif f["kind"] == "trailing":
                trails.append((wf, rel))
            else:
                opts.setdefault(f.get("opt") or "A", []).append((wf, rel))

        # 2. header figures: one per line, above the stem
        if headers:
            head_lines = "\n".join(
                f"\\includegraphics[width={w:.2f}\\linewidth]{{{r}}}" for w, r in headers)
            stem = head_lines + "\n\n" + stem

        # 3. option figures: appended to the matching choice
        for ch in choices:
            lab = (ch.get("label") or "").strip().upper()
            for w, r in opts.get(lab, []):
                tok = f"\\includegraphics[width={w:.2f}\\linewidth]{{{r}}}"
                ch["text"] = (ch["text"] + " " + tok).strip() if ch["text"] else tok

        # 4. trailing figures: below the stem
        if trails:
            tail = "\n".join(
                f"\\includegraphics[width={w:.2f}\\linewidth]{{{r}}}" for w, r in trails)
            stem = stem + "\n\n" + tail

        q["stem"] = stem
        q["images"] = images_meta

    if dry:
        json.dump(bank, open(os.path.join(ROOT, "outputs", "_dryrun_bank.json"),
                             "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"[dry] cropped {made} figures into {out_media}")
        return

    json.dump(bank, open(BANK, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"wrote {BANK}; cropped {made} figures into {out_media}")


if __name__ == "__main__":
    main()
