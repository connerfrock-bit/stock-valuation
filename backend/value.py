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
                    avg_margin, avg_roe, money, pct)
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
def collect(con, rf, erp, rd, tax, betas):
    cur_year = datetime.date.today().year
    rows, excluded = [], []
    for (t,) in con.execute("SELECT ticker FROM companies ORDER BY ticker"):
        name, price, f = load_company(con, t)
        sector, shares_out = con.execute(
            "SELECT sector, shares_out FROM companies WHERE ticker=?", (t,)).fetchone()
        rev = f.get("revenue", {})
        shares = shares_out or latest(f.get("shares", {}))
        cfo_s, cap_s, sbc_s = f.get("cfo", {}), f.get("capex", {}), f.get("sbc", {})
        if not price:
            excluded.append((t, "no price")); continue
        if not shares:
            excluded.append((t, "no share count")); continue
        if not rev or not cfo_s or not cap_s:
            excluded.append((t, "no US-GAAP financials (foreign filer?)")); continue

        # per-year FCF (SBC expensed) and FCF margins over the overlap window
        yrs = sorted(set(rev) & set(cfo_s) & set(cap_s))[-5:]
        fcf_by_year = {y: cfo_s[y] - cap_s[y] - sbc_s.get(y, 0.0) for y in yrs}
        margins = [fcf_by_year[y] / rev[y] for y in yrs if rev[y]]
        fcf_margin = sum(margins) / len(margins) if margins else None
        rev_now = latest(rev)
        fcf_norm = fcf_margin * rev_now if fcf_margin is not None else None
        fcf_last = fcf_by_year[yrs[-1]] if yrs else None

        ebit_s = f.get("ebit", {})
        ebit_now = latest(ebit_s)
        om = avg_margin(ebit_s, rev, years=5)
        ni_s, eq_s = f.get("net_income", {}), f.get("equity", {})
        debt = latest(f.get("long_debt", {})) or 0.0
        cash = latest(f.get("cash", {})) or 0.0
        dna = latest(f.get("dep_amort", {}))
        div = latest(f.get("dividends", {})) or 0.0
        beta = betas.get(t, CFG["beta_default"])
        mcap = price * shares
        g_trail = cagr(rev)                                # honest trailing growth (uncapped)
        g1 = min(max(g_trail or 0.0, CFG["initial_growth_floor"]), CFG["initial_growth_cap"])
        re_ = cost_of_equity(rf, beta, erp)
        wacc = wacc_of(mcap, max(debt, 0.0), re_, rd, tax)

        rows.append(dict(
            t=t, name=name, sector=sector, price=price, shares=shares, mcap=mcap,
            beta=beta, re_=re_, wacc=wacc, rev=rev, rev_now=rev_now,
            fcf_norm=fcf_norm, fcf_last=fcf_last, fcf_margin=fcf_margin,
            ebit_now=ebit_now, om=om, ni_s=ni_s, eq_s=eq_s, debt=debt, cash=cash,
            dna=dna, div=div, g_trail=g_trail, g1=g1,
            last_fy=max(rev), stale=max(rev) < cur_year - 1,
            ni_now=latest(ni_s), equity_now=latest(eq_s), cfo_s=cfo_s,
        ))
    return rows, excluded


# ---------------- quality (cross-sectional percentiles) ----------------
def pct_rank(sorted_vals, v):
    if v is None or not sorted_vals:
        return None
    import bisect
    return bisect.bisect_right(sorted_vals, v) / len(sorted_vals)

def quality_scores(rows):
    dims = {
        "om":        [r["om"] for r in rows if r["om"] is not None],
        "roe":       [avg_roe(r["ni_s"], r["eq_s"]) for r in rows],
        "growth":    [r["g_trail"] for r in rows if r["g_trail"] is not None],
        "fcfm":      [r["fcf_margin"] for r in rows if r["fcf_margin"] is not None],
        "lowlev":    [-(r["debt"] - r["cash"]) / r["ebit_now"] for r in rows
                      if r["ebit_now"] and r["ebit_now"] > 0],
    }
    S = {k: sorted(v for v in vals if v is not None) for k, vals in dims.items()}
    for r in rows:
        roe = avg_roe(r["ni_s"], r["eq_s"])
        lev = (-(r["debt"] - r["cash"]) / r["ebit_now"]
               if r["ebit_now"] and r["ebit_now"] > 0 else None)
        ps = [pct_rank(S["om"], r["om"]), pct_rank(S["roe"], roe),
              pct_rank(S["growth"], r["g_trail"]), pct_rank(S["fcfm"], r["fcf_margin"]),
              pct_rank(S["lowlev"], lev)]
        ps = [p for p in ps if p is not None]
        r["quality"] = round(100 * sum(ps) / len(ps)) if ps else None


def trap_flags(r):
    flags = []
    rev_yrs = sorted(r["rev"])
    if len(rev_yrs) >= 4 and r["rev"][rev_yrs[-1]] < r["rev"][rev_yrs[-4]]:
        flags.append("Declining revenue 3y")
    if (r["fcf_norm"] is None or r["fcf_norm"] <= 0) and (r["fcf_last"] is None or r["fcf_last"] <= 0):
        flags.append("Negative FCF")
    ebitda = (r["ebit_now"] or 0) + (r["dna"] or 0)
    if ebitda > 0 and (r["debt"] - r["cash"]) / ebitda > 3.5:
        flags.append("High leverage")
    if r["equity_now"] is not None and r["equity_now"] < 0:
        flags.append("Negative book value")
    ni, cfo = r["ni_now"], latest(r["cfo_s"])
    if ni and cfo and ni > cfo * 1.2:
        flags.append("High accruals")
    if r["mcap"] < MIN_N100_MCAP:
        flags.append("Suspect share count")
    if r["stale"]:
        flags.append("Stale filings")
    return flags


# ---------------- pass 2: engines + synthesis ----------------
def main():
    rf, rf_src = fetch_risk_free()
    erp, tax = CFG["equity_risk_premium"], CFG["tax_rate"]
    term_g = min(CFG["terminal_growth"], rf)
    H, S1 = CFG["forecast_horizon"], CFG["stage1_years"]
    rd = rf + CFG["cost_of_debt_spread"]
    asof = datetime.datetime.now().strftime("%b %d %Y · %H:%M")
    print(f"Risk-free {rf*100:.2f}% [{rf_src}] · ERP {erp*100:.1f}% · terminal g {term_g*100:.1f}% "
          f"· normalized-FCF base · EPV=floor\n")

    con = sqlite3.connect(DB_PATH)
    try:
        betas = dict(con.execute("SELECT ticker, beta FROM betas"))
    except sqlite3.OperationalError:
        betas = {}
    rows, excluded = collect(con, rf, erp, rd, tax, betas)
    con.close()

    # cross-sectional context
    quality_scores(rows)
    fit_rows = [((r["mcap"] + r["debt"] - r["cash"]) / r["ebit_now"], r["g1"],
                 r["om"] or 0.0, r["beta"])
                for r in rows if r["ebit_now"] and r["ebit_now"] > 0
                and (r["mcap"] + r["debt"] - r["cash"]) / r["ebit_now"] > 0]
    coef = warranted_fit(fit_rows)
    print(f"Warranted-multiple fit on {len(fit_rows)} names: "
          + ("EV/EBIT = {:.1f} + {:.1f}·g + {:.1f}·margin + {:.1f}·β".format(*coef)
         if coef else "FAILED — engine disabled") + "\n")

    out = []
    for r in rows:
        base_fcf = r["fcf_norm"] if (r["fcf_norm"] or 0) > 0 else r["fcf_last"]
        ndebt = r["debt"] - r["cash"]

        dcf_res = dcf(base_fcf, r["wacc"], term_g, ndebt, r["shares"], r["g1"], H, S1,
                      draws=2500, seed=hash(r["t"]) & 0xFFFF)
        dcf_p50 = dcf_res["p50"] if dcf_res else None
        epv_ps = epv((r["om"] or 0) * r["rev_now"], tax, r["wacc"], r["cash"], r["debt"],
                     r["shares"], r["dna"], None)
        book_ps = r["equity_now"] / r["shares"] if (r["equity_now"] and r["shares"]) else None
        roe = avg_roe(r["ni_s"], r["eq_s"])
        rim_ok = (book_ps and book_ps > 0 and roe is not None
                  and book_ps / r["price"] >= 0.15 and roe <= 0.40)
        rim_ps = rim(book_ps, roe, r["re_"], H) if rim_ok else None
        warr_ps = warranted_value(coef, r["g1"], r["om"] or 0.0, r["beta"],
                                  r["ebit_now"], r["cash"], r["debt"], r["shares"])
        impl, op = reverse_dcf(base_fcf, r["wacc"], term_g, ndebt, r["mcap"], H, S1)

        tri = triangulate({"DCF": dcf_p50, "RIM": rim_ps, "Warranted": warr_ps},
                          epv_ps, r["price"])
        flags = trap_flags(r)
        if not tri:
            excluded.append((r["t"], "no applicable engine")); continue

        q = r["quality"] or 50
        upside = tri["upside"]
        score = ((max(-0.5, min(0.6, upside)) + 0.5) * (tri["conf"] / 5)
                 * (q / 100) * (0.55 if flags else 1.0))

        ni_ps = (r["ni_now"] or 0) / r["shares"]
        ebitda = (r["ebit_now"] or 0) + (r["dna"] or 0)
        rec = {
            "ticker": r["t"], "name": r["name"], "sector": r["sector"],
            "sectorShort": SHORT.get(r["sector"], r["sector"][:4]),
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
            "roic": None,  # needs invested-capital history — Phase 3 hardening
            "nde": round(ndebt / ebitda, 2) if ebitda > 0 else None,
            "flags": flags, "score": round(score, 4),
            "methods": [
                {"key": "dcf", "name": "DCF", "value": _r2(dcf_p50),
                 "applicable": dcf_p50 is not None,
                 "note": f"normalized FCF · g₁ {r['g1']*100:.0f}% capped · WACC {r['wacc']*100:.1f}%"},
                {"key": "rim", "name": "RIM", "value": _r2(rim_ps), "applicable": rim_ps is not None,
                 "note": "book + PV excess ROE · ω 0.62" if rim_ps is not None else
                         "N/A — book value buyback-distorted or ROE implausible"},
                {"key": "epv", "name": "EPV (floor)", "value": _r2(epv_ps),
                 "applicable": epv_ps is not None,
                 "note": "no-growth NOPAT / WACC — sets the LOW bound, never in mid"},
                {"key": "warranted", "name": "Warranted mult.", "value": _r2(warr_ps),
                 "applicable": warr_ps is not None,
                 "note": "peer regression: EV/EBIT on growth·margin·β"},
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
