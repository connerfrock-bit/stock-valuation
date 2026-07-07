"""
Plan C — momentum overlay study. 12-1 monthly momentum, top-quintile, MONTHLY rebalance,
with a market-trend crash filter. Price-only (adjclose) — no PIT/engines — so it runs on
the same survivorship-aware membership + prices the fundamental backtest uses.

Tests the Plan 6 lead honestly: standalone momentum topped the per-method table but the
quarterly fixed-weight z-blend killed it. Here it gets what the literature says it needs —
monthly rebalance, its own sizing (not dilution), and a crash filter — evaluated on
2012-2026 with the pre2012-15 window that PREDATES any of our signal design (true OOS).

Variants:
  MOM          — long top-quintile 12-1 momentum, monthly, equal weight
  MOM+trend    — MOM only while the market's own 12-1 is positive; else hold the benchmark
                 (long-only momentum-crash guard: sidesteps the post-crash rebound whipsaw)
Benchmark      — equal-weight of all covered members, monthly.

stdlib only.   python momentum.py [ndx|sp500]
"""
import json, sqlite3, sys
from datetime import date
from common import DB_PATH

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

START = "2012-03"


def month_add(m, k):
    y, mo = int(m[:4]), int(m[5:7])
    i = y * 12 + (mo - 1) + k
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def load(con, suf):
    adj = {}
    for t, m, a in con.execute("SELECT ticker, month, adjclose FROM price_monthly"):
        adj.setdefault(t, {})[m] = a
    mem_q = {}
    for q, t in con.execute(f"SELECT qdate, ticker FROM membership{suf}"):
        mem_q.setdefault(q[:7], set()).add(t)          # keyed by YYYY-MM of the quarter-end
    return adj, mem_q


def members_at(mem_q, month):
    """Forward-fill quarterly membership to a monthly cadence: the most recent snapshot
       on or before this month."""
    keys = [q for q in mem_q if q <= month]
    return mem_q[max(keys)] if keys else set()


def mom_12_1(a, m):
    """12-1 momentum at month m: return from m-12 to m-1 (skip the most recent month)."""
    p0, p1 = a.get(month_add(m, -12)), a.get(month_add(m, -1))
    return (p1 / p0 - 1) if (p0 and p1 and p0 > 0) else None


def run(adj, mem_q, months, mkt, trend_filter, cost_per_side=0.0):
    """-> per-month [(month, strat_ret_net, bench_ret)] holding month m→m+1.
       cost_per_side charged on the turnover of the held basket (monthly momentum is
       high-turnover; the gross number is misleading without it)."""
    out = []
    prev = set()
    for m in months:
        mn = month_add(m, 1)
        members = members_at(mem_q, m)
        rows = []
        for t in members:
            a = adj.get(t, {})
            mm = mom_12_1(a, m)
            f0, f1 = a.get(m), a.get(mn)
            if mm is not None and f0 and f1 and f0 > 0:
                rows.append((t, mm, f1 / f0 - 1))
        if len(rows) < 20:
            continue
        bench = sum(r[2] for r in rows) / len(rows)
        k = max(10, len(rows) // 5)
        top = sorted(rows, key=lambda r: -r[1])[:k]
        mom_ret = sum(r[2] for r in top) / len(top)
        risk_on = (not trend_filter) or (mom_12_1(mkt, m) or -1) > 0
        held = {r[0] for r in top} if risk_on else set()
        turnover = 1 - (len(prev & held) / len(held)) if held else (1.0 if prev else 0.0)
        cost = turnover * 2 * cost_per_side          # both sides of the changed fraction
        strat = (mom_ret if risk_on else bench) - cost
        prev = held
        out.append((m, strat, bench, turnover))
    return out


def stats(series):
    if len(series) < 24:
        return None
    n = len(series)
    yrs = n / 12
    sv = bv = 1.0
    peak_s = peak_b = 1.0
    dd_s = dd_b = 0.0
    hits = 0
    for _, s, b, _tv in series:
        sv *= 1 + s; bv *= 1 + b
        peak_s = max(peak_s, sv); dd_s = min(dd_s, sv / peak_s - 1)
        peak_b = max(peak_b, bv); dd_b = min(dd_b, bv / peak_b - 1)
        hits += (s > b)
    def ann(v):
        return v ** (1 / yrs) - 1
    def sharpe(rets):
        m = sum(rets) / len(rets)
        sd = (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5
        return (m * 12) / (sd * (12 ** 0.5)) if sd > 0 else 0
    return {
        "months": n, "years": round(yrs, 1),
        "stratCAGR": round(ann(sv), 4), "benchCAGR": round(ann(bv), 4),
        "excess": round(ann(sv) - ann(bv), 4),
        "hitRate": round(hits / n, 3),
        "stratSharpe": round(sharpe([s for _, s, _, _ in series]), 2),
        "benchSharpe": round(sharpe([b for _, _, b, _ in series]), 2),
        "stratMaxDD": round(dd_s, 3), "benchMaxDD": round(dd_b, 3),
        "avgTurnover": round(sum(x[3] for x in series) / n, 3),
    }


def window(series, a, b):
    return [x for x in series if a <= x[0] <= b]


def main(universe="ndx"):
    suf = "_sp500" if universe == "sp500" else ""
    con = sqlite3.connect(DB_PATH)
    adj, mem_q = load(con, suf)
    con.close()
    mkt = adj.get("^GSPC", {})
    months = sorted(m for m in {mm for t in adj for mm in adj[t]}
                    if m >= START and month_add(m, 1) in mkt)

    # gross, net of realistic large-cap costs (10bps/side), and trend-filtered
    variants = {"MOM (gross)":   run(adj, mem_q, months, mkt, False, 0.0),
                "MOM (net 10bp)": run(adj, mem_q, months, mkt, False, 0.0010),
                "MOM (net 25bp)": run(adj, mem_q, months, mkt, False, 0.0025),
                "MOM+trend (net)": run(adj, mem_q, months, mkt, True, 0.0010)}
    wins = [("full 2012-26", "2012-01", "2026-12"),
            ("pre2012-15 (OOS)", "2012-01", "2015-12"),
            ("2016-2021", "2016-01", "2021-12"),
            ("2022-2026 (hi-cov)", "2022-01", "2026-12")]

    print(f"\n===== MOMENTUM STUDY [{universe}] monthly 12-1 top-quintile =====")
    print(f"{'variant':16}{'window':20}{'excess/yr':>12}{'hit':>6}{'CAGR':>8}{'bench':>8}"
          f"{'Shrp':>6}{'maxDD':>7}{'turn':>6}")
    print("-" * 89)
    report = {}
    for vn, series in variants.items():
        report[vn] = {}
        for wn, a, b in wins:
            st = stats(window(series, a, b))
            if not st:
                continue
            report[vn][wn] = st
            print(f"{vn:16}{wn:20}{st['excess']*100:>+10.2f}pp{st['hitRate']*100:>5.0f}%"
                  f"{st['stratCAGR']*100:>7.1f}%{st['benchCAGR']*100:>7.1f}%"
                  f"{st['stratSharpe']:>6}{st['stratMaxDD']*100:>6.0f}%{st['avgTurnover']*100:>5.0f}%")
        print()

    payload = {"meta": {"ranAt": date.today().isoformat(), "universe": universe,
                        "signal": "12-1 momentum, monthly rebalance, top quintile",
                        "start": months[0], "end": months[-1]},
               "variants": report}
    out = DB_PATH.parent / f"momentum{suf}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    fe = DB_PATH.parent.parent.parent / "frontend" / "public"
    if fe.is_dir():
        (fe / f"momentum{suf}.json").write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {out} (+ synced to frontend)")
    return report


if __name__ == "__main__":
    main("sp500" if len(sys.argv) > 1 and sys.argv[1] == "sp500" else "ndx")
