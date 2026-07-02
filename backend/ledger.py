"""
Forward paper-trading ledger (Plan 4) — the live out-of-sample test.
The backtest cannot escape its in-sample caveat (the signal's design postdates the
sample). This can: every data refresh freezes the model's top-quintile basket in the
append-only `snapshots` table; this script marks every past basket to the latest run's
prices and reports forward basket-vs-benchmark returns. No look-ahead is possible —
the picks were committed before the returns existed.

Rules:
  - one basket per (model, calendar day): the last run of that day, top quintile by score
  - benchmark = equal-weight of ALL names present in both that run and the latest run
  - price-only returns (no dividends) on BOTH legs — disclosed, not hidden
  - names later excluded from coverage are dropped and counted, never silently ignored
stdlib only.   python ledger.py     (run after value.py)
"""
import json, sqlite3, sys
from datetime import date, datetime
from common import DB_PATH

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CAVEATS = [
    "Baskets are frozen at each run BEFORE forward returns exist — the one test with no in-sample escape hatch.",
    "Price-only returns (no dividends) on both basket and benchmark; the differential is small at this horizon and disclosed.",
    "Marked to the latest run's prices (same source used at ranking time); names later excluded are dropped and counted.",
    "Each model tag is tracked separately — only the CURRENT model's baskets are the live test; older tags are context.",
    "A forward window under ~90 days is noise. This ledger needs quarters, not days, before it means anything.",
]


def build_ledger(runs):
    """runs: {(run_date, model): {ticker: (price, score)}} -> ledger payload dict.
       Pure — testable without the database."""
    if not runs:
        return None
    by_day = {}                                   # (model, day) -> (run_date, rows)
    for (rd, model), rows in runs.items():
        key = (model, rd[:10])
        if key not in by_day or rd > by_day[key][0]:
            by_day[key] = (rd, rows)
    latest_key = max(runs, key=lambda k: k[0])
    latest_rd = latest_key[0]
    latest_px = {t: pv[0] for t, pv in runs[latest_key].items()}
    latest_day = date.fromisoformat(latest_rd[:10])

    baskets = []
    for (model, day), (rd, rows) in sorted(by_day.items(), key=lambda kv: kv[1][0]):
        ranked = sorted(rows.items(), key=lambda kv: -kv[1][1])
        k = max(10, len(ranked) // 5)             # same quintile rule as the backtest
        names = [t for t, _ in ranked[:k]]
        rets = {t: latest_px[t] / pv[0] - 1
                for t, pv in rows.items() if t in latest_px and pv[0]}
        covered = [t for t in names if t in rets]
        b_ret = sum(rets[t] for t in covered) / len(covered) if covered else None
        m_ret = sum(rets.values()) / len(rets) if rets else None
        baskets.append({
            "model": model, "date": day, "runDate": rd,
            "ageDays": (latest_day - date.fromisoformat(day)).days,
            "k": len(names), "covered": len(covered), "missing": len(names) - len(covered),
            "names": names,
            "basketRet": None if b_ret is None else round(b_ret, 4),
            "benchRet": None if m_ret is None else round(m_ret, 4),
            "excess": None if (b_ret is None or m_ret is None) else round(b_ret - m_ret, 4),
        })

    summary = {}
    for b in baskets:
        s = summary.setdefault(b["model"], dict(baskets=0, aged=0, oldestDays=0,
                                                _hits=0, _sum=0.0))
        s["baskets"] += 1
        s["oldestDays"] = max(s["oldestDays"], b["ageDays"])
        if b["ageDays"] > 0 and b["excess"] is not None:
            s["aged"] += 1
            s["_hits"] += b["excess"] > 0
            s["_sum"] += b["excess"]
    for s in summary.values():
        s["hitRate"] = round(s["_hits"] / s["aged"], 3) if s["aged"] else None
        s["avgExcess"] = round(s["_sum"] / s["aged"], 4) if s["aged"] else None
        del s["_hits"], s["_sum"]

    return {
        "meta": {"generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "latestRun": latest_rd, "caveats": CAVEATS},
        "baskets": baskets, "summary": summary,
    }


def main():
    con = sqlite3.connect(DB_PATH)
    runs = {}
    try:
        for rd, model, t, price, score in con.execute(
                "SELECT run_date, model, ticker, price, score FROM snapshots"):
            runs.setdefault((rd, model), {})[t] = (price, score)
    except sqlite3.OperationalError:
        print("No snapshots table yet — run value.py first.")
        return
    con.close()
    payload = build_ledger(runs)
    if not payload:
        print("No snapshots yet — run value.py first.")
        return

    out = DB_PATH.parent / "ledger.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    fe = DB_PATH.parent.parent.parent / "frontend" / "public"
    if fe.is_dir():
        (fe / "ledger.json").write_text(json.dumps(payload), encoding="utf-8")

    print(f"{'DATE':12}{'MODEL':7}{'AGE':>5}{'COV':>8}{'BASKET':>9}{'BENCH':>9}{'EXCESS':>9}")
    print("-" * 59)
    for b in baskets_tail(payload["baskets"], 12):
        fp = lambda v: "    —" if v is None else f"{v*100:+7.1f}%"
        print(f"{b['date']:12}{b['model']:7}{b['ageDays']:>4}d{b['covered']:>4}/{b['k']:<3}"
              f"{fp(b['basketRet']):>9}{fp(b['benchRet']):>9}{fp(b['excess']):>9}")
    for m, s in payload["summary"].items():
        print(f"[{m}] {s['baskets']} basket(s) · oldest {s['oldestDays']}d · "
              + (f"aged avg excess {s['avgExcess']*100:+.1f}% · hit {s['hitRate']*100:.0f}%"
                 if s["aged"] else "no aged baskets yet — forward returns accrue from here"))
    print(f"Wrote {out} (+ synced to frontend)")


def baskets_tail(baskets, n):
    return baskets[-n:]


if __name__ == "__main__":
    main()
