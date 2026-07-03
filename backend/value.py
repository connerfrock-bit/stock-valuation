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
from common import (CFG, DB_PATH, fetch_risk_free, load_company, latest, cagr,
                    avg_margin, avg_roe, effective_tax, cost_of_debt, money, pct)
from engines import (cost_of_equity, wacc_of, reverse_dcf, dcf, epv, rim,
                     warranted_fit, warranted_value, triangulate)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHORT = {"Information Technology": "TECH", "Communication Services": "COMM",
         "Consumer Discretionary": "DISC", "Consumer Staples": "STPL", "Health Care": "HLTH",
         "Industrials": "INDU", "Financials": "FINL", "Real Estate": "REIT",
         "Materials": "MATL", "Energy": "ENGY", "Utilities": "UTIL"}

MIN_N100_MCAP = 15e9          # smallest plausible Nasdaq-100 member — below this, suspect data


# ---------------- pass 1: inputs ----------------
def collect(con, rf, erp, tax_fallback, betas):
    cur_year = datetime.date.today().year
    today = datetime.date.today()
    has_now = bool(con.execute(
        "SELECT name FROM sqlite_master WHERE name='financials_now'").fetchone())
    rows, excluded = [], []
    for (t,) in con.execute("SELECT ticker FROM companies ORDER BY ticker"):
        name, price, f = load_company(con, t)
        sector, shares_out, fin_ccy, cik = con.execute(
            "SELECT sector, shares_out, fin_currency, cik FROM companies WHERE ticker=?",
            (t,)).fetchone()
        rev = f.get("revenue", {})
        shares = shares_out or latest(f.get("shares", {}))
        cfo_s, cap_s, sbc_s = f.get("cfo", {}), f.get("capex", {}), f.get("sbc", {})
        if not price:
            excluded.append((t, "no price")); continue
        if not shares:
            excluded.append((t, "no share count")); continue
        if not rev or not cfo_s or not cap_s:
            excluded.append((t, "missing core financials (revenue/CFO/capex)")); continue

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
            t=t, name=name, sector=sector, fin_ccy=fin_ccy or "USD", cik=cik,
            price=price, shares=shares, mcap=mcap,
            beta=beta, re_=re_, wacc=wacc, rev=rev, rev_now=rev_now,
            fcf_norm=fcf_norm, fcf_last=fcf_last, fcf_margin=fcf_margin,
            ebit_now=ebit_now, om=om, ni_s=ni_s, eq_s=eq_s, debt=debt, cash=cash,
            debt_risk=debt_risk, rd=rd, tax_r=tax_r, capex_now=nv("capex", latest(cap_s)),
            dna=dna, div=div, g_trail=g_trail, g1=g1, roic=roic,
            last_fy=max(rev), stale=_is_stale(nowd, rev, today, cur_year),
            fin_thru=nowd.get("revenue", (None, None, None))[1],
            ni_now=nv("net_income", latest(ni_s)), cfo_now=nv("cfo", latest(cfo_s)),
            equity_now=equity_now, cfo_s=cfo_s, f=f, nowd=nowd,
        ))
    return rows, excluded


def _is_stale(nowd, rev, today, cur_year):
    """Stale = no filing covering the last ~9 months (TTM thru date when we have one,
       else the old annual-year rule)."""
    thru = nowd.get("revenue", (None, None, None))[1]
    if thru:
        return datetime.date.fromisoformat(thru) < today - datetime.timedelta(days=270)
    return max(rev) < cur_year - 1


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
INFO_FLAGS = {"Cyclical revenue"}     # shown but not score-penalized — a characteristic, not a trap
Z_NA_SECTORS = {"Financials", "Real Estate"}   # Altman-Z is calibrated for industrials —
                                               # meaningless for banks/REITs; show n/a, never flag


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


def trap_flags(r, z=None, fscore=None):
    flags = []
    rev_yrs = sorted(r["rev"])
    if len(rev_yrs) >= 4 and r["rev"][rev_yrs[-1]] < r["rev"][rev_yrs[-4]]:
        flags.append("Declining revenue 3y")
    if (r["fcf_norm"] is None or r["fcf_norm"] <= 0) and (r["fcf_last"] is None or r["fcf_last"] <= 0):
        flags.append("Negative FCF")
    ebitda = (r["ebit_now"] or 0) + (r["dna"] or 0)
    if ebitda > 0 and (r["debt_risk"] - r["cash"]) / ebitda > 3.5:   # leases count as risk
        flags.append("High leverage")
    if r["equity_now"] is not None and r["equity_now"] < 0:
        flags.append("Negative book value")
    ni, cfo = r["ni_now"], r["cfo_now"]                   # same (TTM) basis on both sides
    if ni and cfo and ni > cfo * 1.2:
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
    if r["mcap"] < MIN_N100_MCAP:
        flags.append("Suspect share count")
    if r["stale"]:
        flags.append("Stale filings")
    return flags


# ---------------- snapshot history (append-only) ----------------
MODEL_VERSION = "v2.1"        # frozen model tag — bump whenever scoring/engine logic changes
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

def append_snapshot(out, universe, run_id):
    """Append this run's full ranked output to `snapshots` — never overwritten.
       This is the before/after diff surface for every future model change, and the
       raw material for the forward paper-trading ledger (Plan 4)."""
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS snapshots(
        run_date TEXT, model TEXT, universe TEXT, ticker TEXT,
        price REAL, low REAL, mid REAL, high REAL, upside REAL,
        conf INTEGER, quality INTEGER, score REAL, flags TEXT,
        PRIMARY KEY (run_date, ticker))""")
    con.executemany(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(run_id, MODEL_VERSION, universe, x["ticker"], x["price"], x["low"], x["mid"],
          x["high"], x["upside"], x["conf"], x["quality"], x["score"], "|".join(x["flags"]))
         for x in out])
    con.commit()
    n_runs = con.execute("SELECT COUNT(DISTINCT run_date) FROM snapshots").fetchone()[0]
    con.close()
    return n_runs


# ---------------- pass 2: engines + synthesis ----------------
def main():
    rf, rf_src = fetch_risk_free()
    erp, tax = CFG["equity_risk_premium"], CFG["tax_rate"]
    term_g = min(CFG["terminal_growth"], rf)
    H, S1 = CFG["forecast_horizon"], CFG["stage1_years"]
    asof = datetime.datetime.now().strftime("%b %d %Y · %H:%M")
    print(f"Risk-free {rf*100:.2f}% [{rf_src}] · ERP {erp*100:.1f}% · terminal g {term_g*100:.1f}% "
          f"· normalized-FCF base · EPV=floor · Rd from interest exp · effective tax\n")

    con = sqlite3.connect(DB_PATH)
    try:
        betas = dict(con.execute("SELECT ticker, beta FROM betas"))
    except sqlite3.OperationalError:
        betas = {}
    rows, excluded = collect(con, rf, erp, tax, betas)
    con.close()

    # cross-sectional context
    quality_scores(rows)
    fit_rows = [(r["sector"], (r["mcap"] + r["debt"] - r["cash"]) / r["ebit_now"],
                 r["g1"], r["om"] or 0.0)
                for r in rows if r["ebit_now"] and r["ebit_now"] > 0
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
    for r in rows:
        base_fcf = r["fcf_norm"] if (r["fcf_norm"] or 0) > 0 else r["fcf_last"]
        ndebt = r["debt"] - r["cash"]

        dcf_ps = dcf(base_fcf, r["wacc"], term_g, ndebt, r["shares"], r["g1"], H, S1)
        epv_ps = epv((r["om"] or 0) * r["rev_now"], r["tax_r"], r["wacc"], r["cash"],
                     r["debt"], r["shares"], r["dna"], r["capex_now"])
        book_ps = r["equity_now"] / r["shares"] if (r["equity_now"] and r["shares"]) else None
        roe = avg_roe(r["ni_s"], r["eq_s"])
        rim_ok = (book_ps and book_ps > 0 and roe is not None
                  and book_ps / r["price"] >= 0.15 and roe <= 0.40)
        rim_ps = rim(book_ps, roe, r["re_"], H) if rim_ok else None
        warr_ps = warranted_value(wfit, r["sector"], r["g1"], r["om"] or 0.0,
                                  r["ebit_now"], r["cash"], r["debt"], r["shares"])
        impl, op = reverse_dcf(base_fcf, r["wacc"], term_g, ndebt, r["mcap"], H, S1)

        z = altman_z(r) if r["sector"] not in Z_NA_SECTORS else None
        fscore, fn = piotroski(r)
        tri = triangulate({"DCF": dcf_ps, "RIM": rim_ps, "Warranted": warr_ps},
                          epv_ps, r["price"])
        flags = trap_flags(r, z, fscore)
        if not tri:
            excluded.append((r["t"], "no positive FCF/earnings base (GAAP loss-maker)")); continue

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
            "divYield": round(r["div"] / r["mcap"], 4) if r["mcap"] else None,
            "negBook": bool(r["equity_now"] is not None and r["equity_now"] < 0),
            "low": round(tri["low"], 2), "mid": round(tri["mid"], 2),
            "high": round(tri["high"], 2), "upside": round(upside, 4),
            "conf": tri["conf"], "within": tri["within"],
            "impliedGrowth": None if impl is None else round(impl, 4),
            "impliedOp": op,
            "trailingG": None if r["g_trail"] is None else round(r["g_trail"], 4),
            "pe": round(r["price"] / ni_ps, 1) if ni_ps > 0 else None,
            "evebitda": round((r["mcap"] + ndebt) / ebitda, 1) if ebitda > 0 else None,
            "fcfy": round((base_fcf or 0) / r["mcap"], 4) if r["mcap"] else None,
            "om": None if r["om"] is None else round(r["om"], 4),
            "roic": None if r["roic"] is None else round(r["roic"], 4),
            "altmanZ": None if z is None else round(z, 2),
            "piotroski": fscore, "piotroskiN": fn,
            "nde": round((r["debt_risk"] - r["cash"]) / ebitda, 2) if ebitda > 0 else None,
            "flags": flags, "score": round(score, 4),
            "cik": r["cik"], "trends": trend_series(r["f"]),
            "methods": [
                {"key": "dcf", "name": "DCF", "value": _r2(dcf_ps),
                 "applicable": dcf_ps is not None,
                 "note": f"normalized FCF · g₁ {r['g1']*100:.0f}% capped · WACC {r['wacc']*100:.1f}%"},
                {"key": "rim", "name": "RIM", "value": _r2(rim_ps), "applicable": rim_ps is not None,
                 "note": "book + PV excess ROE · ω 0.62" if rim_ps is not None else
                         "N/A — book value buyback-distorted or ROE implausible"},
                {"key": "epv", "name": "EPV (floor)", "value": _r2(epv_ps),
                 "applicable": epv_ps is not None,
                 "note": "no-growth NOPAT / WACC — sets the LOW bound, never in mid"},
                {"key": "warranted", "name": "Warranted mult.", "value": _r2(warr_ps),
                 "applicable": warr_ps is not None,
                 "note": "sector-anchored EV/EBIT, adjusted within sector for growth/margin"},
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

    meta = {"asOf": asof, "riskFree": rf, "riskFreeSource": rf_src, "erp": erp,
            "terminalG": term_g, "universe": "Nasdaq-100",
            "covered": len(out), "excluded": [{"ticker": t, "why": w} for t, w in excluded]}
    payload = {"meta": meta, "companies": out}
    out_path = DB_PATH.parent / "output.json"
    out_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nExcluded ({len(excluded)}): " + ", ".join(t for t, _ in excluded))
    print(f"Wrote {len(out)} Company records → {out_path}")
    fe_public = DB_PATH.parent.parent.parent / "frontend" / "public"
    if fe_public.is_dir():                                # keep the dashboard's copy fresh
        (fe_public / "output.json").write_text(json.dumps(payload), encoding="utf-8")
        print(f"Synced → {fe_public / 'output.json'}")

    run_id = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_runs = append_snapshot(out, meta["universe"], run_id)
    print(f"Snapshot {run_id} [{MODEL_VERSION}] appended ({len(out)} names) · "
          f"{n_runs} runs in history")


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
    main()
