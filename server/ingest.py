"""
Ingestion pipeline: PDF -> draft questions -> (optional AI polish) -> review -> bank.

Flow
  1. POST /api/ingest          saves the upload, runs the deterministic extractor
  2. GET  /api/ingest/<job>    returns the draft for human review
  3. POST /api/ingest/<job>/polish   (optional) runs the AI LaTeX polish
  4. POST /api/ingest/<job>/commit   merges into data/bank.json
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid

from . import ai as ai_mod
from . import bank as bank_mod
from . import extract as extract_mod

INGEST_DIR = os.path.join(bank_mod.ROOT, "ingest")


def _job_dir(job: str) -> str:
    return os.path.join(INGEST_DIR, job)


def _write_meta(job: str, meta: dict) -> None:
    with open(os.path.join(_job_dir(job), "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def read_meta(job: str) -> dict:
    path = os.path.join(_job_dir(job), "meta.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_jobs() -> list:
    if not os.path.isdir(INGEST_DIR):
        return []
    jobs = []
    for name in sorted(os.listdir(INGEST_DIR)):
        meta = read_meta(name)
        if meta:
            jobs.append(meta)
    return jobs


def start(pdf_path: str, doc_id: str | None = None, dpi: int = 300) -> dict:
    os.makedirs(INGEST_DIR, exist_ok=True)
    job = uuid.uuid4().hex[:12]
    d = _job_dir(job)
    media = os.path.join(d, "media")
    os.makedirs(media, exist_ok=True)
    stored = os.path.join(d, "source.pdf")
    shutil.copy(pdf_path, stored)

    doc_id = doc_id or ("DOC-" + job[:6].upper())
    questions = extract_mod.extract_pdf(stored, media, doc_id, dpi=dpi)
    draft = os.path.join(d, "draft.json")
    with open(draft, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=1)

    meta = {
        "job": job,
        "doc_id": doc_id,
        "filename": os.path.basename(pdf_path),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(questions),
        "dpi": dpi,
        "media": os.path.relpath(media, bank_mod.ROOT).replace("\\", "/"),
        "polished": False,
        "committed": False,
        "stage": "draft",
        "fingerprint": extract_mod.file_fingerprint(stored),
    }
    _write_meta(job, meta)
    return meta


def load_questions(job: str) -> list:
    path = os.path.join(_job_dir(job), "draft.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_questions(job: str, questions: list) -> None:
    with open(os.path.join(_job_dir(job), "draft.json"), "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=1)


def polish(job: str, limit: int | None = None) -> dict:
    meta = read_meta(job)
    if not meta:
        return {"ok": False, "error": "unknown job"}
    if not ai_mod.enabled():
        return {"ok": False, "error": "AI_API_KEY is not configured - draft left unchanged"}
    qs = load_questions(job)
    qs = ai_mod.polish_batch(qs, limit)
    save_questions(job, qs)
    meta["polished"] = True
    meta["stage"] = "review"
    _write_meta(job, meta)
    return {"ok": True, "count": len(qs)}


def commit(job: str, replace_source: bool = True) -> dict:
    meta = read_meta(job)
    if not meta:
        return {"ok": False, "error": "unknown job"}
    if meta.get("committed"):
        return {"ok": False, "error": "already committed"}

    qs = load_questions(job)
    if not qs:
        return {"ok": False, "error": "nothing to commit"}

    # move figures into the shared media folder
    src_media = os.path.join(bank_mod.ROOT, meta["media"])
    os.makedirs(bank_mod.MEDIA_DIR, exist_ok=True)
    moved = 0
    for q in qs:
        for im in q.get("images", []):
            src = os.path.join(bank_mod.ROOT, im["rel"])
            if not os.path.exists(src):
                alt = os.path.join(src_media, im["file"])
                if os.path.exists(alt):
                    src = alt
                else:
                    continue
            dst = os.path.join(bank_mod.MEDIA_DIR, im["file"])
            if src != dst:
                shutil.copy(src, dst)
                moved += 1
            im["rel"] = "media/" + im["file"]
        # rewrite include paths inside the LaTeX bodies
        for im in q.get("images", []):
            old = os.path.dirname(im["rel"])  # legacy per-job folder
            for field in ("stem", "solution"):
                if q.get(field):
                    q[field] = q[field].replace(im["file"], im["file"])
            for c in q.get("choices", []):
                if c.get("text"):
                    c["text"] = re_include_path(c["text"], im["file"])
            if q.get("stem"):
                q["stem"] = re_include_path(q["stem"], im["file"])

    bank = bank_mod.load_bank()
    written = bank_mod.upsert(bank, qs, replace_source=meta["doc_id"] if replace_source else None)
    meta["committed"] = True
    meta["stage"] = "committed"
    meta["committed_count"] = written
    _write_meta(job, meta)
    return {"ok": True, "count": written, "figures": moved}


import re  # noqa: E402  (kept at the bottom so the helper reads naturally next to commit)

RE_INC = re.compile(r"\\includegraphics\s*(\[[^\]]*\])?\s*\{[^{}]*?([^/{}\\]+)\}")


def re_include_path(text: str, filename: str) -> str:
    """Rewrite any \\includegraphics path so that it points at media/<filename>."""
    return RE_INC.sub(
        lambda m: "\\includegraphics" + (m.group(1) or "") + "{media/" + m.group(2) + "}"
        if m.group(2) == filename else m.group(0),
        text,
    )


def discard(job: str) -> bool:
    d = _job_dir(job)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False
