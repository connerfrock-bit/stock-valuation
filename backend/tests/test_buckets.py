"""Warranted-anchor buckets + override table (v2.5)."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import OVERRIDES
from value import assign_buckets


def row(t, sector, ok=True):
    return {"t": t, "sector": sector, "_ok": ok}


OK = lambda r: r["_ok"]


class TestAssignBuckets(unittest.TestCase):
    def test_split_holds_at_min_bucket(self):
        rows = [row(f"S{i}", "Tech") for i in range(8)] + [row("X", "Tech")]
        ovr = {f"S{i}": "semis" for i in range(8)}
        assign_buckets(rows, ovr, OK)
        self.assertTrue(all(r["wbucket"] == "semis" for r in rows[:8]))
        self.assertEqual(rows[8]["wbucket"], "Tech")      # unmapped stays parent

    def test_small_bucket_rolls_back_to_sector(self):
        rows = [row(f"S{i}", "Tech") for i in range(7)]   # 7 < 8
        ovr = {f"S{i}": "semis" for i in range(7)}
        assign_buckets(rows, ovr, OK)
        self.assertTrue(all(r["wbucket"] == "Tech" for r in rows))

    def test_only_fitted_names_count_toward_the_gate(self):
        # 8 mapped names but one fails the fit filter -> 7 fitted -> rollup
        rows = [row(f"S{i}", "Tech", ok=(i != 0)) for i in range(8)]
        ovr = {f"S{i}": "semis" for i in range(8)}
        assign_buckets(rows, ovr, OK)
        self.assertTrue(all(r["wbucket"] == "Tech" for r in rows))

    def test_non_overridden_sectors_untouched(self):
        rows = [row("JNJ", "Health Care"), row("XOM", "Energy")]
        assign_buckets(rows, {"NVDA": "semis"}, OK)
        self.assertEqual(rows[0]["wbucket"], "Health Care")
        self.assertEqual(rows[1]["wbucket"], "Energy")


class TestOverrideTable(unittest.TestCase):
    def test_csgp_archetype_corrected(self):
        self.assertEqual(OVERRIDES["archetype"]["CSGP"], "standard")

    def test_subsector_values_are_known_buckets(self):
        self.assertTrue(set(OVERRIDES["subsector"].values()) <= {"semis", "software", "hardware"})


if __name__ == "__main__":
    unittest.main()
