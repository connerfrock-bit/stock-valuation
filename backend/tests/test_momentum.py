"""Tests for the momentum study helpers (Plan C). stdlib only.
Run from backend/:   python tests/test_momentum.py
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from momentum import month_add, mom_12_1, members_at, run


class TestMonthAdd(unittest.TestCase):
    def test_forward_back(self):
        self.assertEqual(month_add("2020-01", 1), "2020-02")
        self.assertEqual(month_add("2020-12", 1), "2021-01")
        self.assertEqual(month_add("2020-01", -1), "2019-12")
        self.assertEqual(month_add("2020-06", -12), "2019-06")
        self.assertEqual(month_add("2020-03", 12), "2021-03")


class TestMom121(unittest.TestCase):
    def test_skips_recent_month(self):
        # 12-1 uses m-12 → m-1, NOT m itself. Build a series where the last month spikes;
        # the signal must ignore it.
        a = {month_add("2021-01", -k): 100.0 for k in range(13)}
        a["2020-01"] = 50.0                                   # 12 months before 2021-01
        a["2020-12"] = 110.0                                  # 1 month before
        a["2021-01"] = 999.0                                  # most recent — must be ignored
        self.assertAlmostEqual(mom_12_1(a, "2021-01"), 110.0 / 50.0 - 1)

    def test_none_when_history_missing(self):
        self.assertIsNone(mom_12_1({"2021-01": 100.0}, "2021-01"))
        self.assertIsNone(mom_12_1({}, "2021-01"))

    def test_none_on_nonpositive_base(self):
        a = {"2020-01": 0.0, "2020-12": 100.0}
        self.assertIsNone(mom_12_1(a, "2021-01"))


class TestMembersAt(unittest.TestCase):
    def test_forward_fill(self):
        mem_q = {"2020-03": {"A", "B"}, "2020-06": {"A", "C"}}
        self.assertEqual(members_at(mem_q, "2020-04"), {"A", "B"})   # most recent ≤ month
        self.assertEqual(members_at(mem_q, "2020-06"), {"A", "C"})
        self.assertEqual(members_at(mem_q, "2020-08"), {"A", "C"})
        self.assertEqual(members_at(mem_q, "2020-01"), set())        # before any snapshot


class TestRunNoLookahead(unittest.TestCase):
    def test_return_uses_only_future_of_signal(self):
        # one clear winner (W) and one loser (L); the winner's forward month is +10%.
        # 20-name floor: pad with flat names so the basket forms.
        months = [f"2021-{mm:02d}" for mm in range(1, 3)]      # decide at 2021-01, hold →02
        adj = {}
        for i in range(25):
            t = f"T{i}"
            s = {month_add("2021-01", -k): 100.0 for k in range(14)}
            s["2021-02"] = 100.0
            adj[t] = s
        # make T0 the momentum leader and give it a +10% forward month
        adj["T0"]["2020-01"] = 50.0; adj["T0"]["2020-12"] = 130.0
        adj["T0"]["2021-02"] = 110.0
        mem_q = {"2021-01": set(adj)}
        series = run(adj, mem_q, ["2021-01"], {}, trend_filter=False)
        self.assertEqual(len(series), 1)
        m, strat, bench, turn = series[0]
        self.assertEqual(m, "2021-01")
        self.assertGreater(strat, bench)                      # the momentum leader lifted the basket


if __name__ == "__main__":
    unittest.main(verbosity=2)
