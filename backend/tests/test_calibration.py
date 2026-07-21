"""Tests for the cross-sectional calibration report. stdlib only.
Run from backend/:   python tests/test_calibration.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibration import (spearman, _ranks, buckets, neutralize, beta_neutral,
                         sector_neutral, build_calibration)

# A 20-session calendar so window-independence can be exercised realistically.
SESSIONS = [f"2026-07-{d:02d}" for d in range(1, 21)]


def row(t, upside, fwd, beta=1.0, sector="Tech", score=None, quality=50, conf=3):
    return {"ticker": t, "upside": upside, "fwd": fwd, "beta": beta, "sector": sector,
            "score": upside if score is None else score, "quality": quality, "conf": conf}


class TestSpearman(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(spearman([(1, 1), (2, 2), (3, 3), (4, 4)]), 1.0)
        self.assertAlmostEqual(spearman([(1, 4), (2, 3), (3, 2), (4, 1)]), -1.0)
        # textbook: x=[1..5], y=[5,6,7,8,7] -> rho = 0.8208
        self.assertAlmostEqual(spearman(list(zip([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]))),
                               0.8208, places=4)

    def test_ties_share_average_rank(self):
        self.assertEqual(_ranks([5, 5, 1, 9]), [2.5, 2.5, 1.0, 4.0])

    def test_float_noise_ties_are_not_ordered_by_rounding_error(self):
        """Demeaning makes equal values differ in the last bit. Ranking those as
           distinct invents an ordering out of noise — it scored a -0.136 IC on data
           whose true correlation is exactly 0."""
        noisy = [0.005, 0.005 + 4e-18, 0.005 - 2e-18, -0.005, -0.005 + 1e-18]
        self.assertEqual(len(set(_ranks(noisy))), 2)   # two tie groups, not five ranks

    def test_undefined_cases_return_none(self):
        self.assertIsNone(spearman([(1, 2), (2, 3)]))              # n < 3
        self.assertIsNone(spearman([(1, 7), (1, 7), (1, 7)]))      # no variance

    def test_rank_based_survives_a_pathological_outlier(self):
        """The live S&P 1500 run has upside values past +24,000%. A Pearson correlation
           would be decided by that single name; a rank IC must not be."""
        clean = [(float(i), float(i)) for i in range(20)]
        wrecked = clean[:-1] + [(240.0, 19.0)]
        self.assertAlmostEqual(spearman(clean), spearman(wrecked))


class TestBuckets(unittest.TestCase):
    def test_equal_count_not_equal_width(self):
        rows = [row(f"T{i}", float(i) ** 3, 0.0) for i in range(100)]
        b = buckets(rows, "upside", 10)
        self.assertEqual([len(x) for x in b], [10] * 10)
        self.assertLess(b[0][0]["upside"], b[-1][0]["upside"])

    def test_too_few_rows_yields_nothing(self):
        self.assertEqual(buckets([row("A", 1.0, 0.0)], "upside", 10), [])


class TestNeutralization(unittest.TestCase):
    def test_neutralize_demeans_within_group(self):
        rows = [row("A", 1, 0.10, sector="X"), row("B", 2, 0.20, sector="X"),
                row("C", 3, 0.30, sector="X")]
        out = sector_neutral(rows)
        self.assertAlmostEqual(sum(r["fwd"] for r in out), 0.0)

    def test_thin_groups_are_dropped_not_self_demeaned(self):
        rows = [row(f"T{i}", i, 0.1, sector="Big") for i in range(5)]
        rows += [row("Solo", 9, 0.9, sector="Tiny")]
        out = neutralize(rows, lambda r: r["sector"])
        self.assertEqual({r["ticker"] for r in out}, {f"T{i}" for i in range(5)})

    def test_beta_neutral_kills_a_pure_beta_bet(self):
        """The confound that matters: a valuation model flags expensive names, expensive
           names run high beta, and in a falling market that reads as skill. Here the
           forward return is a pure function of beta and 'upside' is just -beta, so the
           raw IC is near-perfect and the beta-neutral IC must be ~0."""
        rows = []
        for g, beta in enumerate((0.6, 0.8, 1.0, 1.2, 1.4)):
            for j in range(10):
                idio = 0.005 if j % 2 else -0.005      # mean-zero inside the beta bucket
                rows.append(row(f"G{g}N{j}", -beta, -0.10 * beta + idio, beta=beta))
        raw = spearman([(r["upside"], r["fwd"]) for r in rows])
        bn = spearman([(r["upside"], r["fwd"]) for r in beta_neutral(rows)])
        self.assertGreater(raw, 0.9)
        self.assertLess(abs(bn), 0.1)

    def test_beta_neutral_keeps_a_genuine_stock_pick(self):
        """Same beta structure, but upside now carries real within-bucket information.
           Neutralizing beta must NOT destroy it."""
        rows = []
        for g, beta in enumerate((0.6, 0.8, 1.0, 1.2, 1.4)):
            for j in range(10):
                rows.append(row(f"G{g}N{j}", float(j), -0.10 * beta + 0.002 * j, beta=beta))
        bn = spearman([(r["upside"], r["fwd"]) for r in beta_neutral(rows)])
        self.assertGreater(bn, 0.9)

    def test_beta_neutral_needs_enough_names(self):
        self.assertEqual(beta_neutral([row("A", 1, 0.1, beta=1.0)]), [])


class TestPowerGate(unittest.TestCase):
    """The ledger already shipped a 100% hit rate that was one observation. The
       calibration report must refuse to make the same claim."""

    def _panel(self, days):
        return {d: [row(f"T{i}", float(i), float(i) / 100) for i in range(60)]
                for d in days}

    def test_overlapping_sessions_do_not_count_as_independent(self):
        p = build_calibration(self._panel(SESSIONS[:5]), SESSIONS, horizon=5)
        self.assertEqual(p["power"]["snapshotSessions"], 5)
        self.assertEqual(p["power"]["independentWindows"], 1)   # 5 consecutive days, one window
        self.assertFalse(p["readable"])
        self.assertIn("NOT READABLE", p["verdict"])

    def test_spaced_sessions_count_separately(self):
        days = [SESSIONS[i] for i in (0, 5, 10, 15)]
        p = build_calibration(self._panel(days), SESSIONS, horizon=5)
        self.assertEqual(p["power"]["independentWindows"], 4)

    def test_readable_only_once_windows_clear_the_bar(self):
        days = [SESSIONS[i] for i in (0, 5, 10, 15)]
        p = build_calibration(self._panel(days), SESSIONS, horizon=5, min_windows=4)
        self.assertTrue(p["readable"])
        self.assertNotIn("NOT READABLE", p["verdict"])

    def test_thin_sessions_are_excluded(self):
        panel = {SESSIONS[0]: [row(f"T{i}", float(i), 0.01) for i in range(5)]}
        self.assertIsNone(build_calibration(panel, SESSIONS, horizon=5))


class TestReportShape(unittest.TestCase):
    def test_perfect_signal_reports_monotone_deciles(self):
        panel = {SESSIONS[0]: [row(f"T{i}", float(i), float(i) / 100) for i in range(100)]}
        p = build_calibration(panel, SESSIONS, horizon=5)
        fwds = [d["meanFwd"] for d in p["deciles"]]
        self.assertEqual(fwds, sorted(fwds))
        self.assertGreater(p["decileSpread"], 0)
        self.assertAlmostEqual(p["ic"]["upside"]["mean"], 1.0)

    def test_anti_predictive_signal_is_reported_as_such(self):
        panel = {SESSIONS[0]: [row(f"T{i}", float(i), -float(i) / 100) for i in range(100)]}
        p = build_calibration(panel, SESSIONS, horizon=5, min_windows=1)
        self.assertAlmostEqual(p["ic"]["upside"]["mean"], -1.0)
        self.assertLess(p["decileSpread"], 0)
        self.assertIn("ANTI-predicts", p["verdict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
