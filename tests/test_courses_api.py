"""HTTP surface for the multi-course, recycle-bin and authoring features.

These drive the real FastAPI app against a temporary data root, so they check the
wiring (routes, course parameters, request bodies) rather than the helper
functions underneath.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from test_courses import seed_data_root  # noqa: E402


class CourseApiMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = seed_data_root(self._temp.name)
        self._previous_data = os.environ.get("QB_DATA_DIR")
        self._previous_db = os.environ.get("QB_APP_DB")
        self._previous_login = os.environ.get("QB_REQUIRE_LOGIN")
        os.environ["QB_DATA_DIR"] = self.data_dir
        os.environ["QB_APP_DB"] = str(Path(self._temp.name) / "app.sqlite")
        os.environ["QB_REQUIRE_LOGIN"] = "0"
        conftest.reload_server_modules()
        from server.main import app
        self.client = TestClient(app)

    def tearDown(self) -> None:
        def restore(name, value):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

        restore("QB_DATA_DIR", self._previous_data)
        restore("QB_APP_DB", self._previous_db)
        restore("QB_REQUIRE_LOGIN", self._previous_login)
        conftest.reload_server_modules()
        self._temp.cleanup()


class CourseListingTest(CourseApiMixin):
    def test_courses_are_listed_with_their_question_counts(self) -> None:
        payload = self.client.get("/api/courses").json()
        ids = [c["id"] for c in payload["courses"]]
        self.assertEqual(ids, ["apc-mech", "apc-em", "ap1", "ap2"])
        self.assertEqual(payload["default"], "apc-mech")
        for course in payload["courses"]:
            self.assertEqual(course["questions"], 1, course["id"])
            self.assertTrue(course["title"])
            self.assertTrue(course["short"])

    def test_questions_are_scoped_to_the_requested_course(self) -> None:
        for course_id in ("apc-mech", "apc-em", "ap1", "ap2"):
            payload = self.client.get(
                f"/api/questions?course={course_id}").json()
            ids = [q["id"] for q in payload["questions"]]
            self.assertEqual(ids, [f"{course_id.upper()}-Q1"], course_id)
            self.assertEqual(payload["course"], course_id)

    def test_taxonomy_is_per_course(self) -> None:
        for course_id in ("apc-em", "ap1", "ap2"):
            tax = self.client.get(f"/api/taxonomy?course={course_id}").json()
            self.assertEqual(tax["course"], course_id)
            self.assertEqual(len(tax["units"]), 2)

    def test_an_unknown_course_falls_back_instead_of_failing(self) -> None:
        payload = self.client.get("/api/questions?course=does-not-exist").json()
        self.assertEqual(payload["course"], "apc-mech")


class RecycleBinApiTest(CourseApiMixin):
    def _delete(self, course_id: str, question_id: str):
        return self.client.delete(
            f"/api/questions/{question_id}?course={course_id}")

    def test_delete_sends_the_question_to_the_bin(self) -> None:
        res = self._delete("ap1", "AP1-Q1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("recycled", res.json())

        self.assertEqual(
            self.client.get("/api/questions?course=ap1").json()["questions"], [])
        bin_items = self.client.get("/api/recycle?course=ap1").json()
        self.assertEqual(bin_items["retention_days"], 30)
        self.assertEqual([i["id"] for i in bin_items["items"]], ["AP1-Q1"])
        self.assertEqual(bin_items["items"][0]["days_left"], 30)

    def test_the_bin_is_per_course(self) -> None:
        self._delete("ap1", "AP1-Q1")
        self.assertEqual(self.client.get("/api/recycle?course=ap1")
                         .json()["items"][0]["id"], "AP1-Q1")
        self.assertEqual(self.client.get("/api/recycle?course=ap2")
                         .json()["items"], [])

    def test_restore_brings_it_back(self) -> None:
        self._delete("ap1", "AP1-Q1")
        res = self.client.post("/api/recycle/restore?course=ap1",
                               json={"id": "AP1-Q1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            [q["id"] for q in
             self.client.get("/api/questions?course=ap1").json()["questions"]],
            ["AP1-Q1"])
        self.assertEqual(self.client.get("/api/recycle?course=ap1")
                         .json()["items"], [])

    def test_purge_removes_it_for_good(self) -> None:
        self._delete("ap1", "AP1-Q1")
        self.assertEqual(self.client.post("/api/recycle/purge?course=ap1",
                                          json={"id": "AP1-Q1"}).status_code, 200)
        self.assertEqual(self.client.get("/api/recycle?course=ap1")
                         .json()["items"], [])
        self.assertEqual(
            self.client.get("/api/questions?course=ap1").json()["questions"], [])
        self.assertEqual(self.client.post("/api/recycle/purge?course=ap1",
                                          json={"id": "AP1-Q1"}).status_code, 404)

    def test_empty_clears_the_bin(self) -> None:
        self._delete("ap1", "AP1-Q1")
        res = self.client.post("/api/recycle/empty?course=ap1").json()
        self.assertEqual(res["removed"], 1)
        self.assertEqual(self.client.get("/api/recycle?course=ap1")
                         .json()["items"], [])

    def test_restoring_something_not_in_the_bin_is_a_404(self) -> None:
        self.assertEqual(self.client.post("/api/recycle/restore?course=ap1",
                                          json={"id": "NOPE"}).status_code, 404)

    def test_deleting_a_question_that_is_not_there_is_a_404(self) -> None:
        self.assertEqual(self._delete("ap1", "NOPE").status_code, 404)


class AuthoringApiTest(CourseApiMixin):
    def _author(self, **overrides):
        body = {
            "course": "apc-em",
            "unit": 1,
            "topic": "1.2",
            "additional_topics": ["2.1"],
            "qtype": "mcq",
            "stem_blocks": [
                {"type": "text", "text": "A hand-written stem about $\\vec{E}$."},
                {"type": "image", "path": ""},
                {"type": "text", "text": "Which of the following is correct?"},
            ],
            "choices": [{"label": "A", "text": "one"}, {"label": "B", "text": "two"}],
            "answer": "A",
            "solution": "Because.",
        }
        body.update(overrides)
        return self.client.post("/api/questions", json=body)

    def test_authored_question_is_stored_in_its_course(self) -> None:
        res = self._author()
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["created"])
        question = payload["question"]
        self.assertTrue(question["id"].startswith("APCE-U1-1.2-Q"),
                        question["id"])
        self.assertEqual(question["topic"], "1.2")
        self.assertEqual(question["unit"], 1)
        self.assertEqual(question["topic_title"], "Topic One-Two")
        self.assertEqual(question["choices"][0]["label"], "A")

        ids = [q["id"] for q in
               self.client.get("/api/questions?course=apc-em").json()["questions"]]
        self.assertIn(question["id"], ids)
        # ...and nowhere else
        for other in ("apc-mech", "ap1", "ap2"):
            found = [q["id"] for q in
                     self.client.get(f"/api/questions?course={other}").json()["questions"]]
            self.assertNotIn(question["id"], found, other)

    def test_the_stem_is_derived_from_the_blocks(self) -> None:
        question = self._author().json()["question"]
        self.assertIn("hand-written stem", question["stem"])
        self.assertIn("Which of the following", question["stem"])
        # an empty image block falls back to the placeholder figure
        self.assertIn("placeholder.png", question["stem"])
        self.assertEqual(len(question["stem_blocks"]), 3)

    def test_additional_topics_are_saved_and_searchable(self) -> None:
        question = self._author().json()["question"]
        self.assertEqual(question["additional_topics"], ["2.1"])

        by_topic = self.client.get(
            "/api/questions?course=apc-em&topic=2.1").json()
        self.assertIn(question["id"], [q["id"] for q in by_topic["questions"]])

        by_unit = self.client.get("/api/questions?course=apc-em&unit=2").json()
        self.assertIn(question["id"], [q["id"] for q in by_unit["questions"]])

    def test_an_unknown_topic_is_rejected(self) -> None:
        res = self._author(topic="9.9")
        self.assertEqual(res.status_code, 400)
        self.assertIn("unknown topic", res.json()["error"])

    def test_a_question_needs_a_knowledge_block(self) -> None:
        res = self._author(topic="")
        self.assertEqual(res.status_code, 400)

    def test_an_existing_question_can_gain_more_knowledge_blocks(self) -> None:
        res = self.client.patch("/api/questions/AP1-Q1?course=ap1",
                                json={"additional_topics": ["1.2", "2.1"]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["additional_topics"], ["1.2", "2.1"])

        self.assertIn("AP1-Q1",
                      [q["id"] for q in self.client.get(
                          "/api/questions?course=ap1&topic=2.1").json()["questions"]])
        # the other banks are untouched
        self.assertEqual(self.client.get("/api/questions?course=ap2")
                         .json()["questions"][0].get("additional_topics"), [])

    def test_the_primary_topic_is_never_duplicated_as_additional(self) -> None:
        res = self.client.patch("/api/questions/AP1-Q1?course=ap1",
                                json={"additional_topics": ["1.1", "1.2"]})
        self.assertEqual(res.json()["additional_topics"], ["1.2"])

    def test_unknown_additional_topics_are_dropped(self) -> None:
        res = self.client.patch("/api/questions/AP1-Q1?course=ap1",
                                json={"additional_topics": ["1.2", "9.9"]})
        self.assertEqual(res.json()["additional_topics"], ["1.2"])

    def test_editing_the_stem_directly_clears_the_blocks(self) -> None:
        self._author(stem_blocks=[{"type": "text", "text": "blocks"}])
        res = self.client.patch("/api/questions/APCE-U1-1.2-Q1?course=apc-em",
                                json={"stem": "typed directly"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["stem"], "typed directly")
        self.assertNotIn("stem_blocks", res.json())

    def test_upload_returns_a_namespaced_media_path(self) -> None:
        res = self.client.post(
            "/api/uploads?course=apc-em",
            files={"file": ("figure.png", b"fake-png-bytes", "image/png")})
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["path"].startswith("media/apce_"), payload["path"])
        self.assertTrue(payload["path"].endswith(".png"))

    def test_upload_rejects_a_non_image(self) -> None:
        res = self.client.post(
            "/api/uploads?course=ap1",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
        self.assertEqual(res.status_code, 400)


class PaperCourseIsolationApiTest(CourseApiMixin):
    def test_a_draft_belongs_to_one_course(self) -> None:
        saved = self.client.post("/api/paper-drafts", json={
            "name": "E&M quiz", "course": "apc-em",
            "question_ids": ["APC-EM-Q1"]}).json()["draft"]
        self.assertEqual(saved["course"], "apc-em")

        self.assertEqual(
            [d["id"] for d in self.client.get(
                "/api/paper-drafts?course=apc-em").json()["drafts"]],
            [saved["id"]])
        for other in ("apc-mech", "ap1", "ap2"):
            self.assertEqual(
                self.client.get(f"/api/paper-drafts?course={other}").json()["drafts"],
                [], other)

    def test_sharing_is_scoped_to_a_course(self) -> None:
        self.assertEqual(
            self.client.get("/api/paper-sharing?course=ap1").json()["course"], "ap1")
        self.assertEqual(
            self.client.get("/api/paper-sharing?course=ap1").json()["publications"], [])

    def test_export_only_reaches_its_own_course(self) -> None:
        res = self.client.post("/api/export/latex", json={
            "course": "apc-em", "ids": ["APC-EM-Q1"], "filename": "em"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 1)
        # A question id from another course is simply not found here.
        res = self.client.post("/api/export/latex", json={
            "course": "ap1", "ids": ["APC-EM-Q1"], "filename": "leak"})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
