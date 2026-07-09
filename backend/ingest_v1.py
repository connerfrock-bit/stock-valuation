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
from universe import get_universe, build_union
from common import UNIVERSES
import bulk

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
                    "RegulatedAndUnregulatedOperatingRevenue",    # utilities (XEL, etc.)
                    "RevenuesNetOfInterestExpense"],              # broker-dealers (GS, MS)
    # banks/insurers often carry NO annual-duration NetIncomeLoss point — the full-year
    # bottom line lands under ProfitLoss (total incl. NCI) or the to-common variant.
    "net_income":  ["NetIncomeLoss", "ProfitLoss",
                    "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "ebit":        ["OperatingIncomeLoss",
                    # last resort: pretax income (ADP-style filers report no operating subtotal)
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "cfo":         ["NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex":       ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                    "PaymentsToAcquireOtherPropertyPlantAndEquipment",        # ADP, EA
                    "PaymentsToExploreAndDevelopOilAndGasProperties",         # FANG (development capex)
                    "PaymentsForCapitalImprovements",                         # SNA + some industrials
                    "PaymentsToAcquireOilAndGasProperty"],                    # energy variant
    "dep_amort":   ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                    "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    # Phase 1.2 — REIT FFO gains adjustment (RE-specific tags only; broad
    # disposal tags would false-adjust industrials). Lands on next full refresh.
    "gain_sale":   ["GainsLossesOnSalesOfInvestmentRealEstate",
                    "GainLossOnSaleOfProperties",
                    "GainsLossesOnSalesOfRealEstate"],
    "re_impair":   ["ImpairmentOfRealEstate"],            # FFO adds RE impairments back
                                                          # (CCI's fiber writedown proved it)
    "sbc":         ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    # common-dividend tags first (some filers — BAC — drop PaymentsOfDividendsCommonStock
    # after ~2013 and report DividendsCommonStockCash; without it DDM runs on a stale
    # dividend). PaymentsOfOrdinaryDividends is deliberately NOT here — it bundles
    # preferred, which would overstate the common dividend the DDM discounts.
    "dividends":   ["PaymentsOfDividendsCommonStock", "DividendsCommonStockCash",
                    "PaymentsOfDividends"],
    "equity":      ["StockholdersEquity",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_debt":   ["LongTermDebtNoncurrent", "LongTermDebt",
                    "LongTermDebtAndCapitalLeaseObligations"],                # CMCSA ($93B!)
    "cash":        ["CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "shares":      ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    # Plan 2 — net-debt completeness + effective Rd/tax. Tag order matters only for
    # same-filed collisions (pick_annual: newest filed wins per FY, first tag breaks ties):
    # DebtCurrent (total current debt) preferred over its components.
    "short_debt":  ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings",
                    "CommercialPaper"],
    "op_leases":   ["OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent"],
    "interest_exp": ["InterestExpenseDebt", "InterestExpense",
                     "InterestExpenseNonoperating"],
    "tax_exp":     ["IncomeTaxExpenseBenefit"],
    "pretax":      ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
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
    "short_debt":  ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                    "ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings"],
    "op_leases":   ["LeaseLiabilities", "NoncurrentLeaseLiabilities"],
    "interest_exp": ["InterestExpense", "FinanceCosts"],
    "tax_exp":     ["IncomeTaxExpenseContinuingOperations"],
    "pretax":      ["ProfitLossBeforeTax"],
    "assets":         ["Assets"],
    "assets_current": ["CurrentAssets"],
    "liab_current":   ["CurrentLiabilities"],
    "retained":       ["RetainedEarnings"],
    "liabilities":    ["Liabilities"],
    "gross_profit":   ["GrossProfit"],
}

ANNUAL_FORMS = ("10-K", "20-F", "40-F")                   # amendments match via startswith
TTM_FORMS    = ("10-Q", "10-K")                           # quarterly stitching: US filers only
                                                          # (foreign 6-K interims are irregular — they fall back to FY)

# balance-sheet (instant) concepts — everything else is a flow (duration) that gets TTM'd
INSTANT_CONCEPTS = {"equity", "long_debt", "short_debt", "op_leases", "cash", "shares",
                    "assets", "assets_current", "liab_current", "retained", "liabilities"}


def _days(start, end):
    from datetime import date
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def http_json(url, headers, timeout=25, retries=4):
    """GET JSON with exponential backoff on throttling/transient errors. At universe
       scale (~500 names) EDGAR intermittently 429s a contiguous burst — without a
       retry those names silently vanished from the screener (Plan A found this)."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502, 504) and attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt)); continue
            raise


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
       Duration points must span a full year — some filers put Q4-only durations in the
       10-K with fp=FY (MPWR: 'FY2025 revenue' was one quarter, 0.64B vs the real 2.96B).
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
                start = u.get("start")
                if start and not (350 <= _days(start, end) <= 380):
                    continue                              # partial-year FY-labeled point
                fy, filed = int(end[:4]), u.get("filed", "")
                if fy not in chosen or filed > chosen[fy][1]:
                    chosen[fy] = (u.get("val"), filed)
    return {fy: v[0] for fy, v in sorted(chosen.items())}


# ---------------- TTM (Plan 5) ----------------
def _units_arrs(node, ccy):
    """The unit arrays to scan for a tag node, honoring the chosen currency."""
    units = node.get("units", {})
    return ([units[ccy]] if (ccy and ccy in units) else
            ([units["shares"]] if "shares" in units else
             ([] if ccy else list(units.values()))))


def duration_points(ns, tags, ccy):
    """Deduped duration datapoints [(start, end, value)] across candidate tags from
       10-Q/10-K filings — newest filed wins per (start, end) span."""
    seen = {}                                             # (start, end) -> (filed, val)
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        for arr in _units_arrs(node, ccy):
            for u in arr:
                s, e, v, filed = u.get("start"), u.get("end"), u.get("val"), u.get("filed", "")
                if not (s and e and v is not None):
                    continue
                if not u.get("form", "").startswith(TTM_FORMS):
                    continue
                key = (s, e)
                if key not in seen or filed > seen[key][0]:
                    seen[key] = (filed, float(v))
    return [(s, e, v) for (s, e), (_, v) in sorted(seen.items())]


def ttm_from_durations(points):
    """TTM through the latest reported period end:
         TTM = FY  +  post-FY chain covering (fy_end, latest_end]  −  prior-year mirror.
       Handles both YTD reporters (one 9-month point) and QTD chains. Chain links and
       year-mirrors tolerate a few days' drift (52/53-week fiscal calendars).
       -> (value, thru_date, basis 'ttm'|'fy') or None when no annual point exists."""
    from datetime import date

    def d(s):
        return date.fromisoformat(s)

    fys = [p for p in points if 350 <= (d(p[1]) - d(p[0])).days <= 380]
    if not fys:
        return None
    fy = max(fys, key=lambda p: p[1])
    fy_end, fy_val = fy[1], fy[2]
    post = [p for p in points if p[0] >= fy_end and p[1] > fy_end
            and (d(p[1]) - d(p[0])).days < 350]
    if not post:
        return fy_val, fy_end, "fy"                       # fresh 10-K, no 10-Q yet

    chain, cur_end = [], max(p[1] for p in post)
    for _ in range(8):                                    # walk back to the FY boundary
        cands = [p for p in post if abs((d(p[1]) - d(cur_end)).days) <= 5]
        if not cands:
            return fy_val, fy_end, "fy"
        p = max(cands, key=lambda p: (d(p[1]) - d(p[0])).days)   # prefer YTD over QTD
        chain.append(p)
        if abs((d(p[0]) - d(fy_end)).days) <= 10:
            break
        cur_end = p[0]
    else:
        return fy_val, fy_end, "fy"

    prior_sum = 0.0                                       # same periods, one year earlier
    for s, e, _v in chain:
        m = [p for p in points
             if abs((d(p[0]) - d(s)).days - (-365)) <= 10
             and abs((d(p[1]) - d(e)).days - (-365)) <= 10]
        if not m:
            return fy_val, fy_end, "fy"                   # can't mirror → honest fallback
        prior_sum += m[0][2]
    ttm = fy_val + sum(v for _, _, v in chain) - prior_sum
    return ttm, max(p[1] for p in chain), "ttm"


def freshest_instant(ns, tags, ccy):
    """Freshest balance-sheet point across candidate tags (10-Q/10-K/20-F/40-F).
       -> (value, end_date) or None."""
    best = None                                           # (end, filed, val)
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        for arr in _units_arrs(node, ccy):
            for u in arr:
                e, v, filed = u.get("end"), u.get("val"), u.get("filed", "")
                if e and v is not None and u.get("form", "").startswith(TTM_FORMS + ANNUAL_FORMS):
                    if best is None or (e, filed) > (best[0], best[1]):
                        best = (e, filed, float(v))
    return (best[2], best[0]) if best else None


def compute_now(ns, cmap, ccy):
    """-> {concept: (value, thru, basis)} — TTM flows + freshest instants (Plan 5)."""
    out = {}
    for name, tags in cmap.items():
        if name == "shares":
            continue                                      # current_shares() owns this
        if name in INSTANT_CONCEPTS:
            r = freshest_instant(ns, tags, ccy)
            if r:
                out[name] = (r[0], r[1], "instant")
        else:
            r = ttm_from_durations(duration_points(ns, tags, ccy))
            if r:
                out[name] = r
    return out


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


def fetch_financials(cik, facts_doc=None):
    """-> (annual concept series in USD, shares_now, reporting currency, now-dict).
       us-gaap namespace first (covers ARM/ASML/PDD 20-F filers too); true IFRS filers
       (TRI/CCEP/FER) fall through to the ifrs-full map. Non-USD reporters are converted
       to USD at today's spot — an approximation, disclosed via the currency field.
       facts_doc: pre-loaded companyfacts from the bulk zip (Phase 2); when None we hit
       the per-ticker EDGAR API (unchanged path — a registrant newer than the nightly)."""
    if facts_doc is None:
        facts_doc = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SEC_UA)
    facts = facts_doc.get("facts", {})
    out, ccy, win = {}, None, None
    for ns_name, cmap in [("us-gaap", CONCEPTS), ("ifrs-full", IFRS_CONCEPTS)]:
        ns = facts.get(ns_name, {})
        if not ns:
            continue
        ns_ccy = choose_currency(ns, cmap["revenue"])
        got = {name: pick_annual(ns, tags, ns_ccy) for name, tags in cmap.items()}
        # Accept the namespace on revenue OR net income — brokers/banks (GS, MS) report no
        # revenue under our tags, and gating on revenue alone lost their equity/NI entirely.
        if not (out.get("revenue") or out.get("net_income")) and \
                (got.get("revenue") or got.get("net_income")):
            out, ccy, win = got, ns_ccy, (ns, cmap)
    if not out:
        out = {name: {} for name in CONCEPTS}
    nowd = compute_now(*win, ccy) if win else {}          # TTM flows + fresh instants

    if ccy and ccy != "USD":                              # convert monetary series to USD
        rate = fx_spot(ccy)
        if rate:
            for name, series in out.items():
                if name != "shares":
                    out[name] = {fy: v * rate for fy, v in series.items()}
            nowd = {n: (v * rate, thru, basis) for n, (v, thru, basis) in nowd.items()}
        else:
            out = {name: ({} if name != "shares" else s) for name, s in out.items()}
            nowd = {}

    shares_now = current_shares(facts)
    if not out.get("shares") and shares_now:              # keep a stub history for downstream
        out["shares"] = {int(time.strftime("%Y")): shares_now}
    return out, shares_now, ccy or "USD", nowd


def fetch_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
    meta = http_json(url, YAHOO_UA)["chart"]["result"][0]["meta"]
    return meta.get("regularMarketPrice"), meta.get("currency")


def init_db(con):
    con.executescript("""
    DROP TABLE IF EXISTS companies;               -- rebuilt fully each run (schema evolves)
    DROP TABLE IF EXISTS financials;              -- values are USD-converted; no stale mixes
    DROP TABLE IF EXISTS financials_now;          -- TTM flows + freshest instants (Plan 5)
    CREATE TABLE companies(
        ticker TEXT PRIMARY KEY, name TEXT, cik TEXT, sector TEXT,
        price REAL, currency TEXT, shares_out REAL, fin_currency TEXT, updated TEXT,
        sic TEXT);                                -- SIC code (bulk submissions) → hygiene + subsector
    CREATE TABLE financials(
        ticker TEXT, fiscal_year INTEGER, concept TEXT, value REAL,
        PRIMARY KEY (ticker, fiscal_year, concept));
    CREATE TABLE financials_now(
        ticker TEXT, concept TEXT, value REAL, thru TEXT, basis TEXT,
        PRIMARY KEY (ticker, concept));
    -- Plan A: which CURRENT live universe(s) each ingested ticker belongs to. The
    -- companies/financials tables hold the UNION (one row per distinct CIK); this
    -- junction is how value.py/ledger.py score each universe separately. (Distinct from
    -- the backtest's survivorship-walked membership{_sp500} quarterly snapshot tables.)
    CREATE TABLE IF NOT EXISTS universe_membership(
        universe TEXT, ticker TEXT, PRIMARY KEY (universe, ticker));
    """)


def coverage_check(con, now, warn_drop=0.05, universe="ALL"):
    """Record per-concept ticker coverage in `run_stats` (append-only, survives the
       companies/financials rebuild) and compare against the previous run. A silent
       XBRL tag change shows up here as a coverage drop — loudly, not invisibly.
       Plan A: keyed by (run_date, universe, concept); the union ingest logs as 'ALL'."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(run_stats)")]
    if cols and "universe" not in cols:                   # one-time migration to universe PK
        con.executescript("""
            ALTER TABLE run_stats RENAME TO run_stats_v1;
            CREATE TABLE run_stats(run_date TEXT, universe TEXT, concept TEXT, tickers INTEGER,
                PRIMARY KEY (run_date, universe, concept));
            INSERT INTO run_stats SELECT run_date, 'ALL', concept, tickers FROM run_stats_v1;
            DROP TABLE run_stats_v1;""")
    con.execute("CREATE TABLE IF NOT EXISTS run_stats("
                "run_date TEXT, universe TEXT, concept TEXT, tickers INTEGER, "
                "PRIMARY KEY (run_date, universe, concept))")
    prev_run = con.execute("SELECT MAX(run_date) FROM run_stats WHERE universe=?",
                           (universe,)).fetchone()[0]
    cur = dict(con.execute(
        "SELECT concept, COUNT(DISTINCT ticker) FROM financials GROUP BY concept"))
    con.executemany("INSERT OR REPLACE INTO run_stats VALUES (?,?,?,?)",
                    [(now, universe, c, n) for c, n in cur.items()])
    con.commit()
    if not prev_run or prev_run == now:
        print("Coverage baseline recorded (first tracked run).")
        return
    prev = dict(con.execute(
        "SELECT concept, tickers FROM run_stats WHERE run_date=? AND universe=?",
        (prev_run, universe)))
    drops = [(c, p, cur.get(c, 0)) for c, p in sorted(prev.items())
             if cur.get(c, 0) < p * (1 - warn_drop)]
    if drops:
        print("\n" + "!" * 64)
        print(f"!! COVERAGE REGRESSION vs {prev_run} — check for XBRL tag changes")
        for c, p, n in drops:
            print(f"!!   {c:16} {p:4} → {n:4} tickers")
        print("!" * 64)
    else:
        print(f"Coverage check vs {prev_run}: all {len(cur)} concepts within {warn_drop:.0%}.")


def main(universe_ids=None, resume=False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    use_bulk = bulk.zips_present()
    # bulk ticker→CIK (filers scan ∪ company_tickers.json) when the zips are here,
    # else the classic current-only map. The bulk map also carries delisted registrants.
    cikmap = bulk.ticker_cik_map(con) if use_bulk else load_ticker_map()
    if use_bulk:
        print(f"BULK MODE — facts from {bulk.FACTS_ZIP.name} (local reads, no EDGAR throttle)")
    else:
        print("API MODE — per-ticker EDGAR calls (run `python bulk.py download` for the fast path)")
    if not resume:
        init_db(con)                                      # full rebuild (schema may evolve)
    else:
        con.execute("CREATE TABLE IF NOT EXISTS universe_membership("
                    "universe TEXT, ticker TEXT, PRIMARY KEY (universe, ticker))")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # Plan A: ingest the UNION of all configured live universes ONCE. Each distinct CIK
    # is fetched a single time; the junction below records which universe(s) it serves.
    universe_ids = universe_ids or list(UNIVERSES)
    universe, membership, srcs = build_union(universe_ids)
    n = len(universe)
    print(f"Union universe: {n} distinct names · sources {srcs}"
          + (" · RESUME (backfill missing only)\n" if resume else "\n"))
    ingested = {}                                         # ticker actually ingested -> its universes
    seen_ciks = set()                                     # dedupe share classes (GOOGL/GOOG)
    if resume:                                            # keep well-covered names; re-fetch the rest
        cov = dict(con.execute("SELECT ticker, COUNT(DISTINCT concept) FROM financials "
                               "GROUP BY ticker"))
        have = {t for t, n in cov.items() if n >= 15}     # low-coverage names get re-fetched
        for tk in have:
            ingested[tk] = membership.get(tk, set())
            c = cikmap.get(tk)
            if c:
                seen_ciks.add(c)
    ok = full = n_zip = n_api = 0
    t0 = time.time()
    for i, (ticker, name, sector) in enumerate(universe, 1):
        cik = cikmap.get(ticker)
        if not cik:
            print(f"[{i:3}/{n}] {ticker:6} no CIK (foreign / non-filer?)"); continue
        if resume and ticker in ingested:
            continue                                      # already have it — skip the fetch
        if cik in seen_ciks:
            print(f"[{i:3}/{n}] {ticker:6} duplicate share class — skipped"); continue
        seen_ciks.add(cik)
        facts_doc = bulk.facts_json(cik) if use_bulk else None
        try:
            fins, shares_now, fin_ccy, nowd = fetch_financials(cik, facts_doc)
            if facts_doc is None:                          # only sleep when we hit the network
                time.sleep(0.25); n_api += 1               # (API fallback / non-bulk run)
            else:
                n_zip += 1
        except Exception as e:
            print(f"[{i:3}/{n}] {ticker:6} EDGAR FAILED {type(e).__name__}"); continue
        try:
            price, ccy = fetch_price(ticker)
        except Exception:
            price, ccy = None, None
        sub = bulk.submission_header(cik) if use_bulk else None
        sic = str(sub.get("sic") or "") if sub else ""

        con.execute("INSERT OR REPLACE INTO companies VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ticker, name, cik, sector, price, ccy, shares_now, fin_ccy, now, sic))
        rows = [(ticker, fy, c, float(v))
                for c, s in fins.items() for fy, v in s.items() if v is not None]
        con.executemany("INSERT OR REPLACE INTO financials VALUES (?,?,?,?)", rows)
        con.executemany("INSERT OR REPLACE INTO financials_now VALUES (?,?,?,?,?)",
                        [(ticker, c, v, thru, basis) for c, (v, thru, basis) in nowd.items()])
        con.commit()
        ingested[ticker] = membership.get(ticker, set())

        have = [c for c, s in fins.items() if s]
        rev = fins["revenue"]; last_fy = max(rev) if rev else None
        rv = f"${rev[last_fy]/1e9:,.0f}B" if rev.get(last_fy) else "n/a"
        mc = f"${price*shares_now/1e9:,.0f}B" if (price and shares_now) else "n/a"
        ok += 1; full += (len(have) >= 15)
        pr = f"${price:,.0f}" if price else "n/a"
        cflag = "" if fin_ccy == "USD" else f" [{fin_ccy}→USD]"
        print(f"[{i:3}/{n}] {ticker:6} {pr:>8} mcap {mc:>8} FY{last_fy or '----'} "
              f"rev {rv:>8} cov {len(have):2}/{len(CONCEPTS)}{cflag}")

    # Plan A: rebuild the current-membership junction from what we ACTUALLY ingested
    # (a name that failed EDGAR/price is not claimed as a live member).
    con.execute("DELETE FROM universe_membership")
    con.executemany("INSERT OR REPLACE INTO universe_membership VALUES (?,?)",
                    [(u, t) for t, us in ingested.items() for u in us])
    con.commit()
    per_uni = {u: sum(1 for us in ingested.values() if u in us) for u in universe_ids}

    total = con.execute("SELECT COUNT(*) FROM financials").fetchone()[0]
    dt = max(time.time() - t0, 1e-6)
    print(f"\nIngested {ok}/{n} companies ({full} with ≥15/{len(CONCEPTS)} coverage); {total} datapoints → {DB_PATH}")
    print(f"Facts source: {n_zip} from bulk zip · {n_api} from EDGAR API · "
          f"{dt:.0f}s ({n/dt:.1f} names/s)")
    print(f"Live membership: " + " · ".join(f"{u}={c}" for u, c in per_uni.items()))
    coverage_check(con, now)
    bulk.close()
    con.close()


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if a != "--resume"]
    main(args or None, resume="--resume" in sys.argv)
