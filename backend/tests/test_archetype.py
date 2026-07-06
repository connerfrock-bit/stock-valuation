"""
Tests for the L5 financial-archetype router (Plan A). The non-negotiable: banks/insurers/
REITs must never emit a garbage FCF/EV fair value — DCF/EPV/Warranted/reverse-DCF are N/A
and they price on RIM alone, while the ~75% 'standard' universe is byte-for-byte unchanged.
stdlib only.   python tests/test_archetype.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from value import archetype_of, ARCHETYPE_GATES, apply_archetype_gates
from engines import triangulate

GICS = ["Information Technology", "Communication Services", "Consumer Discretionary",
        "Consumer Staples", "Health Care", "Industrials", "Materials", "Energy",
        "Utilities", "Financials", "Real Estate"]


class TestArchetypeOf(unittest.TestCase):
    def test_financials_and_reits(self):
        self.assertEqual(archetype_of("Financials"), "financial")
        self.assertEqual(archetype_of("Real Estate"), "reit")

    def test_all_nine_others_are_standard(self):
        for s in GICS:
            if s in ("Financials", "Real Estate"):
                continue
            self.assertEqual(archetype_of(s), "standard", s)

    def test_unknown_sector_is_standard(self):
        self.assertEqual(archetype_of("Conglomerates"), "standard")
        self.assertEqual(archetype_of(""), "standard")


class TestGates(unittest.TestCase):
    def test_standard_is_identity(self):
        # every engine passes through untouched for standard names
        got = apply_archetype_gates("standard", 100.0, 60.0, 90.0, 0.12, "=")
        self.assertEqual(got, (100.0, 60.0, 90.0, 0.12, "="))

    def test_financial_gates_fcf_ev_engines(self):
        dcf, epv, warr, impl, op = apply_archetype_gates("financial", 100.0, 60.0, 90.0, 0.12, "=")
        self.assertIsNone(dcf); self.assertIsNone(epv)
        self.assertIsNone(warr); self.assertIsNone(impl); self.assertIsNone(op)

    def test_reit_gates_same_as_financial(self):
        self.assertEqual(apply_archetype_gates("reit", 1, 2, 3, 0.1, ">"),
                         (None, None, None, None, None))

    def test_gate_table_shape(self):
        self.assertTrue(all(ARCHETYPE_GATES["standard"].values()))
        for a in ("financial", "reit"):
            self.assertFalse(any(ARCHETYPE_GATES[a][k] for k in ("DCF", "EPV", "Warranted", "revDCF")))


class TestRimOnlyPricing(unittest.TestCase):
    def test_financial_priced_on_rim_alone_conf2(self):
        # after gating, only RIM survives -> triangulate mid == RIM exactly, conf == 2
        dcf, epv, warr, _, _ = apply_archetype_gates("financial", 120.0, 80.0, 110.0, 0.1, "=")
        rim_ps = 95.0
        tri = triangulate({"DCF": dcf, "RIM": rim_ps, "Warranted": warr}, epv, price=100.0)
        self.assertIsNotNone(tri)
        self.assertAlmostEqual(tri["mid"], 95.0)          # weights irrelevant for a single engine
        self.assertEqual(tri["conf"], 2)                  # single engine can't demonstrate agreement
        self.assertAlmostEqual(tri["low"], 95.0)          # no EPV floor leaks in (gated None)

    def test_financial_with_no_usable_rim_is_unpriceable(self):
        # gated FCF/EV engines + RIM None (neg book) -> triangulate returns None -> excluded
        dcf, epv, warr, _, _ = apply_archetype_gates("reit", 120.0, 80.0, 110.0, 0.1, "=")
        tri = triangulate({"DCF": dcf, "RIM": None, "Warranted": warr}, epv, price=100.0)
        self.assertIsNone(tri)                            # nothing to price on -> honest exclusion

    def test_standard_unchanged_blends_all_engines(self):
        dcf, epv, warr, _, _ = apply_archetype_gates("standard", 100.0, 50.0, 120.0, 0.1, "=")
        tri = triangulate({"DCF": dcf, "RIM": 110.0, "Warranted": warr}, epv, price=100.0)
        self.assertGreater(tri["mid"], 50.0)              # EPV floor (50) never drags the mid
        self.assertEqual(tri["low"], 50.0)                # but it does set the low bound


if __name__ == "__main__":
    unittest.main(verbosity=2)
