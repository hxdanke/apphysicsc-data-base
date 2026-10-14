"""Accounts, sessions and the activity log.

These follow the reference application's approach: every public helper takes a
database *path* and initialises it itself, so a test can simply hand it a throw-
away file inside ``tempfile.TemporaryDirectory()`` and get perfect isolation
without any fixture machinery.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import appdb  # noqa: E402


def new_db(temp_dir: str) -> Path:
    return Path(temp_dir) / "app.sqlite"


class PasswordTest(unittest.TestCase):
    def test_hash_is_salted_and_verifiable(self) -> None:
        first = appdb.hash_password("correct horse")
        second = appdb.hash_password("correct horse")
        self.assertNotEqual(first, second, "each hash must carry its own salt")
        self.assertTrue(appdb.verify_password("correct horse", first))
        self.assertTrue(appdb.verify_password("correct horse", second))
        self.assertFalse(appdb.verify_password("wrong", first))

    def test_stored_hash_keeps_the_iteration_count(self) -> None:
        encoded = appdb.hash_password("abc12345")
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        self.assertEqual(algorithm, appdb.PASSWORD_ALGORITHM)
        self.assertEqual(int(iterations), appdb.PASSWORD_ITERATIONS)
        self.assertEqual(len(salt), 32)
        self.assertEqual(len(digest), 64)

    def test_malformed_hash_is_rejected_without_raising(self) -> None:
        for junk in ("", "nonsense", "pbkdf2_sha256$abc$salt$digest"):
            self.assertFalse(appdb.verify_password("abc12345", junk))


class AccountTest(unittest.TestCase):
    def test_default_admin_exists_and_can_sign_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            user = appdb.authenticate_user(db, username="admin", password="admin")
            self.assertIsNotNone(user)
            self.assertEqual(user["role"], "admin")
            self.assertIsNone(user["organization_id"])
            self.assertNotIn("password_hash", user)

    def test_init_db_is_idempotent_and_keeps_one_admin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            appdb.init_db(db)
            appdb.init_db(db)
            appdb.init_db(db)
            admins = [u for u in appdb.list_users(db) if u["role"] == "admin"]
            self.assertEqual(len(admins), 1)

    def test_wrong_password_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            self.assertIsNone(
                appdb.authenticate_user(db, username="admin", password="nope"))

    def test_teacher_is_created_inside_the_school_organisation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            self.assertEqual(teacher["role"], "teacher")
            self.assertIsNotNone(teacher["organization_id"])
            self.assertEqual(appdb.list_organizations(db)[0]["code"],
                             appdb.ORGANIZATION_CODE)

    def test_duplicate_username_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            appdb.create_user(db, username="dupe", display_name="A",
                              role="teacher", password="physics2026")
            with self.assertRaisesRegex(ValueError, "already exists"):
                appdb.create_user(db, username="dupe", display_name="B",
                                  role="teacher", password="physics2026")

    def test_short_password_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            with self.assertRaisesRegex(ValueError, "at least"):
                appdb.create_user(db, username="shorty", display_name="S",
                                  role="teacher", password="abc")

    def test_username_is_normalised(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            created = appdb.create_user(
                db, username="  MsLi@WHBC  ", display_name="Ms Li",
                role="teacher", password="physics2026")
            self.assertEqual(created["username"], "msli@whbc")
            self.assertIsNotNone(
                appdb.authenticate_user(db, username="MSLI@WHBC", password="physics2026"))

    def test_last_admin_cannot_be_demoted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            with self.assertRaisesRegex(ValueError, "At least one active admin"):
                appdb.update_user(db, admin["id"], role="teacher")

    def test_password_reset_signs_out_other_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            token = appdb.create_session(db, user_id=teacher["id"])
            self.assertIsNotNone(appdb.user_for_session_token(db, token))

            appdb.update_user(db, teacher["id"], password="brandnew99")
            self.assertIsNone(appdb.user_for_session_token(db, token))
            self.assertIsNotNone(
                appdb.authenticate_user(db, username="MsLi", password="brandnew99"))

    def test_self_service_password_change_keeps_own_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            keep = appdb.create_session(db, user_id=teacher["id"])
            other = appdb.create_session(db, user_id=teacher["id"])

            appdb.change_user_password(
                db, user_id=teacher["id"], current_password="physics2026",
                new_password="changed123", preserve_session_token=keep)

            self.assertIsNotNone(appdb.user_for_session_token(db, keep))
            self.assertIsNone(appdb.user_for_session_token(db, other))

    def test_self_service_password_change_needs_the_current_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            with self.assertRaisesRegex(ValueError, "Current password is incorrect"):
                appdb.change_user_password(
                    db, user_id=teacher["id"], current_password="wrong",
                    new_password="changed123")


class SessionTest(unittest.TestCase):
    def test_token_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            token = appdb.create_session(db, user_id=admin["id"])
            self.assertEqual(appdb.user_for_session_token(db, token)["id"], admin["id"])
            appdb.delete_session(db, token)
            self.assertIsNone(appdb.user_for_session_token(db, token))

    def test_only_the_digest_is_stored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            token = appdb.create_session(db, user_id=admin["id"])
            with appdb.connect(db) as conn:
                stored = conn.execute(
                    "SELECT token_hash FROM sessions").fetchone()["token_hash"]
            self.assertNotEqual(stored, token)
            self.assertEqual(stored, appdb.session_token_hash(token))

    def test_expired_session_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            token = appdb.create_session(db, user_id=admin["id"], ttl_seconds=-1)
            self.assertIsNone(appdb.user_for_session_token(db, token))

    def test_disabled_user_loses_access_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            token = appdb.create_session(db, user_id=teacher["id"])
            self.assertIsNotNone(appdb.user_for_session_token(db, token))
            appdb.update_user(db, teacher["id"], active=False)
            self.assertIsNone(appdb.user_for_session_token(db, token))

    def test_resume_is_recorded_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            token = appdb.create_session(db, user_id=admin["id"])
            self.assertTrue(appdb.mark_session_resumed(db, token))
            self.assertFalse(appdb.mark_session_resumed(db, token))


class ActivityLogTest(unittest.TestCase):
    def test_log_keeps_username_after_account_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = appdb.create_user(
                db, username="MsLi", display_name="Ms Li",
                role="teacher", password="physics2026")
            appdb.record_activity(db, user=teacher, action="export",
                                  entity_type="paper", entity_id="set1",
                                  summary="Built PDF with 12 question(s)")
            with appdb.connect(db) as conn:
                conn.execute("DELETE FROM users WHERE id = ?", (teacher["id"],))
            rows = appdb.list_activity_log(db, action="export")
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["user_id"])
            self.assertEqual(rows[0]["username"], "msli")

    def test_log_filters_by_action_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            for index in range(5):
                appdb.record_activity(db, user=admin, action="login", summary=f"#{index}")
            appdb.record_activity(db, user=admin, action="export", summary="once")
            self.assertEqual(len(appdb.list_activity_log(db, action="login")), 5)
            self.assertEqual(len(appdb.list_activity_log(db, action="export")), 1)
            self.assertEqual(len(appdb.list_activity_log(db, limit=2)), 2)


class GeneratedFileTest(unittest.TestCase):
    def test_ownership_is_scoped_to_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            owner = appdb.create_user(db, username="owner", display_name="Owner",
                                      role="teacher", password="physics2026")
            other = appdb.create_user(db, username="other", display_name="Other",
                                      role="teacher", password="physics2026")
            appdb.register_generated_files(db, user_id=owner["id"],
                                           paths=["exports/set1.pdf"])
            self.assertTrue(appdb.generated_file_owned_by(
                db, user_id=owner["id"], path="exports/set1.pdf"))
            self.assertFalse(appdb.generated_file_owned_by(
                db, user_id=other["id"], path="exports/set1.pdf"))

    def test_traversal_paths_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            appdb.register_generated_files(db, user_id=admin["id"],
                                           paths=["../../etc/passwd"])
            self.assertFalse(appdb.generated_file_owned_by(
                db, user_id=admin["id"], path="../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
