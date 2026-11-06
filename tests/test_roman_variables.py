"""Physical quantities are italic; units and labels are upright.

A variable written ``$\\mathrm{m}$`` comes out in the roman font, which makes
"a block of mass m" read like a unit.  Units (m, s, N, W), descriptive subscripts
(v_{\\mathrm{L}}, F_{\\mathrm{W}}) and mathematical constants (e, pi) stay upright.
Physical constants such as g are quantities and are italic.
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
from fix_roman_variables import fix_text  # noqa: E402

BANKS = [ROOT / "data" / "bank.json"] + sorted(
    (ROOT / "data" / "banks").glob("*/bank.json"))


class RomanVariableTest(unittest.TestCase):
    def test_a_quantity_becomes_italic(self) -> None:
        self.assertEqual(fix_text("a block of mass $\\mathrm{m}$"),
                         "a block of mass $m$")
        self.assertEqual(fix_text("a distance $\\mathrm{L}$"),
                         "a distance $L$")

    def test_a_subscripted_quantity_becomes_italic(self) -> None:
        self.assertEqual(fix_text("gravity $\\mathrm{g}_{E}$ and $\\mathrm{g}_{M}$"),
                         "gravity $g_{E}$ and $g_{M}$")
        self.assertEqual(fix_text("$M\\ <\\ \\mathrm{m}_{C}\\ <\\ 2M$"),
                         "$M\\ <\\ m_{C}\\ <\\ 2M$")

    def test_physical_constants_are_italic_too(self) -> None:
        self.assertEqual(fix_text("equal to $\\mathrm{g}$"), "equal to $g$")
        self.assertEqual(fix_text("$2\\ \\mathrm{g}_{S}/3$"), "$2\\ g_{S}/3$")

    def test_units_stay_upright(self) -> None:
        for src in ("$t\\ =\\ 2\\ \\mathrm{s}$",
                    "$x\\ =\\ 1\\ \\mathrm{m}$",
                    "$\\vec{F}\\ = (4.0\\hat{i} + 3.0\\hat{j})\\ \\mathrm{N}$",
                    "$A\\ =\\ 6\\ \\mathrm{W}$",
                    "$0.5\\pi\\ \\mathrm{s}^{-1}$"):
            self.assertEqual(fix_text(src), src)

    def test_scientific_notation_is_followed_by_a_unit(self) -> None:
        # In the AP2 sample bank J is joules, not the impulse variable it is in
        # the mechanics bank.
        for src in ("$8.0\\ \\times 10^{4}\\ \\mathrm{J}$",
                    "$4.0\\ \\times 10^{4}\\ \\mathrm{Pa}$"):
            self.assertEqual(fix_text(src), src)

    def test_compound_units_stay_upright(self) -> None:
        for src in ("$v$ is in $\\mathrm{m/s}$",
                    "$2\\ \\mathrm{W}/\\mathrm{s}$",
                    "$80\\ \\mathrm{N}/\\mathrm{m}$"):
            self.assertEqual(fix_text(src), src)

    def test_descriptive_subscripts_stay_upright(self) -> None:
        for src in ("$v_{\\mathrm{L}}$", "$F_{\\mathrm{W}\\ 1}$",
                    "$T_{\\mathrm{h}}$", "$v_{\\mathrm{avg}}$"):
            self.assertEqual(fix_text(src), src)

    def test_mathematical_constants_stay_upright(self) -> None:
        self.assertEqual(fix_text("$\\mathrm{e}^{-bt}$"), "$\\mathrm{e}^{-bt}$")
        self.assertEqual(fix_text("$4\\pi t$"), "$4\\pi t$")

    def test_edit_only_removes_a_roman_wrapper(self) -> None:
        """Stripping every \\mathrm{...} must leave the text unchanged."""
        strip = lambda s: re.sub(r"\\(?:mathrm|text)\{([^{}]*)\}", r"\1", s)
        for path in BANKS:
            for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
                for t in [q.get("stem") or ""] + [c.get(k) or ""
                                                  for c in q.get("choices") or []
                                                  for k in ("text", "text2")]:
                    n = fix_text(t)
                    self.assertEqual(t.count("$"), n.count("$"), q["id"])
                    self.assertEqual(strip(t), strip(n), q["id"])

    def test_no_quantity_is_left_upright(self) -> None:
        """Fixing again is a no-op: everything that should be italic already is."""
        strays = []
        for path in BANKS:
            for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
                for t in [q.get("stem") or ""] + [c.get(k) or ""
                                                  for c in q.get("choices") or []
                                                  for k in ("text", "text2")]:
                    if fix_text(t) != t:
                        strays.append(q["id"])
        self.assertEqual(strays, [], "a physical quantity is still upright")


if __name__ == "__main__":
    unittest.main()
