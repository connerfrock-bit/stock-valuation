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


class TestFilerForm(unittest.TestCase):
    """bulk.filer_form — the domestic/ADR classifier behind the share-count guard."""

    @staticmethod
    def doc(*forms):
        return {"facts": {"dei": {"Tag": {"units": {"shares": [{"form": f} for f in forms]}}}}}

    def test_domestic(self):
        from bulk import filer_form
        self.assertEqual(filer_form(self.doc("10-K", "10-Q")), "10-K")

    def test_adr(self):
        from bulk import filer_form
        self.assertEqual(filer_form(self.doc("20-F", "6-K")), "20-F")
        self.assertEqual(filer_form(self.doc("40-F")), "20-F")   # Canadian MJDS = foreign

    def test_mixed_prefers_domestic(self):
        # a re-domiciliation that now files 10-Ks is domestic, whatever its history
        from bulk import filer_form
        self.assertEqual(filer_form(self.doc("20-F", "10-K")), "10-K")

    def test_none_when_no_annual_forms(self):
        from bulk import filer_form
        self.assertIsNone(filer_form(self.doc("8-K", "S-1")))
        self.assertIsNone(filer_form(None))
        self.assertIsNone(filer_form({"facts": {}}))


class TestAdrPsSane(unittest.TestCase):
    """value.adr_ps_sane — the 20-F per-share sanity bound (Phase 4.1)."""

    def test_sane_values_pass(self):
        from value import adr_ps_sane
        self.assertTrue(adr_ps_sane(100.0, 60.0))          # +67% deep value: fine
        self.assertTrue(adr_ps_sane(12.0, 100.0))          # −88%: fine (bound is 10×)

    def test_unit_mismatch_fails_both_directions(self):
        from value import adr_ps_sane
        self.assertFalse(adr_ps_sane(53000.0, 50.0))       # Shinhan-style +105,900%
        self.assertFalse(adr_ps_sane(3.0, 50.0))           # 0.06× — inverted basis

    def test_edges(self):
        from value import adr_ps_sane
        self.assertTrue(adr_ps_sane(500.0, 50.0))          # exactly 10× → inclusive
        self.assertFalse(adr_ps_sane(None, 50.0))
        self.assertFalse(adr_ps_sane(50.0, 0.0))


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
