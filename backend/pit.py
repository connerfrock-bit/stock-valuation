"""
POINT-IN-TIME fundamentals store (the backtest's foundation).
Unlike ingest_v1 (newest filing wins — right for TODAY's view, look-ahead for the past),
this keeps EVERY annual vintage with its `filed` date: what was knowable on date D is
exactly the rows with filed <= D. Non-USD reporters are excluded from the backtest
(historical FX would be another approximation layer) and counted, not hidden.
stdlib only.   python pit.py     (run membership.py first)
"""
import json, sqlite3, time
from common import DB_PATH
from ingest_v1 import (CONCEPTS, IFRS_CONCEPTS, ANNUAL_FORMS, SEC_UA,
                       http_json, load_ticker_map, choose_currency)

WAB = "WeightedAverageNumberOfSharesOutstandingBasic"


def annual_vintages(ns, tags, ccy):
    """ALL annual datapoints for a concept -> {(fy, filed): (end, value)}; tag priority
       resolves collisions (first tag that supplied a given (fy, filed) wins)."""
    out = {}
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        arrs = ([units[ccy]] if (ccy and ccy in units) else
                ([units["shares"]] if "shares" in units else
                 ([] if ccy else list(units.values()))))
        for arr in arrs:
            for u in arr:
                if not u.get("form", "").startswith(ANNUAL_FORMS) or u.get("fp") != "FY":
                    continue
                end, filed, val = u.get("end"), u.get("filed"), u.get("val")
                if not (end and filed and val is not None):
                    continue
                key = (int(end[:4]), filed)
                if key not in out:
                    out[key] = (end, float(val))
    return out


def main():
    cikmap = load_ticker_map()
    names = (DB_PATH.parent / "membership_names.txt").read_text().split()
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    DROP TABLE IF EXISTS financials_pit;
    CREATE TABLE financials_pit(
        ticker TEXT, concept TEXT, fy INTEGER, end_date TEXT, filed TEXT, value REAL,
        PRIMARY KEY (ticker, concept, fy, filed));
    CREATE INDEX IF NOT EXISTS pit_idx ON financials_pit(ticker, filed);
    DROP TABLE IF EXISTS pit_meta;
    CREATE TABLE pit_meta(ticker TEXT PRIMARY KEY, fin_currency TEXT, status TEXT);
    """)

    ok = no_cik = non_usd = failed = 0
    for i, t in enumerate(names, 1):
        cik = cikmap.get(t)
        if not cik:
            con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, None, "no_cik"))
            no_cik += 1
            continue
        try:
            data = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SEC_UA)
            time.sleep(0.25)
        except Exception:
            con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, None, "fetch_failed"))
            failed += 1
            continue

        facts = data.get("facts", {})
        rows, ccy_used = [], None
        for ns_name, cmap in [("us-gaap", CONCEPTS), ("ifrs-full", IFRS_CONCEPTS)]:
            ns = facts.get(ns_name, {})
            if not ns:
                continue
            ccy = choose_currency(ns, cmap["revenue"])
            got_rev = annual_vintages(ns, cmap["revenue"], ccy)
            if not got_rev or rows:
                continue
            ccy_used = ccy
            for concept, tags in cmap.items():
                for (fy, filed), (end, val) in annual_vintages(ns, tags, ccy).items():
                    rows.append((t, concept, fy, end, filed, val))
            # weighted-average shares as an explicit PIT concept (split basis = end date)
            for (fy, filed), (end, val) in annual_vintages(ns, [WAB], None).items():
                rows.append((t, "shares_wab", fy, end, filed, val))

        if ccy_used and ccy_used != "USD":
            con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, ccy_used, "non_usd"))
            non_usd += 1
            continue
        if not rows:
            con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, ccy_used, "no_data"))
            failed += 1
            continue
        con.executemany("INSERT OR REPLACE INTO financials_pit VALUES (?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, "USD", "ok"))
        con.commit()
        ok += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(names)}] ok={ok} no_cik={no_cik} non_usd={non_usd} failed={failed}")

    n = con.execute("SELECT COUNT(*) FROM financials_pit").fetchone()[0]
    con.close()
    print(f"\nPIT store: {ok}/{len(names)} names, {n} vintage rows")
    print(f"Excluded from backtest: {no_cik} no-CIK (delisted) · {non_usd} non-USD · {failed} no-data/failed")
    print("These gaps are REPORTED by the backtest as coverage, never silently dropped.")


if __name__ == "__main__":
    main()
