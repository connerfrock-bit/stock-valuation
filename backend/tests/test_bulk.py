"""Phase 2 — bulk transport, delisted CIK recovery, L0 hygiene, SIC subsector."""
import io, sqlite3, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bulk
from value import hygiene_reason, _resolved_bucket


def filers_db(rows):
    """In-memory filers table: rows = [(cik, name, sic, tickers, norm_names)]."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE filers(cik TEXT PRIMARY KEY, name TEXT, sic TEXT, "
                "sic_desc TEXT, tickers TEXT, exchanges TEXT, former_names TEXT, norm_names TEXT)")
    con.executemany("INSERT INTO filers VALUES (?,?,?,'',?,'','',?)", rows)
    return con


class TestNormName(unittest.TestCase):
    def test_strips_suffixes_and_punct(self):
        self.assertEqual(bulk._norm_name("SVB Financial Group /DE/"), "SVB FINANCIAL")
        self.assertEqual(bulk._norm_name("Kohl's Corp"), "KOHLS")
        self.assertEqual(bulk._norm_name("V. F. Corporation"), "V F")

    def test_strips_class_and_parens(self):
        self.assertEqual(bulk._norm_name("Under Armour (Class A)"), "UNDER ARMOUR")
        self.assertEqual(bulk._norm_name("Alphabet Inc. Class C"), "ALPHABET")


class TestCikNameMatches(unittest.TestCase):
    def setUp(self):
        self.con = filers_db([
            ("0000908937", "SIRIUS XM HOLDINGS INC.", "4832", "SIRI",
             "CD RADIO | SIRIUS SATELLITE RADIO | SIRIUS XM | SIRIUS XM RADIO"),
            ("0001877971", "POMDOCTOR LIMITED", "8000", "POM", "POMDOCTOR"),
            ("0000103379", "V F CORP", "2300", "VFC", "V F | V F NC"),
        ])

    def test_spaceless_containment_accepts_rename(self):
        # 'SiriusXM' ↔ 'SIRIUS XM' (space) and 'VF' ↔ 'V F' both match
        self.assertTrue(bulk.cik_name_matches(self.con, "0000908937", "SiriusXM"))
        self.assertTrue(bulk.cik_name_matches(self.con, "0000103379", "VF Corporation"))

    def test_rejects_namesake(self):
        # Pepco's ticker POM now belongs to POMDoctor — must NOT match
        self.assertFalse(bulk.cik_name_matches(self.con, "0001877971", "Pepco Holdings"))

    def test_missing_cik_is_false(self):
        self.assertFalse(bulk.cik_name_matches(self.con, "9999999999", "Anything"))


class TestResolveDelisted(unittest.TestCase):
    def setUp(self):
        self.con = filers_db([
            ("0000101830", "SPRINT CORP", "4812", "", "SPRINT | SPRINT NEXTEL | SPRINT NEXTEL CORP"),
            ("0001583708", "SENTINELONE INC", "7372", "S", "SENTINEL LABS | SENTINELONE"),
            ("0000730464", "Covista Inc.", "8200", "CVSA",
             "ADTALEM GLOBAL EDUCATION | COVISTA | DEVRY | DEVRY EDUCATION"),
            ("0000011111", "AMBIG ONE CORP", "1000", "", "ACME WIDGETS"),
            ("0000022222", "AMBIG TWO CORP", "1000", "", "ACME TOOLS"),
        ])

    def test_exact_former_name_wins(self):
        # 'Sprint Nextel' → SPRINT NEXTEL exact among pipe-separated former names
        self.assertEqual(bulk.resolve_delisted(self.con, "S", "Sprint Nextel"), "0000101830")

    def test_rename_chain_via_former(self):
        self.assertEqual(bulk.resolve_delisted(self.con, "DV", "DeVry"), "0000730464")

    def test_ambiguous_substring_returns_none(self):
        # 'Acme' is a substring-only match of two distinct filers → never guess
        self.assertIsNone(bulk.resolve_delisted(self.con, "ACM", "Acme"))

    def test_exact_beats_substring(self):
        # an exact former-name match is unambiguous even when a substring rival exists
        con = filers_db([
            ("0000101830", "SPRINT CORP", "4812", "", "SPRINT | SPRINT NEXTEL"),
            ("0000333333", "SPRINT NEXTEL LOGISTICS", "4200", "", "SPRINT NEXTEL LOGISTICS"),
        ])
        self.assertEqual(bulk.resolve_delisted(con, "S", "Sprint Nextel"), "0000101830")

    def test_unknown_returns_none(self):
        self.assertIsNone(bulk.resolve_delisted(self.con, "ZZZ", "Nonexistent Holdings"))


class TestHeaderPrefixParse(unittest.TestCase):
    def test_reads_header_before_filings(self):
        blob = (b'{"cik":320193,"name":"Apple Inc.","sic":"3571",'
                b'"tickers":["AAPL"],"exchanges":["Nasdaq"],'
                b'"filings":{"recent":{"form":["10-K"]}}}')
        h = bulk._header_from_stream(io.BytesIO(blob))
        self.assertEqual(h["name"], "Apple Inc.")
        self.assertEqual(h["sic"], "3571")
        self.assertEqual(h["tickers"], ["AAPL"])


class TestHygiene(unittest.TestCase):
    def test_sub_dollar(self):
        self.assertIn("sub-$1", hygiene_reason("XYZ", "Something Inc", 0.42, "3559"))

    def test_spac_sic(self):
        self.assertIn("SPAC", hygiene_reason("SPACU", "Blank Check Acq", 10.0, "6770"))

    def test_instrument_name(self):
        self.assertIsNotNone(hygiene_reason("XYZW", "Acme Warrants", 5.0, "3559"))
        self.assertIsNotNone(hygiene_reason("XYZP", "Acme 6.5% Preferred", 25.0, "6199"))

    def test_clean_common_stock_passes(self):
        self.assertIsNone(hygiene_reason("AAPL", "Apple Inc.", 210.0, "3571"))
        # a real name containing 'Unit' must NOT trip (no false positive)
        self.assertIsNone(hygiene_reason("UNT", "Unit Corporation", 45.0, "1311"))


class TestSubsectorPrecedence(unittest.TestCase):
    def r(self, t, sector, sic):
        return {"t": t, "sector": sector, "sic": sic}

    def test_override_beats_sic(self):
        # AAPL is hand-mapped hardware though its SIC 3571 also maps hardware; override wins
        ovr = {"NVDA": "semis"}
        self.assertEqual(_resolved_bucket(self.r("NVDA", "Information Technology", "7372"), ovr), "semis")

    def test_sic_default_for_unmapped_it(self):
        # unmapped IT name falls to its SIC bucket
        self.assertEqual(_resolved_bucket(self.r("NEWCO", "Information Technology", "3674"), {}), "semis")

    def test_sic_silent_outside_it(self):
        # a stray tech SIC on a non-IT name must NOT pull it into a tech bucket
        self.assertEqual(_resolved_bucket(self.r("XCO", "Industrials", "3674"), {}), "Industrials")

    def test_unknown_sic_falls_to_sector(self):
        self.assertEqual(_resolved_bucket(self.r("XCO", "Information Technology", "9999"), {}),
                         "Information Technology")


if __name__ == "__main__":
    unittest.main()
