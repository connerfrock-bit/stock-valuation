"""
Compute real equity betas: 5-yr monthly regression vs the S&P 500, Blume-adjusted
(0.67*raw + 0.33*1.0), clamped to [floor, cap]. Stores into a `betas` table.
stdlib only.  Run after ingest_v1.  Usage: python betas.py
"""
import json, sqlite3, time, urllib.parse
from common import DB_PATH, CFG, http_text


def fetch_monthly(symbol):
    """{ 'YYYY-MM' -> close } of ~5y monthly closes from Yahoo."""
    sym = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1mo"
    res = json.loads(http_text(url))["chart"]["result"][0]
    out = {}
    for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if c is not None:
            out[time.strftime("%Y-%m", time.gmtime(t))] = c
    return out


def beta_from(stock, mkt, min_months=24):
    months = sorted(set(stock) & set(mkt))
    s, m = [], []
    for i in range(1, len(months)):
        a, b = months[i - 1], months[i]
        if stock[a] and mkt[a]:
            s.append(stock[b] / stock[a] - 1)
            m.append(mkt[b] / mkt[a] - 1)
    n = len(s)
    if n < min_months:
        return None
    ms, ss = sum(m) / n, sum(s) / n
    cov = sum((m[i] - ms) * (s[i] - ss) for i in range(n)) / n
    var = sum((m[i] - ms) ** 2 for i in range(n)) / n
    if var <= 0:
        return None
    raw = cov / var
    adj = max(CFG["beta_floor"], min(CFG["beta_cap"], 0.67 * raw + 0.33 * 1.0))
    return raw, adj, n


def main():
    mkt = fetch_monthly("^GSPC")
    print(f"S&P 500 monthly history: {len(mkt)} months\n")
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS betas("
                "ticker TEXT PRIMARY KEY, beta_raw REAL, beta REAL, months INTEGER, updated TEXT)")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    tickers = [r[0] for r in con.execute("SELECT ticker FROM companies ORDER BY ticker")]

    print(f"{'TICK':6}{'raw β':>8}{'adj β':>8}{'mo':>5}")
    print("-" * 27)
    for t in tickers:
        try:
            stock = fetch_monthly(t); time.sleep(0.2)
        except Exception as e:
            print(f"{t:6} fetch failed {e!r}"); continue
        r = beta_from(stock, mkt)
        if not r:
            print(f"{t:6} insufficient overlap"); continue
        raw, adj, n = r
        con.execute("INSERT OR REPLACE INTO betas VALUES (?,?,?,?,?)", (t, raw, adj, n, now))
        print(f"{t:6}{raw:>8.2f}{adj:>8.2f}{n:>5}")
    con.commit(); con.close()
    print("\nadj β = 0.67·raw + 0.33·1.0 (Blume), clamped to "
          f"[{CFG['beta_floor']}, {CFG['beta_cap']}]. Stored in betas table.")


if __name__ == "__main__":
    main()
