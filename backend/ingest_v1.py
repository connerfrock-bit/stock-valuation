"""
Fair Value — ingest_v1  (Milestone A)
Pulls REAL data, stdlib only (urllib + json + sqlite3):
  - SEC EDGAR companyfacts  -> annual financials (XBRL, with tag-mapping fallbacks)
  - Yahoo Finance chart API  -> current price
into a local SQLite db (backend/data/fairvalue.db).

This is a deliberately small, readable v1 that proves the pipeline end-to-end.
It will be refactored into the fairvalue/ package (ingest/ store/ ...) in a later phase.
"""
import json, sqlite3, time, urllib.request, urllib.error
from pathlib import Path
from universe import get_universe

CONTACT   = "FairValue research conner.frock@gmail.com"   # SEC requires a descriptive UA
SEC_UA    = {"User-Agent": CONTACT}
YAHOO_UA  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

DATA_DIR  = Path(__file__).resolve().parent / "data"
DB_PATH   = DATA_DIR / "fairvalue.db"
TICKERS_CACHE = DATA_DIR / "company_tickers.json"

# XBRL concept -> ordered candidate us-gaap tags (union merged across tags; newest filing wins).
CONCEPTS = {
    "revenue":     ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                    "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "RegulatedAndUnregulatedOperatingRevenue"],   # utilities (XEL, etc.)
    "net_income":  ["NetIncomeLoss"],
    "ebit":        ["OperatingIncomeLoss",
                    # last resort: pretax income (ADP-style filers report no operating subtotal)
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "cfo":         ["NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex":       ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                    "PaymentsToAcquireOtherPropertyPlantAndEquipment",        # ADP, EA
                    "PaymentsToExploreAndDevelopOilAndGasProperties"],        # FANG (development capex)
    "dep_amort":   ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                    "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "sbc":         ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "dividends":   ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "equity":      ["StockholdersEquity",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_debt":   ["LongTermDebtNoncurrent", "LongTermDebt",
                    "LongTermDebtAndCapitalLeaseObligations"],                # CMCSA ($93B!)
    "cash":        ["CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "shares":      ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    # balance-sheet concepts for Altman-Z / Piotroski / ROIC (signal-quality sprint)
    "assets":         ["Assets"],
    "assets_current": ["AssetsCurrent"],
    "liab_current":   ["LiabilitiesCurrent"],
    "retained":       ["RetainedEarningsAccumulatedDeficit"],
    "liabilities":    ["Liabilities"],
    "gross_profit":   ["GrossProfit"],
}

# IFRS fallback map for true ifrs-full filers (TRI 40-F, CCEP/FER 20-F).
IFRS_CONCEPTS = {
    "revenue":     ["Revenue"],
    "net_income":  ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "ebit":        ["ProfitLossFromOperatingActivities"],
    "cfo":         ["CashFlowsFromUsedInOperatingActivities"],
    "capex":       ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                    "PurchaseOfPropertyPlantAndEquipment"],
    "dep_amort":   ["DepreciationAndAmortisationExpense"],
    "sbc":         ["ExpenseFromSharebasedPaymentTransactionsWithEmployees"],
    "dividends":   ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "equity":      ["Equity", "EquityAttributableToOwnersOfParent"],
    "long_debt":   ["NoncurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "Borrowings"],
    "cash":        ["CashAndCashEquivalents"],
    "shares":      [],                                    # handled by current_shares()
    "assets":         ["Assets"],
    "assets_current": ["CurrentAssets"],
    "liab_current":   ["CurrentLiabilities"],
    "retained":       ["RetainedEarnings"],
    "liabilities":    ["Liabilities"],
    "gross_profit":   ["GrossProfit"],
}

ANNUAL_FORMS = ("10-K", "20-F", "40-F")                   # amendments match via startswith


def http_json(url, headers, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_ticker_map():
    """ticker -> 10-digit CIK, cached locally."""
    if TICKERS_CACHE.exists():
        raw = json.loads(TICKERS_CACHE.read_text())
    else:
        raw = http_json("https://www.sec.gov/files/company_tickers.json", SEC_UA)
        TICKERS_CACHE.write_text(json.dumps(raw))
    return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in raw.values()}


def pick_annual(ns, tags, ccy=None):
    """Return {fiscal_year:int -> value} from annual (10-K/20-F/40-F, fp=FY) datapoints.
       Merges across ALL candidate tags (companies switch tags over time — NVDA revenue);
       per fiscal year the most recently filed value wins (handles restatements).
       ccy: restrict monetary units to one currency (PDD files CNY *and* USD — mixing
       units by newest-filed would interleave magnitudes)."""
    chosen = {}  # fy -> (val, filed)
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        arrs = [units[ccy]] if (ccy and ccy in units) else \
               ([units["shares"]] if "shares" in units else
                ([] if ccy else list(units.values())))
        for arr in arrs:
            for u in arr:
                if not u.get("form", "").startswith(ANNUAL_FORMS) or u.get("fp") != "FY":
                    continue
                end = u.get("end")
                if not end:
                    continue
                fy, filed = int(end[:4]), u.get("filed", "")
                if fy not in chosen or filed > chosen[fy][1]:
                    chosen[fy] = (u.get("val"), filed)
    return {fy: v[0] for fy, v in sorted(chosen.items())}


def choose_currency(ns, rev_tags):
    """Pick the reporting currency from the revenue node: USD when it has real annual
       depth (dual filers like PDD/NBIS), else the unit with the most annual points."""
    counts = {}
    for tag in rev_tags:
        node = ns.get(tag)
        if not node:
            continue
        for unit, arr in node.get("units", {}).items():
            if unit in ("shares", "pure") or "/" in unit:
                continue
            n = sum(1 for u in arr if u.get("form", "").startswith(ANNUAL_FORMS)
                    and u.get("fp") == "FY")
            counts[unit] = counts.get(unit, 0) + n
    if not counts:
        return None
    if counts.get("USD", 0) >= 5:
        return "USD"
    return max(counts, key=counts.get)


_fx_cache = {}
def fx_spot(ccy):
    """Spot rate ccy->USD via Yahoo (e.g. EURUSD=X). Cached per run."""
    if ccy in _fx_cache:
        return _fx_cache[ccy]
    try:
        meta = http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ccy}USD%3DX"
                         f"?range=1d&interval=1d", YAHOO_UA)["chart"]["result"][0]["meta"]
        rate = meta.get("regularMarketPrice")
    except Exception:
        rate = None
    _fx_cache[ccy] = rate
    return rate


def newest_point(node):
    """Newest datapoint of an XBRL tag node across all forms. -> (end_date, val) or None."""
    if not node:
        return None
    best = None                                          # (end, filed, val)
    for arr in node.get("units", {}).values():
        for u in arr:
            end, val = u.get("end"), u.get("val")
            if end and val and (best is None or (end, u.get("filed", "")) > (best[0], best[1])):
                best = (end, u.get("filed", ""), val)
    return (best[0], best[2]) if best else None


def current_shares(facts):
    """Freshest TOTAL share count. Sources, freshest end-date wins:
         dei cover-page · us-gaap point-in-time · weighted-average basic (always all-classes).
       Multi-class guard (META/GOOGL/WDAY): dei & point-in-time tags can carry a single
       class — if the winner is far below the weighted-average total, take the WAB total."""
    gaap, dei = facts.get("us-gaap", {}), facts.get("dei", {})
    cands = []
    for src, node in [("dei", dei.get("EntityCommonStockSharesOutstanding")),
                      ("pit", gaap.get("CommonStockSharesOutstanding")),
                      ("pit", gaap.get("CommonStockSharesIssued")),
                      ("wab", gaap.get("WeightedAverageNumberOfSharesOutstandingBasic"))]:
        p = newest_point(node)
        if p:
            cands.append((p[0], p[1], src))              # (end, val, src)
    if not cands:
        return None
    wab = max((v for _, v, s in cands if s == "wab"), default=None)
    end, val, src = max(cands)                           # freshest end date wins
    if wab and src != "wab" and val < 0.6 * wab:
        return wab                                       # single-class undercount detected
    return val


def fetch_financials(cik):
    """-> (annual concept series in USD, shares_now, reporting currency).
       us-gaap namespace first (covers ARM/ASML/PDD 20-F filers too); true IFRS filers
       (TRI/CCEP/FER) fall through to the ifrs-full map. Non-USD reporters are converted
       to USD at today's spot — an approximation, disclosed via the currency field."""
    data = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SEC_UA)
    facts = data.get("facts", {})
    out, ccy = {}, None
    for ns_name, cmap in [("us-gaap", CONCEPTS), ("ifrs-full", IFRS_CONCEPTS)]:
        ns = facts.get(ns_name, {})
        if not ns:
            continue
        ns_ccy = choose_currency(ns, cmap["revenue"])
        got = {name: pick_annual(ns, tags, ns_ccy) for name, tags in cmap.items()}
        if not out.get("revenue") and got.get("revenue"):
            out, ccy = got, ns_ccy                        # namespace with revenue wins
    if not out:
        out = {name: {} for name in CONCEPTS}

    if ccy and ccy != "USD":                              # convert monetary series to USD
        rate = fx_spot(ccy)
        if rate:
            for name, series in out.items():
                if name != "shares":
                    out[name] = {fy: v * rate for fy, v in series.items()}
        else:
            out = {name: ({} if name != "shares" else s) for name, s in out.items()}

    shares_now = current_shares(facts)
    if not out.get("shares") and shares_now:              # keep a stub history for downstream
        out["shares"] = {int(time.strftime("%Y")): shares_now}
    return out, shares_now, ccy or "USD"


def fetch_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
    meta = http_json(url, YAHOO_UA)["chart"]["result"][0]["meta"]
    return meta.get("regularMarketPrice"), meta.get("currency")


def init_db(con):
    con.executescript("""
    DROP TABLE IF EXISTS companies;               -- rebuilt fully each run (schema evolves)
    DROP TABLE IF EXISTS financials;              -- values are USD-converted; no stale mixes
    CREATE TABLE companies(
        ticker TEXT PRIMARY KEY, name TEXT, cik TEXT, sector TEXT,
        price REAL, currency TEXT, shares_out REAL, fin_currency TEXT, updated TEXT);
    CREATE TABLE financials(
        ticker TEXT, fiscal_year INTEGER, concept TEXT, value REAL,
        PRIMARY KEY (ticker, fiscal_year, concept));
    """)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cikmap = load_ticker_map()
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    universe, usrc = get_universe()
    n = len(universe)
    print(f"Universe: {n} names [{usrc}]\n")
    ok = full = 0
    seen_ciks = set()                                     # dedupe share classes (GOOGL/GOOG)
    for i, (ticker, name, sector) in enumerate(universe, 1):
        cik = cikmap.get(ticker)
        if not cik:
            print(f"[{i:3}/{n}] {ticker:6} no CIK (foreign / non-filer?)"); continue
        if cik in seen_ciks:
            print(f"[{i:3}/{n}] {ticker:6} duplicate share class — skipped"); continue
        seen_ciks.add(cik)
        try:
            fins, shares_now, fin_ccy = fetch_financials(cik); time.sleep(0.25)  # polite to EDGAR
        except Exception as e:
            print(f"[{i:3}/{n}] {ticker:6} EDGAR FAILED {type(e).__name__}"); continue
        try:
            price, ccy = fetch_price(ticker)
        except Exception:
            price, ccy = None, None

        con.execute("INSERT OR REPLACE INTO companies VALUES (?,?,?,?,?,?,?,?,?)",
                    (ticker, name, cik, sector, price, ccy, shares_now, fin_ccy, now))
        rows = [(ticker, fy, c, float(v))
                for c, s in fins.items() for fy, v in s.items() if v is not None]
        con.executemany("INSERT OR REPLACE INTO financials VALUES (?,?,?,?)", rows)
        con.commit()

        have = [c for c, s in fins.items() if s]
        rev = fins["revenue"]; last_fy = max(rev) if rev else None
        rv = f"${rev[last_fy]/1e9:,.0f}B" if rev.get(last_fy) else "n/a"
        mc = f"${price*shares_now/1e9:,.0f}B" if (price and shares_now) else "n/a"
        ok += 1; full += (len(have) >= 15)
        pr = f"${price:,.0f}" if price else "n/a"
        cflag = "" if fin_ccy == "USD" else f" [{fin_ccy}→USD]"
        print(f"[{i:3}/{n}] {ticker:6} {pr:>8} mcap {mc:>8} FY{last_fy or '----'} "
              f"rev {rv:>8} cov {len(have):2}/{len(CONCEPTS)}{cflag}")

    total = con.execute("SELECT COUNT(*) FROM financials").fetchone()[0]
    print(f"\nIngested {ok}/{n} companies ({full} with ≥15/{len(CONCEPTS)} coverage); {total} datapoints → {DB_PATH}")
    con.close()


if __name__ == "__main__":
    main()
