"""Tests for the forward paper-trading ledger (Plan 4). stdlib only.
Run from backend/:   python tests/test_ledger.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import build_ledger


def run_rows(price_fn, n=50):
    """{ticker: (price, score)} with T0 the best-scored name."""
    return {f"T{i}": (price_fn(i), float(n - i)) for i in range(n)}


class TestBuildLedger(unittest.TestCase):
    def test_forward_returns_and_quintile(self):
        # Jan basket: 50 names @ $10, top decile-of-score = T0..T9 (k = max(10, 50//5)).
        # By Apr, T0..T9 are +20%, the rest flat → basket +20%, bench +4%, excess +16%.
        runs = {
            ("2026-01-01 10:00:00", "v2"): run_rows(lambda i: 10.0),
            ("2026-04-01 10:00:00", "v2"): run_rows(lambda i: 12.0 if i < 10 else 10.0),
        }
        lg = build_ledger(runs)
        jan, apr = lg["baskets"]
        self.assertEqual(jan["k"], 10)
        self.assertEqual(jan["names"][0], "T0")
        self.assertEqual(jan["ageDays"], 90)
        self.assertAlmostEqual(jan["basketRet"], 0.20)
        self.assertAlmostEqual(jan["benchRet"], 0.04)
        self.assertAlmostEqual(jan["excess"], 0.16)
        # the latest basket has no forward window yet
        self.assertEqual(apr["ageDays"], 0)
        self.assertAlmostEqual(apr["basketRet"], 0.0)

    def test_summary_counts_only_aged_baskets(self):
        runs = {
            ("2026-01-01 10:00:00", "v2"): run_rows(lambda i: 10.0),
            ("2026-04-01 10:00:00", "v2"): run_rows(lambda i: 12.0 if i < 10 else 10.0),
        }
        s = build_ledger(runs)["summary"]["v2"]
        self.assertEqual(s["baskets"], 2)
        self.assertEqual(s["aged"], 1)              # the age-0 basket must not count
        self.assertAlmostEqual(s["avgExcess"], 0.16)
        self.assertAlmostEqual(s["hitRate"], 1.0)
        self.assertEqual(s["oldestDays"], 90)

    def test_same_day_reruns_collapse_to_last(self):
        runs = {
            ("2026-01-01 09:00:00", "v2"): run_rows(lambda i: 99.0),   # superseded
            ("2026-01-01 17:00:00", "v2"): run_rows(lambda i: 10.0),
            ("2026-04-01 10:00:00", "v2"): run_rows(lambda i: 10.0),
        }
        lg = build_ledger(runs)
        self.assertEqual(len(lg["baskets"]), 2)     # one per (model, day)
        self.assertEqual(lg["baskets"][0]["runDate"], "2026-01-01 17:00:00")
        self.assertAlmostEqual(lg["baskets"][0]["basketRet"], 0.0)   # 10 → 10, not 99 → 10

    def test_excluded_names_dropped_and_counted(self):
        early = run_rows(lambda i: 10.0)
        late = run_rows(lambda i: 10.0)
        del late["T0"]                              # T0 later excluded from coverage
        runs = {("2026-01-01 10:00:00", "v2"): early,
                ("2026-04-01 10:00:00", "v2"): late}
        jan = build_ledger(runs)["baskets"][0]
        self.assertEqual(jan["covered"], 9)
        self.assertEqual(jan["missing"], 1)
        self.assertAlmostEqual(jan["basketRet"], 0.0)

    def test_models_tracked_separately(self):
        runs = {
            ("2026-01-01 10:00:00", "v1"): run_rows(lambda i: 10.0),
            ("2026-01-01 12:00:00", "v2"): run_rows(lambda i: 10.0),
            ("2026-04-01 10:00:00", "v2"): run_rows(lambda i: 11.0),
        }
        lg = build_ledger(runs)
        self.assertEqual({b["model"] for b in lg["baskets"]}, {"v1", "v2"})
        self.assertEqual(set(lg["summary"]), {"v1", "v2"})

    def test_empty(self):
        self.assertIsNone(build_ledger({}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
