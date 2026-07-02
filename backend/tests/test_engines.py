"""
Golden-value + invariant tests for the valuation engines (Plan 1 safety net).
Every engine is a pure function — a regression here silently corrupts every number
downstream, so these are the tripwire. stdlib only.

Run from backend/:   python tests/test_engines.py
              or:    python -m unittest discover -s tests -v
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import ev_present_value
from engines import (cost_of_equity, wacc_of, reverse_dcf, dcf, epv, rim,
                     warranted_fit, warranted_value, triangulate)


class TestRates(unittest.TestCase):
    def test_capm(self):
        self.assertAlmostEqual(cost_of_equity(0.04, 1.2, 0.05), 0.10)

    def test_wacc_weighted(self):
        # 80/20 split: 0.8*0.10 + 0.2*0.05*(1-0.21) = 0.0879
        self.assertAlmostEqual(wacc_of(80, 20, 0.10, 0.05, 0.21), 0.0879)

    def test_wacc_degenerate_returns_re(self):
        self.assertAlmostEqual(wacc_of(0, 0, 0.10, 0.05, 0.21), 0.10)


class TestPresentValueKernel(unittest.TestCase):
    def test_gordon_reduction(self):
        # When g1 == terminal g the 2-stage stream IS a growing perpetuity:
        # V = fcf0*(1+g)/(wacc-g) = 100*1.02/0.08 = 1275, exactly.
        self.assertAlmostEqual(
            ev_present_value(100, 0.10, 0.02, 0.02, 10, 5), 1275.0, places=6)

    def test_two_stage_golden(self):
        # H=2, S1=1, fcf0=100, g1=10%, term 4%, wacc=12% — spec arithmetic spelled out:
        # yr1 fcf=110; yr2 fades fully to 4% → fcf=114.4; Gordon TV off yr2.
        expected = 110 / 1.12 + 114.4 / 1.12**2 + (114.4 * 1.04 / 0.08) / 1.12**2
        self.assertAlmostEqual(
            ev_present_value(100, 0.12, 0.04, 0.10, 2, 1), expected, places=9)

    def test_monotone_decreasing_in_wacc(self):
        vals = [ev_present_value(100, w, 0.025, 0.08, 10, 5)
                for w in (0.07, 0.09, 0.11, 0.13)]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_monotone_increasing_in_growth(self):
        vals = [ev_present_value(100, 0.10, 0.025, g, 10, 5)
                for g in (0.00, 0.05, 0.10, 0.15)]
        self.assertEqual(vals, sorted(vals))


class TestReverseDCF(unittest.TestCase):
    def test_inverts_the_kernel(self):
        # Solve for g, plug back in, recover the target exactly.
        g_true, ndebt = 0.07, 50.0
        target = ev_present_value(100, 0.09, 0.025, g_true, 10, 5) - ndebt
        impl, op = reverse_dcf(100, 0.09, 0.025, ndebt, target, 10, 5)
        self.assertEqual(op, "=")
        self.assertAlmostEqual(impl, g_true, places=6)

    def test_bounds_flagged_not_extrapolated(self):
        impl, op = reverse_dcf(100, 0.09, 0.025, 0, 1.0, 10, 5)      # absurdly cheap
        self.assertEqual((impl, op), (-0.30, "<"))
        impl, op = reverse_dcf(100, 0.09, 0.025, 0, 1e9, 10, 5)      # absurdly rich
        self.assertEqual((impl, op), (0.80, ">"))

    def test_na_on_bad_inputs(self):
        self.assertEqual(reverse_dcf(None, 0.09, 0.025, 0, 100, 10, 5), (None, None))
        self.assertEqual(reverse_dcf(-5, 0.09, 0.025, 0, 100, 10, 5), (None, None))
        # wacc - g below the clamp → TV explodes → refuse, don't emit
        self.assertEqual(reverse_dcf(100, 0.03, 0.025, 0, 100, 10, 5), (None, None))


class TestDCFMonteCarlo(unittest.TestCase):
    def test_percentiles_ordered(self):
        r = dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5, draws=500, seed=42)
        self.assertLessEqual(r["p10"], r["p50"])
        self.assertLessEqual(r["p50"], r["p90"])

    def test_deterministic_for_seed(self):
        a = dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5, draws=300, seed=7)
        b = dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5, draws=300, seed=7)
        self.assertEqual(a, b)

    def test_na_on_bad_inputs(self):
        self.assertIsNone(dcf(None, 0.10, 0.02, 0, 10, 0.05, 10, 5))
        self.assertIsNone(dcf(-5, 0.10, 0.02, 0, 10, 0.05, 10, 5))
        self.assertIsNone(dcf(100, 0.10, 0.02, 0, None, 0.05, 10, 5))


class TestEPV(unittest.TestCase):
    def test_golden_no_adjustment(self):
        # NOPAT 100*0.79=79; ops 79/0.10=790; +cash 20 −debt 50 = 760; /10 shares = 76
        self.assertAlmostEqual(epv(100, 0.21, 0.10, 20, 50, 10), 76.0)

    def test_golden_maintenance_capex(self):
        # adj = dna − min(capex, dna) = 30 − 20 = 10 → (79+10)/0.10 = 890 → 86/share.
        # Documents the intended behavior value.py doesn't use yet (Plan 2).
        self.assertAlmostEqual(epv(100, 0.21, 0.10, 20, 50, 10, dna=30, capex=20), 86.0)

    def test_na_on_bad_inputs(self):
        self.assertIsNone(epv(None, 0.21, 0.10, 0, 0, 10))
        self.assertIsNone(epv(-5, 0.21, 0.10, 0, 0, 10))
        self.assertIsNone(epv(100, 0.21, 0.10, 0, 0, None))


class TestRIM(unittest.TestCase):
    def test_roe_equal_re_returns_book_exactly(self):
        self.assertAlmostEqual(rim(50.0, 0.10, 0.10, 10), 50.0)

    def test_golden_h1(self):
        # book 50, ROE 15%, Re 10%, H=1, ω=0.62:
        # RI1 = 0.05*50 = 2.5 → PV 2.5/1.1; RI2 = 1.55 → CV 1.55/(1.10−0.62) disc 1 yr.
        expected = 50 + 2.5 / 1.1 + (1.55 / 0.48) / 1.1
        self.assertAlmostEqual(rim(50.0, 0.15, 0.10, 1), expected, places=9)

    def test_excess_roe_adds_value_monotonically(self):
        lo, mid, hi = (rim(50.0, r, 0.10, 10) for r in (0.10, 0.15, 0.20))
        self.assertLess(lo, mid)
        self.assertLess(mid, hi)
        self.assertAlmostEqual(lo, 50.0)          # no excess → book


class TestWarrantedMultiple(unittest.TestCase):
    ROWS = [("TECH", 10.0, 0.05, 0.20), ("TECH", 12.0, 0.05, 0.20),
            ("TECH", 14.0, 0.05, 0.20)]

    def test_sector_median_anchor(self):
        fit = warranted_fit(self.ROWS)
        # identical growth/margin → regression degenerate → coef [0,0] → pure anchor 12×
        v = warranted_value(fit, "TECH", 0.05, 0.20, ebit=100, cash=20, debt=50, shares=10)
        self.assertAlmostEqual(v, (12 * 100 - 50 + 20) / 10)          # 117.0

    def test_unknown_sector_falls_back_to_global(self):
        fit = warranted_fit(self.ROWS)
        v = warranted_value(fit, "ENERGY", 0.05, 0.20, ebit=100, cash=20, debt=50, shares=10)
        self.assertAlmostEqual(v, 117.0)

    def test_anchor_cap_blocks_market_froth(self):
        rows = [("TECH", 50.0, 0.05, 0.20), ("TECH", 55.0, 0.05, 0.20),
                ("TECH", 60.0, 0.05, 0.20)]
        fit = warranted_fit(rows)
        v = warranted_value(fit, "TECH", 0.05, 0.20, ebit=10, cash=0, debt=0, shares=1)
        self.assertAlmostEqual(v, 28.0 * 10)      # anchored at the 28× cap, not 55×

    def test_na_on_bad_inputs(self):
        fit = warranted_fit(self.ROWS)
        self.assertIsNone(warranted_value(fit, "TECH", 0.05, 0.20, None, 0, 0, 10))
        self.assertIsNone(warranted_value(fit, "TECH", 0.05, 0.20, -5, 0, 0, 10))
        self.assertIsNone(warranted_value(None, "TECH", 0.05, 0.20, 100, 0, 0, 10))
        self.assertIsNone(warranted_fit([]))


class TestTriangulate(unittest.TestCase):
    def test_floor_never_averaged_into_mid(self):
        tri = triangulate({"DCF": 100.0, "Warranted": 100.0}, 10.0, price=80.0)
        self.assertAlmostEqual(tri["mid"], 100.0)     # EPV=10 must not drag the mid
        self.assertAlmostEqual(tri["low"], 10.0)      # but it does set the low bound
        self.assertAlmostEqual(tri["high"], 100.0)

    def test_weighted_mid(self):
        # DCF 0.25, RIM 0.20 → (100*.25 + 200*.20)/0.45
        tri = triangulate({"DCF": 100.0, "RIM": 200.0}, None, price=100.0)
        self.assertAlmostEqual(tri["mid"], 65.0 / 0.45)

    def test_single_engine_cannot_claim_agreement(self):
        tri = triangulate({"DCF": 100.0}, None, price=80.0)
        self.assertEqual(tri["conf"], 2)
        self.assertAlmostEqual(tri["upside"], 100.0 / 80.0 - 1)

    def test_full_agreement_is_conf5(self):
        tri = triangulate({"DCF": 100.0, "RIM": 105.0, "Warranted": 95.0}, None, price=90.0)
        self.assertEqual(tri["within"], 3)
        self.assertEqual(tri["conf"], 5)

    def test_disagreement_is_low_conf(self):
        tri = triangulate({"DCF": 100.0, "RIM": 200.0}, None, price=100.0)
        self.assertEqual(tri["within"], 0)
        self.assertEqual(tri["conf"], 2)

    def test_floor_only_is_mid_at_low_conf(self):
        tri = triangulate({"DCF": None, "RIM": None}, 50.0, price=100.0)
        self.assertAlmostEqual(tri["mid"], 50.0)
        self.assertEqual(tri["conf"], 2)

    def test_nothing_positive_returns_none(self):
        self.assertIsNone(triangulate({"DCF": None}, None, price=100.0))
        self.assertIsNone(triangulate({"DCF": -5.0}, None, price=100.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
