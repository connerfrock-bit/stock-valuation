"""
Monthly price history + splits for the FULL historical membership (202 names),
plus ^GSPC (rolling betas) and ^TNX (historical 10Y yield = risk-free at date D).
Delisted names that Yahoo no longer serves are LOGGED — that residual survivorship
gap is quantified by the backtest, never hidden. stdlib only.  python prices.py
"""
import json, sqlite3, sys, time, urllib.parse
from common import DB_PATH, http_text


def fetch_monthly(symbol, rng="15y"):
    """-> (rows [(month, close, adjclose)], splits [(date, factor)])"""
    sym = urllib.parse.quote(symbol)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range={rng}&interval=1mo&events=splits")
    res = json.loads(http_text(url, timeout=20))["chart"]["result"][0]
    ts = res.get("timestamp") or []
    quote = res["indicators"]["quote"][0].get("close") or []
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or quote
    rows = []
    for i, t in enumerate(ts):
        c = quote[i] if i < len(quote) else None
        a = adj[i] if i < len(adj) else None
        if c is not None:
            rows.append((time.strftime("%Y-%m", time.gmtime(t)), c, a if a is not None else c))
    splits = []
    for ev in (res.get("events", {}).get("splits", {}) or {}).values():
        num, den = ev.get("numerator"), ev.get("denominator")
        if num and den:
            splits.append((time.strftime("%Y-%m-%d", time.gmtime(ev["date"])), num / den))
    return rows, splits


def main(suf=""):
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS price_monthly(ticker TEXT, month TEXT, close REAL, adjclose REAL,
        PRIMARY KEY (ticker, month));
    CREATE TABLE IF NOT EXISTS splits(ticker TEXT, sdate TEXT, factor REAL, PRIMARY KEY (ticker, sdate));
    """)
    names = (DB_PATH.parent / f"membership_names{suf}.txt").read_text().split()
    have = {r[0] for r in con.execute("SELECT DISTINCT ticker FROM price_monthly")}
    names = [n for n in names if n not in have]           # incremental: only new symbols
    symbols = names + [s for s in ("^GSPC", "^TNX") if s not in have]
    ok, missing = 0, []
    for i, s in enumerate(symbols, 1):
        try:
            rows, splits = fetch_monthly(s)
            if not rows:
                raise ValueError("empty")
            con.executemany("INSERT OR REPLACE INTO price_monthly VALUES (?,?,?,?)",
                            [(s, m, c, a) for m, c, a in rows])
            con.executemany("INSERT OR REPLACE INTO splits VALUES (?,?,?)",
                            [(s, d, f) for d, f in splits])
            con.commit()
            ok += 1
            if i % 25 == 0:
                print(f"  [{i}/{len(symbols)}] …")
        except Exception:
            missing.append(s)
        time.sleep(0.15)

    n = con.execute("SELECT COUNT(*) FROM price_monthly").fetchone()[0]
    ns = con.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
    con.close()
    print(f"\nPrices: {ok}/{len(symbols)} symbols, {n} month-rows, {ns} split events")
    print(f"Missing (delisted/renamed — quantified survivorship gap): {len(missing)}")
    print("  " + " ".join(missing))


if __name__ == "__main__":
    main("_sp500" if len(sys.argv) > 1 and sys.argv[1] == "sp500" else "")
