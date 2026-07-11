"""Phase 4 (NYSE universe): SIC→sector layered lookup, the non-company class filter,
and the junction mcap floor semantics. Pure functions only — no DB, no network."""
import unittest

from universe import sector_by_sic, NONCOMPANY_SICS, _FUND_NAME


class TestSectorBySic(unittest.TestCase):
    TABLE = {"60": "Financials", "67": "Real Estate", "6798": "Real Estate",
             "73": "Information Technology", "7389": "Industrials", "738": "Industrials",
             "28": "Health Care", "282": "Materials"}

    def test_exact_four_digit_wins(self):
        # 7389 (services NEC) hand-pinned to Industrials even though 73xx is IT
        self.assertEqual(sector_by_sic("7389", self.TABLE), "Industrials")

    def test_three_digit_beats_two(self):
        # 282x (plastics/synthetics) → Materials while 28 defaults Health Care (pharma)
        self.assertEqual(sector_by_sic("2821", self.TABLE), "Materials")
        self.assertEqual(sector_by_sic("2836", self.TABLE), "Health Care")

    def test_two_digit_fallback(self):
        self.assertEqual(sector_by_sic("6022", self.TABLE), "Financials")

    def test_unmapped_returns_none(self):
        # never guess — the caller drops unmapped-SIC names rather than mislabel them
        self.assertIsNone(sector_by_sic("0100", self.TABLE))
        self.assertIsNone(sector_by_sic("", self.TABLE))
        self.assertIsNone(sector_by_sic(None, self.TABLE))


class TestNonCompanyFilter(unittest.TestCase):
    def test_fund_class_sics(self):
        # closed-end funds, commodity trusts, SPACs, royalty trusts — out of scope
        for sic in ("6726", "6221", "6770", "6792"):
            self.assertIn(sic, NONCOMPANY_SICS)

    def test_reits_survive(self):
        self.assertNotIn("6798", NONCOMPANY_SICS)

    def test_fund_name_patterns(self):
        # the class the census caught slipping through on SIC alone
        for name in ("SPDR GOLD TRUST", "iShares Silver Trust", "XYZ Income Fund Inc",
                     "ACME EXCHANGE TRADED NOTES"):
            self.assertTrue(_FUND_NAME.search(name), name)

    def test_operating_trust_names_survive(self):
        # REIT-style names must NOT trip the fund regex
        for name in ("Tanger Factory Outlet Centers", "Boston Properties",
                     "AMERICAN TOWER REIT TRUST", "Enterprise Products Partners L.P."):
            self.assertFalse(_FUND_NAME.search(name), name)


class TestJunctionFloor(unittest.TestCase):
    """The floor rule ingest applies when building universe_membership."""

    def admit(self, floors, mcap, ingested):
        rows = []
        for t, us in ingested.items():
            for u in us:
                f = floors.get(u)
                if f and mcap.get(t, 0.0) < f:
                    continue
                rows.append((u, t))
        return rows

    def test_floor_only_gates_configured_universe(self):
        floors = {"nyse": 1e9}
        mcap = {"BIG": 5e9, "TINY": 2e8}
        ingested = {"BIG": {"nyse", "sp1500"}, "TINY": {"nyse", "sp1500"}}
        rows = self.admit(floors, mcap, ingested)
        self.assertIn(("nyse", "BIG"), rows)
        self.assertNotIn(("nyse", "TINY"), rows)          # floored out of nyse…
        self.assertIn(("sp1500", "TINY"), rows)           # …but untouched elsewhere

    def test_missing_price_means_not_a_member(self):
        floors = {"nyse": 1e9}
        rows = self.admit(floors, {}, {"NOPRICE": {"nyse"}})
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
