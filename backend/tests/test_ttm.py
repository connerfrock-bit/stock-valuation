"""Tests for the TTM stitcher (Plan 5). stdlib only.
Run from backend/:   python tests/test_ttm.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest_v1 import ttm_from_durations, pick_annual

FY25 = ("2025-01-01", "2025-12-31", 1000.0)


class TestAnnualSpanGuard(unittest.TestCase):
    def test_partial_year_fy_point_rejected(self):
        # MPWR case: a Q4-only duration filed in the 10-K with fp=FY must not become
        # the annual value; the true full-year point must win.
        mk = lambda s, e, v: {"form": "10-K", "fp": "FY", "start": s, "end": e,
                              "val": v, "filed": "2026-02-15"}
        ns = {"Revenues": {"units": {"USD": [
            mk("2025-01-01", "2025-12-31", 2960.0),       # real full year
            mk("2025-10-01", "2025-12-31", 640.0),        # Q4-only, fp=FY (the trap)
        ]}}}
        self.assertEqual(pick_annual(ns, ["Revenues"], "USD"), {2025: 2960.0})

    def test_instant_points_unaffected(self):
        # balance-sheet points have no `start` — the guard must not drop them
        ns = {"Assets": {"units": {"USD": [
            {"form": "10-K", "fp": "FY", "end": "2025-12-31", "val": 500.0,
             "filed": "2026-02-15"},
        ]}}}
        self.assertEqual(pick_annual(ns, ["Assets"], "USD"), {2025: 500.0})


class TestTTMStitcher(unittest.TestCase):
    def test_ytd_reporter(self):
        # standard case: latest 10-Q reports H1 YTD; mirror exists for prior year
        pts = [FY25,
               ("2025-01-01", "2025-06-30", 500.0),       # prior-year mirror
               ("2026-01-01", "2026-06-30", 550.0)]       # current YTD
        v, thru, basis = ttm_from_durations(pts)
        self.assertEqual(basis, "ttm")
        self.assertEqual(thru, "2026-06-30")
        self.assertAlmostEqual(v, 1000 + 550 - 500)       # 1050

    def test_qtd_chain_reporter(self):
        # quarterly-only filer: two discrete QTD points chain back to the FY boundary
        pts = [FY25,
               ("2025-01-01", "2025-03-31", 250.0), ("2025-04-01", "2025-06-30", 280.0),
               ("2026-01-01", "2026-03-31", 260.0), ("2026-04-01", "2026-06-30", 290.0)]
        v, thru, basis = ttm_from_durations(pts)
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(v, 1000 + (260 + 290) - (250 + 280))   # 1020

    def test_prefers_ytd_over_qtd_when_both_filed(self):
        # H1 YTD and Q2 QTD share the same end date — the longer span must win
        pts = [FY25,
               ("2025-01-01", "2025-06-30", 500.0),
               ("2026-01-01", "2026-06-30", 550.0),       # H1 YTD (chosen)
               ("2026-04-01", "2026-06-30", 290.0)]       # Q2 QTD (same end)
        v, _, basis = ttm_from_durations(pts)
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(v, 1050)

    def test_missing_prior_mirror_falls_back_to_fy(self):
        pts = [FY25, ("2026-01-01", "2026-06-30", 550.0)]     # no prior-year H1
        v, thru, basis = ttm_from_durations(pts)
        self.assertEqual((v, thru, basis), (1000.0, "2025-12-31", "fy"))

    def test_fresh_10k_no_quarters_yet(self):
        v, thru, basis = ttm_from_durations([FY25])
        self.assertEqual((v, thru, basis), (1000.0, "2025-12-31", "fy"))

    def test_no_annual_point_returns_none(self):
        self.assertIsNone(ttm_from_durations([("2026-01-01", "2026-03-31", 250.0)]))
        self.assertIsNone(ttm_from_durations([]))

    def test_offset_fiscal_calendar(self):
        # 52/53-week retailer style: FY ends Jan 31; Q1 spans Feb–Apr with slight drift
        pts = [("2025-02-01", "2026-01-31", 2000.0),
               ("2025-02-02", "2025-05-03", 480.0),       # prior Q1 (a couple days off)
               ("2026-02-01", "2026-05-02", 520.0)]       # current Q1
        v, thru, basis = ttm_from_durations(pts)
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(v, 2000 + 520 - 480)       # 2040
        self.assertEqual(thru, "2026-05-02")

    def test_uses_latest_fy_when_several(self):
        pts = [("2024-01-01", "2024-12-31", 900.0), FY25,
               ("2025-01-01", "2025-06-30", 500.0),
               ("2026-01-01", "2026-06-30", 550.0)]
        v, _, basis = ttm_from_durations(pts)
        self.assertAlmostEqual(v, 1050)                   # anchored on FY25, not FY24


if __name__ == "__main__":
    unittest.main(verbosity=2)
