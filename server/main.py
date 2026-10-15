"""FastAPI backend for the AP Physics C: Mechanics question bank."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:  # pragma: no cover - dotenv is optional
    pass

from server import ai as ai_mod          # noqa: E402
from server import appapi as appapi_mod  # noqa: E402
from server import appdb as appdb_mod    # noqa: E402
from server import auth as auth_mod      # noqa: E402
from server import bank as bank_mod      # noqa: E402
from server import blocks as blocks_mod  # noqa: E402
from server import courses as courses_mod  # noqa: E402
from server import ingest as ingest_mod  # noqa: E402
from server import latex as latex_mod    # noqa: E402
from server import recycle as recycle_mod  # noqa: E402


def _record_activity(request, user, action, entity_id, summary, metadata=None):
    """Append one row to the activity log; never let logging break a request."""
    try:
        appdb_mod.record_activity(
            auth_mod.app_db_path(), user=user, action=action,
            entity_type="paper", entity_id=entity_id, summary=summary,
            metadata=metadata or {})
    except Exception:  # noqa: BLE001 - logging must never fail a request
        pass

ROOT = bank_mod.ROOT
WEB_DIR = os.path.join(ROOT, "web")
EXPORT_DIR = bank_mod.EXPORT_DIR
os.makedirs(EXPORT_DIR, exist_ok=True)

app = FastAPI(title="AP Physics C Mechanics Question Bank", version="0.1.0")


@app.middleware("http")
async def require_session_for_api(request, call_next):
    """Protect every API route except sign-in, the health probe and logout.

    The single-page app itself stays public so the sign-in screen can load.
    """
    path = request.url.path
    if path.startswith("/api/") and path not in auth_mod.PUBLIC_API_PATHS \
            and auth_mod.login_required():
        if auth_mod.user_for_request(request) is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Login required"}, status_code=401)
    return await call_next(request)


app.include_router(appapi_mod.router)


@app.exception_handler(StarletteHTTPException)
async def flat_http_errors(request, exc):
    """Return errors as a flat ``{"error": ..., "code": ...}`` body.

    FastAPI would otherwise wrap a structured detail in ``{"detail": {...}}``,
    which makes the browser unwrap two shapes.  One flat shape keeps the UI
    simple and gives every failure the same contract.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        body = detail
    else:
        body = {"error": str(detail)}
    return JSONResponse(body, status_code=exc.status_code)


# --------------------------------------------------------------------------------------
# bank reads
# --------------------------------------------------------------------------------------

@app.get("/api/courses")
def list_courses():
    """Everything the course switcher needs."""
    return {
        "courses": courses_mod.summary(),
        "default": courses_mod.DEFAULT_COURSE_ID,
    }


@app.get("/api/health")
def health(course: str = ""):
    return {
        "ok": True,
        "engine": latex_mod.find_engine(),
        "ai_enabled": ai_mod.enabled(),
        "course": courses_mod.get(course).id,
        "bank": bank_mod.stats(bank_mod.load_bank(course)),
    }


def _topic_counts(bank: dict, course_id: str) -> dict:
    """How many questions touch each topic -- primary *and* additional."""
    counts: dict = {}
    for q in bank["questions"]:
        for topic in bank_mod.topics_of(q):
            unit, _ = bank_mod.resolve_topic(topic, course_id)
            if not unit:
                unit = q.get("unit")
            key = f"{unit}|{topic}"
            counts[key] = counts.get(key, 0) + 1
    return counts


@app.get("/api/taxonomy")
def taxonomy(course: str = ""):
    bank = bank_mod.load_bank(course)
    counts = _topic_counts(bank, courses_mod.get(course).id)
    tax = bank_mod.load_taxonomy(course)
    for u in tax["units"]:
        u["count"] = sum(v for k, v in counts.items() if k.startswith(f"{u['id']}|"))
        for t in u["topics"]:
            t["count"] = counts.get(f"{u['id']}|{t['id']}", 0)
    return tax


@app.get("/api/stats")
def stats(course: str = ""):
    return bank_mod.stats(bank_mod.load_bank(course))


@app.get("/api/questions")
def list_questions(q: str = "", unit: Optional[int] = None, topic: str = "",
                   qtype: str = "", needs_review: bool = False, untagged: bool = False,
                   limit: int = Query(300, le=2000), course: str = ""):
    bank = bank_mod.load_bank(course)
    items = bank_mod.search(bank, q, unit, topic or None, qtype or None,
                            needs_review or None, untagged or None, limit,
                            course_id=courses_mod.get(course).id)
    return {"total": len(items), "questions": items,
            "course": courses_mod.get(course).id}


@app.get("/api/questions/{qid}")
def get_question(qid: str, course: str = ""):
    bank = bank_mod.load_bank(course)
    for item in bank["questions"]:
        if item["id"] == qid:
            return item
    raise HTTPException(404, "question not found")


@app.get("/api/questions/{qid}/tex")
def get_question_tex(qid: str, course: str = ""):
    bank = bank_mod.load_bank(course)
    for item in bank["questions"]:
        if item["id"] == qid:
            return PlainTextResponse(latex_mod.question_tex(item))
    raise HTTPException(404, "question not found")


class PatchBody(BaseModel):
    stem: Optional[str] = None
    stem_blocks: Optional[list] = None
    choices: Optional[list] = None
    answer: Optional[str] = None
    solution: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[list] = None
    topic: Optional[str] = None
    additional_topics: Optional[list] = None
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
def validate_question(qid: str, body: ValidateBody, course: str = ""):
    """Compile a draft of the question with one field replaced.

    Returns {"ok": bool, "log": str}.  Nothing is saved -- this only checks that
    the edited LaTeX still builds through the real TeX engine.
    """
    if body.field not in _EDITABLE_FIELDS:
        raise HTTPException(400, f"cannot validate field '{body.field}'")
    bank = bank_mod.load_bank(course)
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


class PreviewBody(BaseModel):
    """A whole question being edited, for the live preview gate."""
    stem: str = ""
    choices: list = []
    answer: str = ""
    solution: str = ""
    course: str = ""


@app.post("/api/questions/preview")
def preview_question(body: PreviewBody):
    """Does this question build through the real TeX engine?

    The editor calls this once typing settles.  It answers the same question the
    old save-time validation did, but without making the teacher wait: the draft
    is already on screen, and a failure simply means there is nothing to show.
    """
    draft = {
        "id": "preview",
        "unit": 0, "unit_title": "", "topic": "", "topic_title": "",
        "number": 1, "qtype": "mcq",
        "stem": body.stem or "",
        "choices": body.choices or [],
        "answer": body.answer or "",
        "solution": body.solution or "",
        "images": [], "difficulty": "", "tags": [],
        "source": {}, "layout": "inline", "needs_review": False,
    }
    # An empty editor is not a syntax error.  TeX emits no page at all for an
    # empty body and the engine reports that as a failure, so check first --
    # otherwise clearing the textarea would look like broken LaTeX.
    has_content = any([
        (draft["stem"] or "").strip(),
        draft["choices"],
        (body.answer or "").strip(),
        (body.solution or "").strip(),
    ])
    if not has_content:
        return {"ok": True, "log": ""}

    tex = latex_mod.question_tex(draft)
    res = latex_mod.compile_pdf(tex)
    log = res.get("log") or ""
    ok = bool(res.get("ok")) and not _log_has_errors(log)
    return {"ok": ok, "log": "" if ok else _tail(log, 1200)}


def _clean_topic_list(values, course_id: str) -> list:
    """Keep only topic ids that exist in this course's taxonomy, order intact."""
    out = []
    for raw in values or ():
        text = str(raw).strip()
        if not text or text in out:
            continue
        unit, _ = bank_mod.resolve_topic(text, course_id)
        if unit:
            out.append(text)
    return out


@app.patch("/api/questions/{qid}")
def patch_question(qid: str, body: PatchBody, course: str = ""):
    """Edit a question in place.

    ``additional_topics`` and ``stem_blocks`` are the multi-course additions: a
    question can be filed under more than one knowledge block, and a hand-written
    stem carries its blocks alongside the LaTeX derived from them.
    """
    course = courses_mod.get(course).id
    bank = bank_mod.load_bank(course)
    for item in bank["questions"]:
        if item["id"] != qid:
            continue
        fields = body.model_dump(exclude_unset=True)

        if "stem_blocks" in fields and fields["stem_blocks"] is not None:
            # The blocks are the source of truth; the LaTeX follows from them.
            blocks_mod.apply_blocks(item, fields.pop("stem_blocks"))
        elif "stem" in fields and fields["stem"] is not None:
            # Editing the LaTeX directly invalidates any block structure.
            item["stem"] = fields.pop("stem")
            item.pop("stem_blocks", None)

        if "topic" in fields and fields["topic"]:
            unit, title = bank_mod.resolve_topic(fields["topic"], course)
            if not unit:
                raise HTTPException(400, f"unknown topic '{fields['topic']}'")
            item["topic"] = fields.pop("topic")
            item["topic_title"] = title
            item["unit"] = unit
            item["unit_title"] = next(
                (u["title"] for u in bank_mod.load_taxonomy(course)["units"]
                 if u["id"] == unit), "")

        if "additional_topics" in fields and fields["additional_topics"] is not None:
            extras = _clean_topic_list(fields.pop("additional_topics"), course)
            # The primary topic is never duplicated into the additional list.
            item["additional_topics"] = [t for t in extras if t != item.get("topic")]

        if "unit" in fields and fields["unit"] is not None and "topic" not in fields:
            raise HTTPException(400, "change the topic instead of the unit directly")

        for field, value in fields.items():
            if value is not None:
                item[field] = value

        bank_mod.save_bank(bank, course)
        return item
    raise HTTPException(404, "question not found")


@app.delete("/api/questions/{qid}")
def remove_question(qid: str, course: str = ""):
    """Move a question to the recycle bin.

    Deleting is not destructive: the question keeps its whole body in the bin for
    ``recycle.RETENTION_DAYS`` days and can be restored from there.
    """
    course = courses_mod.get(course).id
    bank = bank_mod.load_bank(course)
    item = next((q for q in bank["questions"] if q["id"] == qid), None)
    if item is None:
        raise HTTPException(404, "question not found")
    entry = recycle_mod.move_to_bin(item, course)
    bank_mod.delete_question(bank, qid, course)
    return {"ok": True, "recycled": entry}


# --------------------------------------------------------------------------------------
# recycle bin
# --------------------------------------------------------------------------------------

@app.get("/api/recycle")
def recycle_list(course: str = ""):
    course_id = courses_mod.get(course).id
    return {
        "course": course_id,
        "retention_days": recycle_mod.RETENTION_DAYS,
        "items": recycle_mod.list_items(course_id),
    }


class RecycleBody(BaseModel):
    id: str


@app.post("/api/recycle/restore")
def recycle_restore(body: RecycleBody, course: str = ""):
    course_id = courses_mod.get(course).id
    question = recycle_mod.restore(body.id, course_id)
    if question is None:
        raise HTTPException(404, "question not found in the recycle bin")
    return {"ok": True, "question": question}


@app.post("/api/recycle/purge")
def recycle_purge(body: RecycleBody, course: str = ""):
    course_id = courses_mod.get(course).id
    if not recycle_mod.purge(body.id, course_id):
        raise HTTPException(404, "question not found in the recycle bin")
    return {"ok": True}


@app.post("/api/recycle/empty")
def recycle_empty(course: str = ""):
    course_id = courses_mod.get(course).id
    return {"ok": True, "removed": recycle_mod.empty(course_id)}


# --------------------------------------------------------------------------------------
# authoring a question by hand
# --------------------------------------------------------------------------------------

class AuthorBody(BaseModel):
    id: Optional[str] = None
    # Which bank this question belongs to.  The body wins over the query
    # parameter so a caller can send everything in one place.
    course: str = ""
    unit: Optional[int] = None
    topic: str = ""
    additional_topics: list = []
    number: Optional[int] = None
    qtype: str = "mcq"
    stem_blocks: list = []
    stem: Optional[str] = None
    choices: list = []
    answer: str = ""
    solution: str = ""
    difficulty: str = ""
    tags: list = []


def _apply_topics(item: dict, topic: str, extra, unit_hint, course_id: str) -> None:
    """File a question under a primary topic plus any additional blocks."""
    clean_primary = str(topic or "").strip()
    if unit_hint is not None and not clean_primary:
        raise HTTPException(400, "choose a knowledge block for the question")
    unit, title = bank_mod.resolve_topic(clean_primary, course_id)
    if not unit:
        raise HTTPException(400, f"unknown topic '{clean_primary}'")
    item["topic"] = clean_primary
    item["topic_title"] = title
    item["unit"] = unit
    item["unit_title"] = next(
        (u["title"] for u in bank_mod.load_taxonomy(course_id)["units"]
         if u["id"] == unit), "")
    item["additional_topics"] = [
        t for t in _clean_topic_list(extra, course_id) if t != clean_primary
    ]


@app.post("/api/questions")
def author_question(body: AuthorBody, course: str = ""):
    """Create a question written by hand in the app.

    The stem arrives as blocks; the LaTeX stem is derived from them so the
    question renders, exports and composes exactly like an imported one.
    """
    course_id = courses_mod.get(body.course or course).id
    bank = bank_mod.load_bank(course_id)

    qid = (body.id or "").strip()
    existing = next((q for q in bank["questions"] if q["id"] == qid), None) if qid else None
    if qid and existing is None:
        raise HTTPException(404, f"question not found: {qid}")

    if existing is not None:
        item = existing
    else:
        # The unit comes from the chosen knowledge block, so a new id reads
        # APCE-U1-1.2-Q3 rather than carrying a meaningless unit 0.
        unit_id, _ = bank_mod.resolve_topic(body.topic, course_id)
        if not unit_id:
            raise HTTPException(400, f"unknown topic '{body.topic}'")
        qid = bank_mod.next_id(bank, unit_id, body.topic, course_id)
        item = bank_mod.blank_question(qid)
        item["source"] = {"doc": "AUTHORED"}

    _apply_topics(item, body.topic, body.additional_topics, body.unit, course_id)

    blocks = blocks_mod.normalise_blocks(body.stem_blocks)
    if not blocks:
        # No blocks sent: fall back to whatever LaTeX was handed over.
        item["stem"] = (body.stem or "").strip()
        item.pop("stem_blocks", None)
    else:
        blocks_mod.apply_blocks(item, blocks)

    for choice in body.choices or []:
        if not isinstance(choice, dict):
            continue
        choice.setdefault("label", "")
    item["choices"] = body.choices or []

    item["answer"] = body.answer or ""
    item["solution"] = body.solution or ""
    item["qtype"] = body.qtype or "mcq"
    item["difficulty"] = body.difficulty or ""
    item["tags"] = body.tags or []
    if body.number is not None:
        item["number"] = body.number

    # Figures referenced by the blocks belong to this question.
    item["images"] = [
        {"file": os.path.basename(path), "rel": path}
        for path in blocks_mod.referenced_images(item.get("stem_blocks") or [])
    ]

    if existing is None:
        bank["questions"].append(item)
    bank_mod.save_bank(bank, course_id)
    return {"ok": True, "question": item, "created": existing is None}


@app.post("/api/uploads")
async def upload_image(file: UploadFile = File(...), course: str = ""):
    """Store a figure for a hand-written question; returns its media path."""
    filename = file.filename or "figure.png"
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "empty upload")
    if len(payload) > 12 * 1024 * 1024:
        raise HTTPException(400, "image is larger than 12 MB")
    try:
        rel = blocks_mod.store_upload(filename, payload, course)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "path": rel, "url": "/api/file?path=" + rel}


# --------------------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------------------

class ExportBody(BaseModel):
    ids: list = []
    title: str = ""
    subtitle: str = ""
    show_answer: bool = False
    show_solution: bool = False
    group_by_topic: bool = True
    instructions: str = ""
    filename: str = "practice-set"
    # A paper belongs to one course; composing never reaches across banks.
    course: str = ""


def _collect(ids: list, course: str = "") -> list:
    bank = bank_mod.load_bank(course)
    if not ids:
        return bank["questions"]
    wanted = set(ids)
    return [q for q in bank["questions"] if q["id"] in wanted]


def _paper_title(body: ExportBody) -> str:
    return body.title or (courses_mod.get(body.course).title + " Practice Set")


@app.post("/api/export/latex")
def export_latex(body: ExportBody):
    qs = _collect(body.ids, body.course)
    if not qs:
        raise HTTPException(400, "no questions selected")
    tex = latex_mod.build_document(
        qs, _paper_title(body), body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    path = os.path.join(EXPORT_DIR, body.filename + ".tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tex)
    return {"tex": tex, "path": path, "count": len(qs)}


@app.post("/api/export/latex/file")
def export_latex_file(body: ExportBody):
    qs = _collect(body.ids, body.course)
    if not qs:
        raise HTTPException(400, "no questions selected")
    tex = latex_mod.build_document(
        qs, _paper_title(body), body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    path = os.path.join(EXPORT_DIR, body.filename + ".tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tex)
    return FileResponse(path, filename=body.filename + ".tex", media_type="application/x-tex")


@app.post("/api/export/pdf")
def export_pdf(body: ExportBody, request: Request,
               user: dict = Depends(auth_mod.current_user)):
    qs = _collect(body.ids, body.course)
    if not qs:
        raise HTTPException(400, "no questions selected")
    course_id = courses_mod.get(body.course).id
    tex = latex_mod.build_document(
        qs, _paper_title(body), body.subtitle, body.show_answer, body.show_solution,
        body.group_by_topic, body.instructions)
    res = latex_mod.compile_pdf(tex, jobname=body.filename)
    failed = not res["ok"] or _log_has_errors(res.get("log", ""))
    if failed:
        _record_activity(request, user, "export.failed", body.filename,
                         f"PDF build failed for {len(qs)} question(s)")
        return JSONResponse({"ok": False, "log": _tail(res.get("log", ""))},
                            status_code=501)
    out = os.path.join(EXPORT_DIR, body.filename + ".pdf")
    with open(res["pdf"], "rb") as src, open(out, "wb") as dst:
        dst.write(src.read())
    # Remember who produced this file so /api/file can keep it private to them.
    appdb_mod.register_generated_files(
        auth_mod.app_db_path(), user_id=int(user["id"]),
        paths=[os.path.relpath(out, ROOT).replace("\\", "/")])
    _record_activity(request, user, "export", body.filename,
                     f"Built PDF with {len(qs)} question(s)",
                     {"count": len(qs), "title": _paper_title(body),
                      "course": course_id})
    return FileResponse(out, filename=body.filename + ".pdf",
                        media_type="application/pdf")


@app.get("/api/engine")
def engine():
    return {"engine": latex_mod.find_engine()}


# --------------------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------------------

@app.post("/api/ingest")
async def ingest_upload(file: UploadFile = File(...), doc_id: str = "", dpi: int = 300,
                        course: str = ""):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF files are accepted")
    tmp = os.path.join(EXPORT_DIR, "upload-" + os.urandom(4).hex() + ".pdf")
    with open(tmp, "wb") as f:
        f.write(await file.read())
    try:
        meta = ingest_mod.start(tmp, doc_id or None, dpi=dpi, course_id=course)
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
def ingest_commit(job: str, replace_source: bool = True, course: str = ""):
    res = ingest_mod.commit(job, replace_source, course_id=course or None)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)
    return res


@app.delete("/api/ingest/{job}")
def ingest_delete(job: str):
    return {"ok": ingest_mod.discard(job)}


@app.get("/api/file")
def serve_file(path: str, request: Request,
               user: dict = Depends(auth_mod.current_user)):
    """Serve a figure, or one of my own generated exports.

    Bank figures are shared by everyone, but a PDF another teacher built is not:
    knowing its URL must not be enough to download it.
    """
    rel = path.lstrip("/").replace("..", "")
    full = os.path.normpath(os.path.join(ROOT, rel))
    if not full.startswith(ROOT):
        raise HTTPException(403, "outside repository")
    if not os.path.exists(full):
        raise HTTPException(404, "file not found")

    exports_root = os.path.normpath(EXPORT_DIR)
    if os.path.normpath(os.path.commonpath([full, exports_root])) == exports_root:
        rel_path = os.path.relpath(full, ROOT).replace("\\", "/")
        if user.get("role") != "admin" and not appdb_mod.generated_file_owned_by(
                auth_mod.app_db_path(), user_id=int(user["id"]), path=rel_path):
            # Deliberately 404: do not confirm that the file exists.
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
