"""
Fair Value — external data-trust cross-check (run after ingest_v1, before value).
Batches all tickers against Yahoo's quote API (cookie+crumb, no key) and compares
our market cap (price × shares_out) to Yahoo's marketCap — the one field that is
reliably TOTAL across share classes (Yahoo's sharesOutstanding is per-class!).

  |diff| ≤ 5%   ok
  5–15%         drift (reported, not patched — usually WAB vs point-in-time timing)
  > 15%         BAD → shares_out patched to implied total (yahoo_mcap / our_price)

Results land in the data_quality table + console. stdlib only.  python sanity.py
"""
import http.cookiejar, json, sqlite3, sys, time, urllib.request
from common import DB_PATH

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def yahoo_quotes(symbols):
    """Batched quote fields via the crumb-authenticated v7 endpoint."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    try:
        op.open("https://fc.yahoo.com", timeout=15)
    except Exception:
        pass                                              # only the cookie matters
    crumb = op.open("https://query1.finance.yahoo.com/v1/test/getcrumb",
                    timeout=15).read().decode()
    out = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        url = ("https://query1.finance.yahoo.com/v7/finance/quote?symbols="
               + ",".join(chunk)
               + "&fields=marketCap,regularMarketPrice&crumb="
               + urllib.request.quote(crumb))
        res = json.loads(op.open(url, timeout=20).read())["quoteResponse"]["result"]
        for x in res:
            out[x["symbol"]] = (x.get("marketCap"), x.get("regularMarketPrice"))
        time.sleep(0.3)
    return out


def main():
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS data_quality("
                "ticker TEXT PRIMARY KEY, check_name TEXT, status TEXT, detail TEXT)")
    con.execute("DELETE FROM data_quality")
    rows = con.execute("SELECT ticker, price, shares_out FROM companies "
                       "WHERE price IS NOT NULL").fetchall()   # incl. NULL shares → derive from Yahoo
    try:
        ext = yahoo_quotes([t for t, _, _ in rows])
    except Exception as e:
        print(f"External check unavailable ({e!r}) — skipping, internal guards still apply.")
        return

    ok = drift = bad = miss = derived = 0
    print(f"{'TICK':6}{'ours':>10}{'yahoo':>10}{'diff':>8}  action")
    print("-" * 46)
    for t, price, shares in rows:
        emcap, eprice = ext.get(t, (None, None))
        if not emcap:
            miss += 1
            con.execute("INSERT OR REPLACE INTO data_quality VALUES (?,?,?,?)",
                        (t, "mcap_xcheck", "no_ext", "")); continue
        if not shares:                                        # no share count at all → derive it
            new_shares = emcap / price if price else None
            if new_shares:
                con.execute("UPDATE companies SET shares_out=? WHERE ticker=?", (new_shares, t))
                derived += 1
                print(f"{t:6}{'—':>10}{emcap/1e9:>9.1f}B{'':>8}  shares derived → {new_shares/1e9:.2f}B")
                con.execute("INSERT OR REPLACE INTO data_quality VALUES (?,?,?,?)",
                            (t, "mcap_xcheck", "derived", ""));
            continue
        ours = price * shares
        diff = ours / emcap - 1
        if abs(diff) <= 0.05:
            ok += 1; status, action = "ok", ""
        elif abs(diff) <= 0.15:
            drift += 1; status, action = "drift", ""
        else:
            bad += 1; status = "patched"
            new_shares = emcap / price if price else None
            if new_shares:
                con.execute("UPDATE companies SET shares_out=? WHERE ticker=?",
                            (new_shares, t))
                action = f"shares {shares/1e9:.2f}B → {new_shares/1e9:.2f}B"
            else:
                action = "no price — unpatched"
        if status != "ok":
            print(f"{t:6}{ours/1e9:>9.1f}B{emcap/1e9:>9.1f}B{diff*100:>7.1f}%  {action or status}")
        con.execute("INSERT OR REPLACE INTO data_quality VALUES (?,?,?,?)",
                    (t, "mcap_xcheck", status, f"{diff:+.3f}"))
    con.commit()
    print(f"\n{ok} ok (≤5%) · {drift} drift (5–15%) · {bad} patched (>15%) · "
          f"{derived} shares derived · {miss} no external quote")
    # Re-apply the universe mcap floors with the PATCHED share counts: an ADR whose
    # EDGAR count was missing/local-only had unknowable mcap at ingest time and was
    # floored out of the junction — the floor must see the verified denominators.
    try:
        from ingest_v1 import apply_floor
        apply_floor(con)
    except Exception as e:
        print(f"floor re-apply skipped ({e!r})")           # pre-Phase-4 DB (no raw table)
    con.close()


if __name__ == "__main__":
    main()
