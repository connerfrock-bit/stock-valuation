"""REIT FFO engine (v2.4): FFO series, P/FFO anchor, and the replace-RIM contract."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from value import ffo_series, pffo_anchor
from engines import triangulate


class TestFfoSeries(unittest.TestCase):
    def test_golden_with_gains(self):
        ni = {2022: 100.0, 2023: 110.0}
        dna = {2022: 40.0, 2023: 42.0}
        gains = {2023: 12.0}
        self.assertEqual(ffo_series(ni, dna, gains), {2022: 140.0, 2023: 140.0})

    def test_no_gains_tag_means_plain_addback(self):
        ni, dna = {2023: 100.0}, {2023: 40.0}
        self.assertEqual(ffo_series(ni, dna, {}), {2023: 140.0})

    def test_only_overlapping_years(self):
        self.assertEqual(ffo_series({2022: 1.0, 2023: 2.0}, {2023: 3.0}, {}), {2023: 5.0})

    def test_impairment_added_back(self):
        # the CCI shape: a huge writedown crushes NI; FFO adds it back
        ni, dna, imp = {2024: -30.0}, {2024: 40.0}, {2024: 50.0}
        self.assertEqual(ffo_series(ni, dna, {}, imp), {2024: 60.0})


class TestPffoAnchor(unittest.TestCase):
    def test_median_within_band(self):
        self.assertEqual(pffo_anchor([10, 12, 14, 16, 18]), 14)

    def test_cap_and_floor(self):
        self.assertEqual(pffo_anchor([30, 32, 34, 36, 38]), 20.0)   # frothy pool -> cap
        self.assertEqual(pffo_anchor([3, 4, 5, 6, 7]), 8.0)         # distressed pool -> floor

    def test_min_peers(self):
        self.assertIsNone(pffo_anchor([12, 14, 15, 16]))             # 4 < 5 -> no anchor

    def test_ignores_nonpositive(self):
        self.assertIsNone(pffo_anchor([12, 14, 15, 16, -3, 0]))      # only 4 valid


class TestReplaceRimContract(unittest.TestCase):
    def test_single_ffo_engine_prices_negative_book_reit(self):
        # a tower REIT: book useless, FFO real -> mid == FFO value, conf 2 (single engine)
        tri = triangulate({"DCF": None, "RIM": None, "Warranted": None, "FFO": 84.0},
                          None, price=70.0)
        self.assertAlmostEqual(tri["mid"], 84.0)
        self.assertEqual(tri["conf"], 2)
        self.assertAlmostEqual(tri["upside"], 0.2)


if __name__ == "__main__":
    unittest.main()
