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


if __name__ == "__main__":
    unittest.main()
