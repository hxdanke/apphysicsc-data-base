"""Multi-course banks, the recycle bin, block stems and extra knowledge blocks.

Every test runs against a throw-away data root (``QB_DATA_DIR``) holding four
tiny courses, so nothing here can touch the real bank.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import conftest  # noqa: E402

COURSE_IDS = ("apc-mech", "apc-em", "ap1", "ap2")

TAXONOMY = {
    "course": "Test Course",
    "units": [
        {"id": 1, "title": "Unit One", "topics": [
            {"id": "1.1", "title": "Topic One-One"},
            {"id": "1.2", "title": "Topic One-Two"},
        ]},
        {"id": 2, "title": "Unit Two", "topics": [
            {"id": "2.1", "title": "Topic Two-One"},
        ]},
    ],
}


def seed_data_root(temp_dir: str) -> str:
    """Build a bank tree for four courses under a fresh data directory."""
    data = Path(temp_dir) / "data"
    (data / "media").mkdir(parents=True, exist_ok=True)
    for index, course_id in enumerate(COURSE_IDS):
        if course_id == "apc-mech":
            base = data
        else:
            base = data / "banks" / course_id
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "taxonomy.json", "w", encoding="utf-8") as fh:
            json.dump({**TAXONOMY, "course": course_id}, fh, ensure_ascii=False)
        bank = {
            "version": 1,
            "course": course_id,
            "questions": [{
                "id": f"{course_id.upper()}-Q1",
                "unit": 1, "unit_title": "Unit One",
                "topic": "1.1", "topic_title": "Topic One-One",
                "additional_topics": [],
                "number": 1, "qtype": "mcq",
                "stem": f"Stem for {course_id}",
                "choices": [{"label": "A", "text": "one"}],
                "answer": "A", "solution": "", "images": [],
                "difficulty": "", "tags": [], "source": {},
                "layout": "inline", "needs_review": False,
            }],
        }
        with open(base / "bank.json", "w", encoding="utf-8") as fh:
            json.dump(bank, fh, ensure_ascii=False)
    return str(data)


class DataRootMixin(unittest.TestCase):
    """Import the server modules against a temporary data root.

    Dropping the entries from ``sys.modules`` is not enough on its own: the
    ``server`` package keeps an attribute pointing at the module that was
    imported first, and ``from server import bank`` would hand that stale module
    back.  ``reload_server_modules`` clears both, so each test really does read
    its own bank tree.
    """

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = seed_data_root(self._temp.name)
        self._previous = os.environ.get("QB_DATA_DIR")
        os.environ["QB_DATA_DIR"] = self.data_dir
        conftest.reload_server_modules()
        from server import courses
        self.courses = courses

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("QB_DATA_DIR", None)
        else:
            os.environ["QB_DATA_DIR"] = self._previous
        conftest.reload_server_modules()
        self._temp.cleanup()


class CourseIsolationTest(DataRootMixin):
    def test_each_course_has_its_own_bank(self) -> None:
        from server import bank
        for course_id in COURSE_IDS:
            loaded = bank.load_bank(course_id)
            self.assertEqual(len(loaded["questions"]), 1, course_id)
            self.assertEqual(loaded["questions"][0]["id"],
                             f"{course_id.upper()}-Q1")

    def test_question_ids_never_bleed_between_courses(self) -> None:
        from server import bank
        seen = {}
        for course_id in COURSE_IDS:
            for question in bank.load_bank(course_id)["questions"]:
                self.assertNotIn(question["id"], seen,
                                 f"{question['id']} appears in two banks")
                seen[question["id"]] = course_id

    def test_writing_one_bank_leaves_the_others_untouched(self) -> None:
        from server import bank
        before = {cid: bank.load_bank(cid) for cid in COURSE_IDS}
        edited = bank.load_bank("ap1")
        edited["questions"][0]["stem"] = "changed"
        bank.save_bank(edited, "ap1")
        self.assertEqual(bank.load_bank("ap1")["questions"][0]["stem"], "changed")
        for cid in ("apc-mech", "apc-em", "ap2"):
            self.assertEqual(bank.load_bank(cid), before[cid], cid)

    def test_each_course_has_its_own_taxonomy(self) -> None:
        from server import bank
        for course_id in COURSE_IDS:
            tax = bank.load_taxonomy(course_id)
            self.assertEqual(tax["course"], course_id)
            self.assertEqual(len(tax["units"]), 2)

    def test_unknown_course_falls_back_to_the_default(self) -> None:
        self.assertEqual(self.courses.get("nope").id,
                         self.courses.DEFAULT_COURSE_ID)
        self.assertEqual(self.courses.get(None).id,
                         self.courses.DEFAULT_COURSE_ID)

    def test_question_ids_are_prefixed_per_course(self) -> None:
        from server import bank
        made = bank.next_id(bank.load_bank("apc-em"), 1, "1.1", "apc-em")
        self.assertTrue(made.startswith("APCE-"), made)
        made = bank.next_id(bank.load_bank("ap2"), 2, "2.1", "ap2")
        self.assertTrue(made.startswith("AP2-"), made)


class RecycleBinTest(DataRootMixin):
    def _delete(self, course_id: str, question_id: str):
        from server import bank, recycle
        loaded = bank.load_bank(course_id)
        item = next(q for q in loaded["questions"] if q["id"] == question_id)
        entry = recycle.move_to_bin(item, course_id, {"id": 1, "display_name": "Ms Li"})
        bank.delete_question(loaded, question_id, course_id)
        return entry

    def test_deleting_moves_the_question_out_of_the_bank(self) -> None:
        from server import bank, recycle
        self._delete("ap1", "AP1-Q1")
        self.assertEqual(bank.load_bank("ap1")["questions"], [])
        items = recycle.list_items("ap1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "AP1-Q1")
        self.assertEqual(items[0]["deleted_by_name"], "Ms Li")

    def test_bin_is_per_course(self) -> None:
        from server import recycle
        self._delete("ap1", "AP1-Q1")
        self.assertEqual(len(recycle.list_items("ap1")), 1)
        self.assertEqual(recycle.list_items("ap2"), [])

    def test_restore_puts_it_back_with_its_body(self) -> None:
        from server import bank, recycle
        self._delete("ap1", "AP1-Q1")
        restored = recycle.restore("AP1-Q1", "ap1")
        self.assertIsNotNone(restored)
        self.assertEqual(restored["choices"], [{"label": "A", "text": "one"}])
        back = bank.load_bank("ap1")["questions"]
        self.assertEqual([q["id"] for q in back], ["AP1-Q1"])
        self.assertEqual(recycle.list_items("ap1"), [])

    def test_restoring_twice_is_harmless(self) -> None:
        from server import bank, recycle
        self._delete("ap1", "AP1-Q1")
        recycle.restore("AP1-Q1", "ap1")
        self.assertIsNone(recycle.restore("AP1-Q1", "ap1"))
        self.assertEqual(len(bank.load_bank("ap1")["questions"]), 1)

    def test_purge_deletes_it_for_good(self) -> None:
        from server import bank, recycle
        self._delete("ap1", "AP1-Q1")
        self.assertTrue(recycle.purge("AP1-Q1", "ap1"))
        self.assertEqual(recycle.list_items("ap1"), [])
        self.assertEqual(bank.load_bank("ap1")["questions"], [])
        self.assertFalse(recycle.purge("AP1-Q1", "ap1"))

    def test_empty_clears_the_whole_bin(self) -> None:
        from server import bank, recycle
        loaded = bank.load_bank("ap1")
        loaded["questions"].append({**loaded["questions"][0], "id": "AP1-Q2"})
        bank.save_bank(loaded, "ap1")
        self._delete("ap1", "AP1-Q1")
        self._delete("ap1", "AP1-Q2")
        self.assertEqual(recycle.empty("ap1"), 2)
        self.assertEqual(recycle.list_items("ap1"), [])

    def test_items_expire_after_the_retention_window(self) -> None:
        from server import recycle
        self._delete("ap1", "AP1-Q1")
        data = recycle.load("ap1")
        data["items"][0]["deleted_at"] = "2000-01-01 00:00:00"   # long past
        recycle.save(data, "ap1")
        self.assertEqual(recycle.list_items("ap1"), [], "expired item should be swept")
        # and the sweep is persisted, not just filtered on read
        self.assertEqual(recycle.load("ap1")["items"], [])

    def test_items_inside_the_window_survive_a_sweep(self) -> None:
        from server import recycle
        from datetime import timedelta
        self._delete("ap1", "AP1-Q1")
        data = recycle.load("ap1")
        recent = recycle._stamp(recycle._now() - timedelta(days=recycle.RETENTION_DAYS - 2))
        data["items"][0]["deleted_at"] = recent
        recycle.save(data, "ap1")
        items = recycle.list_items("ap1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["days_left"], 2)

    def test_a_corrupt_timestamp_never_destroys_a_question(self) -> None:
        from server import recycle
        self._delete("ap1", "AP1-Q1")
        data = recycle.load("ap1")
        data["items"][0]["deleted_at"] = "not a date"
        recycle.save(data, "ap1")
        self.assertEqual(len(recycle.list_items("ap1")), 1)

    def test_retention_window_is_thirty_days(self) -> None:
        from server import recycle
        self.assertEqual(recycle.RETENTION_DAYS, 30)


class StemBlockTest(DataRootMixin):
    def test_text_blocks_become_paragraphs(self) -> None:
        from server import blocks
        latex = blocks.blocks_to_latex([
            {"type": "text", "text": "First paragraph."},
            {"type": "text", "text": "Second paragraph."},
        ])
        self.assertEqual(latex, "First paragraph.\n\nSecond paragraph.")

    def test_an_empty_image_block_renders_the_placeholder(self) -> None:
        from server import blocks
        latex = blocks.blocks_to_latex([{"type": "image", "path": ""}])
        self.assertIn(blocks.PLACEHOLDER, latex)
        self.assertIn("\\includegraphics", latex)

    def test_blocks_keep_the_order_they_were_given(self) -> None:
        from server import blocks
        latex = blocks.blocks_to_latex([
            {"type": "text", "text": "before"},
            {"type": "image", "path": "media/figure.png"},
            {"type": "text", "text": "after"},
        ])
        self.assertLess(latex.index("before"), latex.index("figure.png"))
        self.assertLess(latex.index("figure.png"), latex.index("after"))

    def test_image_width_is_clamped(self) -> None:
        from server import blocks
        latex = blocks.blocks_to_latex([{"type": "image", "path": "m.png", "width": 9}])
        self.assertIn("width=1.00\\linewidth", latex)
        latex = blocks.blocks_to_latex([{"type": "image", "path": "m.png", "width": -3}])
        self.assertIn("width=0.50\\linewidth", latex)

    def test_apply_blocks_derives_the_stem(self) -> None:
        from server import blocks
        question = {"id": "X", "stem": ""}
        blocks.apply_blocks(question, [{"type": "text", "text": "Derived stem."}])
        self.assertEqual(question["stem"], "Derived stem.")
        self.assertEqual(len(question["stem_blocks"]), 1)

    def test_an_imported_question_becomes_one_text_block(self) -> None:
        from server import blocks
        question = {"id": "X", "stem": "Plain imported stem with $x$."}
        out = blocks.blocks_from_question(question)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "text")
        self.assertEqual(out[0]["text"], "Plain imported stem with $x$.")

    def test_a_figure_only_stem_becomes_image_blocks(self) -> None:
        from server import blocks
        question = {"id": "X",
                    "stem": "\\includegraphics[width=0.48\\linewidth]{media/a.png}"}
        out = blocks.blocks_from_question(question)
        self.assertEqual([b["type"] for b in out], ["image"])
        self.assertEqual(out[0]["path"], "media/a.png")
        self.assertAlmostEqual(out[0]["width"], 0.48, places=2)

    def test_unknown_blocks_are_dropped(self) -> None:
        from server import blocks
        out = blocks.normalise_blocks([
            {"type": "video", "src": "x"},
            "not a dict",
            {"type": "text", "text": "kept"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "kept")

    def test_uploads_are_namespaced_and_deduplicated(self) -> None:
        import os
        from server import blocks, courses
        first = blocks.store_upload("figure.png", b"payload", "apc-em")
        second = blocks.store_upload("figure.png", b"payload", "apc-em")
        self.assertEqual(first, second, "identical bytes reuse the same file")
        self.assertTrue(first.startswith("media/apce_"))
        self.assertTrue(os.path.exists(
            os.path.join(courses.MEDIA_DIR, os.path.basename(first))))

    def test_upload_rejects_unknown_extensions(self) -> None:
        from server import blocks
        with self.assertRaisesRegex(ValueError, "Unsupported image type"):
            blocks.store_upload("payload.exe", b"x", "ap1")


class AdditionalTopicTest(DataRootMixin):
    def test_search_matches_additional_topics(self) -> None:
        from server import bank
        loaded = bank.load_bank("ap1")
        loaded["questions"][0]["additional_topics"] = ["2.1"]
        bank.save_bank(loaded, "ap1")

        found = bank.search(bank.load_bank("ap1"), topic="2.1", course_id="ap1")
        self.assertEqual(len(found), 1, "an additional topic should be findable")

        found = bank.search(bank.load_bank("ap1"), unit=2, course_id="ap1")
        self.assertEqual(len(found), 1, "the additional topic's unit should match")

    def test_primary_topic_still_matches(self) -> None:
        from server import bank
        found = bank.search(bank.load_bank("ap1"), topic="1.1", course_id="ap1")
        self.assertEqual(len(found), 1)

    def test_topics_of_starts_with_the_primary(self) -> None:
        from server import bank
        question = {"topic": "1.1", "additional_topics": ["2.1", "1.2"]}
        self.assertEqual(bank.topics_of(question), ["1.1", "2.1", "1.2"])

    def test_topics_of_tolerates_a_missing_primary(self) -> None:
        from server import bank
        self.assertEqual(bank.topics_of({"additional_topics": ["2.1"]}), ["2.1"])

    def test_resolve_topic_finds_the_unit(self) -> None:
        from server import bank
        unit, title = bank.resolve_topic("2.1", "ap1")
        self.assertEqual(unit, 2)
        self.assertEqual(title, "Topic Two-One")
        self.assertEqual(bank.resolve_topic("nope", "ap1"), (0, ""))


if __name__ == "__main__":
    unittest.main()
