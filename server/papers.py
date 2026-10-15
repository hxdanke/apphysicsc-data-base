"""Saved papers: drafts, sharing groups, publications and notifications.

The model is the reference application's, trimmed to what this project needs:

* a **draft** is private, mutable state owned by one teacher -- the selected
  question ids, the cover details and the export settings.  Saving carries a
  version so two browser tabs cannot silently overwrite each other.
* a **publication** is the decision to share a draft.  Its content is stored as
  an append-only chain of **revisions**.  A revision is never updated or
  deleted, so a colleague who opened a shared paper keeps seeing exactly what
  they were shown, even while the author keeps editing the draft.
* a **revision** is created only when the content really changes, decided by a
  SHA-256 fingerprint of the specification.  Re-publishing an unchanged paper is
  rejected instead of producing a duplicate version.
* **folders** are named groups of colleagues; a publication may target any mix
  of folders and individual people.

Question ids are strings in this bank (``EB3-U1-1.1-Q2``), so every column that
holds one is TEXT.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from server import appdb  # noqa: E402

TS = appdb.TIMESTAMP_EXPR


class DraftConflictError(Exception):
    """The draft was changed elsewhere; the caller must reload before saving."""


class PaperSharingConflictError(Exception):
    """The publication changed underneath the caller (audience or content)."""


PAPER_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS paper_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  course TEXT NOT NULL DEFAULT '',
  question_ids_json TEXT NOT NULL DEFAULT '[]',
  question_overrides_json TEXT NOT NULL DEFAULT '{{}}',
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  settings_json TEXT NOT NULL DEFAULT '{{}}',
  copied_from_revision_id INTEGER,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  updated_at TEXT NOT NULL DEFAULT ({TS})
);

CREATE INDEX IF NOT EXISTS idx_paper_drafts_user_updated
  ON paper_drafts(user_id, updated_at);

CREATE TABLE IF NOT EXISTS paper_shared_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  all_organization_teachers INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  updated_at TEXT NOT NULL DEFAULT ({TS})
);

CREATE TABLE IF NOT EXISTS paper_shared_folder_members (
  folder_id INTEGER NOT NULL REFERENCES paper_shared_folders(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  member_role TEXT NOT NULL DEFAULT 'member'
    CHECK(member_role IN ('manager', 'member')),
  created_at TEXT NOT NULL DEFAULT ({TS}),
  PRIMARY KEY(folder_id, user_id)
);

CREATE TABLE IF NOT EXISTS paper_publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  source_draft_id INTEGER REFERENCES paper_drafts(id) ON DELETE SET NULL,
  course TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  updated_at TEXT NOT NULL DEFAULT ({TS}),
  UNIQUE(owner_user_id, source_draft_id)
);

CREATE TABLE IF NOT EXISTS paper_publication_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  publication_id INTEGER NOT NULL REFERENCES paper_publications(id) ON DELETE CASCADE,
  revision_number INTEGER NOT NULL,
  source_draft_version INTEGER,
  question_overrides_json TEXT NOT NULL DEFAULT '{{}}',
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  settings_json TEXT NOT NULL DEFAULT '{{}}',
  specification_fingerprint TEXT NOT NULL,
  published_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  UNIQUE(publication_id, revision_number)
);

CREATE TABLE IF NOT EXISTS paper_publication_questions (
  revision_id INTEGER NOT NULL REFERENCES paper_publication_revisions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  question_id TEXT NOT NULL,
  PRIMARY KEY(revision_id, position),
  UNIQUE(revision_id, question_id)
);

CREATE TABLE IF NOT EXISTS paper_publication_folders (
  publication_id INTEGER NOT NULL REFERENCES paper_publications(id) ON DELETE CASCADE,
  folder_id INTEGER NOT NULL REFERENCES paper_shared_folders(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  PRIMARY KEY(publication_id, folder_id)
);

CREATE TABLE IF NOT EXISTS paper_publication_recipients (
  publication_id INTEGER NOT NULL REFERENCES paper_publications(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  PRIMARY KEY(publication_id, user_id)
);

CREATE TABLE IF NOT EXISTS paper_subscriptions (
  publication_id INTEGER NOT NULL REFERENCES paper_publications(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({TS}),
  updated_at TEXT NOT NULL DEFAULT ({TS}),
  PRIMARY KEY(publication_id, user_id)
);

CREATE TABLE IF NOT EXISTS paper_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  publication_id INTEGER REFERENCES paper_publications(id) ON DELETE SET NULL,
  revision_id INTEGER REFERENCES paper_publication_revisions(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('shared', 'updated', 'withdrawn')),
  message TEXT NOT NULL,
  read_at TEXT,
  created_at TEXT NOT NULL DEFAULT ({TS})
);

CREATE INDEX IF NOT EXISTS idx_paper_notifications_user_created
  ON paper_notifications(user_id, read_at, created_at DESC);
"""


def init_papers(db_path: Path | str) -> None:
    """Create the paper-sharing tables.  Idempotent."""
    appdb.init_db(db_path)
    with appdb.connect(db_path) as conn:
        conn.executescript(PAPER_SCHEMA)
        _ensure_course_columns(conn)


def _ensure_course_columns(conn: sqlite3.Connection) -> None:
    """Add ``course`` to tables created before courses existed."""
    for table in ("paper_drafts", "paper_publications"):
        columns = {row["name"] for row in
                   conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "course" not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN course TEXT NOT NULL DEFAULT ''")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return []
        return loaded if isinstance(loaded, list) else []
    return []


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def clean_question_ids(ids: Any) -> list[str]:
    """Keep order, drop blanks and duplicates -- the paper order is meaningful."""
    out: list[str] = []
    for raw in _json_list(ids):
        text = str(raw).strip()
        if text and text not in out:
            out.append(text)
    return out


def clean_cover_metadata(value: Any) -> dict:
    """Cover fields are always plain strings; the renderer concatenates them."""
    out: dict[str, str] = {}
    for key, item in _json_dict(value).items():
        name = str(key).strip()
        if not name:
            continue
        out[name] = "" if item is None else str(item)
    return out


def clean_published_settings(value: Any) -> dict:
    """Settings that travel in a shared revision.

    ``question_exclusions`` is deliberately dropped: it records which questions
    *this* teacher has already used, which is private book-keeping and must not
    leak into an immutable shared revision.
    """
    settings = dict(_json_dict(value))
    settings.pop("question_exclusions", None)
    return settings


def paper_specification_fingerprint(specification: dict) -> str:
    return hashlib.sha256(
        json.dumps(specification, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def specification_fingerprint(*, question_ids: list, question_overrides: Any,
                              metadata: Any, settings: Any) -> str:
    return paper_specification_fingerprint({
        "question_ids": clean_question_ids(question_ids),
        "question_overrides": _json_dict(question_overrides),
        "metadata": clean_cover_metadata(metadata),
        "settings": clean_published_settings(settings),
    })


def clean_unique_positive_ids(values: Iterable[Any]) -> list[int]:
    out: list[int] = []
    for raw in values or ():
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in out:
            out.append(number)
    return out


# --------------------------------------------------------------------------------------
# drafts
# --------------------------------------------------------------------------------------

def _draft_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "user_id": row["user_id"],
        "name": row["name"],
        "course": row["course"] if "course" in keys else "",
        "question_ids": clean_question_ids(row["question_ids_json"]),
        "question_overrides": _json_dict(row["question_overrides_json"]),
        "metadata": _json_dict(row["metadata_json"]),
        "settings": _json_dict(row["settings_json"]),
        "copied_from_revision_id": row["copied_from_revision_id"],
        "version": int(row["version"] or 1),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_paper_drafts(db_path: Path | str, *, user_id: int | None = None,
                      include_all: bool = False,
                      course_id: str | None = None) -> list[dict[str, Any]]:
    """Drafts belong to their owner; another teacher's draft is invisible.

    Filtering by ``course_id`` is what keeps the composing views separate: an
    AP Physics 1 paper never appears in the AP Physics C list.
    """
    init_papers(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None and not include_all:
        clauses.append("user_id = ?")
        params.append(int(user_id))
    if course_id:
        clauses.append("course = ?")
        params.append(str(course_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with appdb.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM paper_drafts {where} ORDER BY updated_at DESC, id DESC",
            params,
        ).fetchall()
    return [_draft_row(row) for row in rows]


def save_paper_draft(db_path: Path | str, *, user_id: int, name: str,
                     question_ids: Iterable[Any] = (),
                     question_overrides: Any = None, metadata: Any = None,
                     settings: Any = None, draft_id: int | None = None,
                     expected_version: int | None = None,
                     copied_from_revision_id: int | None = None,
                     course_id: str | None = None) -> dict[str, Any]:
    init_papers(db_path)
    clean_name = (name or "").strip() or "Untitled paper"
    ids = clean_question_ids(question_ids)
    overrides = _json_dict(question_overrides)
    cover = clean_cover_metadata(metadata)
    options = _json_dict(settings)

    with appdb.connect(db_path) as conn:
        if draft_id:
            existing = conn.execute(
                "SELECT * FROM paper_drafts WHERE id = ? AND user_id = ?",
                (int(draft_id), int(user_id)),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Saved paper not found: {draft_id}")
            if expected_version is not None and \
                    int(existing["version"] or 1) != int(expected_version):
                raise DraftConflictError(
                    "This paper was changed elsewhere. Reload it before saving again.")
            conn.execute(
                f"""
                UPDATE paper_drafts
                SET name = ?, question_ids_json = ?, question_overrides_json = ?,
                    metadata_json = ?, settings_json = ?, version = version + 1,
                    updated_at = {TS}
                WHERE id = ?
                """,
                (clean_name, json.dumps(ids, ensure_ascii=False),
                 json.dumps(overrides, ensure_ascii=False),
                 json.dumps(cover, ensure_ascii=False),
                 json.dumps(options, ensure_ascii=False), int(draft_id)),
            )
            target = int(draft_id)
        else:
            owner = int(user_id) if user_id is not None \
                else appdb.default_admin_user_id(db_path)
            cursor = conn.execute(
                """
                INSERT INTO paper_drafts
                  (user_id, name, course, question_ids_json, question_overrides_json,
                   metadata_json, settings_json, copied_from_revision_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner, clean_name, str(course_id or ""),
                 json.dumps(ids, ensure_ascii=False),
                 json.dumps(overrides, ensure_ascii=False),
                 json.dumps(cover, ensure_ascii=False),
                 json.dumps(options, ensure_ascii=False),
                 copied_from_revision_id),
            )
            target = int(cursor.lastrowid)
        row = conn.execute(
            "SELECT * FROM paper_drafts WHERE id = ?", (target,)
        ).fetchone()
    return _draft_row(row)


def delete_paper_draft(db_path: Path | str, draft_id: int,
                       *, user_id: int | None = None) -> bool:
    init_papers(db_path)
    params: list[Any] = [int(draft_id)]
    owner_clause = ""
    if user_id is not None:
        owner_clause = " AND user_id = ?"
        params.append(int(user_id))
    with appdb.connect(db_path) as conn:
        cursor = conn.execute(
            f"DELETE FROM paper_drafts WHERE id = ?{owner_clause}", params)
        return cursor.rowcount > 0


# --------------------------------------------------------------------------------------
# sharing groups
# --------------------------------------------------------------------------------------

def list_paper_folders(db_path: Path | str) -> list[dict[str, Any]]:
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM paper_shared_folders WHERE active = 1 ORDER BY name"
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["members"] = [
                int(m["user_id"]) for m in conn.execute(
                    "SELECT user_id FROM paper_shared_folder_members WHERE folder_id = ?",
                    (int(row["id"]),),
                ).fetchall()
            ]
            out.append(item)
    return out


def save_paper_shared_folder(db_path: Path | str, *, actor_user_id: int,
                             name: str, description: str = "",
                             member_ids: Iterable[Any] = (),
                             all_organization_teachers: bool = False,
                             folder_id: int | None = None,
                             expected_version: int | None = None) -> dict[str, Any]:
    init_papers(db_path)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("A sharing group needs a name")
    members = clean_unique_positive_ids(member_ids)

    with appdb.connect(db_path) as conn:
        if folder_id:
            row = conn.execute(
                "SELECT * FROM paper_shared_folders WHERE id = ?", (int(folder_id),)
            ).fetchone()
            if row is None:
                raise ValueError(f"Sharing group not found: {folder_id}")
            if expected_version is not None and \
                    int(row["version"] or 1) != int(expected_version):
                raise PaperSharingConflictError(
                    "This sharing group changed elsewhere. Reload before saving.")
            conn.execute(
                f"""
                UPDATE paper_shared_folders
                SET name = ?, description = ?, all_organization_teachers = ?,
                    version = version + 1, updated_at = {TS}
                WHERE id = ?
                """,
                (clean_name, description or "", 1 if all_organization_teachers else 0,
                 int(folder_id)),
            )
            target = int(folder_id)
        else:
            cursor = conn.execute(
                """
                INSERT INTO paper_shared_folders
                  (name, description, all_organization_teachers, created_by_user_id)
                VALUES (?, ?, ?, ?)
                """,
                (clean_name, description or "",
                 1 if all_organization_teachers else 0, int(actor_user_id)),
            )
            target = int(cursor.lastrowid)

        conn.execute(
            "DELETE FROM paper_shared_folder_members WHERE folder_id = ?", (target,))
        conn.executemany(
            """
            INSERT INTO paper_shared_folder_members (folder_id, user_id, member_role)
            VALUES (?, ?, 'member')
            """,
            ((target, member) for member in members),
        )
        row = conn.execute(
            "SELECT * FROM paper_shared_folders WHERE id = ?", (target,)
        ).fetchone()
        item = dict(row)
        item["members"] = members
    return item


def archive_paper_shared_folder(db_path: Path | str, folder_id: int,
                                *, actor_user_id: int) -> bool:
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE paper_shared_folders
            SET active = 0, version = version + 1, updated_at = {TS}
            WHERE id = ? AND active = 1
            """,
            (int(folder_id),),
        )
        if cursor.rowcount == 0:
            return False
        # Anyone who loses access is told, and their subscription is dropped.
        affected = [
            int(r["user_id"]) for r in conn.execute(
                """
                SELECT DISTINCT user_id FROM paper_publication_recipients
                WHERE publication_id IN (
                  SELECT publication_id FROM paper_publication_folders WHERE folder_id = ?
                )
                """,
                (int(folder_id),),
            ).fetchall()
        ]
        for uid in affected:
            create_paper_notification(
                conn, user_id=uid, event_type="withdrawn",
                message="A shared paper is no longer available because a "
                        "sharing group was archived.")
        prune_inaccessible_subscriptions(conn)
    return True


# --------------------------------------------------------------------------------------
# access control
# --------------------------------------------------------------------------------------

def paper_publication_access(conn: sqlite3.Connection, publication: sqlite3.Row,
                             actor: sqlite3.Row) -> set[str]:
    """Which ways can `actor` reach `publication`?  An empty set means no access."""
    access: set[str] = set()
    if actor["role"] == "admin":
        access.add("admin")
    if int(publication["owner_user_id"]) == int(actor["id"]):
        access.add("owned")
    if actor["role"] not in {"teacher", "student"}:
        return access

    if conn.execute(
        "SELECT 1 FROM paper_publication_recipients "
        "WHERE publication_id = ? AND user_id = ?",
        (int(publication["id"]), int(actor["id"])),
    ).fetchone():
        access.add("direct")

    row = conn.execute(
        """
        SELECT 1
        FROM paper_publication_folders pf
        JOIN paper_shared_folders f ON f.id = pf.folder_id AND f.active = 1
        LEFT JOIN paper_shared_folder_members m
          ON m.folder_id = f.id AND m.user_id = ?
        WHERE pf.publication_id = ?
          AND (m.user_id IS NOT NULL
               OR (f.all_organization_teachers = 1 AND ? = 'teacher'))
        LIMIT 1
        """,
        (int(actor["id"]), int(publication["id"]), actor["role"]),
    ).fetchone()
    if row is not None:
        access.add("folder")
    return access


def _actor_row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    if row is None:
        raise ValueError(f"User not found: {user_id}")
    if not bool(row["active"]):
        raise ValueError("This account is disabled")
    if row["role"] not in appdb.USER_ROLES:
        raise ValueError("Paper sharing is unavailable for this account")
    return row


def _audience_ids(conn: sqlite3.Connection, publication_id: int) -> set[int]:
    """Everyone who can currently see `publication_id`."""
    out = {int(r["user_id"]) for r in conn.execute(
        "SELECT user_id FROM paper_publication_recipients WHERE publication_id = ?",
        (int(publication_id),),
    ).fetchall()}
    for row in conn.execute(
        """
        SELECT m.user_id AS member_id, f.all_organization_teachers AS all_teachers
        FROM paper_publication_folders pf
        JOIN paper_shared_folders f ON f.id = pf.folder_id AND f.active = 1
        LEFT JOIN paper_shared_folder_members m ON m.folder_id = f.id
        WHERE pf.publication_id = ?
        """,
        (int(publication_id),),
    ).fetchall():
        if row["member_id"] is not None:
            out.add(int(row["member_id"]))
        if row["all_teachers"]:
            out |= {int(u["id"]) for u in conn.execute(
                "SELECT id FROM users WHERE role = 'teacher' AND active = 1"
            ).fetchall()}
    return out


def create_paper_notification(conn: sqlite3.Connection, *, user_id: int,
                              event_type: str, message: str,
                              publication_id: int | None = None,
                              revision_id: int | None = None) -> None:
    conn.execute(
        """
        INSERT INTO paper_notifications
          (user_id, publication_id, revision_id, event_type, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(user_id), publication_id, revision_id, event_type, message),
    )


def prune_inaccessible_subscriptions(conn: sqlite3.Connection) -> None:
    """Drop subscriptions whose publication is gone, withdrawn or out of reach."""
    conn.execute(
        """
        DELETE FROM paper_subscriptions
        WHERE publication_id NOT IN (
          SELECT id FROM paper_publications WHERE active = 1
        )
        """
    )


# --------------------------------------------------------------------------------------
# publishing
# --------------------------------------------------------------------------------------

def publish_paper_draft(db_path: Path | str, *, actor_user_id: int, draft_id: int,
                        title: str, message: str = "",
                        folder_ids: Iterable[Any] = (),
                        recipient_ids: Iterable[Any] = (),
                        expected_version: int | None = None) -> dict[str, Any]:
    """Share a draft.  A new immutable revision is appended only if content changed."""
    init_papers(db_path)
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("A shared paper needs a title")
    folders = clean_unique_positive_ids(folder_ids)
    recipients = clean_unique_positive_ids(recipient_ids)
    if not folders and not recipients:
        raise ValueError("Choose at least one sharing group or colleague")

    with appdb.connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _actor_row(conn, actor_user_id)
        draft = conn.execute(
            "SELECT * FROM paper_drafts WHERE id = ? AND user_id = ?",
            (int(draft_id), int(actor_user_id)),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Saved paper not found: {draft_id}")

        fingerprint = specification_fingerprint(
            question_ids=clean_question_ids(draft["question_ids_json"]),
            question_overrides=draft["question_overrides_json"],
            metadata=draft["metadata_json"],
            settings=draft["settings_json"],
        )
        existing = conn.execute(
            "SELECT * FROM paper_publications WHERE owner_user_id = ? AND source_draft_id = ?",
            (int(actor_user_id), int(draft_id)),
        ).fetchone()
        if existing is not None and expected_version is not None and \
                int(existing["version"] or 1) != int(expected_version):
            raise PaperSharingConflictError(
                "This shared paper changed elsewhere. Reload before publishing.")

        current = None
        if existing is not None:
            current = conn.execute(
                """
                SELECT * FROM paper_publication_revisions
                WHERE publication_id = ?
                ORDER BY revision_number DESC LIMIT 1
                """,
                (int(existing["id"]),),
            ).fetchone()

        content_changed = (
            existing is None
            or not bool(existing["active"])
            or current is None
            or str(current["specification_fingerprint"]) != fingerprint
        )
        sharing_changed = (
            existing is None
            or not bool(existing["active"])
            or str(existing["title"]) != clean_title
            or str(existing["message"] or "") != (message or "")
            or _folder_set(conn, existing["id"]) != set(folders)
            or _recipient_set(conn, existing["id"]) != set(recipients)
        )
        if existing is not None and not content_changed and not sharing_changed:
            raise ValueError("This paper and its sharing settings are already up to date")

        if existing is None:
            draft_course = draft["course"] if "course" in draft.keys() else ""
            cursor = conn.execute(
                """
                INSERT INTO paper_publications
                  (owner_user_id, source_draft_id, course, title, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(actor_user_id), int(draft_id), str(draft_course or ""),
                 clean_title, message or ""),
            )
            publication_id = int(cursor.lastrowid)
        else:
            publication_id = int(existing["id"])
            conn.execute(
                f"""
                UPDATE paper_publications
                SET title = ?, message = ?, active = 1, version = version + 1,
                    updated_at = {TS}
                WHERE id = ?
                """,
                (clean_title, message or "", publication_id),
            )

        conn.execute(
            "DELETE FROM paper_publication_folders WHERE publication_id = ?",
            (publication_id,))
        conn.executemany(
            "INSERT INTO paper_publication_folders (publication_id, folder_id) VALUES (?, ?)",
            ((publication_id, f) for f in folders))
        conn.execute(
            "DELETE FROM paper_publication_recipients WHERE publication_id = ?",
            (publication_id,))
        conn.executemany(
            "INSERT INTO paper_publication_recipients (publication_id, user_id) VALUES (?, ?)",
            ((publication_id, r) for r in recipients))

        revision_id = int(current["id"]) if current is not None else None
        if content_changed:
            next_number = 1 if current is None else int(current["revision_number"]) + 1
            cursor = conn.execute(
                """
                INSERT INTO paper_publication_revisions
                  (publication_id, revision_number, source_draft_version,
                   question_overrides_json, metadata_json, settings_json,
                   specification_fingerprint, published_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id, next_number, int(draft["version"] or 1),
                    draft["question_overrides_json"], draft["metadata_json"],
                    json.dumps(clean_published_settings(draft["settings_json"]),
                               ensure_ascii=False),
                    fingerprint, int(actor_user_id),
                ),
            )
            revision_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO paper_publication_questions (revision_id, position, question_id)
                VALUES (?, ?, ?)
                """,
                ((revision_id, position, qid) for position, qid in enumerate(
                    clean_question_ids(draft["question_ids_json"]), start=1)),
            )

        _notify_publication_change(conn, publication_id=publication_id,
                                   revision_id=revision_id,
                                   actor_id=int(actor_user_id),
                                   content_changed=content_changed,
                                   title=clean_title)
        prune_inaccessible_subscriptions(conn)

        row = conn.execute(
            "SELECT * FROM paper_publications WHERE id = ?", (publication_id,)
        ).fetchone()
    return _publication_payload(db_path, row, actor_user_id=actor_user_id)


def _folder_set(conn: sqlite3.Connection, publication_id: Any) -> set[int]:
    return {int(r["folder_id"]) for r in conn.execute(
        "SELECT folder_id FROM paper_publication_folders WHERE publication_id = ?",
        (int(publication_id),),
    ).fetchall()}


def _recipient_set(conn: sqlite3.Connection, publication_id: Any) -> set[int]:
    return {int(r["user_id"]) for r in conn.execute(
        "SELECT user_id FROM paper_publication_recipients WHERE publication_id = ?",
        (int(publication_id),),
    ).fetchall()}


def _notify_publication_change(conn: sqlite3.Connection, *, publication_id: int,
                               revision_id: int | None, actor_id: int,
                               content_changed: bool, title: str) -> None:
    audience = _audience_ids(conn, publication_id)
    audience.discard(actor_id)
    if not audience:
        return
    subscribed = {int(r["user_id"]) for r in conn.execute(
        "SELECT user_id FROM paper_subscriptions WHERE publication_id = ?",
        (publication_id,),
    ).fetchall()}
    already = {int(r["user_id"]) for r in conn.execute(
        """
        SELECT user_id FROM paper_notifications
        WHERE publication_id = ? AND event_type = 'shared'
        """,
        (publication_id,),
    ).fetchall()}
    notified_before = already & audience

    for uid in audience - notified_before:
        create_paper_notification(conn, user_id=uid, publication_id=publication_id,
                                  revision_id=revision_id, event_type="shared",
                                  message=f"{title} was shared with you")
    if content_changed:
        for uid in (audience & subscribed) - notified_before:
            create_paper_notification(
                conn, user_id=uid, publication_id=publication_id,
                revision_id=revision_id, event_type="updated",
                message=f"{title} has a new version")

    # Newly reached people follow the paper automatically.
    conn.executemany(
        """
        INSERT INTO paper_subscriptions (publication_id, user_id)
        VALUES (?, ?)
        ON CONFLICT(publication_id, user_id) DO UPDATE SET updated_at = {ts}
        """.format(ts=TS),
        ((publication_id, uid) for uid in audience),
    )


def withdraw_paper_publication(db_path: Path | str, publication_id: int,
                              *, actor_user_id: int) -> bool:
    """Stop sharing.  Revisions are kept; nobody can reach them any more."""
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _actor_row(conn, actor_user_id)
        row = conn.execute(
            "SELECT * FROM paper_publications WHERE id = ?", (int(publication_id),)
        ).fetchone()
        if row is None:
            return False
        if int(row["owner_user_id"]) != int(actor["id"]) and actor["role"] != "admin":
            raise ValueError("Only the paper owner can withdraw it")
        if not bool(row["active"]):
            return False
        conn.execute(
            f"""
            UPDATE paper_publications
            SET active = 0, version = version + 1, updated_at = {TS}
            WHERE id = ?
            """,
            (int(publication_id),),
        )
        for uid in _audience_ids(conn, publication_id):
            create_paper_notification(
                conn, user_id=uid, publication_id=int(publication_id),
                event_type="withdrawn",
                message=f"{row['title']} is no longer shared")
        prune_inaccessible_subscriptions(conn)
    return True


def copy_paper_publication(db_path: Path | str, publication_id: int,
                           *, actor_user_id: int, name: str | None = None,
                           expected_revision_id: int | None = None) -> dict[str, Any]:
    """Save a colleague's shared paper as my own independent draft."""
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _actor_row(conn, actor_user_id)
        publication = conn.execute(
            "SELECT * FROM paper_publications WHERE id = ? AND active = 1",
            (int(publication_id),),
        ).fetchone()
        if publication is None:
            raise ValueError("This shared paper is no longer available")
        access = paper_publication_access(conn, publication, actor)
        if not access:
            raise ValueError("This shared paper is no longer available")

        revision = conn.execute(
            """
            SELECT * FROM paper_publication_revisions
            WHERE publication_id = ?
            ORDER BY revision_number DESC LIMIT 1
            """,
            (int(publication_id),),
        ).fetchone()
        if revision is None:
            raise ValueError("This shared paper has no content yet")
        if expected_revision_id is not None and \
                int(revision["id"]) != int(expected_revision_id):
            raise PaperSharingConflictError(
                "This shared paper was updated. Reload it before copying.")

        question_ids = [
            r["question_id"] for r in conn.execute(
                """
                SELECT question_id FROM paper_publication_questions
                WHERE revision_id = ? ORDER BY position
                """,
                (int(revision["id"]),),
            ).fetchall()
        ]
        draft_name = (name or publication["title"] or "Shared paper").strip()
        if conn.execute(
            "SELECT 1 FROM paper_drafts WHERE user_id = ? AND name = ?",
            (int(actor_user_id), draft_name),
        ).fetchone():
            draft_name = f"{draft_name} (copy)"
        cursor = conn.execute(
            """
            INSERT INTO paper_drafts
              (user_id, name, course, question_ids_json, question_overrides_json,
               metadata_json, settings_json, copied_from_revision_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(actor_user_id), draft_name,
                str(publication["course"] if "course" in publication.keys() else ""),
                json.dumps(question_ids, ensure_ascii=False),
                revision["question_overrides_json"],
                revision["metadata_json"],
                revision["settings_json"],
                int(revision["id"]),
            ),
        )
        draft_id = int(cursor.lastrowid)
        row = conn.execute(
            "SELECT * FROM paper_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
    return _draft_row(row)


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------

def _publication_payload(db_path: Path | str, row: sqlite3.Row,
                         *, actor_user_id: int) -> dict[str, Any]:
    """Build the reader-facing view of one publication.

    Deliberately does *not* re-run ``init_papers``: callers may be inside a read
    transaction on another connection, and schema creation would needlessly take
    a write lock.  Every public entry point initialises before getting here.
    """
    publication_id = int(row["id"])
    with appdb.connect(db_path) as conn:
        revision = conn.execute(
            """
            SELECT * FROM paper_publication_revisions
            WHERE publication_id = ?
            ORDER BY revision_number DESC LIMIT 1
            """,
            (publication_id,),
        ).fetchone()
        questions: list[str] = []
        if revision is not None:
            questions = [r["question_id"] for r in conn.execute(
                """
                SELECT question_id FROM paper_publication_questions
                WHERE revision_id = ? ORDER BY position
                """,
                (int(revision["id"]),),
            ).fetchall()]
        subscribed = conn.execute(
            "SELECT 1 FROM paper_subscriptions WHERE publication_id = ? AND user_id = ?",
            (publication_id, int(actor_user_id)),
        ).fetchone() is not None

    # Does the author still have unpublished edits?  Compare fingerprints rather
    # than exposing the living draft.
    has_unpublished = False
    if revision is not None and row["source_draft_id"] is not None:
        with appdb.connect(db_path) as conn:
            draft = conn.execute(
                "SELECT * FROM paper_drafts WHERE id = ?",
                (int(row["source_draft_id"]),),
            ).fetchone()
        if draft is not None:
            has_unpublished = specification_fingerprint(
                question_ids=draft["question_ids_json"],
                question_overrides=draft["question_overrides_json"],
                metadata=draft["metadata_json"],
                settings=draft["settings_json"],
            ) != str(revision["specification_fingerprint"])

    return {
        "id": publication_id,
        "title": row["title"],
        "message": row["message"],
        "course": row["course"] if "course" in row.keys() else "",
        "owner_user_id": int(row["owner_user_id"]),
        "source_draft_id": row["source_draft_id"],
        "revision_id": int(revision["id"]) if revision is not None else None,
        "revision_number": int(revision["revision_number"]) if revision is not None else 0,
        "question_ids": questions,
        "metadata": _json_dict(revision["metadata_json"]) if revision is not None else {},
        "settings": _json_dict(revision["settings_json"]) if revision is not None else {},
        "is_owner": int(row["owner_user_id"]) == int(actor_user_id),
        "is_subscribed": subscribed,
        "has_unpublished_changes": has_unpublished,
        "version": int(row["version"] or 1),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def paper_sharing_payload(db_path: Path | str, *, user_id: int,
                          course_id: str | None = None) -> dict[str, Any]:
    """Everything the My Papers tab needs, already filtered for this reader.

    ``course_id`` narrows the list to one course, so a shared AP Physics 2 paper
    does not clutter an AP Physics C teacher's view.
    """
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        actor = _actor_row(conn, user_id)
        where = "p.active = 1"
        params: list[Any] = []
        if course_id:
            where += " AND p.course = ?"
            params.append(str(course_id))
        rows = conn.execute(
            f"""
            SELECT p.*, u.display_name AS owner_display_name, u.username AS owner_username
            FROM paper_publications p
            JOIN users u ON u.id = p.owner_user_id
            WHERE {where}
            ORDER BY p.updated_at DESC, p.id DESC
            """,
            params,
        ).fetchall()
        publications = []
        for row in rows:
            access = paper_publication_access(conn, row, actor)
            if not access:
                continue
            payload = _publication_payload(db_path, row, actor_user_id=user_id)
            payload["owner_display_name"] = row["owner_display_name"]
            payload["owner_username"] = row["owner_username"]
            payload["folders"] = sorted(_folder_set(conn, row["id"]))
            payload["recipients"] = sorted(_recipient_set(conn, row["id"]))
            payload["access"] = sorted(access)
            publications.append(payload)

        notifications = [
            dict(r) for r in conn.execute(
                """
                SELECT * FROM paper_notifications
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 60
                """,
                (int(user_id),),
            ).fetchall()
        ]
        unread = int(conn.execute(
            "SELECT COUNT(*) AS count FROM paper_notifications "
            "WHERE user_id = ? AND read_at IS NULL",
            (int(user_id),),
        ).fetchone()["count"])
        people = [
            {"id": int(r["id"]), "display_name": r["display_name"],
             "username": r["username"], "role": r["role"]}
            for r in conn.execute(
                "SELECT id, display_name, username, role FROM users "
                "WHERE active = 1 ORDER BY display_name, username"
            ).fetchall()
        ]
    return {
        "publications": publications,
        "folders": list_paper_folders(db_path),
        "people": people,
        "notifications": notifications,
        "unread_notification_count": unread,
    }


def set_paper_subscription(db_path: Path | str, publication_id: int, *,
                           user_id: int, follow: bool) -> bool:
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        actor = _actor_row(conn, user_id)
        row = conn.execute(
            "SELECT * FROM paper_publications WHERE id = ? AND active = 1",
            (int(publication_id),),
        ).fetchone()
        if row is None:
            raise ValueError("This shared paper is no longer available")
        if not paper_publication_access(conn, row, actor):
            raise ValueError("This shared paper is no longer available")
        if int(row["owner_user_id"]) == int(user_id):
            raise ValueError("You cannot follow your own paper")
        if follow:
            conn.execute(
                """
                INSERT INTO paper_subscriptions (publication_id, user_id)
                VALUES (?, ?)
                ON CONFLICT(publication_id, user_id) DO UPDATE SET updated_at = {ts}
                """.format(ts=TS),
                (int(publication_id), int(user_id)),
            )
        else:
            conn.execute(
                "DELETE FROM paper_subscriptions WHERE publication_id = ? AND user_id = ?",
                (int(publication_id), int(user_id)),
            )
    return follow


def mark_paper_notifications_read(db_path: Path | str, *, user_id: int,
                                  notification_ids: Iterable[Any] = ()) -> int:
    """Mark some (or, with no ids, all) of *my* notifications as read."""
    init_papers(db_path)
    clean = clean_unique_positive_ids(notification_ids)
    with appdb.connect(db_path) as conn:
        if clean:
            placeholders = ",".join("?" for _ in clean)
            cursor = conn.execute(
                f"""
                UPDATE paper_notifications SET read_at = {TS}
                WHERE user_id = ? AND id IN ({placeholders}) AND read_at IS NULL
                """,
                [int(user_id), *clean],
            )
        else:
            cursor = conn.execute(
                f"""
                UPDATE paper_notifications SET read_at = {TS}
                WHERE user_id = ? AND read_at IS NULL
                """,
                (int(user_id),),
            )
    return int(cursor.rowcount)


def publication_source_update(db_path: Path | str, draft: dict[str, Any]) -> dict[str, Any] | None:
    """If this draft was copied from a shared paper, is there a newer revision?"""
    revision_id = draft.get("copied_from_revision_id")
    if not revision_id:
        return None
    init_papers(db_path)
    with appdb.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT publication_id, revision_number FROM paper_publication_revisions
            WHERE id = ?
            """,
            (int(revision_id),),
        ).fetchone()
        if row is None:
            return None
        latest = conn.execute(
            """
            SELECT * FROM paper_publication_revisions
            WHERE publication_id = ? ORDER BY revision_number DESC LIMIT 1
            """,
            (int(row["publication_id"]),),
        ).fetchone()
        publication = conn.execute(
            "SELECT * FROM paper_publications WHERE id = ? AND active = 1",
            (int(row["publication_id"]),),
        ).fetchone()
        if latest is None or publication is None:
            return None
        if int(latest["id"]) == int(revision_id):
            return None
    return {
        "publication_id": int(publication["id"]),
        "title": publication["title"],
        "latest_revision_id": int(latest["id"]),
        "latest_revision_number": int(latest["revision_number"]),
    }
