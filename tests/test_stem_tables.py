"""Stem tables: a data table that belongs to the question, not to its options.

The printed book puts some tables inside the stem -- a set of readings to reason
from rather than a set of choices to pick.  They have to survive into the paper
as real tables, and the book prints them either above the text or below it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import latex  # noqa: E402


def question(**overrides) -> dict:
    q = {
        "id": "T-1", "unit": 1, "unit_title": "U", "topic": "1.1", "topic_title": "T",
        "number": 1, "qtype": "mcq",
        "stem": "The data shown in the table is collected.",
        "choices": [{"label": "A", "text": "one"}, {"label": "B", "text": "two"}],
        "answer": "", "solution": "", "images": [], "difficulty": "", "tags": [],
        "layout": "inline", "needs_review": False,
    }
    q.update(overrides)
    return q


TABLE = {
    "position": "before",
    "headers": ["$t$ (s)", "$x$ (m)"],
    "rows": [["0", "160"], ["2", "136"]],
}


class StemTableLatexTest(unittest.TestCase):
    def test_it_draws_a_ruled_table(self) -> None:
        tex = latex.stem_table_latex(TABLE)
        self.assertIn("\\begin{tabular}{|c|c|}", tex)
        self.assertIn("\\hline", tex)
        self.assertIn("$t$ (s) & $x$ (m)", tex)
        self.assertIn("0 & 160", tex)

    def test_it_fills_short_rows_so_the_grid_stays_square(self) -> None:
        tex = latex.stem_table_latex({
            "headers": ["a", "b", "c"], "rows": [["1"]],
        })
        self.assertIn("1 &  & ", tex)

    def test_a_table_without_headers_still_builds(self) -> None:
        tex = latex.stem_table_latex({"headers": [], "rows": [["1", "2"]]})
        self.assertIn("\\begin{tabular}{|c|c|}", tex)
        self.assertNotIn("&  & ", tex)


class StemTablePlacementTest(unittest.TestCase):
    def test_before_puts_the_table_above_the_item(self) -> None:
        q = question(stem_table=TABLE)
        tex = latex.build_document([q])
        table_at = tex.index("\\begin{tabular}")
        item_at = tex.index("\\item")
        self.assertLess(table_at, item_at,
                        "a leading table must be set above the numbered item")

    def test_before_keeps_the_number_on_the_first_line_of_text(self) -> None:
        q = question(stem_table=TABLE)
        tex = latex.build_document([q])
        self.assertIn("\\item The data shown in the table", tex)

    def test_after_puts_the_table_below_the_text(self) -> None:
        q = question(stem_table={**TABLE, "position": "after"})
        tex = latex.build_document([q])
        self.assertLess(tex.index("The data shown"), tex.index("\\begin{tabular}"))

    def test_no_table_means_the_document_is_unchanged(self) -> None:
        plain = latex.build_document([question()])
        self.assertNotIn("\\begin{tabular}", plain)


if __name__ == "__main__":
    unittest.main()
