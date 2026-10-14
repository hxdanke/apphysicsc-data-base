"""End-to-end HTTP tests against the real FastAPI app.

The reference project starts a real server on port 0 and drives it with real
HTTP requests; that catches wiring mistakes (a router that was never included, a
dependency that raises) that unit tests over the helper functions cannot see.
Here TestClient gives the same coverage without binding a port.

Two invariants matter most:

* with login enforced, every API route except sign-in answers 401 until a cookie
  is presented;
* one teacher's saved paper is neither visible nor deletable by another, and the
  API says "not found" rather than "forbidden" so it never confirms existence.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402


def build_client(temp_dir: str):
    """Import a fresh copy of the app pointed at a throw-away database."""
    db = Path(temp_dir) / "app.sqlite"
    import os
    os.environ["QB_APP_DB"] = str(db)
    os.environ["QB_REQUIRE_LOGIN"] = "1"
    os.environ["QB_ADMIN_USERNAME"] = "admin"
    os.environ["QB_ADMIN_PASSWORD"] = "admin"

    for name in ("server.main", "server.appapi", "server.auth", "server.appdb",
                 "server.papers"):
        sys.modules.pop(name, None)

    from server.main import app
    return TestClient(app), db


class AuthFlowTest(unittest.TestCase):
    def test_api_is_locked_until_signed_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _ = build_client(temp_dir)
            self.assertEqual(client.get("/api/session").status_code, 200)
            self.assertEqual(client.get("/api/health").status_code, 200)
            for path in ("/api/questions", "/api/paper-drafts", "/api/stats",
                         "/api/paper-sharing", "/api/users"):
                self.assertEqual(client.get(path).status_code, 401, path)

    def test_login_sets_a_cookie_and_identifies_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _ = build_client(temp_dir)
            res = client.post("/api/session", json={"username": "admin",
                                                    "password": "admin"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["user"]["role"], "admin")
            self.assertIn("qb_session", res.cookies)
            self.assertNotIn("password_hash", res.json()["user"])

            me = client.get("/api/session").json()
            self.assertEqual(me["user"]["username"], "admin")
            # Now the protected routes open up.
            self.assertEqual(client.get("/api/paper-drafts").status_code, 200)

    def test_bad_password_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _ = build_client(temp_dir)
            res = client.post("/api/session", json={"username": "admin",
                                                    "password": "wrong"})
            self.assertEqual(res.status_code, 401)

    def test_logout_clears_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _ = build_client(temp_dir)
            client.post("/api/session", json={"username": "admin", "password": "admin"})
            client.post("/api/logout", json={})
            self.assertEqual(client.get("/api/paper-drafts").status_code, 401)

    def test_stale_tab_is_stopped_before_it_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            client.post("/api/session", json={"username": "admin", "password": "admin"})
            from server import appdb
            teacher = appdb.create_user(db, username="msli", display_name="Ms Li",
                                        role="teacher", password="physics2026")
            # Sign in as the teacher but keep claiming to be the admin.
            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "msli",
                                              "password": "physics2026"})
            res = client.post(
                "/api/paper-drafts",
                json={"name": "Wrong account"},
                headers={"X-QB-Expected-User-Id": "1"})
            self.assertEqual(res.status_code, 409)
            self.assertEqual(res.json()["code"], "session_user_mismatch")
            # Nothing was written.
            self.assertEqual(client.get("/api/paper-drafts").json()["drafts"], [])

    def test_admin_only_routes_reject_teachers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            from server import appdb
            appdb.create_user(db, username="msli", display_name="Ms Li",
                              role="teacher", password="physics2026")
            client.post("/api/session", json={"username": "msli",
                                              "password": "physics2026"})
            self.assertEqual(client.get("/api/users").status_code, 403)
            self.assertEqual(client.get("/api/activity").status_code, 403)


class SavedPaperApiTest(unittest.TestCase):
    def _two_teachers(self, client, db):
        from server import appdb
        author = appdb.create_user(db, username="author", display_name="Author",
                                   role="teacher", password="physics2026")
        reader = appdb.create_user(db, username="reader", display_name="Reader",
                                   role="teacher", password="physics2026")
        return author, reader

    def test_save_list_and_delete_my_own_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            author, _ = self._two_teachers(client, db)
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            saved = client.post("/api/paper-drafts", json={
                "name": "Unit 1 quiz",
                "question_ids": ["EB3-U1-1.1-Q2", "EB3-U1-1.1-Q5"],
                "settings": {"show_answer": True},
            }).json()["draft"]
            self.assertEqual(saved["question_ids"],
                             ["EB3-U1-1.1-Q2", "EB3-U1-1.1-Q5"])

            listed = client.get("/api/paper-drafts").json()["drafts"]
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["settings"], {"show_answer": True})

            self.assertEqual(
                client.post("/api/paper-drafts/delete",
                            json={"id": saved["id"]}).status_code, 200)
            self.assertEqual(client.get("/api/paper-drafts").json()["drafts"], [])

    def test_other_teacher_cannot_see_or_delete_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            author, reader = self._two_teachers(client, db)
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            draft = client.post("/api/paper-drafts", json={
                "name": "Private", "question_ids": ["Q1"]}).json()["draft"]

            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "reader",
                                              "password": "physics2026"})
            self.assertEqual(client.get("/api/paper-drafts").json()["drafts"], [])
            self.assertEqual(
                client.post("/api/paper-drafts/delete",
                            json={"id": draft["id"]}).status_code, 404)

    def test_conflicting_save_answers_409_with_a_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            author, _ = self._two_teachers(client, db)
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            draft = client.post("/api/paper-drafts", json={
                "name": "Quiz", "question_ids": ["Q1"]}).json()["draft"]
            client.post("/api/paper-drafts", json={
                "id": draft["id"], "version": draft["version"],
                "name": "Quiz", "question_ids": ["Q1", "Q2"]})
            stale = client.post("/api/paper-drafts", json={
                "id": draft["id"], "version": draft["version"],
                "name": "Stale", "question_ids": ["Q9"]})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["code"], "draft_conflict")


class SharingApiTest(unittest.TestCase):
    def test_publish_then_copy_then_withdraw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            from server import appdb
            author = appdb.create_user(db, username="author", display_name="Author",
                                       role="teacher", password="physics2026")
            reader = appdb.create_user(db, username="reader", display_name="Reader",
                                       role="teacher", password="physics2026")

            client.post("/api/session", json={"username": "admin", "password": "admin"})
            folder = client.post("/api/paper-folders", json={
                "name": "Department", "member_ids": [reader["id"]]}).json()["folder"]

            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            draft = client.post("/api/paper-drafts", json={
                "name": "Unit 1 quiz", "question_ids": ["Q1", "Q2"]}).json()["draft"]
            published = client.post("/api/paper-publications", json={
                "draft_id": draft["id"], "title": "Unit 1 quiz",
                "folder_ids": [folder["id"]]}).json()["publication"]
            self.assertEqual(published["question_ids"], ["Q1", "Q2"])

            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "reader",
                                              "password": "physics2026"})
            shared = client.get("/api/paper-sharing").json()
            self.assertEqual(len(shared["publications"]), 1)
            self.assertEqual(shared["unread_notification_count"], 1)

            copied = client.post("/api/paper-publications/copy", json={
                "publication_id": published["id"],
                "revision_id": published["revision_id"]}).json()["draft"]
            self.assertEqual(copied["question_ids"], ["Q1", "Q2"])
            self.assertEqual(len(client.get("/api/paper-drafts").json()["drafts"]), 1)

            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            self.assertEqual(client.post("/api/paper-publications/withdraw", json={
                "publication_id": published["id"]}).status_code, 200)
            client.post("/api/logout", json={})
            client.post("/api/session", json={"username": "reader",
                                              "password": "physics2026"})
            self.assertEqual(
                client.get("/api/paper-sharing").json()["publications"], [])

    def test_publish_needs_an_audience(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client, db = build_client(temp_dir)
            from server import appdb
            appdb.create_user(db, username="author", display_name="Author",
                              role="teacher", password="physics2026")
            client.post("/api/session", json={"username": "author",
                                              "password": "physics2026"})
            draft = client.post("/api/paper-drafts", json={
                "name": "Quiz", "question_ids": ["Q1"]}).json()["draft"]
            res = client.post("/api/paper-publications", json={
                "draft_id": draft["id"], "title": "Quiz"})
            self.assertEqual(res.status_code, 400)


class LoginDisabledTest(unittest.TestCase):
    def test_without_login_the_default_admin_owns_the_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            import os
            db = Path(temp_dir) / "app.sqlite"
            os.environ["QB_APP_DB"] = str(db)
            os.environ["QB_REQUIRE_LOGIN"] = "0"
            for name in ("server.main", "server.appapi", "server.auth",
                         "server.appdb", "server.papers"):
                sys.modules.pop(name, None)
            from server.main import app
            client = TestClient(app)

            self.assertEqual(client.get("/api/questions").status_code, 200)
            saved = client.post("/api/paper-drafts", json={
                "name": "Solo", "question_ids": ["Q1"]})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(len(client.get("/api/paper-drafts").json()["drafts"]), 1)
        os.environ["QB_REQUIRE_LOGIN"] = "1"


if __name__ == "__main__":
    unittest.main()
