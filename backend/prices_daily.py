"""
Daily price history for the deep-dive Price chart (split/dividend-adjusted), plus the
compact per-universe prices_<uid>.json the dashboard lazy-loads when a deep-dive opens.

This is DELIBERATELY isolated from the monthly beta/momentum pipeline (betas.py keeps
price_monthly fresh; nothing here touches it). It adds one extra Yahoo pass over the
covered names to populate a `price_daily` table, then bakes a shared-axis JSON:
  { "daily":   {"dates":[...],  "series": {TICK: [adj|null, ...]}},   # trailing ~14mo
    "monthly": {"months":[...], "series": {TICK: [adj|null, ...]}} }  # full lifetime
The dashboard uses daily for ranges <= 1Y and monthly for 5Y / Max. A shared date axis
(US trading calendar is common to every name) keeps the payload small; leading nulls mark
pre-IPO gaps. stdlib only.

  python prices_daily.py                 # fetch all companies (nightly), then export every universe
  python prices_daily.py ndx             # fetch only one universe's members (fast validation)
  python prices_daily.py --tickers=NVDA,AAPL   # fetch an explicit list
  python prices_daily.py --export        # skip the fetch, just re-bake prices_*.json from the DB
"""
import datetime, json, sqlite3, sys, time, urllib.parse
from common import BASE, DB_PATH, UNIVERSES, ACTIVE, http_text

PUB = BASE.parent / "frontend" / "public"      # BASE = backend/ ; sibling frontend/public
DAILY_FETCH_RANGE = "2y"                        # Yahoo pull (2y is the smallest range >= our export window)
EXPORT_DAILY_DAYS = 420                         # trailing daily window baked into JSON (covers 1Y + buffer)


def fetch_daily(symbol, rng=DAILY_FETCH_RANGE):
    """-> rows [(date 'YYYY-MM-DD', close, adjclose)] of daily bars (same Yahoo chart
       endpoint betas.py uses, interval=1d)."""
    sym = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
    res = json.loads(http_text(url, timeout=25))["chart"]["result"][0]
    quote = res["indicators"]["quote"][0].get("close") or []
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or quote
    rows = []
    for i, ts in enumerate(res.get("timestamp") or []):
        c = quote[i] if i < len(quote) else None
        if c is None:
            continue
        d = time.strftime("%Y-%m-%d", time.gmtime(ts))
        a = adj[i] if i < len(adj) and adj[i] is not None else c
        rows.append((d, c, a))
    return rows


def ensure_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS price_daily(ticker TEXT, date TEXT, "
                "close REAL, adjclose REAL, PRIMARY KEY (ticker, date))")


def upsert_daily(con, symbol, rows):
    con.executemany("INSERT OR REPLACE INTO price_daily VALUES (?,?,?,?)",
                    [(symbol, d, c, a) for d, c, a in rows])


def _members(con, uid):
    return [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM universe_membership WHERE universe=? ORDER BY ticker", (uid,))]


def _r(v):
    """Chart-grade precision: cents for normal prices, finer for sub-$5 names (keeps the
    line smooth for low-priced/early-split-adjusted stocks). Trims JSON size vs raw 4dp."""
    return round(v, 2) if v >= 5 else round(v, 4)


def export_all(con):
    """Bake prices_<uid>.json (+ prices.json for the active universe) for every universe.
       Loads the windowed daily + full monthly tables ONCE, then slices per membership."""
    ensure_table(con)
    maxd = con.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
    cutoff = ((datetime.date.fromisoformat(maxd) - datetime.timedelta(days=EXPORT_DAILY_DAYS)).isoformat()
              if maxd else "9999-99")

    dprice = {}                                   # ticker -> {date: adjclose}
    for t, d, a in con.execute("SELECT ticker, date, adjclose FROM price_daily WHERE date>=?", (cutoff,)):
        if a is not None:
            dprice.setdefault(t, {})[d] = a
    mprice = {}                                   # ticker -> {month: adjclose}
    for t, mo, a in con.execute("SELECT ticker, month, adjclose FROM price_monthly"):
        if a is not None:
            mprice.setdefault(t, {})[mo] = a

    # Align the current (partial) month's monthly bar to the latest daily close, so the
    # daily ranges (<=1Y) and the monthly ranges (5Y/Max) agree on the "today" endpoint.
    # betas.py refreshes the month bar nightly, but a mid-cycle run can leave it stale.
    for t, dd in dprice.items():
        if dd:
            last_d = max(dd)
            mprice.setdefault(t, {})[last_d[:7]] = dd[last_d]

    written = []
    for uid in UNIVERSES:
        members = [t for t in _members(con, uid) if t in dprice or t in mprice]
        ddates = sorted({d for t in members if t in dprice for d in dprice[t]})
        dseries = {t: [_r(dprice[t][d]) if d in dprice[t] else None for d in ddates]
                   for t in members if t in dprice}
        mmonths = sorted({mo for t in members if t in mprice for mo in mprice[t]})
        mseries = {t: [_r(mprice[t][mo]) if mo in mprice[t] else None for mo in mmonths]
                   for t in members if t in mprice}
        payload = {"generated": maxd or "",
                   "daily":   {"dates": ddates,  "series": dseries},
                   "monthly": {"months": mmonths, "series": mseries}}
        blob = json.dumps(payload)
        fnames = [f"prices_{uid}.json"] + (["prices.json"] if uid == ACTIVE else [])
        for d in (PUB, DB_PATH.parent):
            if d.is_dir():
                for fn in fnames:
                    (d / fn).write_text(blob, encoding="utf-8")
        written.append((uid, len(members), len(ddates), len(mmonths), len(blob)))
    return written


def _scope_tickers(con, argv):
    expl = [a for a in argv[1:] if a.startswith("--tickers=")]
    if expl:
        return [t.strip() for t in expl[0].split("=", 1)[1].split(",") if t.strip()]
    if len(argv) > 1 and not argv[1].startswith("--"):
        m = _members(con, argv[1])
        if m:
            return m
        print(f"  (no members for universe '{argv[1]}' — fetching all companies instead)")
    return [r[0] for r in con.execute("SELECT ticker FROM companies ORDER BY ticker")]


def main():
    argv = sys.argv
    con = sqlite3.connect(DB_PATH)
    ensure_table(con)
    if "--export" not in argv:
        tickers = _scope_tickers(con, argv)
        print(f"Fetching daily bars ({DAILY_FETCH_RANGE}) for {len(tickers)} names...")
        ok = fail = 0
        for i, t in enumerate(tickers, 1):
            try:
                rows = fetch_daily(t); time.sleep(0.15)
            except Exception as e:
                fail += 1
                if fail <= 20:
                    print(f"  {t}: fetch failed {e!r}")
                continue
            upsert_daily(con, t, rows); ok += 1
            if i % 100 == 0:
                con.commit(); print(f"  {i}/{len(tickers)} ... ({ok} ok, {fail} failed)")
        con.commit()
        print(f"Daily fetch done: {ok} ok, {fail} failed.")
    print("Baking prices_<uid>.json ...")
    for uid, nm, nd, nmo, sz in export_all(con):
        print(f"  prices_{uid}.json: {nm} names · {nd} daily dates · {nmo} months · {sz/1e6:.2f} MB")
    con.commit(); con.close()


if __name__ == "__main__":
    main()
