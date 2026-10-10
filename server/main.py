"""FastAPI backend for the AP Physics C: Mechanics question bank."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:  # pragma: no cover - dotenv is optional
    pass

from server import ai as ai_mod          # noqa: E402
from server import bank as bank_mod      # noqa: E402
from server import ingest as ingest_mod  # noqa: E402
from server import latex as latex_mod    # noqa: E402

ROOT = bank_mod.ROOT
WEB_DIR = os.path.join(ROOT, "web")
EXPORT_DIR = bank_mod.EXPORT_DIR
os.makedirs(EXPORT_DIR, exist_ok=True)

app = FastAPI(title="AP Physics C Mechanics Question Bank", version="0.1.0")


# --------------------------------------------------------------------------------------
# bank reads
# --------------------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "engine": latex_mod.find_engine(),
        "ai_enabled": ai_mod.enabled(),
        "bank": bank_mod.stats(bank_mod.load_bank()),
    }


@app.get("/api/taxonomy")
def taxonomy():
    bank = bank_mod.load_bank()
    counts: dict = {}
    for q in bank["questions"]:
        counts[f"{q.get('unit')}|{q.get('topic')}"] = \
            counts.get(f"{q.get('unit')}|{q.get('topic')}", 0) + 1
    tax = bank_mod.load_taxonomy()
    for u in tax["units"]:
        u["count"] = sum(v for k, v in counts.items() if k.startswith(f"{u['id']}|"))
        for t in u["topics"]:
            t["count"] = counts.get(f"{u['id']}|{t['id']}", 0)
    return tax


@app.get("/api/stats")
def stats():
    return bank_mod.stats(bank_mod.load_bank())


@app.get("/api/questions")
def list_questions(q: str = "", unit: Optional[int] = None, topic: str = "",
                   qtype: str = "", needs_review: bool = False, untagged: bool = False,
                   limit: int = Query(300, le=2000)):
    bank = bank_mod.load_bank()
    items = bank_mod.search(bank, q, unit, topic or None, qtype or None,
                            needs_review or None, untagged or None, limit)
    return {"total": len(items), "questions": items}


@app.get("/api/questions/{qid}")
def get_question(qid: str):
    bank = bank_mod.load_bank()
    for item in bank["questions"]:
        if item["id"] == qid:
            return item
    raise HTTPException(404, "question not found")


@app.get("/api/questions/{qid}/tex")
def get_question_tex(qid: str):
    bank = bank_mod.load_bank()
    for item in bank["questions"]:
        if item["id"] == qid:
            return PlainTextResponse(latex_mod.question_tex(item))
    raise HTTPException(404, "question not found")


class PatchBody(BaseModel):
    stem: Optional[str] = None
    choices: Optional[list] = None
    answer: Optional[str] = None
    solution: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[list] = None
    topic: Optional[str] = None
    unit: Optional[int] = None
    needs_review: Optional[bool] = None


class ValidateBody(BaseModel):
    field: str
    value: Any


_EDITABLE_FIELDS = {"stem", "choices", "answer", "solution"}


def _tail(log: str, n: int = 1600) -> str:
    if not log:
        return ""
    return log if len(log) <= n else "...\n" + log[-n:]


# tectonic still emits a PDF when it hits a non-fatal error, so "a PDF was
# produced" is not enough.  These markers are genuine TeX/LaTeX errors in the
# controlled preamble we use, and mean the edit must not be kept.
def _log_has_errors(log: str) -> bool:
    """Return True when `log` contains a genuine TeX/LaTeX build error.

    tectonic still emits a PDF when it hits a non-fatal error, so "a PDF was
    produced" is not enough on its own.  tectonic reports real errors as
    "error: <file>:<line>: <msg>"; other engines prefix them with "! ".
    """
    if not log:
        return False
    for line in log.splitlines():
        s = line.strip()
        if s.startswith("error:"):
            return True
        if s.startswith("!") and any(m in s for m in (
            "Undefined control sequence", "LaTeX Error", "Emergency stop",
            "Missing $ inserted", "Missing } inserted", "Extra }, or forgotten",
            "Too many }", "File ended", "Runaway argument", "Illegal unit",
            "Improper alphabetic", "Undefined sequence",
        )):
            return True
    return any(m in log for m in (
        "Undefined control sequence", "LaTeX Error:", "Emergency stop",
        "Missing $ inserted", "Runaway argument",
    ))


@app.post("/api/questions/{qid}/validate")
def validate_question(qid: str, body: ValidateBody):
    """Compile a draft of the question with one field replaced.

    Returns {"ok": bool, "log": str}.  Nothing is saved -- this only checks that
    the edited LaTeX still builds through the real TeX engine.
    """
    if body.field not in _EDITABLE_FIELDS:
        raise HTTPException(400, f"cannot validate field '{body.field}'")
    bank = bank_mod.load_bank()
    item = next((q for q in bank["questions"] if q["id"] == qid), None)
    if item is None:
        raise HTTPException(404, "question not found")
    import copy
    draft = copy.deepcopy(item)
    draft[body.field] = body.value
    tex = latex_mod.question_tex(draft)
    res = latex_mod.compile_pdf(tex)
    if not res.get("ok") or _log_has_errors(res.get("log", "")):
        return {"ok": False, "log": _tail(res.get("log", ""))}
    return {"ok": True, "log": ""}


@app.patch("/api/questions/{qid}")
def patch_question(qid: str, body: PatchBody):
    bank = bank_mod.load_bank()
    for item in bank["questions"]:
        if item["id"] == qid:
            for field, value in body.model_dump(exclude_unset=True).items():
                item[field] = value
            bank_mod.save_bank(bank)
            return item
    raise HTTPException(404, "question not found")


@app.delete("/api/questions/{qid}")
def remove_question(qid: str):
    bank = bank_mod.load_bank()
    if not bank_mod.delete_question(bank, qid):
        raise HTTPException(404, "question not found")
    return {"ok": True}


# --------------------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------------------

class ExportBody(BaseModel):
    ids: list = []
    title: str = "AP Physics C: Mechanics Practice Set"
    subtitle: str = ""
    show_answer: bool = False
    show_solution: bool = False
    group_by_topic: bool = True
    instructions: str = ""
    filename: str = "practice-set"


def _collect(ids: list) -> list:
    bank = bank_mod.load_bank()
    if not ids:
        return bank["questions"]
    wanted = set(ids)
    return [q for q in bank["questions"] if q["id"] in wanted]


@app.post("/api/export/latex")
def export_latex(body: ExportBody):
    qs = _collect(body.ids)
    if not qs:
        raise HTTPException(400, "no questions selected")
    tex = latex_mod.build_document(
        qs, body.title, body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    path = os.path.join(EXPORT_DIR, body.filename + ".tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tex)
    return {"tex": tex, "path": path, "count": len(qs)}


@app.post("/api/export/latex/file")
def export_latex_file(body: ExportBody):
    qs = _collect(body.ids)
    if not qs:
        raise HTTPException(400, "no questions selected")
    tex = latex_mod.build_document(
        qs, body.title, body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    path = os.path.join(EXPORT_DIR, body.filename + ".tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tex)
    return FileResponse(path, filename=body.filename + ".tex", media_type="application/x-tex")


@app.post("/api/export/pdf")
def export_pdf(body: ExportBody):
    qs = _collect(body.ids)
    if not qs:
        raise HTTPException(400, "no questions selected")
    tex = latex_mod.build_document(
        qs, body.title, body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    res = latex_mod.compile_pdf(tex, jobname=body.filename)
    if not res["ok"]:
        return JSONResponse({"ok": False, "log": res["log"]}, status_code=501)
    out = os.path.join(EXPORT_DIR, body.filename + ".pdf")
    with open(res["pdf"], "rb") as src, open(out, "wb") as dst:
        dst.write(src.read())
    return FileResponse(out, filename=body.filename + ".pdf",
                        media_type="application/pdf")


@app.get("/api/engine")
def engine():
    return {"engine": latex_mod.find_engine()}


# --------------------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------------------

@app.post("/api/ingest")
async def ingest_upload(file: UploadFile = File(...), doc_id: str = "", dpi: int = 300):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF files are accepted")
    tmp = os.path.join(EXPORT_DIR, "upload-" + os.urandom(4).hex() + ".pdf")
    with open(tmp, "wb") as f:
        f.write(await file.read())
    try:
        meta = ingest_mod.start(tmp, doc_id or None, dpi=dpi)
    finally:
        os.unlink(tmp)
    return meta


@app.get("/api/ingest")
def ingest_list():
    return {"jobs": ingest_mod.list_jobs()}


@app.get("/api/ingest/{job}")
def ingest_get(job: str):
    meta = ingest_mod.read_meta(job)
    if not meta:
        raise HTTPException(404, "job not found")
    return {"meta": meta, "questions": ingest_mod.load_questions(job)}


@app.post("/api/ingest/{job}/polish")
def ingest_polish(job: str, limit: Optional[int] = None):
    res = ingest_mod.polish(job, limit)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)
    return res


@app.post("/api/ingest/{job}/commit")
def ingest_commit(job: str, replace_source: bool = True):
    res = ingest_mod.commit(job, replace_source)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)
    return res


@app.delete("/api/ingest/{job}")
def ingest_delete(job: str):
    return {"ok": ingest_mod.discard(job)}


@app.get("/api/file")
def serve_file(path: str):
    """Serve a figure by repo-relative path (draft media lives under ingest/)."""
    rel = path.lstrip("/").replace("..", "")
    full = os.path.normpath(os.path.join(ROOT, rel))
    if not full.startswith(ROOT):
        raise HTTPException(403, "outside repository")
    if not os.path.exists(full):
        raise HTTPException(404, "file not found")
    return FileResponse(full)


# --------------------------------------------------------------------------------------
# static
# --------------------------------------------------------------------------------------

class NoCacheStatic(StaticFiles):
    """StaticFiles that forbids caching, so a code change is picked up on the
    next page load instead of serving a stale JS/CSS module from disk cache.
    Without this, the SPA's ES modules can stay cached after an edit and the
    UI silently shows the old version."""

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/media", StaticFiles(directory=bank_mod.MEDIA_DIR, check_dir=False), name="media")
if os.path.isdir(WEB_DIR):
    app.mount("/", NoCacheStatic(directory=WEB_DIR, html=True), name="web")
