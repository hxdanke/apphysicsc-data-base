"""Drafts, sharing groups, immutable revisions and notifications.

The invariants tested here are the ones the reference application enforces:

* a draft is invisible to everybody but its owner;
* saving with a stale version is refused instead of silently overwriting;
* a published revision is append-only -- the author editing the draft afterwards
  must not change what a colleague already saw;
* re-publishing identical content is rejected rather than producing a duplicate;
* lose access and you lose the subscription and get told.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import appdb, papers  # noqa: E402


def new_db(temp_dir: str) -> Path:
    return Path(temp_dir) / "app.sqlite"


def make_teacher(db: Path, username: str, display: str, password: str = "physics2026"):
    return appdb.create_user(db, username=username, display_name=display,
                             role="teacher", password=password)


class DraftTest(unittest.TestCase):
    def test_draft_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = make_teacher(db, "msli", "Ms Li")
            saved = papers.save_paper_draft(
                db, user_id=teacher["id"], name="Unit 1 quiz",
                question_ids=["EB3-U1-1.1-Q2", "EB3-U1-1.1-Q5"],
                metadata={"title": "Quiz 1"}, settings={"show_answer": True})
            self.assertEqual(saved["version"], 1)
            reloaded = papers.list_paper_drafts(db, user_id=teacher["id"])[0]
            self.assertEqual(reloaded["question_ids"],
                             ["EB3-U1-1.1-Q2", "EB3-U1-1.1-Q5"])
            self.assertEqual(reloaded["metadata"], {"title": "Quiz 1"})
            self.assertEqual(reloaded["settings"], {"show_answer": True})

    def test_drafts_are_invisible_to_other_teachers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            owner = make_teacher(db, "owner", "Owner")
            other = make_teacher(db, "other", "Other")
            papers.save_paper_draft(db, user_id=owner["id"], name="Private",
                                    question_ids=["Q1"])
            self.assertEqual(len(papers.list_paper_drafts(db, user_id=owner["id"])), 1)
            self.assertEqual(papers.list_paper_drafts(db, user_id=other["id"]), [])

    def test_other_teacher_cannot_delete_or_save_over_a_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            owner = make_teacher(db, "owner", "Owner")
            other = make_teacher(db, "other", "Other")
            draft = papers.save_paper_draft(db, user_id=owner["id"], name="Private",
                                            question_ids=["Q1"])
            self.assertFalse(papers.delete_paper_draft(
                db, draft["id"], user_id=other["id"]))
            with self.assertRaisesRegex(ValueError, "not found"):
                papers.save_paper_draft(db, user_id=other["id"], name="Hijack",
                                        draft_id=draft["id"])
            self.assertTrue(papers.delete_paper_draft(
                db, draft["id"], user_id=owner["id"]))

    def test_stale_version_is_refused_with_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = make_teacher(db, "msli", "Ms Li")
            draft = papers.save_paper_draft(db, user_id=teacher["id"], name="Quiz",
                                            question_ids=["Q1"])
            papers.save_paper_draft(db, user_id=teacher["id"], name="Quiz",
                                    question_ids=["Q1", "Q2"],
                                    draft_id=draft["id"],
                                    expected_version=draft["version"])
            with self.assertRaises(papers.DraftConflictError):
                papers.save_paper_draft(db, user_id=teacher["id"], name="Stale",
                                        question_ids=["Q9"], draft_id=draft["id"],
                                        expected_version=draft["version"])

    def test_question_ids_keep_order_and_drop_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            teacher = make_teacher(db, "msli", "Ms Li")
            saved = papers.save_paper_draft(
                db, user_id=teacher["id"], name="Ordered",
                question_ids=["Q3", "Q1", "Q3", "", "Q2"])
            self.assertEqual(saved["question_ids"], ["Q3", "Q1", "Q2"])


class SharingGroupTest(unittest.TestCase):
    def test_folder_membership_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            a = make_teacher(db, "tea", "Teacher A")
            b = make_teacher(db, "teb", "Teacher B")
            folder = papers.save_paper_shared_folder(
                db, actor_user_id=admin["id"], name="Physics department",
                member_ids=[a["id"], b["id"]])
            listed = papers.list_paper_folders(db)[0]
            self.assertEqual(listed["name"], "Physics department")
            self.assertEqual(set(listed["members"]), {a["id"], b["id"]})

    def test_folder_name_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            with self.assertRaisesRegex(ValueError, "needs a name"):
                papers.save_paper_shared_folder(db, actor_user_id=admin["id"], name="  ")


class PublicationTest(unittest.TestCase):
    def _published(self, db: Path):
        author = make_teacher(db, "author", "Author")
        reader = make_teacher(db, "reader", "Reader")
        admin = appdb.authenticate_user(db, username="admin", password="admin")
        folder = papers.save_paper_shared_folder(
            db, actor_user_id=admin["id"], name="Department", member_ids=[reader["id"]])
        draft = papers.save_paper_draft(
            db, user_id=author["id"], name="Unit 1 quiz",
            question_ids=["Q1", "Q2"], metadata={"title": "Quiz"})
        publication = papers.publish_paper_draft(
            db, actor_user_id=author["id"], draft_id=draft["id"],
            title="Unit 1 quiz", folder_ids=[folder["id"]])
        return author, reader, draft, publication

    def test_publish_creates_a_revision_with_the_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            _, _, _, publication = self._published(db)
            self.assertEqual(publication["revision_number"], 1)
            self.assertEqual(publication["question_ids"], ["Q1", "Q2"])
            self.assertEqual(publication["title"], "Unit 1 quiz")
            self.assertTrue(publication["is_owner"])

    def test_reader_sees_the_paper_and_can_copy_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            _, reader, _, publication = self._published(db)
            shared = papers.paper_sharing_payload(db, user_id=reader["id"])
            self.assertEqual(len(shared["publications"]), 1)
            self.assertEqual(shared["publications"][0]["title"], "Unit 1 quiz")
            self.assertFalse(shared["publications"][0]["is_owner"])

            copy = papers.copy_paper_publication(
                db, publication["id"], actor_user_id=reader["id"])
            self.assertEqual(copy["question_ids"], ["Q1", "Q2"])
            self.assertEqual(copy["user_id"], reader["id"])
            self.assertEqual(copy["copied_from_revision_id"], publication["revision_id"])
            self.assertEqual(len(papers.list_paper_drafts(db, user_id=reader["id"])), 1)

    def test_outside_teacher_sees_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            _, reader, _, publication = self._published(db)
            stranger = make_teacher(db, "stranger", "Stranger")
            self.assertEqual(
                papers.paper_sharing_payload(db, user_id=stranger["id"])["publications"], [])
            with self.assertRaisesRegex(ValueError, "no longer available"):
                papers.copy_paper_publication(
                    db, publication["id"], actor_user_id=stranger["id"])

    def test_publish_twice_without_changes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author, _, draft, _ = self._published(db)
            with self.assertRaisesRegex(ValueError, "already up to date"):
                papers.publish_paper_draft(
                    db, actor_user_id=author["id"], draft_id=draft["id"],
                    title="Unit 1 quiz", folder_ids=[_first_folder(db)])

    def test_editing_the_draft_does_not_change_the_published_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author, reader, draft, publication = self._published(db)
            revision_id = publication["revision_id"]

            papers.save_paper_draft(db, user_id=author["id"], name="Unit 1 quiz",
                                    question_ids=["Q1", "Q2", "Q3", "Q4"],
                                    draft_id=draft["id"],
                                    expected_version=draft["version"])

            # The reader still sees the original two questions.
            shared = papers.paper_sharing_payload(db, user_id=reader["id"])
            self.assertEqual(shared["publications"][0]["question_ids"], ["Q1", "Q2"])
            self.assertEqual(shared["publications"][0]["revision_id"], revision_id)
            self.assertTrue(shared["publications"][0]["has_unpublished_changes"])

    def test_republish_appends_a_new_revision_and_keeps_the_old_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author, _, draft, publication = self._published(db)
            first_revision = publication["revision_id"]

            papers.save_paper_draft(db, user_id=author["id"], name="Unit 1 quiz",
                                    question_ids=["Q1", "Q2", "Q3"],
                                    draft_id=draft["id"],
                                    expected_version=draft["version"])
            updated = papers.publish_paper_draft(
                db, actor_user_id=author["id"], draft_id=draft["id"],
                title="Unit 1 quiz", folder_ids=[_first_folder(db)])

            self.assertEqual(updated["revision_number"], 2)
            self.assertNotEqual(updated["revision_id"], first_revision)
            # The previous revision is still on disk, untouched.
            with appdb.connect(db) as conn:
                old = conn.execute(
                    "SELECT question_id FROM paper_publication_questions "
                    "WHERE revision_id = ? ORDER BY position",
                    (first_revision,),
                ).fetchall()
            self.assertEqual([r["question_id"] for r in old], ["Q1", "Q2"])

    def test_private_usage_settings_are_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author = make_teacher(db, "author", "Author")
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            folder = papers.save_paper_shared_folder(
                db, actor_user_id=admin["id"], name="Dept", member_ids=[])
            draft = papers.save_paper_draft(
                db, user_id=author["id"], name="Quiz", question_ids=["Q1"],
                settings={"show_answer": False,
                          "question_exclusions": ["EB3-U1-1.1-Q2"]})
            publication = papers.publish_paper_draft(
                db, actor_user_id=author["id"], draft_id=draft["id"],
                title="Quiz", folder_ids=[folder["id"]])
            self.assertNotIn("question_exclusions", publication["settings"])

    def test_withdraw_hides_the_paper_and_tells_the_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author, reader, _, publication = self._published(db)
            self.assertTrue(papers.withdraw_paper_publication(
                db, publication["id"], actor_user_id=author["id"]))
            shared = papers.paper_sharing_payload(db, user_id=reader["id"])
            self.assertEqual(shared["publications"], [])
            self.assertTrue(
                any(n["event_type"] == "withdrawn" for n in shared["notifications"]))

    def test_only_the_owner_can_withdraw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            _, reader, _, publication = self._published(db)
            with self.assertRaisesRegex(ValueError, "Only the paper owner"):
                papers.withdraw_paper_publication(
                    db, publication["id"], actor_user_id=reader["id"])


def _first_folder(db: Path) -> int:
    return papers.list_paper_folders(db)[0]["id"]


class NotificationTest(unittest.TestCase):
    def test_being_shared_creates_a_notification_and_a_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author = make_teacher(db, "author", "Author")
            reader = make_teacher(db, "reader", "Reader")
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            folder = papers.save_paper_shared_folder(
                db, actor_user_id=admin["id"], name="Dept", member_ids=[reader["id"]])
            draft = papers.save_paper_draft(db, user_id=author["id"], name="Quiz",
                                            question_ids=["Q1"])
            papers.publish_paper_draft(db, actor_user_id=author["id"],
                                       draft_id=draft["id"], title="Quiz",
                                       folder_ids=[folder["id"]])
            shared = papers.paper_sharing_payload(db, user_id=reader["id"])
            self.assertEqual(shared["unread_notification_count"], 1)
            self.assertTrue(shared["publications"][0]["is_subscribed"])

    def test_marking_read_only_touches_my_own_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author = make_teacher(db, "author", "Author")
            reader = make_teacher(db, "reader", "Reader")
            other = make_teacher(db, "other", "Other")
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            folder = papers.save_paper_shared_folder(
                db, actor_user_id=admin["id"], name="Dept",
                member_ids=[reader["id"], other["id"]])
            draft = papers.save_paper_draft(db, user_id=author["id"], name="Quiz",
                                            question_ids=["Q1"])
            papers.publish_paper_draft(db, actor_user_id=author["id"],
                                       draft_id=draft["id"], title="Quiz",
                                       folder_ids=[folder["id"]])
            self.assertEqual(papers.mark_paper_notifications_read(
                db, user_id=reader["id"]), 1)
            self.assertEqual(
                papers.paper_sharing_payload(db, user_id=reader["id"])
                ["unread_notification_count"], 0)
            # The colleague's own notification is untouched.
            self.assertEqual(
                papers.paper_sharing_payload(db, user_id=other["id"])
                ["unread_notification_count"], 1)

    def test_cannot_follow_your_own_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = new_db(temp_dir)
            author = make_teacher(db, "author", "Author")
            admin = appdb.authenticate_user(db, username="admin", password="admin")
            folder = papers.save_paper_shared_folder(
                db, actor_user_id=admin["id"], name="Dept", member_ids=[])
            draft = papers.save_paper_draft(db, user_id=author["id"], name="Quiz",
                                            question_ids=["Q1"])
            publication = papers.publish_paper_draft(
                db, actor_user_id=author["id"], draft_id=draft["id"],
                title="Quiz", folder_ids=[folder["id"]])
            with self.assertRaisesRegex(ValueError, "cannot follow your own"):
                papers.set_paper_subscription(db, publication["id"],
                                              user_id=author["id"], follow=True)


if __name__ == "__main__":
    unittest.main()
