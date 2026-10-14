"""Account, saved-paper and sharing endpoints.

Everything here mirrors the reference application's contract:

* ``/api/session`` is the only route that works without a cookie;
* drafts and publications are always filtered to the caller, and a cross-owner
  write is reported as "not found" rather than "forbidden", so the API never
  confirms that somebody else's paper exists;
* optimistic concurrency uses a ``version`` field and answers ``409`` with
  ``{"code": ...}`` so the UI can offer a reload instead of losing work.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from server import appdb, auth, papers  # noqa: E402

router = APIRouter()

CONFLICT_CODES = {
    papers.DraftConflictError: "draft_conflict",
    papers.PaperSharingConflictError: "sharing_conflict",
}


def _db() -> str:
    return str(auth.app_db_path())


def _fail(exc: Exception) -> HTTPException:
    """Map domain errors onto status codes the UI can act on."""
    if isinstance(exc, (papers.DraftConflictError, papers.PaperSharingConflictError)):
        return HTTPException(409, {"error": str(exc),
                                   "code": CONFLICT_CODES[type(exc)]})
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    raise exc


def _record(request: Request, user: dict[str, Any], action: str, **kwargs) -> None:
    appdb.record_activity(_db(), user=user, action=action, **kwargs)


# --------------------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.get("/api/session")
def get_session(request: Request):
    """Who am I?  Returns ``{"user": null}`` when nobody is signed in."""
    user = auth.user_for_request(request)
    if user is not None and appdb.mark_session_resumed(_db(), auth.cookie_value(request)):
        _record(request, user, "session.resumed", entity_type="user",
                entity_id=user["id"], summary="Browser session resumed")
    return {"user": user, "login_required": auth.login_required()}


@router.post("/api/session")
def login(request: Request, body: LoginBody):
    db = _db()
    username = (body.username or "").strip().lower()
    host = request.client.host if request.client else "unknown"
    attempt_key = f"{host}:{username}"
    if auth.LOGIN_ATTEMPT_LIMITER.blocked(attempt_key) or \
            auth.LOGIN_IP_LIMITER.blocked(host):
        return auth.json_response(
            {"error": "Too many sign-in attempts. Try again later."}, status=429,
            headers=[("Retry-After", "900")])

    user = appdb.authenticate_user(db, username=username, password=body.password)
    if user is None:
        auth.LOGIN_ATTEMPT_LIMITER.record_failure(attempt_key)
        auth.LOGIN_IP_LIMITER.record_failure(host)
        return auth.json_response({"error": "Invalid username or password"}, status=401)

    auth.LOGIN_ATTEMPT_LIMITER.clear(attempt_key)
    token = appdb.create_session(db, user_id=user["id"])
    _record(request, user, "login", entity_type="user", entity_id=user["id"],
            summary="Logged in")
    return auth.json_response(
        {"message": f"Signed in as {user['display_name']}", "user": user},
        headers=[auth.session_cookie_header(token)])


@router.post("/api/logout")
def logout(request: Request):
    db = _db()
    user = auth.user_for_request(request)
    appdb.delete_session(db, auth.cookie_value(request))
    if user is not None:
        _record(request, user, "logout", entity_type="user",
                entity_id=user["id"], summary="Logged out")
    return auth.json_response(
        {"message": "Signed out", "user": None},
        headers=[auth.clear_session_cookie_header()])


@router.post("/api/profile/password")
def change_password(request: Request, body: PasswordBody,
                    user: dict = Depends(auth.current_user)):
    try:
        saved = appdb.change_user_password(
            _db(), user_id=int(user["id"]),
            current_password=body.current_password,
            new_password=body.new_password,
            preserve_session_token=auth.cookie_value(request))
    except Exception as exc:  # noqa: BLE001 - mapped below
        raise _fail(exc)
    _record(request, saved, "password.change", entity_type="user",
            entity_id=saved["id"], summary="Changed own password")
    return {"message": "Password changed successfully", "user": saved}


# --------------------------------------------------------------------------------------
# user administration
# --------------------------------------------------------------------------------------

class UserBody(BaseModel):
    id: Optional[int] = None
    username: str = ""
    display_name: str = ""
    role: str = "teacher"
    password: str = ""
    active: bool = True


@router.get("/api/users")
def list_users(_admin: dict = Depends(auth.admin_user)):
    return {
        "users": appdb.list_users(_db()),
        "organizations": appdb.list_organizations(_db()),
    }


@router.post("/api/users")
def save_user(request: Request, body: UserBody,
              admin: dict = Depends(auth.admin_user)):
    db = _db()
    try:
        if body.id:
            saved = appdb.update_user(
                db, int(body.id),
                username=body.username or None,
                display_name=body.display_name or None,
                role=body.role or None,
                password=body.password or None,
                active=body.active)
            action = "user.update"
        else:
            saved = appdb.create_user(
                db, username=body.username, display_name=body.display_name,
                role=body.role, password=body.password, active=body.active)
            action = "user.create"
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    _record(request, admin, action, entity_type="user", entity_id=saved["id"],
            summary=f"{action.split('.')[1].title()}d user '{saved['username']}'")
    return {"message": "Saved", "user": saved, "users": appdb.list_users(db)}


@router.get("/api/activity")
def activity(limit: int = Query(100, le=500), user_id: Optional[int] = None,
             days: Optional[int] = None, action: Optional[str] = None,
             _admin: dict = Depends(auth.admin_user)):
    return {"activity": appdb.list_activity_log(
        _db(), limit=limit, user_id=user_id, days=days, action=action)}


# --------------------------------------------------------------------------------------
# saved papers
# --------------------------------------------------------------------------------------

class DraftBody(BaseModel):
    id: Optional[int] = None
    name: str = "Untitled paper"
    question_ids: list = Field(default_factory=list)
    question_overrides: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)
    version: Optional[int] = None


@router.get("/api/paper-drafts")
def drafts(user: dict = Depends(auth.current_user)):
    items = papers.list_paper_drafts(_db(), user_id=int(user["id"]))
    for item in items:
        item["source_update"] = papers.publication_source_update(_db(), item)
    return {"drafts": items}


@router.post("/api/paper-drafts")
def save_draft(request: Request, body: DraftBody,
               user: dict = Depends(auth.current_user)):
    try:
        saved = papers.save_paper_draft(
            _db(), user_id=int(user["id"]), name=body.name,
            question_ids=body.question_ids,
            question_overrides=body.question_overrides,
            metadata=body.metadata, settings=body.settings,
            draft_id=body.id, expected_version=body.version)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    _record(request, user, "paper_draft.save", entity_type="paper",
            entity_id=saved["id"], summary=f"Saved paper '{saved['name']}'",
            metadata={"questions": len(saved["question_ids"])})
    return {"draft": saved}


@router.post("/api/paper-drafts/delete")
def delete_draft(request: Request, body: DraftBody,
                 user: dict = Depends(auth.current_user)):
    if not body.id:
        raise HTTPException(400, "A saved paper id is required")
    removed = papers.delete_paper_draft(_db(), int(body.id), user_id=int(user["id"]))
    if not removed:
        raise HTTPException(404, "Saved paper not found")
    _record(request, user, "paper_draft.delete", entity_type="paper",
            entity_id=body.id, summary="Deleted a saved paper")
    return {"ok": True}


# --------------------------------------------------------------------------------------
# sharing
# --------------------------------------------------------------------------------------

class FolderBody(BaseModel):
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    member_ids: list = Field(default_factory=list)
    all_organization_teachers: bool = False
    version: Optional[int] = None


@router.get("/api/paper-sharing")
def sharing(user: dict = Depends(auth.current_user)):
    return papers.paper_sharing_payload(_db(), user_id=int(user["id"]))


@router.post("/api/paper-folders")
def save_folder(request: Request, body: FolderBody,
                user: dict = Depends(auth.current_user)):
    try:
        saved = papers.save_paper_shared_folder(
            _db(), actor_user_id=int(user["id"]), name=body.name,
            description=body.description, member_ids=body.member_ids,
            all_organization_teachers=body.all_organization_teachers,
            folder_id=body.id, expected_version=body.version)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    _record(request, user, "paper_folder.save", entity_type="folder",
            entity_id=saved["id"], summary=f"Saved sharing group '{saved['name']}'")
    return {"folder": saved, "folders": papers.list_paper_folders(_db())}


@router.post("/api/paper-folders/archive")
def archive_folder(request: Request, body: FolderBody,
                   user: dict = Depends(auth.current_user)):
    if not body.id:
        raise HTTPException(400, "A sharing group id is required")
    if not papers.archive_paper_shared_folder(_db(), int(body.id),
                                              actor_user_id=int(user["id"])):
        raise HTTPException(404, "Sharing group not found")
    _record(request, user, "paper_folder.archive", entity_type="folder",
            entity_id=body.id, summary="Archived a sharing group")
    return {"ok": True}


class PublishBody(BaseModel):
    draft_id: int
    title: str
    message: str = ""
    folder_ids: list = Field(default_factory=list)
    recipient_ids: list = Field(default_factory=list)
    version: Optional[int] = None


@router.post("/api/paper-publications")
def publish(request: Request, body: PublishBody,
            user: dict = Depends(auth.current_user)):
    try:
        saved = papers.publish_paper_draft(
            _db(), actor_user_id=int(user["id"]), draft_id=body.draft_id,
            title=body.title, message=body.message, folder_ids=body.folder_ids,
            recipient_ids=body.recipient_ids, expected_version=body.version)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    _record(request, user, "paper_publication.publish", entity_type="paper",
            entity_id=saved["id"],
            summary=f"Shared '{saved['title']}' (revision {saved['revision_number']})",
            metadata={"questions": len(saved["question_ids"])})
    return {"publication": saved}


class PublicationBody(BaseModel):
    publication_id: int
    version: Optional[int] = None
    name: Optional[str] = None
    revision_id: Optional[int] = None
    follow: bool = True
    notification_ids: list = Field(default_factory=list)


@router.post("/api/paper-publications/withdraw")
def withdraw(request: Request, body: PublicationBody,
             user: dict = Depends(auth.current_user)):
    try:
        removed = papers.withdraw_paper_publication(
            _db(), body.publication_id, actor_user_id=int(user["id"]))
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    if not removed:
        raise HTTPException(404, "Shared paper not found")
    _record(request, user, "paper_publication.withdraw", entity_type="paper",
            entity_id=body.publication_id, summary="Withdrew a shared paper")
    return {"ok": True}


@router.post("/api/paper-publications/copy")
def copy_shared(request: Request, body: PublicationBody,
                user: dict = Depends(auth.current_user)):
    try:
        draft = papers.copy_paper_publication(
            _db(), body.publication_id, actor_user_id=int(user["id"]),
            name=body.name, expected_revision_id=body.revision_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    _record(request, user, "paper_copy.save", entity_type="paper",
            entity_id=draft["id"], summary=f"Copied a shared paper to '{draft['name']}'")
    return {"draft": draft}


@router.post("/api/paper-subscriptions")
def subscribe(request: Request, body: PublicationBody,
              user: dict = Depends(auth.current_user)):
    try:
        papers.set_paper_subscription(
            _db(), body.publication_id, user_id=int(user["id"]), follow=body.follow)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)
    return {"ok": True, "follow": body.follow}


@router.post("/api/paper-notifications/read")
def read_notifications(body: PublicationBody,
                       user: dict = Depends(auth.current_user)):
    count = papers.mark_paper_notifications_read(
        _db(), user_id=int(user["id"]), notification_ids=body.notification_ids)
    return {"ok": True, "updated": count}
