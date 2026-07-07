"""Bank-quality dims (v2.3): pure helpers + the archetype-aware grouping.

Goldens hand-derived: ROE series {10,12,14}% -> mean 12%, population stdev
sqrt(8/3)% ~= 1.633%; equity/assets means over aligned FYs only.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import roe_stability, equity_to_assets, avg_roe
from value import quality_scores


def series(**kv):
    return {int(k): v for k, v in kv.items()}


class TestBankDims(unittest.TestCase):
    def test_roe_stability_golden(self):
        ni = series(**{"2021": 10.0, "2022": 12.0, "2023": 14.0})
        eq = series(**{"2021": 100.0, "2022": 100.0, "2023": 100.0})
        self.assertAlmostEqual(roe_stability(ni, eq), (8 / 3) ** 0.5 / 100, places=9)

    def test_roe_stability_needs_min_obs(self):
        ni = series(**{"2022": 10.0, "2023": 12.0})
        eq = series(**{"2022": 100.0, "2023": 100.0})
        self.assertIsNone(roe_stability(ni, eq))          # 2 obs < min 3

    def test_roe_stability_skips_nonpositive_equity(self):
        ni = series(**{"2020": 8.0, "2021": 10.0, "2022": 12.0, "2023": 14.0})
        eq = series(**{"2020": -50.0, "2021": 100.0, "2022": 100.0, "2023": 100.0})
        # the negative-equity year drops out; 3 obs remain
        self.assertAlmostEqual(roe_stability(ni, eq), (8 / 3) ** 0.5 / 100, places=9)

    def test_equity_to_assets_golden(self):
        eq = series(**{"2021": 8.0, "2022": 9.0, "2023": 10.0})
        ta = series(**{"2021": 100.0, "2022": 100.0, "2023": 100.0})
        self.assertAlmostEqual(equity_to_assets(eq, ta), 0.09, places=9)

    def test_equity_to_assets_alignment(self):
        eq = series(**{"2022": 9.0, "2023": 10.0})
        ta = series(**{"2023": 100.0})                    # only FY2023 overlaps
        self.assertAlmostEqual(equity_to_assets(eq, ta), 0.10, places=9)
        self.assertIsNone(equity_to_assets(eq, {}))


def fin_row(t, roe_avg, roe_pts, eq, ta):
    """Minimal row for the financial path of quality_scores."""
    yrs = range(2018, 2018 + len(roe_pts))
    ni_s = {y: rp * 100 for y, rp in zip(yrs, roe_pts)}
    eq_s = {y: 100.0 for y in yrs}
    return {"t": t, "eff_arch": "financial", "roe_avg": roe_avg,
            "ni_s": ni_s, "eq_s": eq_s,
            "f": {"assets": {y: ta for y in yrs}},
            # eq/assets uses the LAST 3 overlapping years of eq_s vs f.assets
            }


class TestArchetypeQuality(unittest.TestCase):
    def _fins(self):
        # five banks: A dominates every dim, E is worst on every dim
        rows = []
        for i, (t, roe) in enumerate([("A", .18), ("B", .15), ("C", .12), ("D", .09), ("E", .05)]):
            spread = 0.002 * (i + 1)                      # A steadiest, E most volatile
            pts = [roe - spread, roe, roe + spread]
            r = fin_row(t, roe, pts, eq=100.0, ta=100.0 / (0.12 - 0.01 * i))
            rows.append(r)
        return rows

    def test_fin_ranking_monotone(self):
        rows = self._fins()
        quality_scores(rows)
        qs = {r["t"]: r["quality"] for r in rows}
        self.assertTrue(qs["A"] > qs["B"] > qs["C"] > qs["D"] > qs["E"])
        self.assertEqual(qs["A"], 100)

    def test_small_fin_pool_never_fakes_a_number(self):
        rows = self._fins()[:4]                           # below the 5-peer floor
        quality_scores(rows)
        self.assertTrue(all(r["quality"] is None for r in rows))

    def test_standard_pools_exclude_gated_names(self):
        # one standard name + four financials: the standard om pool must not
        # see the financials' garbage om values
        std = {"t": "S", "eff_arch": "standard", "om": 0.25, "roic": 0.20,
               "roe_avg": 0.15, "fcf_margin": 0.18, "ni_s": {}, "eq_s": {},
               "debt_risk": 0.0, "cash": 50.0, "ebit_now": 100.0, "f": {}}
        fins = self._fins()[:4]
        for f in fins:
            f["om"] = 1.7                                 # NII-ratio garbage
        rows = [std] + fins
        quality_scores(rows)
        self.assertEqual(std["quality"], 100)             # alone in every pool -> top


if __name__ == "__main__":
    unittest.main()
