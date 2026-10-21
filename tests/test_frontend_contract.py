"""Guards for the front-end behaviours that have regressed before.

These read the browser sources as text, in the same spirit as the reference
project's UI tests: a mistake here is invisible to the Python suite but breaks
the page, and the failure mode ("the menu never closes") is the kind that gets
reported by a teacher rather than caught by a test.

The rule being enforced: an element is hidden with the ``hidden`` *attribute*,
and that only works while nothing in ``app.css`` outranks the browser's own
``[hidden] { display: none }``.  A component rule such as ``display: flex`` does
exactly that, which is why the sheet re-asserts ``[hidden]`` with ``!important``.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSS_SOURCE = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
# Comments quote example rules such as `[hidden] { display: none }`, which would
# otherwise be picked up as if they were real declarations.
CSS = re.sub(r"/\*.*?\*/", "", CSS_SOURCE, flags=re.DOTALL)
COURSES_JS = (ROOT / "web" / "js" / "courses.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
EDIT_JS = (ROOT / "web" / "js" / "edit.js").read_text(encoding="utf-8")
BROWSE_JS = (ROOT / "web" / "js" / "browse.js").read_text(encoding="utf-8")
MAIN_PY = (ROOT / "server" / "main.py").read_text(encoding="utf-8")
BANK_PY = (ROOT / "server" / "bank.py").read_text(encoding="utf-8")


def css_rule(selector: str) -> str:
    """The body of the first rule matching `selector`, or ''."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return match.group(1) if match else ""


class HiddenAttributeTest(unittest.TestCase):
    def test_hidden_is_reasserted_over_component_display_rules(self) -> None:
        self.assertIn("[hidden] { display: none !important; }", CSS,
                      "app.css must re-assert [hidden]: a `display: flex` rule "
                      "otherwise beats the browser default and hidden stops working")

    def test_every_element_hidden_with_display_set_in_css_is_covered(self) -> None:
        """No component may set `display` and rely on `hidden` without the guard."""
        guarded = "!important" in css_rule("[hidden]")
        self.assertTrue(guarded)
        # `.course-menu` and `.user-chip` are the known cases: both are flex and
        # both are toggled with the hidden attribute.
        for selector in (".course-menu", ".user-chip"):
            body = css_rule(selector)
            self.assertIn("display:", body, f"{selector} should still be styled")
        # and both are toggled via `hidden` in the markup / JS
        self.assertIn("hidden", (ROOT / "web" / "index.html").read_text(encoding="utf-8"))


class CourseSwitcherTest(unittest.TestCase):
    def test_the_menu_starts_hidden(self) -> None:
        self.assertIn('class="course-menu" id="course-menu" hidden', COURSES_JS)

    def test_the_toggle_stops_the_click_reaching_the_document_handler(self) -> None:
        # Without this, the same click would toggle open and immediately close.
        self.assertIn("event.stopPropagation()", COURSES_JS)

    def test_clicking_an_option_closes_the_menu(self) -> None:
        self.assertIn("menu.hidden = true", COURSES_JS)

    def test_outside_clicks_and_escape_close_the_menu(self) -> None:
        self.assertIn('document.addEventListener("keydown"', COURSES_JS)
        self.assertIn('event.key !== "Escape"', COURSES_JS)
        self.assertIn('document.addEventListener("click"', COURSES_JS)

    def test_the_outside_click_handler_is_installed(self) -> None:
        self.assertIn("courses.installOutsideClick()", APP_JS)


class SourceProvenanceTest(unittest.TestCase):
    """Questions do not advertise which file they were imported from.

    The card used to carry an "EB3 p.1" badge.  It told a teacher nothing useful
    and it is not wanted back, so the field is gone from the data and from every
    code path that would have recorded it.
    """

    def test_no_question_in_the_bank_has_a_source_field(self) -> None:
        for name in ("data/bank.json", "data/banks/apc-em/bank.json",
                     "data/banks/ap1/bank.json", "data/banks/ap2/bank.json"):
            bank = json.loads((ROOT / name).read_text(encoding="utf-8"))
            strays = [q["id"] for q in bank["questions"] if "source" in q]
            self.assertEqual(strays, [], f"{name} still carries a source tag")

    def test_the_card_does_not_render_a_source_badge(self) -> None:
        self.assertNotIn("q.source", BROWSE_JS)
        self.assertNotIn("book_page", BROWSE_JS)

    def test_new_questions_are_not_stamped_with_a_source(self) -> None:
        self.assertNotIn('item["source"]', MAIN_PY)
        self.assertNotIn('"source": {}', MAIN_PY)
        self.assertNotIn('"source": {}', BANK_PY)

    def test_upsert_strips_any_source_that_reaches_it(self) -> None:
        # The extractor still tracks pages for its own use; the bank must not.
        self.assertIn('q.pop("source", None)', BANK_PY)


class WholeEditorTest(unittest.TestCase):
    """The whole-question editor previews live and saves without validating."""

    def test_the_editor_has_a_preview_pane(self) -> None:
        self.assertIn('class="qedit-preview"', EDIT_JS)
        self.assertIn("qedit-split", EDIT_JS)

    def test_typing_redraws_the_preview(self) -> None:
        self.assertIn('area.addEventListener("input"', EDIT_JS)
        self.assertIn("drawNow()", EDIT_JS)

    def test_a_broken_source_blanks_the_preview(self) -> None:
        self.assertIn("preview.innerHTML = \"\"", EDIT_JS)

    def test_the_real_engine_is_consulted_once_typing_settles(self) -> None:
        self.assertIn("api.preview(", EDIT_JS)
        self.assertIn("setTimeout(", EDIT_JS)

    def test_a_stale_reply_cannot_overwrite_a_newer_edit(self) -> None:
        # Each request carries a sequence number; a late reply is discarded.
        self.assertIn("requestSeq", EDIT_JS)

    def test_saving_does_not_validate(self) -> None:
        # The old flow ran a validate pass on save; the live preview replaces it.
        self.assertNotIn("validateWhole", EDIT_JS)
        self.assertNotIn("Validating…", EDIT_JS)
        self.assertIn("No validation step", EDIT_JS)

    def test_the_single_formula_popup_still_validates(self) -> None:
        # Only the whole-question editor changed: a single formula is still
        # compile-checked before it is committed.
        self.assertIn("api.validate(id, field, value)", EDIT_JS)


if __name__ == "__main__":
    unittest.main()
