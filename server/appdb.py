"""Application state: accounts, sessions, activity log, generated-file ownership.

This is the SQLite half of the project and it is deliberately separate from the
question bank.  ``data/bank.json`` stays the authoritative, git-friendly store
for question *content*; ``data/app.sqlite`` holds server-owned *live app state*
-- who can sign in, which saved papers belong to whom, what was shared with
whom, and what happened when.

The design follows the reference question-bank application:

* passwords are ``pbkdf2_sha256`` with a per-user random salt, and the iteration
  count travels inside the stored string so it can be raised later;
* the browser only ever holds an opaque session token -- the database stores its
  SHA-256 digest, so a leaked database cannot be replayed as a login;
* every mutation of interest writes an ``activity_log`` row, which keeps the
  ``username``/``role`` denormalised so history survives account deletion.

Every public function takes a ``Path`` and calls ``init_db`` itself, so callers
never have to remember to migrate first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_APP_DB = Path(DATA_DIR) / "app.sqlite"

USER_ROLES = ("admin", "teacher", "student")

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
MIN_PASSWORD_LENGTH = 8
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30          # 30 days

# The project timestamps app state in Shanghai time so that an operator reading
# the database sees the same clock the school works on.
TIMESTAMP_EXPR = "datetime('now', '+8 hours')"

ORGANIZATION_CODE = "WHBC"
ORGANIZATION_NAME = "Wuhan Britain-China School"

DEFAULT_COURSE_ID = "ap-physics-c-mechanics"


def timestamp_expr(offset: str | None = None) -> str:
    """SQL expression for "now" (Shanghai time), optionally shifted.

    ``offset`` is a SQLite modifier such as ``'-7 days'``.
    """
    if not offset:
        return TIMESTAMP_EXPR
    return f"datetime('now', '+8 hours', '{offset}')"


# --------------------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------------------

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS organizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR}),
  updated_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR})
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'teacher' CHECK(role IN ('admin', 'teacher', 'student')),
  organization_id INTEGER REFERENCES organizations(id) ON DELETE RESTRICT,
  password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR}),
  updated_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR}),
  last_login_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role_active ON users(role, active);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR}),
  last_seen_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR}),
  resumed_at TEXT,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS generated_files (
  path TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR})
);

CREATE INDEX IF NOT EXISTS idx_generated_files_user_created
  ON generated_files(user_id, created_at);

CREATE TABLE IF NOT EXISTS activity_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  username TEXT,
  role TEXT,
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  summary TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL DEFAULT ({TIMESTAMP_EXPR})
);

CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_action ON activity_log(action);
CREATE INDEX IF NOT EXISTS idx_activity_log_user_created_at
  ON activity_log(user_id, created_at);
"""


@contextmanager
def connect(db_path: Path | str):
    """Open the app database with dict-like rows and sane concurrency settings."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release.  Idempotent."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "resumed_at" not in existing:
        conn.execute("ALTER TABLE sessions ADD COLUMN resumed_at TEXT")


def init_db(db_path: Path | str, *, ensure_admin: bool = True) -> None:
    """Create or migrate the app database.  Safe to call on every request."""
    path = Path(db_path)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        ensure_columns(conn)
        if ensure_admin:
            org_id = ensure_organization(conn)
            ensure_default_admin(conn)
            backfill_organization(conn, org_id)


# --------------------------------------------------------------------------------------
# organisations
# --------------------------------------------------------------------------------------

def ensure_organization(conn: sqlite3.Connection) -> int:
    """Create the single school organisation and return its id."""
    row = conn.execute(
        "SELECT id FROM organizations WHERE code = ?", (ORGANIZATION_CODE,)
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE organizations SET name = ?, active = 1 WHERE id = ?",
            (ORGANIZATION_NAME, int(row["id"])),
        )
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO organizations (code, name) VALUES (?, ?)",
        (ORGANIZATION_CODE, ORGANIZATION_NAME),
    )
    return int(cursor.lastrowid)


def backfill_organization(conn: sqlite3.Connection, org_id: int) -> None:
    """Give every teacher/student the school organisation if they lack one."""
    conn.execute(
        """
        UPDATE users
        SET organization_id = ?
        WHERE organization_id IS NULL AND role IN ('teacher', 'student')
        """,
        (org_id,),
    )


def list_organizations(db_path: Path | str) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM organizations ORDER BY code"
        ).fetchall()
    return [dict(row) for row in rows]


def active_organization_id(conn: sqlite3.Connection, wanted: Any = None) -> int:
    if wanted is not None:
        row = conn.execute(
            "SELECT id FROM organizations WHERE id = ? AND active = 1", (wanted,)
        ).fetchone()
        if row is not None:
            return int(row["id"])
    row = conn.execute(
        "SELECT id FROM organizations WHERE active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No active organization is configured")
    return int(row["id"])


# --------------------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = encoded.split("$", 3)
        iterations = int(iterations_text)
    except (ValueError, AttributeError):
        return False
    if algorithm != PASSWORD_ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)


# --------------------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------------------

def normalize_username(username: str) -> str:
    normalized = re.sub(r"\s+", "", str(username or "").strip().lower())
    if not normalized:
        raise ValueError("Username is required")
    if not re.fullmatch(r"[a-z0-9_.@-]{2,64}", normalized):
        raise ValueError(
            "Username must use 2-64 letters, numbers, dots, underscores, @, or hyphens"
        )
    return normalized


def normalize_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in USER_ROLES:
        raise ValueError(f"Unsupported role: {role}")
    return normalized


def ensure_default_admin(conn: sqlite3.Connection) -> int:
    """Guarantee one working admin account exists.  Idempotent."""
    row = conn.execute(
        "SELECT id FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row is not None:
        return int(row["id"])

    username = normalize_username(os.environ.get("QB_ADMIN_USERNAME") or "admin")
    display_name = (os.environ.get("QB_ADMIN_DISPLAY_NAME") or "Admin").strip() or "Admin"
    password = os.environ.get("QB_ADMIN_PASSWORD") or "admin"

    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE users SET display_name = ?, role = 'admin', active = 1 WHERE id = ?",
            (display_name, int(existing["id"])),
        )
        return int(existing["id"])
    cursor = conn.execute(
        """
        INSERT INTO users (username, display_name, role, password_hash, active)
        VALUES (?, ?, 'admin', ?, 1)
        """,
        (username, display_name, hash_password(password)),
    )
    return int(cursor.lastrowid)


def default_admin_user_id(db_path: Path | str) -> int:
    """The admin account drafts fall back to when login is disabled."""
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if row is not None:
            return int(row["id"])
        return ensure_default_admin(conn)


def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    """The user shape the browser is allowed to see (never the hash)."""
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "organization_id": row["organization_id"],
        "organization_code": row["organization_code"] if "organization_code" in row.keys() else None,
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login_at": row["last_login_at"],
    }


_USER_SELECT = """
    SELECT u.*, o.code AS organization_code
    FROM users u
    LEFT JOIN organizations o ON o.id = u.organization_id
"""


def create_user(db_path: Path | str, *, username: str, display_name: str,
                role: str = "teacher", password: str = "",
                organization_id: int | None = None,
                active: bool = True) -> dict[str, Any]:
    init_db(db_path)
    clean_username = normalize_username(username)
    clean_role = normalize_role(role)
    clean_display = (display_name or "").strip() or clean_username
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    with connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (clean_username,)
        ).fetchone():
            raise ValueError(f"Username already exists: {clean_username}")
        # An admin works across the whole school; everyone else belongs to it.
        org_id = None if clean_role == "admin" else active_organization_id(conn, organization_id)
        cursor = conn.execute(
            """
            INSERT INTO users
              (username, display_name, role, organization_id, password_hash, active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (clean_username, clean_display, clean_role, org_id,
             hash_password(password), 1 if active else 0),
        )
        row = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(cursor.lastrowid),)
        ).fetchone()
    return user_payload(row)


def update_user(db_path: Path | str, user_id: int, *, username: str | None = None,
                display_name: str | None = None, role: str | None = None,
                password: str | None = None, active: bool | None = None,
                organization_id: int | None = None) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(user_id),)
        ).fetchone()
        if row is None:
            raise ValueError(f"User not found: {user_id}")

        next_username = normalize_username(username) if username else row["username"]
        next_role = normalize_role(role) if role else row["role"]
        next_active = bool(row["active"]) if active is None else bool(active)
        next_display = row["display_name"] if display_name is None else display_name.strip()
        next_org = (None if next_role == "admin"
                    else active_organization_id(conn, organization_id))

        # Never let the last admin demote or disable itself.
        if row["role"] == "admin" and (next_role != "admin" or not next_active):
            others = int(conn.execute(
                "SELECT COUNT(*) AS count FROM users "
                "WHERE role = 'admin' AND active = 1 AND id != ?",
                (int(user_id),),
            ).fetchone()["count"])
            if others == 0:
                raise ValueError("At least one active admin is required")

        if next_username != row["username"] and conn.execute(
            "SELECT 1 FROM users WHERE username = ? AND id != ?",
            (next_username, int(user_id)),
        ).fetchone():
            raise ValueError(f"Username already exists: {next_username}")

        conn.execute(
            """
            UPDATE users
            SET username = ?, display_name = ?, role = ?, organization_id = ?,
                active = ?, updated_at = {ts}
            WHERE id = ?
            """.format(ts=TIMESTAMP_EXPR),
            (next_username, next_display, next_role, next_org,
             1 if next_active else 0, int(user_id)),
        )
        # A password reset must invalidate every session that used the old one.
        if password:
            if len(password) < MIN_PASSWORD_LENGTH:
                raise ValueError(
                    f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), int(user_id)),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))

        row = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(user_id),)
        ).fetchone()
    return user_payload(row)


def list_users(db_path: Path | str) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            _USER_SELECT + " ORDER BY u.role, u.username"
        ).fetchall()
        logins = {
            int(row["user_id"]): row["last_login_at"]
            for row in conn.execute(
                """
                SELECT user_id, MAX(created_at) AS last_login_at
                FROM activity_log
                WHERE action = 'login' AND user_id IS NOT NULL
                GROUP BY user_id
                """
            ).fetchall()
        }
    out = []
    for row in rows:
        payload = user_payload(row)
        payload["last_login_at"] = logins.get(payload["id"])
        out.append(payload)
    return out


def authenticate_user(db_path: Path | str, *, username: str, password: str) -> dict[str, Any] | None:
    init_db(db_path)
    clean = normalize_username(username)
    with connect(db_path) as conn:
        row = conn.execute(
            _USER_SELECT + " WHERE u.username = ?", (clean,)
        ).fetchone()
        if row is None or not bool(row["active"]):
            return None
        if not verify_password(password or "", row["password_hash"]):
            return None
        conn.execute(
            f"UPDATE users SET last_login_at = {TIMESTAMP_EXPR} WHERE id = ?",
            (int(row["id"]),),
        )
        refreshed = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(row["id"]),)
        ).fetchone()
    return user_payload(refreshed)


def change_user_password(db_path: Path | str, *, user_id: int, current_password: str,
                         new_password: str,
                         preserve_session_token: str | None = None) -> dict[str, Any]:
    """Self-service password change: keeps the caller's own session alive."""
    init_db(db_path)
    if len(new_password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"New password must be at least {MIN_PASSWORD_LENGTH} characters")
    with connect(db_path) as conn:
        row = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(user_id),)
        ).fetchone()
        if row is None:
            raise ValueError("User not found")
        if not verify_password(current_password or "", row["password_hash"]):
            raise ValueError("Current password is incorrect")
        if verify_password(new_password, row["password_hash"]):
            raise ValueError("New password must be different from the current password")
        conn.execute(
            f"UPDATE users SET password_hash = ?, updated_at = {TIMESTAMP_EXPR} WHERE id = ?",
            (hash_password(new_password), int(user_id)),
        )
        if preserve_session_token:
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (int(user_id), session_token_hash(preserve_session_token)),
            )
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
        refreshed = conn.execute(
            _USER_SELECT + " WHERE u.id = ?", (int(user_id),)
        ).fetchone()
    return user_payload(refreshed)


# --------------------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------------------

def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db_path: Path | str, *, user_id: int,
                   ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    init_db(db_path)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with connect(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (session_token_hash(token), int(user_id), now + ttl_seconds),
        )
    return token


def user_for_session_token(db_path: Path | str, token: str | None) -> dict[str, Any] | None:
    init_db(db_path)
    if not token:
        return None
    token_hash = session_token_hash(token)
    now = int(time.time())
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.*, o.code AS organization_code
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ? OR expires_at <= ?",
                (token_hash, now),
            )
            return None
        conn.execute(
            f"UPDATE sessions SET last_seen_at = {TIMESTAMP_EXPR} WHERE token_hash = ?",
            (token_hash,),
        )
    return user_payload(row)


def delete_session(db_path: Path | str, token: str | None) -> None:
    if not token:
        return
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (session_token_hash(token),))


def mark_session_resumed(db_path: Path | str, token: str | None) -> bool:
    """Record the first time a browser tab is re-seen, so we log it once only."""
    if not token:
        return False
    init_db(db_path)
    token_hash = session_token_hash(token)
    with connect(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE sessions SET resumed_at = {TIMESTAMP_EXPR}
            WHERE token_hash = ? AND resumed_at IS NULL
            """,
            (token_hash,),
        )
        return cursor.rowcount > 0


# --------------------------------------------------------------------------------------
# activity log
# --------------------------------------------------------------------------------------

def record_activity(db_path: Path | str, *, user: dict[str, Any] | None, action: str,
                    entity_type: str | None = None, entity_id: Any | None = None,
                    summary: str | None = None,
                    metadata: dict[str, Any] | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO activity_log
              (user_id, username, role, action, entity_type, entity_id, summary, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user["id"]) if user and user.get("id") is not None else None,
                str(user.get("username")) if user else None,
                str(user.get("role")) if user else None,
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                summary,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )


def list_activity_log(db_path: Path | str, *, limit: int = 100,
                      user_id: int | None = None, days: int | None = None,
                      action: str | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    clean_limit = max(1, min(int(limit), 500))
    clauses = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(int(user_id))
    if days is not None:
        clean_days = max(1, min(int(days), 3650))
        clauses.append(f"created_at >= {timestamp_expr(f'-{clean_days} days')}")
    if action:
        clauses.append("action = ?")
        params.append(str(action).strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(clean_limit)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM activity_log {where} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            item["metadata"] = {}
        out.append(item)
    return out


# --------------------------------------------------------------------------------------
# generated files
# --------------------------------------------------------------------------------------

def register_generated_files(db_path: Path | str, *, user_id: int,
                             paths: Iterable[str]) -> None:
    """Record that these export artifacts belong to `user_id`."""
    init_db(db_path)
    clean = []
    for raw in paths or ():
        rel = str(raw).replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        clean.append(rel)
    if not clean:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO generated_files (path, user_id)
            VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET
              user_id = excluded.user_id,
              created_at = {ts}
            """.format(ts=TIMESTAMP_EXPR),
            ((path, int(user_id)) for path in clean),
        )
        # Housekeeping: ownership records are only needed while files linger.
        conn.execute(
            f"DELETE FROM generated_files WHERE created_at < {timestamp_expr('-7 days')}"
        )


def generated_file_owned_by(db_path: Path | str, *, user_id: int, path: str) -> bool:
    clean_path = str(path).replace("\\", "/").lstrip("/")
    if not clean_path or ".." in clean_path.split("/"):
        return False
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM generated_files WHERE path = ? AND user_id = ?",
            (clean_path, int(user_id)),
        ).fetchone()
    return row is not None
