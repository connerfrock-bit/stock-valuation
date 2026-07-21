"""
Forward paper-trading ledger (Plan 4) — the live out-of-sample test.
The backtest cannot escape its in-sample caveat (the signal's design postdates the
sample). This can: every data refresh freezes the model's top-quintile basket in the
append-only `snapshots` table; this script marks every past basket to the latest run's
prices and reports forward basket-vs-benchmark returns. No look-ahead is possible —
the picks were committed before the returns existed.

Rules:
  - one basket per (model, TRADING day): the last run of that day, top quintile by score
  - benchmark = equal-weight of ALL names present in both that run and the latest run
  - total-return (adjclose) on BOTH legs — splits and dividends handled identically
  - names later excluded from coverage are dropped and counted, never silently ignored

Two things this file gets deliberately right, both of which it used to get wrong:

  1. MARK-TO-MARKET IS DECOUPLED FROM THE SNAPSHOT WRITE. Baskets are marked to the
     latest available CLOSE, not to the latest row in `snapshots`. Snapshot writes are
     ISO-week-gated (value.py::append_snapshot), so keying the mark off the newest
     snapshot froze every forward return Tue–Sun and released a week of accrual in one
     step each Monday — a sawtooth that read as "the model had a good week".
  2. WEEKEND SNAPSHOTS ARE NOT INDEPENDENT BASKETS. A Saturday run carries Friday's
     close, so a Sat/Sun basket is Friday's basket with a different label: identical
     entry price, near-identical names. Counting them separately inflated the basket
     count and made hit-rate a foregone conclusion. They now collapse into their
     trading day and are reported as `collapsed`, not silently dropped.

Overlapping baskets are still NOT independent observations — consecutive runs re-rank
the same universe and share most names. `distinctBaskets` and `avgOverlap` exist so the
headline can't imply more evidence than there is.
stdlib only.   python ledger.py     (run after value.py)
"""
import json, sqlite3, sys
from datetime import date, datetime
from common import DB_PATH, UNIVERSES, ACTIVE, resolve_universe

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CAVEATS = [
    "Baskets are frozen at each run BEFORE forward returns exist — the one test with no in-sample escape hatch.",
    "Total-return (split- and dividend-adjusted) on both basket and benchmark, from the same price series used at ranking time.",
    "Marked to the latest available close, not the latest snapshot — forward returns accrue daily, not in weekly steps.",
    "Weekend/duplicate runs carry the prior session's close and are collapsed into their trading day, never counted twice.",
    "Consecutive baskets overlap heavily — the basket count is NOT the number of independent bets; see distinct/overlap.",
    "Each model tag is tracked separately — only the CURRENT model's baskets are the live test; older tags are context.",
    "A forward window under ~90 days is noise. This ledger needs quarters, not days, before it means anything.",
]


def _session_mapper(trading_days):
    """ISO day -> the trading session it prices off (the latest session <= that day).
       A Saturday run carries Friday's close, so it maps to Friday. Identity when no
       calendar is supplied (keeps build_ledger usable without a database)."""
    if not trading_days:
        return lambda day: day
    sessions = sorted(trading_days)

    def session_of(day):
        lo, hi = 0, len(sessions) - 1
        best = None
        while lo <= hi:                            # rightmost session <= day
            mid = (lo + hi) // 2
            if sessions[mid] <= day:
                best, lo = sessions[mid], mid + 1
            else:
                hi = mid - 1
        return best or day                         # pre-history run: leave it alone
    return session_of


def _jaccard(a, b):
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def build_ledger(runs, mark_px=None, mark_day=None, trading_days=None, entry_px=None):
    """runs: {(run_date, model): {ticker: (price, score)}} -> ledger payload dict.

       mark_px       {ticker: price} every basket is marked to (default: latest run's
                     prices — the old, snapshot-coupled behaviour)
       mark_day      ISO day the mark is as of (default: the latest run's day)
       trading_days  sorted ISO session dates; runs on non-sessions collapse into the
                     prior session (default: identity, i.e. calendar days)
       entry_px      {(session, ticker): price} entry marks. When given, a name absent
                     from it is DROPPED rather than falling back to the snapshot price —
                     mixing an unadjusted entry with an adjusted exit would manufacture
                     a return out of a dividend. (default: snapshot prices)

       Pure — testable without the database. Every default reproduces the pre-fix
       behaviour, so the original semantics stay pinned by test_ledger.py."""
    if not runs:
        return None
    session_of = _session_mapper(trading_days)

    by_day = {}                                   # (model, calendar day) -> (run_date, rows)
    for (rd, model), rows in runs.items():        # same-day re-runs: the last one wins
        key = (model, rd[:10])
        if key not in by_day or rd > by_day[key][0]:
            by_day[key] = (rd, rows)

    # Collapse to one basket per trading session. Where several calendar days price off
    # the same session (Fri/Sat/Sun), the EARLIEST is kept: it is the commit that was
    # made first at that price, so it has the least information behind it.
    by_session, collapsed = {}, {}
    for (model, day), (rd, rows) in sorted(by_day.items()):
        key = (model, session_of(day))
        if key not in by_session or day < by_session[key][0]:
            if key in by_session:
                collapsed[model] = collapsed.get(model, 0) + 1
            by_session[key] = (day, rd, rows)
        else:
            collapsed[model] = collapsed.get(model, 0) + 1

    latest_key = max(runs, key=lambda k: k[0])
    latest_rd = latest_key[0]
    if mark_px is None:
        mark_px = {t: pv[0] for t, pv in runs[latest_key].items()}
    mark_day = mark_day or latest_rd[:10]
    mark_session = session_of(mark_day)
    latest_day = date.fromisoformat(mark_day)
    sessions = sorted(trading_days) if trading_days else []

    baskets = []
    for (model, session), (day, rd, rows) in sorted(by_session.items(), key=lambda kv: kv[1][1]):
        ranked = sorted(rows.items(), key=lambda kv: -kv[1][1])
        k = max(10, len(ranked) // 5)              # same quintile rule as the backtest
        names = [t for t, _ in ranked[:k]]
        entry = ((lambda t, pv: entry_px.get((session, t))) if entry_px is not None
                 else (lambda t, pv: pv[0]))
        rets = {}
        for t, pv in rows.items():
            e, x = entry(t, pv), mark_px.get(t)
            if e and x:
                rets[t] = x / e - 1
        covered = [t for t in names if t in rets]
        b_ret = sum(rets[t] for t in covered) / len(covered) if covered else None
        m_ret = sum(rets.values()) / len(rets) if rets else None
        baskets.append({
            "model": model, "date": session, "runDate": rd,
            "ageDays": (latest_day - date.fromisoformat(session)).days,
            "tradingDays": sum(1 for s in sessions if session < s <= mark_session),
            "k": len(names), "covered": len(covered), "missing": len(names) - len(covered),
            "names": names,
            "basketRet": None if b_ret is None else round(b_ret, 4),
            "benchRet": None if m_ret is None else round(m_ret, 4),
            "excess": None if (b_ret is None or m_ret is None) else round(b_ret - m_ret, 4),
        })

    summary = {}
    for b in baskets:
        s = summary.setdefault(b["model"], dict(baskets=0, aged=0, oldestDays=0,
                                                _hits=0, _sum=0.0, _sets=[]))
        s["baskets"] += 1
        s["oldestDays"] = max(s["oldestDays"], b["ageDays"])
        if b["ageDays"] > 0 and b["excess"] is not None:
            s["aged"] += 1
            s["_hits"] += b["excess"] > 0
            s["_sum"] += b["excess"]
            s["_sets"].append(frozenset(b["names"]))
    for model, s in summary.items():
        sets = s.pop("_sets")
        s["hitRate"] = round(s["_hits"] / s["aged"], 3) if s["aged"] else None
        s["avgExcess"] = round(s["_sum"] / s["aged"], 4) if s["aged"] else None
        s["collapsed"] = collapsed.get(model, 0)
        # How much of that basket count is actually new information? Identical baskets
        # are one bet; heavily-overlapping ones are close to one bet.
        s["distinctBaskets"] = len(set(sets))
        pairs = [_jaccard(set(a), set(b)) for i, a in enumerate(sets) for b in sets[i + 1:]]
        s["avgOverlap"] = round(sum(pairs) / len(pairs), 3) if pairs else None
        del s["_hits"], s["_sum"]

    return {
        "meta": {"generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "latestRun": latest_rd, "markedTo": mark_session, "caveats": CAVEATS},
        "baskets": baskets, "summary": summary,
    }


def load_marks(con, runs):
    """Trading calendar + split/dividend-adjusted entry and exit marks from `price_daily`.
       Deliberately NOT sourced from `snapshots`: snapshot writes are ISO-week-gated, so
       marking off the newest snapshot froze forward returns for days at a time.
       -> (trading_days, mark_px, entry_px, mark_day); all None if there is no price table."""
    try:
        trading_days = [r[0] for r in
                        con.execute("SELECT DISTINCT date FROM price_daily ORDER BY date")]
    except sqlite3.OperationalError:
        return None, None, None, None
    if not trading_days:
        return None, None, None, None
    session_of = _session_mapper(trading_days)
    mark_day = trading_days[-1]
    need = sorted({session_of(rd[:10]) for rd, _ in runs} | {mark_day})
    entry_px = {}
    for d, t, px in con.execute(
            "SELECT date, ticker, adjclose FROM price_daily WHERE date IN (%s)"
            % ",".join("?" * len(need)), need):
        if px:
            entry_px[(d, t)] = px
    mark_px = {t: px for (d, t), px in entry_px.items() if d == mark_day}
    return trading_days, mark_px, entry_px, mark_day


def main(universe_id=ACTIVE):
    ucfg = resolve_universe(universe_id)
    uid, uname = ucfg["id"], ucfg["name"]
    con = sqlite3.connect(DB_PATH)
    runs = {}
    try:                                                  # Plan A: one universe's baskets only
        has_uni = "universe" in [r[1] for r in con.execute("PRAGMA table_info(snapshots)")]
        if has_uni:
            q = ("SELECT run_date, model, ticker, price, score FROM snapshots "
                 "WHERE universe=?")
            cur = con.execute(q, (uname,))
        else:
            cur = con.execute("SELECT run_date, model, ticker, price, score FROM snapshots")
        for rd, model, t, price, score in cur:
            runs.setdefault((rd, model), {})[t] = (price, score)
    except sqlite3.OperationalError:
        print("No snapshots table yet — run value.py first.")
        return
    trading_days, mark_px, entry_px, mark_day = load_marks(con, runs)
    con.close()
    if trading_days is None:
        print("No price_daily table — falling back to snapshot-priced marks.")
    payload = build_ledger(runs, mark_px=mark_px, mark_day=mark_day,
                           trading_days=trading_days, entry_px=entry_px)
    if not payload:
        print(f"No {uname} snapshots yet — run value.py {uid} first.")
        return
    payload["meta"]["universe"] = uname
    payload["meta"]["universeId"] = uid

    default = (uid == ACTIVE)
    fnames = [f"ledger_{uid}.json"] + (["ledger.json"] if default else [])
    for d in [DB_PATH.parent, DB_PATH.parent.parent.parent / "frontend" / "public"]:
        if d.is_dir():
            for fn in fnames:
                (d / fn).write_text(json.dumps(payload, indent=1 if d == DB_PATH.parent else None),
                                    encoding="utf-8")
    out = DB_PATH.parent / fnames[0]

    print(f"{'DATE':12}{'MODEL':7}{'AGE':>5}{'SESS':>6}{'COV':>8}{'BASKET':>9}{'BENCH':>9}{'EXCESS':>9}")
    print("-" * 65)
    for b in baskets_tail(payload["baskets"], 12):
        fp = lambda v: "    —" if v is None else f"{v*100:+7.1f}%"
        print(f"{b['date']:12}{b['model']:7}{b['ageDays']:>4}d{b['tradingDays']:>5}s"
              f"{b['covered']:>4}/{b['k']:<3}"
              f"{fp(b['basketRet']):>9}{fp(b['benchRet']):>9}{fp(b['excess']):>9}")
    print(f"marked to {payload['meta']['markedTo']}")
    for m, s in payload["summary"].items():
        print(f"[{m}] {s['baskets']} basket(s) · oldest {s['oldestDays']}d · "
              + (f"aged avg excess {s['avgExcess']*100:+.1f}% · hit {s['hitRate']*100:.0f}%"
                 if s["aged"] else "no aged baskets yet — forward returns accrue from here"))
        if s["aged"]:
            ov = "—" if s["avgOverlap"] is None else f"{s['avgOverlap']*100:.0f}%"
            print(f"       └ {s['distinctBaskets']} distinct of {s['aged']} aged · "
                  f"avg pairwise name overlap {ov} · {s['collapsed']} duplicate run(s) collapsed"
                  + ("  ⚠ effectively ONE bet" if s["distinctBaskets"] < 2 else ""))
    print(f"[{uname}] Wrote {out} (+ synced to frontend)")


def baskets_tail(baskets, n):
    return baskets[-n:]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        for _uid in UNIVERSES:
            main(_uid)
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else ACTIVE)
