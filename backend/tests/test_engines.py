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

from common import (ev_present_value, ev_present_value_nopat, effective_tax, cost_of_debt,
                    size_premium)
from engines import (cost_of_equity, wacc_of, reverse_dcf, dcf, epv, rim, ddm,
                     warranted_fit, warranted_value, triangulate)
from value import quality_band

BANDS = [[10e9, 0.000], [2e9, 0.003], [0.5e9, 0.008], [0.0, 0.015]]


class TestDDM(unittest.TestCase):
    def test_gordon_zero_growth(self):
        # g=0, no fade (stage1=horizon): PV of a flat perpetuity-ish stream + Gordon TV.
        # For a flat $1 dividend at Re=10%, term_g=0: value → D/Re = $10 as horizon→∞.
        v = ddm(1.0, 0.10, 0.0, 0.0, 120, 120)
        self.assertAlmostEqual(v, 10.0, places=1)

    def test_none_without_dividend(self):
        self.assertIsNone(ddm(0.0, 0.10, 0.025, 0.05, 10, 5))
        self.assertIsNone(ddm(None, 0.10, 0.025, 0.05, 10, 5))

    def test_none_when_re_not_above_terminal_g(self):
        self.assertIsNone(ddm(2.0, 0.03, 0.025, 0.02, 10, 5))   # Re−term_g < 0.5%

    def test_higher_growth_raises_value(self):
        lo = ddm(2.0, 0.09, 0.025, 0.02, 10, 5)
        hi = ddm(2.0, 0.09, 0.025, 0.06, 10, 5)
        self.assertGreater(hi, lo)

    def test_lower_discount_raises_value(self):
        cheap = ddm(2.0, 0.07, 0.025, 0.03, 10, 5)
        dear = ddm(2.0, 0.11, 0.025, 0.03, 10, 5)
        self.assertGreater(cheap, dear)


class TestRates(unittest.TestCase):
    def test_capm(self):
        self.assertAlmostEqual(cost_of_equity(0.04, 1.2, 0.05), 0.10)

    def test_capm_with_size_premium(self):
        self.assertAlmostEqual(cost_of_equity(0.04, 1.2, 0.05, size_prem=0.008), 0.108)


class TestSizePremium(unittest.TestCase):
    def test_bands(self):
        self.assertAlmostEqual(size_premium(50e9, BANDS), 0.000)   # mega
        self.assertAlmostEqual(size_premium(5e9, BANDS), 0.003)    # mid ($2–10B)
        self.assertAlmostEqual(size_premium(1e9, BANDS), 0.008)    # small ($0.5–2B)
        self.assertAlmostEqual(size_premium(0.3e9, BANDS), 0.015)  # micro

    def test_boundaries_inclusive(self):
        self.assertAlmostEqual(size_premium(10e9, BANDS), 0.000)   # exactly at a threshold
        self.assertAlmostEqual(size_premium(2e9, BANDS), 0.003)

    def test_zero_without_bands_or_mcap(self):
        self.assertEqual(size_premium(5e9, []), 0.0)
        self.assertEqual(size_premium(None, BANDS), 0.0)
        self.assertEqual(size_premium(0, BANDS), 0.0)

    def test_wacc_weighted(self):
        # 80/20 split: 0.8*0.10 + 0.2*0.05*(1-0.21) = 0.0879
        self.assertAlmostEqual(wacc_of(80, 20, 0.10, 0.05, 0.21), 0.0879)

    def test_wacc_degenerate_returns_re(self):
        self.assertAlmostEqual(wacc_of(0, 0, 0.10, 0.05, 0.21), 0.10)


class TestEffectiveTax(unittest.TestCase):
    def test_mean_of_clean_years(self):
        r = effective_tax({2023: 21, 2024: 24}, {2023: 100, 2024: 100})
        self.assertAlmostEqual(r, 0.225)

    def test_clamped_to_band(self):
        self.assertAlmostEqual(effective_tax({2024: 50}, {2024: 100}), 0.35)   # cap
        self.assertAlmostEqual(effective_tax({2024: 2}, {2024: 100}), 0.10)    # floor

    def test_loss_and_benefit_years_skipped(self):
        # 2023: pretax loss; 2024: net tax benefit — neither has a meaningful rate
        r = effective_tax({2023: 10, 2024: -5, 2025: 20},
                          {2023: -100, 2024: 100, 2025: 100})
        self.assertAlmostEqual(r, 0.20)                    # only 2025 counts

    def test_fallback_when_unmeasurable(self):
        self.assertAlmostEqual(effective_tax({}, {}), 0.21)
        self.assertAlmostEqual(effective_tax({2024: -5}, {2024: -100}, fallback=0.25), 0.25)


class TestCostOfDebt(unittest.TestCase):
    def test_effective_rate(self):
        self.assertAlmostEqual(cost_of_debt(5, 100, rf=0.04, spread=0.01), 0.05)

    def test_floored_at_rf_plus_50bp(self):
        self.assertAlmostEqual(cost_of_debt(0.1, 100, rf=0.04, spread=0.01), 0.045)

    def test_capped(self):
        self.assertAlmostEqual(cost_of_debt(30, 100, rf=0.04, spread=0.01), 0.15)

    def test_fallback_when_unmeasurable(self):
        self.assertAlmostEqual(cost_of_debt(None, 100, rf=0.04, spread=0.01), 0.05)
        self.assertAlmostEqual(cost_of_debt(5, 0, rf=0.04, spread=0.01), 0.05)
        self.assertAlmostEqual(cost_of_debt(-2, 100, rf=0.04, spread=0.01), 0.05)


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


class TestNopatKernel(unittest.TestCase):
    def test_high_roic_reinvestment_is_cheap(self):
        # As ROIC → ∞ the reinvestment rate → 0, so the NOPAT stream approaches a pure
        # FCFF stream of size NOPAT: ev_present_value_nopat ≈ ev_present_value(nopat0).
        big = ev_present_value_nopat(100, 1e6, 0.10, 0.025, 0.08, 10, 5)
        pure = ev_present_value(100, 0.10, 0.025, 0.08, 10, 5)
        self.assertAlmostEqual(big, pure, places=3)

    def test_reinvestment_lowers_value(self):
        # Same NOPAT + growth, lower ROIC = more reinvestment = less free cash = lower EV.
        hi_roic = ev_present_value_nopat(100, 0.40, 0.10, 0.025, 0.08, 10, 5)
        lo_roic = ev_present_value_nopat(100, 0.12, 0.10, 0.025, 0.08, 10, 5)
        self.assertGreater(hi_roic, lo_roic)

    def test_reinvestment_capped_keeps_stream_positive(self):
        # ROIC far below growth would imply rr > 1 (negative FCFF); the 0.90 cap keeps
        # every year's contribution non-negative, so EV stays > 0.
        ev = ev_present_value_nopat(100, 0.05, 0.10, 0.025, 0.20, 10, 5)
        self.assertGreater(ev, 0)


class TestDCFNopatPath(unittest.TestCase):
    def test_prefers_nopat_when_supplied(self):
        expected = (ev_present_value_nopat(80, 0.30, 0.10, 0.02, 0.06, 10, 5) - 50) / 10
        got = dcf(999, 0.10, 0.02, 50, 10, 0.06, 10, 5, nopat0=80, roic=0.30)
        self.assertAlmostEqual(got, expected)                # fcf0=999 ignored in favor of NOPAT

    def test_falls_back_to_fcf_when_nopat_unusable(self):
        # nopat0 <= 0 or roic <= 0 → old FCF path exactly (backward compatible).
        expected = dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5)
        self.assertAlmostEqual(dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5, nopat0=-5, roic=0.3),
                               expected)
        self.assertAlmostEqual(dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5, nopat0=80, roic=0),
                               expected)

    def test_reverse_dcf_nopat_inverts(self):
        g_true, ndebt = 0.06, 40.0
        target = ev_present_value_nopat(90, 0.35, 0.09, 0.025, g_true, 10, 5) - ndebt
        impl, op = reverse_dcf(None, 0.09, 0.025, ndebt, target, 10, 5,
                               nopat0=90, roic=0.35)
        self.assertEqual(op, "=")
        self.assertAlmostEqual(impl, g_true, places=5)

    def test_reverse_dcf_na_when_growth_destroys_value(self):
        # ROIC < WACC → EV is non-increasing in g → implied-growth solve is degenerate → n/a.
        self.assertEqual(reverse_dcf(None, 0.10, 0.025, 0, 500, 10, 5,
                                     nopat0=100, roic=0.06), (None, None))


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


class TestDCF(unittest.TestCase):
    def test_is_the_kernel_minus_net_debt_per_share(self):
        expected = (ev_present_value(100, 0.10, 0.02, 0.05, 10, 5) - 50) / 10
        self.assertAlmostEqual(dcf(100, 0.10, 0.02, 50, 10, 0.05, 10, 5), expected)

    def test_na_on_bad_inputs(self):
        self.assertIsNone(dcf(None, 0.10, 0.02, 0, 10, 0.05, 10, 5))
        self.assertIsNone(dcf(-5, 0.10, 0.02, 0, 10, 0.05, 10, 5))
        self.assertIsNone(dcf(100, 0.10, 0.02, 0, None, 0.05, 10, 5))
        # wacc − g below the clamp → TV explodes → refuse, don't emit
        self.assertIsNone(dcf(100, 0.03, 0.025, 0, 10, 0.05, 10, 5))


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
    # (sector, ev_ebit, growth, margin, roic) — identical g/m/roic → degenerate regression
    ROWS = [("TECH", 10.0, 0.05, 0.20, 0.15), ("TECH", 12.0, 0.05, 0.20, 0.15),
            ("TECH", 14.0, 0.05, 0.20, 0.15)]

    def test_sector_median_anchor(self):
        fit = warranted_fit(self.ROWS)
        # identical growth/margin/roic → regression degenerate → coef [0,0,0] → pure anchor 12×
        v = warranted_value(fit, "TECH", 0.05, 0.20, 0.15, ebit=100, cash=20, debt=50, shares=10)
        self.assertAlmostEqual(v, (12 * 100 - 50 + 20) / 10)          # 117.0

    def test_unknown_sector_falls_back_to_global(self):
        fit = warranted_fit(self.ROWS)
        v = warranted_value(fit, "ENERGY", 0.05, 0.20, 0.15, ebit=100, cash=20, debt=50, shares=10)
        self.assertAlmostEqual(v, 117.0)

    def test_higher_roic_earns_a_higher_multiple(self):
        # mechanism: with a positive fitted ROIC coef, a high-ROIC name is valued above a
        # low-ROIC peer at identical growth/margin. Manual fit (smeds, gmed, coef) so the
        # test isolates warranted_value's ROIC term from OLS sampling noise.
        fit = ({}, (12.0, 0.05, 0.20, 0.15), [0.0, 0.0, 20.0])
        lo = warranted_value(fit, "X", 0.05, 0.20, 0.10, ebit=100, cash=0, debt=0, shares=10)
        hi = warranted_value(fit, "X", 0.05, 0.20, 0.40, ebit=100, cash=0, debt=0, shares=10)
        self.assertGreater(hi, lo)                # 170 vs 110

    def test_fit_returns_three_nonneg_coefs(self):
        # varied g/margin/roic → full-rank design → three sign-guarded (≥0) coefficients.
        rows = [("TECH", 8.0, 0.04, 0.16, 0.08), ("TECH", 12.0, 0.06, 0.24, 0.16),
                ("TECH", 18.0, 0.05, 0.18, 0.28), ("TECH", 24.0, 0.07, 0.22, 0.40)]
        _smeds, _gmed, coef = warranted_fit(rows)
        self.assertEqual(len(coef), 3)
        self.assertTrue(all(c >= 0 for c in coef))

    def test_anchor_cap_blocks_market_froth(self):
        rows = [("TECH", 50.0, 0.05, 0.20, 0.15), ("TECH", 55.0, 0.05, 0.20, 0.15),
                ("TECH", 60.0, 0.05, 0.20, 0.15)]
        fit = warranted_fit(rows)
        v = warranted_value(fit, "TECH", 0.05, 0.20, 0.15, ebit=10, cash=0, debt=0, shares=1)
        self.assertAlmostEqual(v, 28.0 * 10)      # anchored at the 28× cap, not 55×

    def test_na_on_bad_inputs(self):
        fit = warranted_fit(self.ROWS)
        self.assertIsNone(warranted_value(fit, "TECH", 0.05, 0.20, 0.15, None, 0, 0, 10))
        self.assertIsNone(warranted_value(fit, "TECH", 0.05, 0.20, 0.15, -5, 0, 0, 10))
        self.assertIsNone(warranted_value(None, "TECH", 0.05, 0.20, 0.15, 100, 0, 0, 10))
        self.assertIsNone(warranted_fit([]))


class TestTriangulate(unittest.TestCase):
    def test_floor_never_averaged_into_mid(self):
        tri = triangulate({"DCF": 100.0, "Warranted": 100.0}, 10.0, price=80.0)
        self.assertAlmostEqual(tri["mid"], 100.0)     # EPV=10 must not drag the mid
        self.assertAlmostEqual(tri["low"], 10.0)      # but it does set the low bound
        self.assertAlmostEqual(tri["high"], 100.0)

    def test_weighted_mid_explicit_weights(self):
        # explicit override: DCF 0.25, RIM 0.20 → (100*.25 + 200*.20)/0.45
        tri = triangulate({"DCF": 100.0, "RIM": 200.0}, None, price=100.0,
                          weights={"DCF": 0.25, "RIM": 0.20})
        self.assertAlmostEqual(tri["mid"], 65.0 / 0.45)

    def test_weighted_mid_default_weights(self):
        from engines import CENTRAL_WEIGHTS as W
        tri = triangulate({"DCF": 100.0, "RIM": 200.0}, None, price=100.0)
        expected = (100 * W["DCF"] + 200 * W["RIM"]) / (W["DCF"] + W["RIM"])
        self.assertAlmostEqual(tri["mid"], expected)

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

    def test_min_band_widens_high_not_low_or_confidence(self):
        eng = {"DCF": 100.0, "RIM": 105.0, "Warranted": 98.0}
        base = triangulate(eng, None, price=100.0)
        wide = triangulate(eng, None, price=100.0, min_band=0.30)
        self.assertEqual(base["conf"], wide["conf"])          # agreement untouched
        self.assertEqual(base["within"], wide["within"])
        self.assertEqual(wide["low"], base["low"])            # low stays at the real engine floor
        self.assertGreaterEqual(wide["high"], wide["mid"] * 1.30 - 1e-9)
        self.assertGreater(wide["high"], base["high"])        # only the high widens

    def test_min_band_does_not_push_low_below_epv_floor(self):
        # value-like name: EPV floor near mid. The band must NOT synthesize a low beneath it —
        # EPV is the floor by design (would be mid·0.60 ≈ 60.9 without the fix).
        tri = triangulate({"DCF": 100.0, "Warranted": 102.0}, floor=95.0, price=100.0, min_band=0.40)
        self.assertAlmostEqual(tri["low"], 95.0)

    def test_min_band_never_narrows_a_wide_spread(self):
        # engines already span far more than the band → range unchanged.
        tri = triangulate({"DCF": 50.0, "RIM": 150.0}, None, price=100.0, min_band=0.10)
        self.assertAlmostEqual(tri["low"], 50.0)
        self.assertAlmostEqual(tri["high"], 150.0)


class TestQualityBand(unittest.TestCase):
    def test_pristine_is_tight(self):
        self.assertAlmostEqual(quality_band(100, False), 0.10)

    def test_low_quality_cyclical_is_wide(self):
        self.assertAlmostEqual(quality_band(0, True), 0.50)   # 0.10 + 0.30 + 0.10

    def test_mid_quality(self):
        self.assertAlmostEqual(quality_band(50, False), 0.25) # 0.10 + 0.5·0.30

    def test_none_quality_defaults_to_50(self):
        self.assertAlmostEqual(quality_band(None, False), 0.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
