"""
Fair Value — full valuation pipeline (L4→L10).
Two passes: (1) load + derive inputs for every company, (2) cross-sectional context
(warranted-multiple regression, quality percentiles) then engines per name:
  Reverse DCF (anchor) · DCF Monte Carlo (normalized FCF) · EPV (floor) ·
  RIM (router-gated) · Warranted multiple (peer regression)
→ triangulated range + agreement → quality score + trap flags → composite score →
ranked output + data/output.json (the Company contract the dashboard binds to).
stdlib only.  Run after ingest_v1.py and betas.py:   python value.py
"""
import datetime, json, sqlite3, statistics, sys
from common import (CFG, UNIVERSES, ACTIVE, resolve_universe, DB_PATH, fetch_risk_free,
                    load_company, latest, cagr, avg_margin, avg_roe, effective_tax,
                    cost_of_debt, money, pct)
from engines import (cost_of_equity, wacc_of, reverse_dcf, dcf, epv, rim,
                     warranted_fit, warranted_value, triangulate)


def load_live_momentum(tickers):
    """Per-name 12-1 momentum from price_monthly (Plan C — the one factor that showed a
       real edge). CALENDAR-based (adj[L-1]/adj[L-12], skipping the latest partial month L)
       so gaps / recent relistings (e.g. SanDisk) correctly yield None instead of a bogus
       multi-year ratio. Returns {ticker: mom}."""
    from momentum import mom_12_1
    tset = set(tickers)
    px = {}
    con = sqlite3.connect(DB_PATH)
    for t, m, a in con.execute("SELECT ticker, month, adjclose FROM price_monthly"):
        if t in tset and a:
            px.setdefault(t, {})[m] = a
    con.close()
    latest = max((m for a in px.values() for m in a), default=None)
    if not latest:
        return {}
    out = {}
    for t, a in px.items():
        v = mom_12_1(a, latest)                        # adj[latest-1] / adj[latest-12] - 1
        if v is not None:
            out[t] = v
    return out

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHORT = {"Information Technology": "TECH", "Communication Services": "COMM",
         "Consumer Discretionary": "DISC", "Consumer Staples": "STPL", "Health Care": "HLTH",
         "Industrials": "INDU", "Financials": "FINL", "Real Estate": "REIT",
         "Materials": "MATL", "Energy": "ENGY", "Utilities": "UTIL"}

# universe identity + plausibility floor come from assumptions.toml [[universe]] (Plan 7/A)


# ---------------- L5 archetype router (Plan A) ----------------
# The ONLY garbage-number source is running FCFF/EV engines (DCF, EPV, Warranted,
# reverse-DCF) on a company whose CFO, net debt and EV/EBIT are economically undefined —
# banks/insurers (deposits/float, not debt) and REITs (historical-cost book, FFO not NI).
# For those, force the FCF/EV engines to N/A and price on RIM alone (book + excess ROE),
# behind RIM's existing per-name quality gate. ~75% of the universe is 'standard' and is
# byte-for-byte unchanged. GICS sector is the sole classifier — we have no sub-industry,
# FFO or net-interest-income, so finer splitting would be false precision.
def archetype_of(sector):
    if sector == "Financials":
        return "financial"
    if sector == "Real Estate":
        return "reit"
    return "standard"

# per-archetype: which engines may run. RIM is always allowed here (its own rim_ok gate
# still decides priceability per name); DDM is N/A everywhere as today.
ARCHETYPE_GATES = {
    "standard":  {"DCF": True,  "EPV": True,  "Warranted": True,  "revDCF": True},
    "financial": {"DCF": False, "EPV": False, "Warranted": False, "revDCF": False},
    "reit":      {"DCF": False, "EPV": False, "Warranted": False, "revDCF": False},
}
GATED_NOTE = {
    "financial": "N/A — no EV/net-debt/EV-EBIT concept for a deposit/float-funded balance sheet",
    "reit": "N/A — REIT: needs FFO/NAV, not derivable from GAAP net income + historical-cost book",
}

def apply_archetype_gates(arch, dcf_ps, epv_ps, warr_ps, impl, op):
    """Force the FCF/EV engines to None for financials/REITs (pure, testable). This one
       mechanism removes them from triangulate's mid AND flips methods[].applicable."""
    g = ARCHETYPE_GATES[arch]
    return (dcf_ps if g["DCF"] else None,
            epv_ps if g["EPV"] else None,
            warr_ps if g["Warranted"] else None,
            (impl if g["revDCF"] else None),
            (op if g["revDCF"] else None))


# ---------------- pass 1: inputs ----------------
def universe_tickers(con, universe_id):
    """Tickers in this live universe via the junction (Plan A); all companies if absent."""
    has_junction = bool(con.execute(
        "SELECT name FROM sqlite_master WHERE name='universe_membership'").fetchone())
    if has_junction:
        return [r[0] for r in con.execute(
            "SELECT c.ticker FROM companies c JOIN universe_membership m ON c.ticker=m.ticker "
            "WHERE m.universe=? ORDER BY c.ticker", (universe_id,))]
    return [r[0] for r in con.execute("SELECT ticker FROM companies ORDER BY ticker")]


def collect(con, rf, erp, tax_fallback, betas, universe_id):
    cur_year = datetime.date.today().year
    today = datetime.date.today()
    has_now = bool(con.execute(
        "SELECT name FROM sqlite_master WHERE name='financials_now'").fetchone())
    rows, excluded = [], []
    for t in universe_tickers(con, universe_id):
        name, price, f = load_company(con, t)
        sector, shares_out, fin_ccy, cik = con.execute(
            "SELECT sector, shares_out, fin_currency, cik FROM companies WHERE ticker=?",
            (t,)).fetchone()
        arch = archetype_of(sector)
        rev = f.get("revenue", {})
        shares = shares_out or latest(f.get("shares", {}))
        cfo_s, cap_s, sbc_s = f.get("cfo", {}), f.get("capex", {}), f.get("sbc", {})
        if not price:
            excluded.append((t, "no price")); continue
        if not shares:
            excluded.append((t, "no share count")); continue
        # Standard names need CFO/capex (FCF engines). Financials/REITs are priced on RIM
        # (book + ROE) — CFO/capex are meaningless for them — so require only the RIM inputs;
        # names that lack even those fall through to the archetype-aware exclusion in pass 2.
        if arch == "standard":
            if not rev or not cfo_s or not cap_s:
                excluded.append((t, "missing core financials (revenue/CFO/capex)")); continue
        else:
            if not f.get("equity", {}) or not f.get("net_income", {}):
                excluded.append((t, f"{arch}: no book value / net income for RIM")); continue

        # Plan 5: TTM flows + freshest quarterly instants for every "now" input; the
        # ANNUAL series remain the history (margins, CAGR, ROE, quality, trends).
        nowd = ({c: (v, thru, basis) for c, v, thru, basis in con.execute(
                 "SELECT concept, value, thru, basis FROM financials_now WHERE ticker=?",
                 (t,))} if has_now else {})
        def nv(c, fb=None):
            return nowd[c][0] if c in nowd else fb

        # per-year FCF (SBC expensed) and FCF margins over the overlap window
        yrs = sorted(set(rev) & set(cfo_s) & set(cap_s))[-5:]
        fcf_by_year = {y: cfo_s[y] - cap_s[y] - sbc_s.get(y, 0.0) for y in yrs}
        margins = [fcf_by_year[y] / rev[y] for y in yrs if rev[y]]
        fcf_margin = sum(margins) / len(margins) if margins else None
        rev_now = nv("revenue", latest(rev))
        fcf_norm = fcf_margin * rev_now if fcf_margin is not None else None
        fcf_last = fcf_by_year[yrs[-1]] if yrs else None
        cfo_ttm, cap_ttm = nv("cfo"), nv("capex")
        if cfo_ttm is not None and cap_ttm is not None:
            fcf_last = cfo_ttm - cap_ttm - (nv("sbc") or 0.0)

        ebit_s = f.get("ebit", {})
        ebit_now = nv("ebit", latest(ebit_s))
        om = avg_margin(ebit_s, rev, years=5)
        ni_s, eq_s = f.get("net_income", {}), f.get("equity", {})
        # Plan 2: valuation debt = ALL borrowings (long + previously-missing short/current).
        # Operating leases go in debt_risk only — every engine discounts post-rent flows
        # (CFO and EBIT are after lease expense), so leases in the EV bridge double-count.
        # Plan 5: instants come from the freshest quarterly balance sheet when available.
        def inst(c):
            v = nv(c)
            return v if v is not None else latest(f.get(c, {}))
        borrowings = (inst("long_debt") or 0.0) + (inst("short_debt") or 0.0)
        leases = inst("op_leases") or 0.0
        debt = borrowings
        debt_risk = borrowings + (leases if CFG["include_op_leases"] else 0.0)
        cash = inst("cash") or 0.0
        dna = nv("dep_amort", latest(f.get("dep_amort", {})))
        div = nv("dividends", latest(f.get("dividends", {}))) or 0.0
        beta = betas.get(t, CFG["beta_default"])
        mcap = price * shares
        g_trail = cagr(rev)                                # honest trailing growth (uncapped)
        g1 = min(max(g_trail or 0.0, CFG["initial_growth_floor"]), CFG["initial_growth_cap"])
        re_ = cost_of_equity(rf, beta, erp)
        rd = cost_of_debt(nv("interest_exp", latest(f.get("interest_exp", {}))), borrowings,
                          rf, CFG["cost_of_debt_spread"], CFG["cost_of_debt_cap"])
        tax_r = effective_tax(f.get("tax_exp", {}), f.get("pretax", {}),
                              floor=CFG["tax_floor"], cap=CFG["tax_cap"],
                              fallback=tax_fallback)
        wacc = wacc_of(mcap, max(debt, 0.0), re_, rd, tax_r)

        equity_now = inst("equity")
        inv_cap = (equity_now or 0.0) + debt - cash
        roic = (ebit_now * (1 - tax_r) / inv_cap
                if (ebit_now is not None and inv_cap > 0) else None)

        rows.append(dict(
            t=t, name=name, sector=sector, arch=arch, fin_ccy=fin_ccy or "USD", cik=cik,
            price=price, shares=shares, mcap=mcap,
            beta=beta, re_=re_, wacc=wacc, rev=rev, rev_now=rev_now,
            fcf_norm=fcf_norm, fcf_last=fcf_last, fcf_margin=fcf_margin,
            ebit_now=ebit_now, om=om, ni_s=ni_s, eq_s=eq_s, debt=debt, cash=cash,
            debt_risk=debt_risk, rd=rd, tax_r=tax_r, capex_now=nv("capex", latest(cap_s)),
            dna=dna, div=div, g_trail=g_trail, g1=g1, roic=roic,
            last_fy=max(rev) if rev else None, stale=_is_stale(nowd, rev, today, cur_year),
            fin_thru=nowd.get("revenue", (None, None, None))[1],
            ni_now=nv("net_income", latest(ni_s)), cfo_now=nv("cfo", latest(cfo_s)),
            equity_now=equity_now, cfo_s=cfo_s, f=f, nowd=nowd,
        ))
    return rows, excluded


def _is_stale(nowd, rev, today, cur_year):
    """Stale = no filing covering the last ~9 months (TTM thru date when we have one,
       else the old annual-year rule). Banks may have no mapped revenue at all — fall
       back to any 'now' thru date, then to not-stale rather than crash on empty rev."""
    thru = nowd.get("revenue", (None, None, None))[1]
    if not thru:                                          # any freshest-instant date will do
        thru = max((v[1] for v in nowd.values() if v[1]), default=None)
    if thru:
        return datetime.date.fromisoformat(thru) < today - datetime.timedelta(days=270)
    return max(rev) < cur_year - 1 if rev else True       # no filings we can date → stale


# ---------------- safety metrics (signal-quality sprint) ----------------
def altman_z(r):
    """Original Altman Z. None when a core component is unavailable — never guessed.
       Balance-sheet inputs use the freshest quarterly instants (Plan 5) so Z isn't a
       mix of fresh EBIT/mcap and a year-old balance sheet."""
    f, nowd = r["f"], r.get("nowd", {})
    def cur(c):
        e = nowd.get(c)
        return e[0] if e is not None else latest(f.get(c, {}))
    ta = cur("assets")
    if not ta or ta <= 0:
        return None
    tl = cur("liabilities")
    if tl is None and r["equity_now"] is not None:
        tl = ta - r["equity_now"]
    ac, lc = cur("assets_current"), cur("liab_current")
    re_ = cur("retained")
    if None in (tl, ac, lc, re_, r["ebit_now"]) or tl <= 0:
        return None
    wc = ac - lc
    return (1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * r["ebit_now"] / ta
            + 0.6 * r["mcap"] / tl + 1.0 * (r["rev_now"] or 0.0) / ta)


def piotroski(r):
    """F-score over the signals we can actually evaluate (needs 2 overlapping years
       per signal). -> (score, n_evaluated); score None when fewer than 5 evaluable."""
    f = r["f"]
    score = n = 0
    def add(ok):
        nonlocal score, n
        n += 1
        if ok:
            score += 1
    def pair(k1, k2):
        s1, s2 = f.get(k1, {}), f.get(k2, {})
        ys = sorted(set(s1) & set(s2))
        return (ys[-2], ys[-1], s1, s2) if len(ys) >= 2 else None
    p = pair("net_income", "assets")
    if p:
        a, b, ni, ta = p
        add(ni[b] > 0)                                            # 1 ROA > 0
        if ta[a] and ta[b]:
            add(ni[b] / ta[b] > ni[a] / ta[a])                    # 3 ΔROA > 0
    p = pair("cfo", "net_income")
    if p:
        a, b, cfo, ni = p
        add(cfo[b] > 0)                                           # 2 CFO > 0
        add(cfo[b] > ni[b])                                       # 4 CFO > NI (accruals)
    p = pair("long_debt", "assets")
    if p:
        a, b, d, ta = p
        if ta[a] and ta[b]:
            add(d[b] / ta[b] <= d[a] / ta[a])                     # 5 leverage not up
    p = pair("assets_current", "liab_current")
    if p:
        a, b, ac, lc = p
        if lc[a] and lc[b]:
            add(ac[b] / lc[b] > ac[a] / lc[a])                    # 6 liquidity up
    sh = f.get("shares", {})
    ys = sorted(sh)
    if len(ys) >= 2 and sh[ys[-2]]:
        add(sh[ys[-1]] <= sh[ys[-2]] * 1.005)                     # 7 no net issuance
    p = pair("gross_profit", "revenue") or pair("ebit", "revenue")
    if p:
        a, b, gp, rv = p
        if rv[a] and rv[b]:
            add(gp[b] / rv[b] > gp[a] / rv[a])                    # 8 margin up
    p = pair("revenue", "assets")
    if p:
        a, b, rv, ta = p
        if ta[a] and ta[b]:
            add(rv[b] / ta[b] > rv[a] / ta[a])                    # 9 turnover up
    return (score if n >= 5 else None), n


def rev_volatility(r):
    """Stdev of YoY revenue growth (≤6 obs) — the data-driven cyclicality detector."""
    s = r["rev"]
    ys = sorted(s)
    gr = [s[ys[i]] / s[ys[i - 1]] - 1 for i in range(1, len(ys)) if s[ys[i - 1]]][-6:]
    if len(gr) < 3:
        return None
    m = sum(gr) / len(gr)
    return (sum((x - m) ** 2 for x in gr) / len(gr)) ** 0.5


ADR_STRUCTURE_RISK = {"PDD"}          # VIE/ADR structures the numbers can't see
REIT_RIM_FLAG = "REIT: RIM on book, not FFO/NAV"
# shown but NOT score-penalized — characteristics/disclosures, not traps
INFO_FLAGS = {"Cyclical revenue", REIT_RIM_FLAG}


def trend_series(f):
    """Real 8-yr trend series for the dashboard sparklines (None where unavailable)."""
    yrs = sorted(f.get("revenue", {}))[-8:]
    rev, ebit = f.get("revenue", {}), f.get("ebit", {})
    cfo, cap, sbc = f.get("cfo", {}), f.get("capex", {}), f.get("sbc", {})
    eq = f.get("equity", {})
    def ser(fn):
        out = []
        for y in yrs:
            v = fn(y)
            out.append(None if v is None else round(v, 3))
        return out
    return {
        "years": yrs,
        "revenueB": ser(lambda y: rev[y] / 1e9 if y in rev else None),
        "opMargin": ser(lambda y: ebit[y] / rev[y] if (y in ebit and rev.get(y)) else None),
        "fcfB": ser(lambda y: (cfo[y] - cap[y] - sbc.get(y, 0.0)) / 1e9
                    if (y in cfo and y in cap) else None),
        "equityB": ser(lambda y: eq[y] / 1e9 if y in eq else None),
    }


# ---------------- quality (cross-sectional percentiles) ----------------
def pct_rank(sorted_vals, v):
    if v is None or not sorted_vals:
        return None
    import bisect
    return bisect.bisect_right(sorted_vals, v) / len(sorted_vals)

def quality_scores(rows):
    # growth removed from quality (Plan 3): quality = profitability/stability/leverage;
    # growth is the value/growth axis scored elsewhere — mixing entangled the two.
    dims = {
        "om":        [r["om"] for r in rows if r["om"] is not None],
        "roe":       [avg_roe(r["ni_s"], r["eq_s"]) for r in rows],
        "roic":      [r["roic"] for r in rows if r["roic"] is not None],
        "fcfm":      [r["fcf_margin"] for r in rows if r["fcf_margin"] is not None],
        "lowlev":    [-(r["debt_risk"] - r["cash"]) / r["ebit_now"] for r in rows
                      if r["ebit_now"] and r["ebit_now"] > 0],
    }
    S = {k: sorted(v for v in vals if v is not None) for k, vals in dims.items()}
    for r in rows:
        roe = avg_roe(r["ni_s"], r["eq_s"])
        lev = (-(r["debt_risk"] - r["cash"]) / r["ebit_now"]
               if r["ebit_now"] and r["ebit_now"] > 0 else None)
        ps = [pct_rank(S["om"], r["om"]), pct_rank(S["roe"], roe),
              pct_rank(S["roic"], r["roic"]),
              pct_rank(S["fcfm"], r["fcf_margin"]),
              pct_rank(S["lowlev"], lev)]
        ps = [p for p in ps if p is not None]
        r["quality"] = round(100 * sum(ps) / len(ps)) if ps else None


def trap_flags(r, z=None, fscore=None, min_mcap=0.0):
    flags = []
    fin = r["arch"] != "standard"          # FCF/leverage traps are undefined for banks/REITs
    rev_yrs = sorted(r["rev"])
    if len(rev_yrs) >= 4 and r["rev"][rev_yrs[-1]] < r["rev"][rev_yrs[-4]]:
        flags.append("Declining revenue 3y")
    if not fin and (r["fcf_norm"] is None or r["fcf_norm"] <= 0) and (r["fcf_last"] is None or r["fcf_last"] <= 0):
        flags.append("Negative FCF")
    ebitda = (r["ebit_now"] or 0) + (r["dna"] or 0)
    if not fin and ebitda > 0 and (r["debt_risk"] - r["cash"]) / ebitda > 3.5:   # leases count as risk
        flags.append("High leverage")
    if r["equity_now"] is not None and r["equity_now"] < 0:
        flags.append("Negative book value")
    ni, cfo = r["ni_now"], r["cfo_now"]                   # same (TTM) basis on both sides
    if not fin and ni and cfo and ni > cfo * 1.2:
        flags.append("High accruals")
    if z is not None and z < 1.81:
        flags.append("Altman-Z: distress")
    if fscore is not None and fscore <= 3:
        flags.append(f"Piotroski {fscore}/9")
    vol = rev_volatility(r)
    if vol is not None and vol > 0.18:
        flags.append("Cyclical revenue")
    if r["t"] in ADR_STRUCTURE_RISK:
        flags.append("VIE/ADR structure")
    if r["mcap"] < min_mcap:
        flags.append("Suspect share count")
    if r["arch"] == "reit":
        flags.append(REIT_RIM_FLAG)
    if r["stale"]:
        flags.append("Stale filings")
    return flags


# ---------------- snapshot history (append-only) ----------------
MODEL_VERSION = "v2.2"        # frozen model tag — bump whenever scoring/engine logic changes
# v1   — original inputs (long-term debt only, flat Rd = rf+1%, statutory 21% tax)
# v1.1 — Plan 2: + short debt in borrowings · leases in risk debt · Rd from interest
#        expense · effective tax from filings · maintenance capex wired into EPV
# v2   — Plan 3 (split-validated as backtest variant 'v2w'): engine weights DCF .10 /
#        RIM .35 / Warranted .30 · deterministic DCF (MC removed) · 0.85^n flag decay
#        (Cyclical revenue informational) · growth out of quality · Altman-Z gated off
#        for Financials/Real Estate. Reverse-DCF gap blend REJECTED (regime-fragile).
# v2.1 — Plan 5: every "now" input is TTM (flows) or freshest quarterly instant
#        (balance sheet) from financials_now; annual series remain the history.
#        Staleness = no filing covering the last ~9 months.
# v2.2 — Plan A: L5 archetype router. Financials/REITs price on RIM only (DCF/EPV/
#        Warranted/reverse-DCF forced N/A — no EV/net-debt/FFO concept); FCF/leverage
#        traps skipped for them; Warranted regression fit on 'standard' names only.

def _migrate_snapshots(con):
    """One-time (Plan A): snapshots PK (run_date, ticker) -> (run_date, universe, ticker) so
       two universes' baskets on the same day don't collide. Existing rows already carry
       universe='Nasdaq-100'; idempotent (checks the PK before touching anything)."""
    if not con.execute("SELECT name FROM sqlite_master WHERE name='snapshots'").fetchone():
        return
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='snapshots'").fetchone()[0]
    if "universe, ticker" in ddl.replace("\n", " ").replace("  ", " "):
        return                                            # already migrated
    con.executescript("""
        ALTER TABLE snapshots RENAME TO snapshots_v1;
        CREATE TABLE snapshots(
            run_date TEXT, model TEXT, universe TEXT, ticker TEXT,
            price REAL, low REAL, mid REAL, high REAL, upside REAL,
            conf INTEGER, quality INTEGER, score REAL, flags TEXT,
            PRIMARY KEY (run_date, universe, ticker));
        INSERT INTO snapshots SELECT * FROM snapshots_v1;
        DROP TABLE snapshots_v1;""")
    con.commit()


def append_snapshot(out, universe, run_id):
    """Append this run's full ranked output to `snapshots` — never overwritten.
       This is the before/after diff surface for every future model change, and the
       raw material for the forward paper-trading ledger (Plan 4)."""
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS snapshots(
        run_date TEXT, model TEXT, universe TEXT, ticker TEXT,
        price REAL, low REAL, mid REAL, high REAL, upside REAL,
        conf INTEGER, quality INTEGER, score REAL, flags TEXT,
        PRIMARY KEY (run_date, universe, ticker))""")
    _migrate_snapshots(con)
    con.executemany(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(run_id, MODEL_VERSION, universe, x["ticker"], x["price"], x["low"], x["mid"],
          x["high"], x["upside"], x["conf"], x["quality"], x["score"], "|".join(x["flags"]))
         for x in out])
    con.commit()
    n_runs = con.execute("SELECT COUNT(DISTINCT run_date) FROM snapshots WHERE universe=?",
                         (universe,)).fetchone()[0]
    con.close()
    return n_runs


# ---------------- pass 2: engines + synthesis ----------------
def main(universe_id=ACTIVE):
    ucfg = resolve_universe(universe_id)
    uid, uname, min_mcap = ucfg["id"], ucfg["name"], ucfg["min_mcap"]
    rf, rf_src = fetch_risk_free()
    erp, tax = CFG["equity_risk_premium"], CFG["tax_rate"]
    term_g = min(CFG["terminal_growth"], rf)
    H, S1 = CFG["forecast_horizon"], CFG["stage1_years"]
    asof = datetime.datetime.now().strftime("%b %d %Y · %H:%M")
    print(f"[{uname}] Risk-free {rf*100:.2f}% [{rf_src}] · ERP {erp*100:.1f}% · terminal g "
          f"{term_g*100:.1f}% · normalized-FCF base · EPV=floor · effective tax · archetype router\n")

    con = sqlite3.connect(DB_PATH)
    try:
        betas = dict(con.execute("SELECT ticker, beta FROM betas"))
    except sqlite3.OperationalError:
        betas = {}
    rows, excluded = collect(con, rf, erp, tax, betas, uid)
    con.close()

    # Plan C: per-name 12-1 momentum + within-universe percentile (a DISPLAYED factor —
    # the backtest showed momentum is real on this growth universe but it is NOT blended
    # into the fair-value composite; see momentum.py / Methodology).
    mom = load_live_momentum([r["t"] for r in rows])
    mom_sorted = sorted(v for v in mom.values() if v is not None)

    # cross-sectional context. Warranted anchor is fit on 'standard' names ONLY — banks/
    # REITs have no meaningful EV/EBIT and would pollute the sector-median regression.
    quality_scores(rows)
    fit_rows = [(r["sector"], (r["mcap"] + r["debt"] - r["cash"]) / r["ebit_now"],
                 r["g1"], r["om"] or 0.0)
                for r in rows if r["arch"] == "standard" and r["ebit_now"] and r["ebit_now"] > 0
                and (r["mcap"] + r["debt"] - r["cash"]) / r["ebit_now"] > 0]
    wfit = warranted_fit(fit_rows)
    if wfit:
        smeans, gmean, coef = wfit
        print(f"Warranted v2 fit on {len(fit_rows)} names · {len(smeans)} sector anchors "
              f"(global mean EV/EBIT {gmean[0]:.1f}) · within-sector: "
              f"+{coef[0]:.1f}·Δg +{coef[1]:.1f}·Δmargin\n")
    else:
        print("Warranted v2 fit FAILED — engine disabled\n")

    out = []
    tally = {"standard": 0, "financial": 0, "reit": 0}
    rim_only = fcf_routed = 0
    for r in rows:
        arch = r["arch"]
        base_fcf = r["fcf_norm"] if (r["fcf_norm"] or 0) > 0 else r["fcf_last"]
        ndebt = r["debt"] - r["cash"]

        dcf_ps = dcf(base_fcf, r["wacc"], term_g, ndebt, r["shares"], r["g1"], H, S1)
        epv_ps = epv((r["om"] or 0) * (r["rev_now"] or 0), r["tax_r"], r["wacc"], r["cash"],
                     r["debt"], r["shares"], r["dna"], r["capex_now"])
        book_ps = r["equity_now"] / r["shares"] if (r["equity_now"] and r["shares"]) else None
        roe = avg_roe(r["ni_s"], r["eq_s"])
        rim_ok = (book_ps and book_ps > 0 and roe is not None
                  and book_ps / r["price"] >= 0.15 and roe <= 0.40)
        rim_ps = rim(book_ps, roe, r["re_"], H) if rim_ok else None
        warr_ps = warranted_value(wfit, r["sector"], r["g1"], r["om"] or 0.0,
                                  r["ebit_now"], r["cash"], r["debt"], r["shares"])
        impl, op = reverse_dcf(base_fcf, r["wacc"], term_g, ndebt, r["mcap"], H, S1)

        # L5 router (Plan A) — the ONE enforcement seam. Forcing a gated engine to None
        # simultaneously (a) removes it from triangulate's mid, (b) flips methods[].applicable
        # to False on the dashboard, and (c) needs no weight override (triangulate normalizes
        # for the single surviving engine, so mid == RIM exactly for banks/REITs).
        # Asset-light exception: a 'Financials' name whose book is immaterial (RIM fails on
        # book/price) but which has clean, UNDISTORTED FCF is a fee/network business (Visa,
        # Mastercard, Moody's, exchanges), NOT a deposit bank — value it on FCF like a
        # standard name. Float-guard: a normalized FCF yield above ~6% on a large financial
        # signals the FCF base is inflated by insurance float / lending receivable flows
        # (Ameriprise fcfy 13%, Amex 7%) — distrust it, keep those RIM-gated. This data-sanity
        # clamp is in the same family as the 28× anchor cap and the tax/Rd clamps.
        eff_arch = arch
        if (arch == "financial" and not rim_ok and base_fcf is not None and base_fcf > 0
                and r["mcap"] and base_fcf / r["mcap"] <= 0.06):
            eff_arch = "standard"; fcf_routed += 1
        gates = ARCHETYPE_GATES[eff_arch]
        dcf_ps, epv_ps, warr_ps, impl, op = apply_archetype_gates(
            eff_arch, dcf_ps, epv_ps, warr_ps, impl, op)

        z = altman_z(r) if eff_arch == "standard" else None
        fscore, fn = piotroski(r)
        tri = triangulate({"DCF": dcf_ps, "RIM": rim_ps, "Warranted": warr_ps},
                          epv_ps, r["price"])
        flags = trap_flags(r, z, fscore, min_mcap)
        if not tri:
            reason = {"financial": "financial: RIM only, and book value/ROE not usable "
                                    "(negative/buyback-distorted book, or implausible ROE)",
                      "reit": "reit: unpriceable — needs FFO/NAV; book is negative or "
                              "historical-cost-distorted and no EV/FCF engine applies"}.get(
                          arch, "no positive FCF/earnings base (GAAP loss-maker)")
            excluded.append((r["t"], reason)); continue
        tally[arch] += 1
        if eff_arch != "standard":
            rim_only += 1                                 # truly gated (RIM-only) bank/insurer/REIT

        q = r["quality"] or 50
        upside = tri["upside"]
        # per-flag decay (Plan 3): one flag ≠ five flags; informational flags don't penalize
        n_pen = sum(1 for fl in flags if fl not in INFO_FLAGS)
        score = ((max(-0.5, min(0.6, upside)) + 0.5) * (tri["conf"] / 5)
                 * (q / 100) * (0.85 ** n_pen))

        ni_ps = (r["ni_now"] or 0) / r["shares"]
        ebitda = (r["ebit_now"] or 0) + (r["dna"] or 0)
        rec = {
            "ticker": r["t"], "name": r["name"], "sector": r["sector"],
            "sectorShort": SHORT.get(r["sector"], r["sector"][:4]),
            "finCurrency": r["fin_ccy"], "finThru": r["fin_thru"],
            "price": round(r["price"], 2), "mcapB": round(r["mcap"] / 1e9, 1),
            "quality": q, "growth5y": None if r["g_trail"] is None else round(r["g_trail"], 4),
            "mom12": None if mom.get(r["t"]) is None else round(mom[r["t"]], 4),
            "momPct": (round(100 * pct_rank(mom_sorted, mom[r["t"]]))
                       if mom.get(r["t"]) is not None else None),
            "divYield": round(r["div"] / r["mcap"], 4) if r["mcap"] else None,
            "negBook": bool(r["equity_now"] is not None and r["equity_now"] < 0),
            "low": round(tri["low"], 2), "mid": round(tri["mid"], 2),
            "high": round(tri["high"], 2), "upside": round(upside, 4),
            "conf": tri["conf"], "within": tri["within"],
            "impliedGrowth": None if impl is None else round(impl, 4),
            "impliedOp": op,
            "trailingG": None if r["g_trail"] is None else round(r["g_trail"], 4),
            # EV/FCF display metrics are meaningless for a deposit/float balance sheet —
            # null them for RIM-gated financials/REITs (P/E is fine; banks have real earnings).
            "pe": round(r["price"] / ni_ps, 1) if ni_ps > 0 else None,
            "evebitda": round((r["mcap"] + ndebt) / ebitda, 1)
                        if (eff_arch == "standard" and ebitda > 0) else None,
            "fcfy": round(base_fcf / r["mcap"], 4)
                    if (eff_arch == "standard" and base_fcf is not None and r["mcap"]) else None,
            # om is pretax/NII-based and inv-cap is deposits/float for gated financials —
            # both meaningless; same honesty rule as fcfy/evebitda/nde above.
            "om": round(r["om"], 4) if (eff_arch == "standard" and r["om"] is not None) else None,
            "roic": round(r["roic"], 4) if (eff_arch == "standard" and r["roic"] is not None) else None,
            "altmanZ": None if z is None else round(z, 2),
            "piotroski": fscore, "piotroskiN": fn,
            "nde": round((r["debt_risk"] - r["cash"]) / ebitda, 2)
                   if (eff_arch == "standard" and ebitda > 0) else None,
            "flags": flags, "score": round(score, 4),
            "cik": r["cik"], "trends": trend_series(r["f"]),
            "methods": [
                {"key": "dcf", "name": "DCF", "value": _r2(dcf_ps),
                 "applicable": dcf_ps is not None,
                 "note": GATED_NOTE.get(arch) if not gates["DCF"] else
                         f"normalized FCF · g₁ {r['g1']*100:.0f}% capped · WACC {r['wacc']*100:.1f}%"},
                {"key": "rim", "name": "RIM", "value": _r2(rim_ps), "applicable": rim_ps is not None,
                 "note": ("book + PV excess ROE · ω 0.62"
                          + (" · the anchor for this archetype" if arch != "standard" else ""))
                         if rim_ps is not None else
                         "N/A — book value buyback-distorted or ROE implausible"},
                {"key": "epv", "name": "EPV (floor)", "value": _r2(epv_ps),
                 "applicable": epv_ps is not None,
                 "note": GATED_NOTE.get(arch) if not gates["EPV"] else
                         "no-growth NOPAT / WACC — sets the LOW bound, never in mid"},
                {"key": "warranted", "name": "Warranted mult.", "value": _r2(warr_ps),
                 "applicable": warr_ps is not None,
                 "note": GATED_NOTE.get(arch) if not gates["Warranted"] else
                         "sector-anchored EV/EBIT, adjusted within sector for growth/margin"},
                {"key": "ddm", "name": "DDM", "value": None, "applicable": False,
                 "note": "replaced by warranted multiple for this universe (few payers)"},
            ],
        }
        out.append(rec)

    out.sort(key=lambda x: x["score"], reverse=True)

    # ---- console: the ranked board ----
    hdr = (f"{'#':>3} {'TICK':5}{'SEC':>5}{'PRICE':>9}{'FAIR':>9}{'UPSIDE':>8}"
           f"{'Q':>4}{'conf':>5}{'impl vs trail':>15}  flags")
    print(hdr); print("-" * len(hdr))
    for i, x in enumerate(out[:25], 1):
        ivt = _ivt(x)
        print(f"{i:>3} {x['ticker']:5}{x['sectorShort']:>5}{money(x['price']):>9}"
              f"{money(x['mid']):>9}{pct(x['upside']):>8}{x['quality']:>4}{x['conf']:>5}"
              f"{ivt:>15}  {','.join(x['flags']) or '—'}")
    print(f"  … {max(0, len(out)-25)} more · ranked by composite score "
          f"(upside × confidence × quality × trap-penalty)")
    # archetype tally — a single mislabeled GICS sector flips a name's whole engine set,
    # so make it visible each run rather than silent.
    print(f"Archetype: standard {tally['standard']} · financial {tally['financial']} · "
          f"reit {tally['reit']} (RIM-only {rim_only} · asset-light→FCF {fcf_routed}); "
          f"{sum(1 for t,w in excluded if w.startswith(('financial','reit')))} financials/REITs "
          f"excluded-with-reason")

    meta = {"asOf": asof, "riskFree": rf, "riskFreeSource": rf_src, "erp": erp,
            "terminalG": term_g, "universe": uname, "universeId": uid,
            "covered": len(out), "excluded": [{"ticker": t, "why": w} for t, w in excluded]}
    payload = {"meta": meta, "companies": out}
    default = (uid == ACTIVE)
    fnames = [f"output_{uid}.json"] + (["output.json"] if default else [])
    for d in [DB_PATH.parent, DB_PATH.parent.parent.parent / "frontend" / "public"]:
        if d.is_dir():
            for fn in fnames:
                (d / fn).write_text(json.dumps(payload, indent=1 if d == DB_PATH.parent else None),
                                    encoding="utf-8")
            _write_manifest(d)                            # universes.json — enumerates the toggle
    print(f"\nExcluded ({len(excluded)}): " + ", ".join(t for t, _ in excluded))
    print(f"Wrote {len(out)} Company records → {', '.join(fnames)}")

    run_id = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_runs = append_snapshot(out, uname, run_id)
    print(f"Snapshot {run_id} [{MODEL_VERSION}] appended ({len(out)} {uname} names) · "
          f"{n_runs} {uname} runs in history")


def _write_manifest(d):
    """frontend manifest of universes that actually have an output_<id>.json present,
       so the dashboard toggle enumerates real files with no hardcoding."""
    avail = []
    for u in UNIVERSES.values():
        p = d / f"output_{u['id']}.json"
        if p.exists():
            try:
                cov = json.loads(p.read_text(encoding="utf-8"))["meta"]["covered"]
            except Exception:
                cov = None
            avail.append({"id": u["id"], "name": u["name"], "covered": cov,
                          "default": u["id"] == ACTIVE})
    (d / "universes.json").write_text(json.dumps(avail), encoding="utf-8")


def _r2(v):
    return None if v is None else round(v, 2)

def _ivt(x):
    if x["impliedGrowth"] is None:
        return "n/a"
    g = f"{x['impliedGrowth']*100:.0f}%"
    if x.get("impliedOp") and x["impliedOp"] != "=":
        g = x["impliedOp"] + g
    tr = "n/a" if x["trailingG"] is None else f"{x['trailingG']*100:.0f}%"
    return f"{g} vs {tr}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "all":        # score every configured universe
        for _uid in UNIVERSES:
            main(_uid)
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else ACTIVE)
