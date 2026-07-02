"""
Fair Value — BACKTEST (Phase 7 / L11). Point-in-time, survivorship-aware.
For each quarter-end since 2016: reconstruct index membership, rebuild every input
from vintages filed ON OR BEFORE that date (no look-ahead), run the engine stack,
rank by the composite score, hold the top quintile to the next quarter. Coverage
gaps (delisted names Yahoo/EDGAR no longer serve) are measured and reported.
stdlib only.  Run after membership.py, prices.py, pit.py:   python backtest.py
"""
import json, sqlite3, statistics, sys
from datetime import date
from common import DB_PATH, CFG, cagr
from engines import (cost_of_equity, wacc_of, ev_present_value, reverse_dcf,
                     epv, rim, warranted_fit, warranted_value, triangulate)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ERP, TAX = 0.05, 0.21
START = "2016-03-31"


# ---------------- data access ----------------
def load_all(con, suf):
    pit = {}
    for t, c, fy, end, filed, v in con.execute(
            "SELECT ticker, concept, fy, end_date, filed, value FROM financials_pit"):
        pit.setdefault(t, {}).setdefault(c, []).append((filed, fy, end, v))
    for t in pit:
        for c in pit[t]:
            pit[t][c].sort()
    px, adj = {}, {}
    for t, m, c, a in con.execute("SELECT ticker, month, close, adjclose FROM price_monthly"):
        px.setdefault(t, {})[m] = c
        adj.setdefault(t, {})[m] = a
    spl = {}
    for t, d, f in con.execute("SELECT ticker, sdate, factor FROM splits"):
        spl.setdefault(t, []).append((d, f))
    mem = {}
    for q, t in con.execute(f"SELECT qdate, ticker FROM membership{suf}"):
        mem.setdefault(q, set()).add(t)
    try:
        sectors = dict(con.execute(f"SELECT ticker, sector FROM sectors{suf}"))
    except sqlite3.OperationalError:
        sectors = dict(con.execute("SELECT ticker, sector FROM companies"))
    status = dict(con.execute("SELECT ticker, status FROM pit_meta"))
    return pit, px, adj, spl, mem, sectors, status


def series_asof(pit_t, concept, D):
    """{fy: value} from vintages filed <= D (latest filed per fy wins)."""
    out = {}
    for filed, fy, _end, v in pit_t.get(concept, []):
        if filed <= D:
            out[fy] = v                       # sorted by filed → later overwrite = newest
    return out


def shares_asof(pit_t, splits_t, D):
    """Latest WAB share count filed <= D, adjusted to TODAY's split basis
       (Yahoo monthly closes are retroactively split-adjusted to current basis)."""
    best = None
    for filed, fy, end, v in pit_t.get("shares_wab", []):
        if filed <= D and (best is None or end > best[0]):
            best = (end, v)
    if not best:
        return None
    end, val = best
    for sdate, factor in splits_t:
        if sdate > end:
            val *= factor
    return val


def rolling_beta(adj_t, adj_mkt, month, n=60):
    ms = sorted(m for m in adj_t if m <= month and m in adj_mkt)[-(n + 1):]
    if len(ms) < 25:
        return CFG["beta_default"]
    rs, rm = [], []
    for i in range(1, len(ms)):
        a0, a1 = adj_t[ms[i - 1]], adj_t[ms[i]]
        m0, m1 = adj_mkt[ms[i - 1]], adj_mkt[ms[i]]
        if a0 and m0:
            rs.append(a1 / a0 - 1)
            rm.append(m1 / m0 - 1)
    k = len(rs)
    if k < 24:
        return CFG["beta_default"]
    mean_s, mean_m = sum(rs) / k, sum(rm) / k
    var = sum((x - mean_m) ** 2 for x in rm) / k
    if var <= 0:
        return CFG["beta_default"]
    cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(k)) / k
    raw = cov / var
    return max(CFG["beta_floor"], min(CFG["beta_cap"], 0.67 * raw + 0.33))


# ---------------- the PIT signal ----------------
def signal(t, D, month, pit, px, adj, spl, sectors, rf, adj_mkt):
    pt = pit.get(t)
    price = px.get(t, {}).get(month)
    if not pt or price is None:
        return None
    rev = series_asof(pt, "revenue", D)
    if len(rev) < 3 or max(rev) < int(D[:4]) - 2:         # stale/short history → no signal
        return None
    shares = shares_asof(pt, spl.get(t, []), D)
    if not shares:
        return None
    cfo = series_asof(pt, "cfo", D)
    cap = series_asof(pt, "capex", D)
    sbc = series_asof(pt, "sbc", D)
    ebit = series_asof(pt, "ebit", D)
    ni = series_asof(pt, "net_income", D)
    eq = series_asof(pt, "equity", D)
    debt_s = series_asof(pt, "long_debt", D)
    cash_s = series_asof(pt, "cash", D)
    if not cfo or not cap:
        return None

    def latest(s):
        return s[max(s)] if s else None

    rev_now = latest(rev)
    yrs = sorted(set(rev) & set(cfo) & set(cap))[-5:]
    if not yrs:
        return None
    margins = [(cfo[y] - cap[y] - sbc.get(y, 0.0)) / rev[y] for y in yrs if rev[y]]
    fcf_margin = sum(margins) / len(margins) if margins else None
    fcf_norm = fcf_margin * rev_now if fcf_margin is not None else None
    om_yrs = sorted(set(ebit) & set(rev))[-5:]
    om = (sum(ebit[y] / rev[y] for y in om_yrs if rev[y]) / len(om_yrs)) if om_yrs else None

    mcap = price * shares
    debt, cash = latest(debt_s) or 0.0, latest(cash_s) or 0.0
    ndebt = debt - cash
    beta = rolling_beta(adj.get(t, {}), adj_mkt, month)
    re_ = cost_of_equity(rf, beta, ERP)
    wacc = wacc_of(mcap, max(debt, 0.0), re_, rf + 0.01, TAX)
    term_g = min(CFG["terminal_growth"], rf) if rf > 0.005 else 0.005
    g_tr = cagr(rev)
    g1 = min(max(g_tr or 0.0, 0.0), CFG["initial_growth_cap"])

    dcf_ps = None
    if fcf_norm and fcf_norm > 0 and wacc - term_g >= CFG["min_wacc_minus_g"]:
        dcf_ps = (ev_present_value(fcf_norm, wacc, term_g, g1, 10, 5) - ndebt) / shares
    epv_ps = epv((om or 0) * rev_now, TAX, wacc, cash, debt, shares)
    impl, _op = reverse_dcf(fcf_norm, wacc, term_g, ndebt, mcap, 10, 5)

    ebit_now = latest(ebit)
    # quality raw dims (percentiled cross-sectionally by the caller)
    roe_yrs = sorted(set(ni) & set(eq))[-5:]
    roe = (sum(ni[y] / eq[y] for y in roe_yrs if eq[y] and eq[y] > 0) / len(roe_yrs)) if roe_yrs else None
    lev = (-(ndebt) / ebit_now) if ebit_now and ebit_now > 0 else None

    # RIM — router-gated exactly like live; in a bank-rich universe it finally applies
    book_ps = (latest(eq) / shares) if (latest(eq) and latest(eq) > 0) else None
    rim_ps = None
    if (book_ps and roe is not None and roe <= 0.40 and book_ps / price >= 0.15):
        rim_ps = rim(book_ps, roe, re_, 10)

    flags = 0
    ry = sorted(rev)
    if len(ry) >= 4 and rev[ry[-1]] < rev[ry[-4]]:
        flags += 1
    if fcf_norm is None or fcf_norm <= 0:
        flags += 1
    if ebit_now and ebit_now > 0 and ndebt / ebit_now > 3.5:
        flags += 1
    ni_now, cfo_now = latest(ni), latest(cfo)
    if ni_now and cfo_now and ni_now > cfo_now * 1.2:
        flags += 1
    gr = [rev[ry[i]] / rev[ry[i - 1]] - 1 for i in range(1, len(ry)) if rev[ry[i - 1]]][-6:]
    if len(gr) >= 3:
        m = sum(gr) / len(gr)
        if (sum((x - m) ** 2 for x in gr) / len(gr)) ** 0.5 > 0.18:
            flags += 1

    return dict(t=t, price=price, shares=shares, mcap=mcap, sector=sectors.get(t),
                g1=g1, g_tr=g_tr, om=om, roe=roe, lev=lev, fcf_margin=fcf_margin,
                ebit_now=ebit_now, debt=debt, cash=cash, dcf=dcf_ps, epv=epv_ps,
                rim=rim_ps, impl=impl, flags=flags)


def pct_rank(sorted_vals, v):
    if v is None or not sorted_vals:
        return None
    import bisect
    return bisect.bisect_right(sorted_vals, v) / len(sorted_vals)


def build_quarter(D, month, members, pit, px, adj, spl, sectors, rf, adj_mkt):
    sigs = []
    for t in sorted(members):
        s = signal(t, D, month, pit, px, adj, spl, sectors, rf, adj_mkt)
        if s:
            sigs.append(s)
    if len(sigs) < 20:
        return []
    # warranted multiple: PIT cross-section only
    fit_rows = [(s["sector"] or "UNKNOWN", (s["mcap"] + s["debt"] - s["cash"]) / s["ebit_now"],
                 s["g1"], s["om"] or 0.0)
                for s in sigs if s["ebit_now"] and s["ebit_now"] > 0
                and (s["mcap"] + s["debt"] - s["cash"]) > 0]
    wfit = warranted_fit(fit_rows)
    # quality percentiles
    dims = {k: sorted(v for v in (s[k] for s in sigs) if v is not None)
            for k in ("om", "roe", "g_tr", "fcf_margin", "lev")}
    out = []
    for s in sigs:
        warr = warranted_value(wfit, s["sector"] or "UNKNOWN", s["g1"], s["om"] or 0.0,
                               s["ebit_now"], s["cash"], s["debt"], s["shares"])
        tri = triangulate({"DCF": s["dcf"], "RIM": s["rim"], "Warranted": warr},
                          s["epv"], s["price"])
        if not tri:
            continue
        ps = [pct_rank(dims[k], s[k]) for k in dims]
        ps = [p for p in ps if p is not None]
        q = 100 * sum(ps) / len(ps) if ps else 50
        upside = tri["upside"]
        score = ((max(-0.5, min(0.6, upside)) + 0.5) * (tri["conf"] / 5)
                 * (q / 100) * (0.55 if s["flags"] else 1.0))
        gap = (s["g_tr"] - s["impl"]) if (s["g_tr"] is not None and s["impl"] is not None) else None
        out.append(dict(t=s["t"], score=score, upside=upside,
                        dcf_up=(s["dcf"] / s["price"] - 1) if s["dcf"] else None,
                        warr_up=(warr / s["price"] - 1) if warr else None,
                        epv_up=(s["epv"] / s["price"] - 1) if s["epv"] else None,
                        rim_up=(s["rim"] / s["price"] - 1) if s["rim"] else None,
                        rev_gap=gap))
    return out


# ---------------- simulation ----------------
def simulate(quarters, ranked, fwd):
    """ranked: {D: [signal dicts]}, fwd: {(D, t): forward return}."""
    curve = [{"d": quarters[0], "strat": 1.0, "bench": 1.0}]
    sv = bv = 1.0
    hits = 0
    used = []
    prev_basket = set()
    turnover = []
    per_method = {k: {"hit": 0, "n": 0, "excess": []} for k in
                  ("score", "dcf_up", "warr_up", "epv_up", "rim_up", "rev_gap")}
    for i in range(len(quarters) - 1):
        D = quarters[i]
        rows = [r for r in ranked.get(D, []) if (D, r["t"]) in fwd]
        if len(rows) < 20:
            continue
        rets = {r["t"]: fwd[(D, r["t"])] for r in rows}
        bench_q = sum(rets.values()) / len(rets)
        k = max(10, len(rows) // 5)
        for mkey, agg in per_method.items():
            cand = [r for r in rows if r.get(mkey) is not None]
            if len(cand) < 20:
                continue
            top = sorted(cand, key=lambda r: r[mkey], reverse=True)[:max(10, len(cand) // 5)]
            mret = sum(rets[r["t"]] for r in top) / len(top)
            agg["n"] += 1
            agg["hit"] += (mret > bench_q)
            agg["excess"].append(mret - bench_q)
        basket = [r["t"] for r in sorted(rows, key=lambda r: r["score"], reverse=True)[:k]]
        strat_q = sum(rets[t] for t in basket) / len(basket)
        if prev_basket:
            turnover.append(1 - len(prev_basket & set(basket)) / len(basket))
        prev_basket = set(basket)
        sv *= 1 + strat_q
        bv *= 1 + bench_q
        hits += (strat_q > bench_q)
        used.append((D, strat_q, bench_q, len(rows)))
        curve.append({"d": quarters[i + 1], "strat": round(sv, 4), "bench": round(bv, 4)})
    return curve, used, hits, turnover, per_method


def stats_from(curve, used, hits, turnover):
    n = len(used)
    if n < 8:
        return None
    yrs = n / 4
    sv, bv = curve[-1]["strat"], curve[-1]["bench"]
    s_rets = [u[1] for u in used]
    b_rets = [u[2] for u in used]
    def ann(v):
        return v ** (1 / yrs) - 1
    def sharpe(rets):
        m = sum(rets) / len(rets)
        sd = (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5
        return (m * 4) / (sd * 2) if sd > 0 else 0     # quarterly → annualized
    def maxdd(key):
        peak, dd = 1.0, 0.0
        for p in curve:
            peak = max(peak, p[key])
            dd = min(dd, p[key] / peak - 1)
        return dd
    return {"quarters": n, "years": round(yrs, 1),
            "stratCAGR": round(ann(sv), 4), "benchCAGR": round(ann(bv), 4),
            "hitRate": round(hits / n, 3),
            "stratSharpe": round(sharpe(s_rets), 2), "benchSharpe": round(sharpe(b_rets), 2),
            "stratMaxDD": round(maxdd("strat"), 3), "benchMaxDD": round(maxdd("bench"), 3),
            "avgTurnover": round(sum(turnover) / len(turnover), 3) if turnover else None,
            "avgNames": round(sum(u[3] for u in used) / n, 1)}


def main(universe="ndx"):
    suf = "_sp500" if universe == "sp500" else ""
    con = sqlite3.connect(DB_PATH)
    pit, px, adj, spl, mem, sectors, status = load_all(con, suf)
    con.close()
    print(f"Universe: {universe}  ({len(mem)} snapshots)")

    quarters = sorted(q for q in mem if q >= START)
    tnx = px.get("^TNX", {})
    adj_mkt = adj.get("^GSPC", {})

    ranked, coverage = {}, []
    for D in quarters:
        month = D[:7]
        raw_rf = tnx.get(month)
        rf = (raw_rf / 1000 if raw_rf and raw_rf > 20 else raw_rf / 100) if raw_rf else 0.025
        members = mem[D]
        rows = build_quarter(D, month, members, pit, px, adj, spl, sectors, rf, adj_mkt)
        ranked[D] = rows
        coverage.append({"d": D, "members": len(members), "signals": len(rows),
                         "rf": round(rf, 4)})
        print(f"  {D}  members {len(members):3}  signals {len(rows):3}  rf {rf*100:.2f}%")

    # forward returns from adjclose (total-return proxy)
    fwd = {}
    for i in range(len(quarters) - 1):
        D, Dn = quarters[i], quarters[i + 1]
        m0, m1 = D[:7], Dn[:7]
        for r in ranked.get(D, []):
            a = adj.get(r["t"], {})
            if a.get(m0) and a.get(m1):
                fwd[(D, r["t"])] = a[m1] / a[m0] - 1

    curve, used, hits, turnover, per_method = simulate(quarters, ranked, fwd)
    st = stats_from(curve, used, hits, turnover)
    if not st:
        print("Not enough usable quarters — aborting.")
        return

    pm = []
    label = {"score": "Composite score", "dcf_up": "DCF upside", "warr_up": "Warranted upside",
             "epv_up": "EPV-floor upside", "rim_up": "RIM upside", "rev_gap": "Reverse-DCF gap"}
    for k, agg in per_method.items():
        if agg["n"]:
            pm.append({"method": label[k], "hitRate": round(agg["hit"] / agg["n"], 3),
                       "avgExcessQ": round(sum(agg["excess"]) / len(agg["excess"]), 4),
                       "quarters": agg["n"]})

    avg_cov = sum(c["signals"] / c["members"] for c in coverage) / len(coverage)
    n_missing = sum(1 for s in status.values() if s != "ok")
    payload = {
        "meta": {
            "ranAt": date.today().isoformat(), "universe": universe,
            "start": quarters[0], "end": quarters[-1],
            "rebalance": "quarterly", "portfolio": "top quintile by composite score, equal-weight",
            "benchmark": "equal-weight of all covered members",
            "avgCoverage": round(avg_cov, 3), "namesExcluded": n_missing,
            "caveats": [
                "Fundamentals are point-in-time (vintages by SEC `filed` date) — no restatement look-ahead.",
                f"Average signal coverage {avg_cov:.0%} of members; delisted names without price/EDGAR data are missing (residual survivorship bias, direction unknown).",
                "RIM, Altman-Z and Piotroski excluded from the historical signal (v1); DCF is deterministic (no Monte Carlo).",
                "ERP constant at 5.0%; risk-free from ^TNX at each date; sector for departed names unknown (global multiple anchor).",
                "The signal's design postdates the sample — treat results as validation of plausibility, not proof.",
            ],
        },
        "coverage": coverage, "curve": curve, "stats": st, "perMethod": pm,
    }
    out = DB_PATH.parent / f"backtest{suf}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    fe = DB_PATH.parent.parent.parent / "frontend" / "public"
    if fe.is_dir():
        (fe / f"backtest{suf}.json").write_text(json.dumps(payload), encoding="utf-8")

    print(f"\n===== BACKTEST [{universe}] {quarters[0]} → {quarters[-1]} =====")
    print(f"Strategy CAGR {st['stratCAGR']*100:6.2f}%   vs benchmark {st['benchCAGR']*100:6.2f}%   "
          f"({st['quarters']} quarters, avg {st['avgNames']:.0f} names)")
    print(f"Hit rate {st['hitRate']*100:.0f}% · Sharpe {st['stratSharpe']} vs {st['benchSharpe']} · "
          f"MaxDD {st['stratMaxDD']*100:.0f}% vs {st['benchMaxDD']*100:.0f}% · "
          f"turnover {st['avgTurnover']*100:.0f}%/q")
    print("\nPer-method reliability (top-quintile vs benchmark):")
    for p in pm:
        print(f"  {p['method']:22} hit {p['hitRate']*100:3.0f}%   excess {p['avgExcessQ']*100:+.2f}%/q")
    print(f"\nWrote {out} (+ synced to frontend)")


if __name__ == "__main__":
    main("sp500" if len(sys.argv) > 1 and sys.argv[1] == "sp500" else "ndx")
