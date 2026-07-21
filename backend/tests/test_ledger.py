"""Tests for the forward paper-trading ledger (Plan 4). stdlib only.
Run from backend/:   python tests/test_ledger.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import build_ledger, _session_mapper


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


# 2026-07-10 Fri, 07-11 Sat, 07-12 Sun, 07-13 Mon — the shape that produced the bugs.
WEEK = ["2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14"]


class TestSessionCollapse(unittest.TestCase):
    """Weekend runs price off Friday's close — they are Friday's basket relabelled,
       not new evidence. Counting them tripled the sample and made hit-rate a
       foregone conclusion."""

    def test_session_mapper_folds_weekend_into_friday(self):
        s = _session_mapper(WEEK)
        self.assertEqual(s("2026-07-10"), "2026-07-10")     # Fri -> itself
        self.assertEqual(s("2026-07-11"), "2026-07-10")     # Sat -> Fri
        self.assertEqual(s("2026-07-12"), "2026-07-10")     # Sun -> Fri
        self.assertEqual(s("2026-07-13"), "2026-07-13")     # Mon -> itself
        self.assertEqual(s("2020-01-01"), "2020-01-01")     # pre-history: unchanged

    def test_weekend_runs_collapse_and_are_counted(self):
        runs = {(f"{d} 17:00:00", "v2"): run_rows(lambda i: 10.0)
                for d in ("2026-07-10", "2026-07-11", "2026-07-12")}
        runs[("2026-07-14 17:00:00", "v2")] = run_rows(lambda i: 11.0)
        lg = build_ledger(runs, trading_days=WEEK)
        days = [b["date"] for b in lg["baskets"]]
        self.assertEqual(days, ["2026-07-10", "2026-07-14"])   # not four baskets
        self.assertEqual(lg["summary"]["v2"]["collapsed"], 2)   # disclosed, not silent

    def test_earliest_commit_wins_the_session(self):
        """Fri and Sat share a close; the Fri basket is the one committed first at
           that price, so it is the honest one to keep."""
        runs = {("2026-07-10 17:00:00", "v2"): run_rows(lambda i: 10.0),
                ("2026-07-11 09:00:00", "v2"): run_rows(lambda i: 99.0),
                ("2026-07-14 17:00:00", "v2"): run_rows(lambda i: 10.0)}
        lg = build_ledger(runs, trading_days=WEEK)
        self.assertEqual(lg["baskets"][0]["runDate"], "2026-07-10 17:00:00")
        self.assertAlmostEqual(lg["baskets"][0]["basketRet"], 0.0)   # 10 -> 10, not 99 -> 10

    def test_same_day_rerun_still_takes_the_last_run(self):
        """Within one calendar day a re-run supersedes (value.py replaces the row);
           across days sharing a session the earliest wins. Both rules coexist."""
        runs = {("2026-07-10 09:00:00", "v2"): run_rows(lambda i: 99.0),
                ("2026-07-10 17:00:00", "v2"): run_rows(lambda i: 10.0),
                ("2026-07-14 17:00:00", "v2"): run_rows(lambda i: 10.0)}
        lg = build_ledger(runs, trading_days=WEEK)
        self.assertEqual(lg["baskets"][0]["runDate"], "2026-07-10 17:00:00")


class TestMarkDecoupledFromSnapshots(unittest.TestCase):
    """The regression that mattered: marking to the newest SNAPSHOT froze forward
       returns for a week at a time, because snapshot writes are ISO-week-gated."""

    def test_mark_price_comes_from_the_argument_not_the_latest_run(self):
        runs = {("2026-07-09 17:00:00", "v2"): run_rows(lambda i: 10.0),
                ("2026-07-10 17:00:00", "v2"): run_rows(lambda i: 10.0)}
        # No new snapshot since 07-10, but the market moved: top names +30%, rest flat.
        mark = {f"T{i}": (13.0 if i < 10 else 10.0) for i in range(50)}
        lg = build_ledger(runs, mark_px=mark, mark_day="2026-07-14",
                          trading_days=WEEK)
        first = lg["baskets"][0]
        self.assertAlmostEqual(first["basketRet"], 0.30)     # would be 0.0 if snapshot-coupled
        self.assertAlmostEqual(first["excess"], 0.24)
        self.assertEqual(lg["meta"]["markedTo"], "2026-07-14")

    def test_returns_advance_between_snapshot_writes(self):
        """Same snapshots, two different mark days -> two different answers. Under the
           old behaviour both would be identical until a new snapshot landed."""
        runs = {("2026-07-09 17:00:00", "v2"): run_rows(lambda i: 10.0)}
        a = build_ledger(runs, mark_px={f"T{i}": 11.0 for i in range(50)},
                         mark_day="2026-07-10", trading_days=WEEK)
        b = build_ledger(runs, mark_px={f"T{i}": 12.0 for i in range(50)},
                         mark_day="2026-07-14", trading_days=WEEK)
        self.assertAlmostEqual(a["baskets"][0]["basketRet"], 0.10)
        self.assertAlmostEqual(b["baskets"][0]["basketRet"], 0.20)
        self.assertEqual(a["baskets"][0]["tradingDays"], 1)
        self.assertEqual(b["baskets"][0]["tradingDays"], 3)

    def test_entry_px_drops_rather_than_mixing_price_sources(self):
        """An adjusted exit against an unadjusted entry would invent a return out of a
           dividend. A name with no adjusted entry is dropped and counted instead."""
        runs = {("2026-07-09 17:00:00", "v2"): run_rows(lambda i: 10.0)}
        entry = {("2026-07-09", f"T{i}"): 10.0 for i in range(50) if i != 0}
        lg = build_ledger(runs, mark_px={f"T{i}": 11.0 for i in range(50)},
                          mark_day="2026-07-14", trading_days=WEEK, entry_px=entry)
        b = lg["baskets"][0]
        self.assertEqual(b["covered"], 9)
        self.assertEqual(b["missing"], 1)


class TestOverlapDisclosure(unittest.TestCase):
    """A basket count is not a bet count. Consecutive runs re-rank the same universe."""

    def test_identical_baskets_report_as_one_distinct(self):
        runs = {(f"{d} 17:00:00", "v2"): run_rows(lambda i: 10.0)
                for d in ("2026-07-09", "2026-07-10", "2026-07-13")}
        lg = build_ledger(runs, mark_px={f"T{i}": 11.0 for i in range(50)},
                          mark_day="2026-07-14", trading_days=WEEK)
        s = lg["summary"]["v2"]
        self.assertEqual(s["aged"], 3)
        self.assertEqual(s["distinctBaskets"], 1)     # three labels, one bet
        self.assertAlmostEqual(s["avgOverlap"], 1.0)

    def test_disjoint_baskets_report_as_independent(self):
        a = {f"A{i}": (10.0, float(50 - i)) for i in range(50)}
        b = {f"B{i}": (10.0, float(50 - i)) for i in range(50)}
        runs = {("2026-07-09 17:00:00", "v2"): a, ("2026-07-10 17:00:00", "v2"): b}
        mark = {f"A{i}": 11.0 for i in range(50)} | {f"B{i}": 11.0 for i in range(50)}
        s = build_ledger(runs, mark_px=mark, mark_day="2026-07-14",
                         trading_days=WEEK)["summary"]["v2"]
        self.assertEqual(s["distinctBaskets"], 2)
        self.assertAlmostEqual(s["avgOverlap"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
