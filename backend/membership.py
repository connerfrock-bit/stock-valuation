"""
Historical Nasdaq-100 membership (survivorship-free universe for the backtest).
Parses Wikipedia's documented changes table and walks BACKWARD from today's
membership, reversing each change (back out adds, restore removes). Quarter-end
snapshots land in the `membership` table; anomalies are logged, not hidden.
stdlib only.   python membership.py
"""
import re, sqlite3, time
from datetime import date
from common import DB_PATH, http_text
from universe import get_universe, _Tables

# Renames/mergers so old tickers match modern price/EDGAR symbols where possible.
ALIASES = {"FB": "META", "FISV": "FI", "DISCA": "WBD", "RTN": "RTX", "CTRP": "TCOM"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

TICK_RE = re.compile(r"^[A-Z]{1,5}$")


def parse_date(s):
    m = re.match(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", s.strip())
    if not m or m.group(1) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def fetch_changes():
    """-> [(date, added_ticker|None, removed_ticker|None)], newest data first or not — we sort."""
    html = http_text("https://en.wikipedia.org/wiki/Nasdaq-100", timeout=25)
    p = _Tables(); p.feed(html)
    best, changes = 0, []
    for tbl in p.tables:
        rows = [r for r in tbl if r]
        if len(rows) < 50:
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
            # remaining layout: [addT, addName, remT, remName, (reason)] with gaps possible
            ticks = [(i, c) for i, c in enumerate(cells) if TICK_RE.match(c)]
            add = rem = None
            for i, c in ticks:
                # heuristic: first ticker column is the addition, later one the removal
                if add is None and i <= 1:
                    add = c
                elif rem is None and i >= 1:
                    rem = c
            if add or rem:
                out.append((cur_date, add, rem))
        if len(out) > best:
            best, changes = len(out), out
    return sorted(changes, key=lambda x: x[0], reverse=True)   # newest first


def quarter_ends(start_year=2015, end=None):
    end = end or date.today()
    out = []
    for y in range(start_year, end.year + 1):
        for m, dd in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            q = date(y, m, dd)
            if q < end:
                out.append(q)
    return out


def main():
    current, src = get_universe()
    members = {ALIASES.get(t, t) for t, _, _ in current}
    # GOOG/GOOGL are one company — track once
    members.discard("GOOG")
    print(f"Current members: {len(members)} [{src}]")

    changes = fetch_changes()
    print(f"Parsed {len(changes)} membership changes "
          f"({changes[-1][0]} → {changes[0][0]})")

    snaps = sorted(quarter_ends(), reverse=True)   # newest first, walk back
    snapshots, anomalies = {}, []
    ci = 0
    cur = set(members)
    today = date.today()
    # changes newest-first; reverse them as we cross each date going backward
    for q in snaps:
        while ci < len(changes) and changes[ci][0] > q:
            d, add, rem = changes[ci]
            if d <= today:
                a = ALIASES.get(add, add) if add else None
                r = ALIASES.get(rem, rem) if rem else None
                if a:
                    if a in cur:
                        cur.discard(a)             # back out the addition
                    else:
                        anomalies.append(f"{d} back-out add {a}: not in set")
                if r:
                    if r not in cur:
                        cur.add(r)                 # restore the removal
                    else:
                        anomalies.append(f"{d} restore {r}: already in set")
            ci += 1
        snapshots[q] = set(cur)

    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    DROP TABLE IF EXISTS membership;
    CREATE TABLE membership(qdate TEXT, ticker TEXT, PRIMARY KEY (qdate, ticker));
    """)
    for q, s in snapshots.items():
        con.executemany("INSERT INTO membership VALUES (?,?)",
                        [(q.isoformat(), t) for t in sorted(s)])
    con.commit()

    all_names = sorted({t for s in snapshots.values() for t in s})
    print(f"\nQuarter-end snapshots: {len(snapshots)} "
          f"({min(snapshots)} → {max(snapshots)})")
    for q in sorted(snapshots)[::4]:
        print(f"  {q}: {len(snapshots[q])} members")
    print(f"Distinct names across history: {len(all_names)} "
          f"({len(set(all_names) - members)} past members no longer in the index)")
    if anomalies:
        print(f"\n⚠ {len(anomalies)} parse anomalies (walk-back inconsistencies):")
        for a in anomalies[:10]:
            print("   ", a)
        print("   → these quarters may be slightly off; coverage stats will show impact.")
    (DB_PATH.parent / "membership_names.txt").write_text("\n".join(all_names))
    print(f"\nWrote membership table + membership_names.txt ({time.strftime('%H:%M:%S')})")


if __name__ == "__main__":
    main()
