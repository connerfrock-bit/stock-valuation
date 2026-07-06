"""
Historical index membership (survivorship-free universes for the backtest).
Walks BACKWARD from today's constituents, reversing each documented change
(back out adds, restore removes) from Wikipedia's change tables.

Universes:
  ndx    — Nasdaq-100 (default; legacy table names)
  sp500  — S&P 500 (value-rich: financials, energy, industrials → the real test)

python membership.py [ndx|sp500]
"""
import json, re, sqlite3, sys, time
from datetime import date
from common import DB_PATH, http_text
from universe import get_universe, _Tables

ALIASES = {"FB": "META", "FISV": "FI", "DISCA": "WBD", "RTN": "RTX", "CTRP": "TCOM"}
DUP_CLASSES = {"GOOG", "FOX", "NWS"}          # second share classes — one company, one signal

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

TICK_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")

GICS = {"Information Technology", "Communication Services", "Consumer Discretionary",
        "Consumer Staples", "Health Care", "Financials", "Industrials", "Energy",
        "Materials", "Real Estate", "Utilities"}


def norm(t):
    t = t.replace(".", "-").strip()
    return ALIASES.get(t, t)


def parse_date(s):
    m = re.match(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", s.strip())
    if not m or m.group(1) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def parse_changes(tables, min_rows=50):
    best, changes = 0, []
    for tbl in tables:
        rows = [r for r in tbl if r]
        if len(rows) < min_rows:
            continue
        out, cur_date = [], None
        for r in rows:
            cells = [c.strip() for c in r]
            d = parse_date(cells[0]) if cells else None
            if d:
                cur_date = d
                cells = cells[1:]
            if cur_date is None or not cells:
                continue
            ticks = [(i, c) for i, c in enumerate(cells) if TICK_RE.match(c)]
            add = rem = None
            for i, c in ticks:
                if add is None and i <= 1:
                    add = c
                elif rem is None and i >= 1:
                    rem = c
            if add or rem:
                out.append((cur_date, add, rem))
        if len(out) > best:
            best, changes = len(out), out
    return sorted(changes, key=lambda x: x[0], reverse=True)


def sp500_current(tables):
    """Constituents table -> [(ticker, sector)]. Identified by GICS sector column."""
    best = []
    for tbl in tables:
        rows = [r for r in tbl if r]
        out = []
        for r in rows:
            cells = [c.strip() for c in r]
            tick = next((c for c in cells[:2] if TICK_RE.match(c)), None)
            sec = next((c for c in cells if c in GICS), None)
            if tick and sec:
                out.append((tick, sec))
        if len(out) > len(best):
            best = out
    return best


def quarter_ends(start_year=2012, end=None):        # Plan B: 2015 → 2012 (XBRL floor ~2009)
    end = end or date.today()
    return [date(y, m, dd) for y in range(start_year, end.year + 1)
            for m, dd in [(3, 31), (6, 30), (9, 30), (12, 31)] if date(y, m, dd) < end]


def load_universe(key):
    """-> (current member set, {ticker: sector}, changes list, table suffix)."""
    if key == "ndx":
        current, src = get_universe()
        members = {norm(t) for t, _, _ in current} - DUP_CLASSES
        sectors = {norm(t): s for t, _, s in current}
        html = http_text("https://en.wikipedia.org/wiki/Nasdaq-100", timeout=25)
        p = _Tables(); p.feed(html)
        return members, sectors, parse_changes(p.tables), "", src
    if key == "sp500":
        html = http_text("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", timeout=25)
        p = _Tables(); p.feed(html)
        cur = sp500_current(p.tables)
        if len(cur) < 450:
            raise SystemExit(f"S&P constituents parse failed ({len(cur)} rows)")
        members = {norm(t) for t, _ in cur} - DUP_CLASSES
        sectors = {norm(t): s for t, s in cur}
        return members, sectors, parse_changes(p.tables), "_sp500", "Wikipedia (live)"
    raise SystemExit(f"unknown universe {key!r}")


def main(key):
    members, sectors, changes, suf, src = load_universe(key)
    print(f"[{key}] current members: {len(members)} [{src}]")
    print(f"[{key}] parsed {len(changes)} changes ({changes[-1][0]} → {changes[0][0]})")

    # Plan 7 parse-drift guard: a Wikipedia table-format change shows up as a shrunken
    # parse — warn against the last known-good counts before overwriting anything.
    mc_path = DB_PATH.parent / "membership_cache.json"
    try:
        mcache = json.loads(mc_path.read_text(encoding="utf-8"))
    except Exception:
        mcache = {}
    prev = mcache.get(key)
    if prev and (len(members) < prev["members"] * 0.9 or len(changes) < prev["changes"] * 0.9):
        print(f"⚠ [{key}] parse SHRANK vs {prev['date']}: members {prev['members']}→{len(members)}, "
              f"changes {prev['changes']}→{len(changes)} — check Wikipedia's table format")
    mcache[key] = {"members": len(members), "changes": len(changes),
                   "date": date.today().isoformat()}
    mc_path.write_text(json.dumps(mcache), encoding="utf-8")

    snaps, anomalies, cur, ci = {}, [], set(members), 0
    today = date.today()
    for q in sorted(quarter_ends(), reverse=True):
        while ci < len(changes) and changes[ci][0] > q:
            d, add, rem = changes[ci]
            if d <= today:
                a = norm(add) if add else None
                r = norm(rem) if rem else None
                if a and a not in DUP_CLASSES:
                    if a in cur:
                        cur.discard(a)
                    else:
                        anomalies.append(f"{d} back-out add {a}: not in set")
                if r and r not in DUP_CLASSES:
                    if r not in cur:
                        cur.add(r)
                    else:
                        anomalies.append(f"{d} restore {r}: already in set")
            ci += 1
        snaps[q] = set(cur)

    con = sqlite3.connect(DB_PATH)
    con.executescript(f"""
    DROP TABLE IF EXISTS membership{suf};
    CREATE TABLE membership{suf}(qdate TEXT, ticker TEXT, PRIMARY KEY (qdate, ticker));
    DROP TABLE IF EXISTS sectors{suf};
    CREATE TABLE sectors{suf}(ticker TEXT PRIMARY KEY, sector TEXT);
    """)
    for q, s in snaps.items():
        con.executemany(f"INSERT INTO membership{suf} VALUES (?,?)",
                        [(q.isoformat(), t) for t in sorted(s)])
    con.executemany(f"INSERT OR REPLACE INTO sectors{suf} VALUES (?,?)",
                    list(sectors.items()))
    con.commit()

    all_names = sorted({t for s in snaps.values() for t in s})
    print(f"[{key}] snapshots: {len(snaps)} ({min(snaps)} → {max(snaps)}); "
          f"sizes {min(len(s) for s in snaps.values())}–{max(len(s) for s in snaps.values())}")
    print(f"[{key}] distinct names: {len(all_names)} "
          f"({len(set(all_names) - members)} past members)")
    if anomalies:
        print(f"⚠ {len(anomalies)} walk-back anomalies (first 8):")
        for a in anomalies[:8]:
            print("   ", a)
    (DB_PATH.parent / f"membership_names{suf}.txt").write_text("\n".join(all_names))
    print(f"Wrote membership{suf} + sectors{suf} + membership_names{suf}.txt "
          f"({time.strftime('%H:%M:%S')})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ndx")
