"""
POINT-IN-TIME fundamentals store (the backtest's foundation).
Unlike ingest_v1 (newest filing wins — right for TODAY's view, look-ahead for the past),
this keeps EVERY annual vintage with its `filed` date: what was knowable on date D is
exactly the rows with filed <= D. Non-USD reporters are excluded from the backtest
(historical FX would be another approximation layer) and counted, not hidden.
stdlib only.   python pit.py     (run membership.py first)
"""
import json, sqlite3, sys, time
from common import DB_PATH, SEC_UA, http_json
from ingest_v1 import (CONCEPTS, IFRS_CONCEPTS, ANNUAL_FORMS,
                       load_ticker_map, choose_currency)
import bulk

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


def main(suf=""):
    con = sqlite3.connect(DB_PATH)
    use_bulk = bulk.zips_present()
    cikmap = bulk.ticker_cik_map(con) if use_bulk else load_ticker_map()
    names = (DB_PATH.parent / f"membership_names{suf}.txt").read_text().split()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS financials_pit(
        ticker TEXT, concept TEXT, fy INTEGER, end_date TEXT, filed TEXT, value REAL,
        PRIMARY KEY (ticker, concept, fy, filed));
    CREATE INDEX IF NOT EXISTS pit_idx ON financials_pit(ticker, filed);
    CREATE TABLE IF NOT EXISTS pit_meta(ticker TEXT PRIMARY KEY, fin_currency TEXT, status TEXT);
    """)
    done = {t for (t,) in con.execute("SELECT ticker FROM pit_meta WHERE status='ok'")}
    # incremental: keep the 'ok' names; on a BULK run re-attempt every prior miss
    # (no_cik/failed/no_data) — local reads are free, and the bulk ticker map plus
    # name-recovery may now resolve delisted members the API map never could.
    names = [n for n in names if n not in done]
    # active constituents: for these the live ticker is authoritative. DELISTED members
    # must be name-validated — their ticker may have been reassigned to a namesake
    # (Sprint's S → SentinelOne), and the current map would inject the wrong company.
    current = {r[0] for r in con.execute(
        f"SELECT ticker FROM membership{suf} "
        f"WHERE qdate=(SELECT MAX(qdate) FROM membership{suf})")}
    print(f"[{suf or 'ndx'}] {'BULK' if use_bulk else 'API'} mode · {len(names)} names to (re)attempt")

    ok = no_cik = non_usd = failed = recovered = 0
    t_start = time.time()
    for i, t in enumerate(names, 1):
        nm_row = con.execute("SELECT name FROM member_names WHERE ticker=?", (t,)).fetchone()
        nm = nm_row[0] if nm_row else None
        if t in current:
            cik = cikmap.get(t)                            # active member — ticker authoritative
        else:                                              # delisted — name-validate to reject namesakes
            cik = bulk.resolve_delisted(con, t, nm) if (use_bulk and nm) else None
            if cik:
                recovered += 1
            else:
                tc = cikmap.get(t)                         # accept ticker hit only if name-consistent
                if tc and (not use_bulk or not nm or bulk.cik_name_matches(con, tc, nm)):
                    cik = tc
        if not cik:
            con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, None, "no_cik"))
            no_cik += 1
            continue
        facts_doc = bulk.facts_json(cik) if use_bulk else None
        if facts_doc is None:
            try:
                facts_doc = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SEC_UA)
                time.sleep(0.25)
            except Exception:
                con.execute("INSERT OR REPLACE INTO pit_meta VALUES (?,?,?)", (t, None, "fetch_failed"))
                failed += 1
                continue

        facts = facts_doc.get("facts", {})
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
    main("_sp500" if len(sys.argv) > 1 and sys.argv[1] == "sp500" else "")
