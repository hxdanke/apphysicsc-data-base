"""Prose punctuation must not sit inside a maths run.

Inside ``$...$`` TeX sets a comma or a full stop as maths: a spaced-out period, a
maths-style comma.  The book keeps them in the prose, so they belong outside.

This checks the bank as data (so a stray edit cannot reintroduce it) and the
fixer that repairs it.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from server.latex import _scan_math  # noqa: E402
from fix_math_punctuation import fix_text  # noqa: E402
from fix_item_labels import fix_text as fix_labels  # noqa: E402
from fix_plain_quantities import fix_text as plain_qty  # noqa: E402

ENDING = re.compile(r"([.,;:!?])\s*$")
BANKS = [ROOT / "data" / "bank.json"] + sorted(
    (ROOT / "data" / "banks").glob("*/bank.json"))


def texts_of(q: dict):
    yield q.get("stem") or ""
    for c in q.get("choices") or []:
        for key in ("text", "text2", "text3", "text4"):
            if c.get(key):
                yield c[key]
    for head in q.get("table_headers") or []:
        yield head
    spec = q.get("stem_table") or {}
    for head in spec.get("headers") or []:
        yield head
    for row in spec.get("rows") or []:
        for cell in row:
            if cell:
                yield str(cell)
    if q.get("solution"):
        yield q["solution"]


class BankIsCleanTest(unittest.TestCase):
    def test_no_maths_run_ends_in_punctuation(self) -> None:
        strays = []
        for path in BANKS:
            for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
                for text in texts_of(q):
                    for kind, body in _scan_math(text):
                        if kind != "math":
                            continue
                        m = ENDING.search(body)
                        # \, \; \: \! are spacing commands, not prose
                        if m and not body[:m.start()].rstrip().endswith("\\"):
                            strays.append((q["id"], body))
        self.assertEqual(strays, [],
                         "punctuation still inside maths: " + str(strays[:3]))


class FixerTest(unittest.TestCase):
    def test_a_full_stop_moves_out(self) -> None:
        self.assertEqual(fix_text("$30\\ \\mathrm{m/s}.$ text"),
                         "$30\\ \\mathrm{m/s}$. text")

    def test_a_question_mark_moves_out(self) -> None:
        self.assertEqual(fix_text("when $\\theta\\ <\\ 10^{\\circ}?$"),
                         "when $\\theta\\ <\\ 10^{\\circ}$?")

    def test_a_comma_between_two_runs_is_left_alone(self) -> None:
        # correct prose -- the comma is already outside
        self.assertEqual(fix_text("$a$, $b$"), "$a$, $b$")

    def test_a_comma_listed_inside_one_run_moves_out(self) -> None:
        self.assertEqual(fix_text("cars $1,\\ 2,$ and $3$"),
                         "cars $1,\\ 2$, and $3$")

    def test_a_decimal_point_is_untouched(self) -> None:
        self.assertEqual(fix_text("$0.40$ and $3.14$"), "$0.40$ and $3.14$")

    def test_a_spacing_command_is_not_punctuation(self) -> None:
        self.assertEqual(fix_text("$a\\, b$"), "$a\\, b$")

    def test_punctuation_swallowing_the_next_sentence_is_split(self) -> None:
        self.assertEqual(fix_text("At $t\\ =\\ t_{f}/2. a_{x}$ and"),
                         "At $t\\ =\\ t_{f}/2$. $a_{x}$ and")


if __name__ == "__main__":
    unittest.main()


class ItemLabelTest(unittest.TestCase):
    """Labels name things; they are not quantities and stay in the prose.

    "Object 1" set as "Object $1$" comes out in the maths font, spaced like a
    formula.  Quantities are the opposite case and must keep their maths.
    """

    def test_a_labelled_number_becomes_plain_text(self) -> None:
        self.assertEqual(fix_labels("Object $1$ and Object $2$"),
                         "Object 1 and Object 2")

    def test_a_labelled_letter_becomes_plain_text(self) -> None:
        self.assertEqual(fix_labels("Block $A$"), "Block A")

    def test_a_label_carried_on_by_and_is_plain_too(self) -> None:
        self.assertEqual(fix_labels("Blocks 2 and $3$ slide"),
                         "Blocks 2 and 3 slide")

    def test_a_list_of_labels_is_plain(self) -> None:
        self.assertEqual(fix_labels("points, $1,\\ 2$, and $3$,"),
                         "points, 1, 2, and 3,")

    def test_a_quantity_keeps_its_maths(self) -> None:
        self.assertEqual(fix_labels("After $3$ seconds"), "After $3$ seconds")
        self.assertEqual(fix_labels("Between $1$ and $3$ seconds"),
                         "Between $1$ and $3$ seconds")

    def test_a_symbol_keeps_its_maths(self) -> None:
        self.assertEqual(fix_labels("a mass $M$ and a force $F$"),
                         "a mass $M$ and a force $F$")

    def test_no_bare_label_follows_a_noun_anywhere(self) -> None:
        pattern = re.compile(r"\b(?:Object|Objects|Block|Blocks|Figure|Collision|"
                             r"Scenario|Trial|Ball|Car|Disk|Boat|Spring|Student|"
                             r"Location|Group|Cart|Asteroid|Satellite|Hoop|Point|"
                             r"Pulley|System|Systems|objects|blocks|figures|"
                             r"collisions|scenarios|trials|balls|cars|disks|boats|"
                             r"springs|students|locations|groups|carts|asteroids|"
                             r"satellites|hoops|points|pulleys|systems)\s+\$"
                             r"(?:\\mathrm\{)?(?:\d{1,3}|[A-Z])\}?\$")
        strays = []
        for path in BANKS:
            for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
                for text in texts_of(q):
                    strays += pattern.findall(text)
        self.assertEqual(strays, [], "item label still set as maths")


class PlainQuantityTest(unittest.TestCase):
    """A number and a unit are not mathematics.

    "3.0 m/s" has no subscript, no superscript and no algebra, so it belongs in
    the prose.  A quantity that does have any of those keeps its maths.
    """

    def test_number_and_unit_become_text(self) -> None:
        self.assertEqual(plain_qty("$4\\ \\mathrm{m/s}$"), "4 m/s")
        self.assertEqual(plain_qty("$0.50\\ \\mathrm{m}$"), "0.50 m")

    def test_a_number_with_its_unit_in_the_prose_becomes_text(self) -> None:
        self.assertEqual(plain_qty("a force of $6$ N"), "a force of 6 N")

    def test_a_superscript_keeps_its_maths(self) -> None:
        src = "$9.8\\ \\mathrm{m/s}^{2}$"
        self.assertEqual(plain_qty(src), src)

    def test_an_algebraic_expression_keeps_its_maths(self) -> None:
        src = "$A = 3.0\\ \\mathrm{m}$"
        self.assertEqual(plain_qty(src), src)

    def test_a_symbol_keeps_its_maths(self) -> None:
        for src in ("$v_{0}$", "$30^{\\circ}$", "$\\frac{1}{2}I_{0}$"):
            self.assertEqual(plain_qty(src), src)

    def test_no_plain_quantity_is_left_in_maths(self) -> None:
        pure = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*(?:\\\s+|\s+)?"
                          r"(?:\\mathrm|\\text)\{[^}]*\}\s*$")
        bare = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*$")
        strays = []
        for path in BANKS:
            for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
                for text in texts_of(q):
                    for kind, body in _scan_math(text):
                        if kind == "math" and (pure.match(body) or bare.match(body)):
                            strays.append(body)
        self.assertEqual(strays, [], "a plain quantity is still set as maths")
