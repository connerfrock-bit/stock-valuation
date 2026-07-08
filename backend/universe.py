"""
Nasdaq-100 constituent list (L0). Pulls the live components table from Wikipedia
(ticker + GICS sector). Robustness (Plan 7): every good parse is cached to disk;
on Wikipedia failure the cache is used (a stale-but-real list beats the 50-name
built-in); abnormal churn vs the cache warns loudly (parse-drift detector).
stdlib only.  python universe.py  to inspect.
"""
import json, re, time
from html.parser import HTMLParser
from pathlib import Path
from common import http_text

CACHE = Path(__file__).resolve().parent / "data" / "universe_cache.json"

# Wikipedia's components table uses ICB industry names — map them to our sector scheme.
ICB_MAP = {
    "Technology": "Information Technology", "Telecommunications": "Communication Services",
    "Consumer Discretionary": "Consumer Discretionary", "Consumer Staples": "Consumer Staples",
    "Health Care": "Health Care", "Industrials": "Industrials", "Financials": "Financials",
    "Energy": "Energy", "Utilities": "Utilities", "Basic Materials": "Materials",
    "Real Estate": "Real Estate",
}

# Fallback: verified Nasdaq-100 names (from the design prototype) — used only if Wikipedia fails.
FALLBACK = [
    ("AAPL", "Apple", "Information Technology"), ("MSFT", "Microsoft", "Information Technology"),
    ("NVDA", "NVIDIA", "Information Technology"), ("AMZN", "Amazon", "Consumer Discretionary"),
    ("GOOGL", "Alphabet", "Communication Services"), ("META", "Meta Platforms", "Communication Services"),
    ("AVGO", "Broadcom", "Information Technology"), ("TSLA", "Tesla", "Consumer Discretionary"),
    ("COST", "Costco", "Consumer Staples"), ("NFLX", "Netflix", "Communication Services"),
    ("PEP", "PepsiCo", "Consumer Staples"), ("ADBE", "Adobe", "Information Technology"),
    ("CSCO", "Cisco", "Information Technology"), ("AMD", "AMD", "Information Technology"),
    ("TMUS", "T-Mobile US", "Communication Services"), ("INTC", "Intel", "Information Technology"),
    ("QCOM", "Qualcomm", "Information Technology"), ("TXN", "Texas Instruments", "Information Technology"),
    ("AMAT", "Applied Materials", "Information Technology"), ("INTU", "Intuit", "Information Technology"),
    ("ISRG", "Intuitive Surgical", "Health Care"), ("BKNG", "Booking Holdings", "Consumer Discretionary"),
    ("HON", "Honeywell", "Industrials"), ("AMGN", "Amgen", "Health Care"),
    ("VRTX", "Vertex Pharma", "Health Care"), ("GILD", "Gilead Sciences", "Health Care"),
    ("REGN", "Regeneron", "Health Care"), ("PANW", "Palo Alto Networks", "Information Technology"),
    ("LRCX", "Lam Research", "Information Technology"), ("MU", "Micron", "Information Technology"),
    ("ADI", "Analog Devices", "Information Technology"), ("KLAC", "KLA Corp", "Information Technology"),
    ("SBUX", "Starbucks", "Consumer Discretionary"), ("MDLZ", "Mondelez", "Consumer Staples"),
    ("ADP", "Automatic Data", "Industrials"), ("GEHC", "GE HealthCare", "Health Care"),
    ("MELI", "MercadoLibre", "Consumer Discretionary"), ("CRWD", "CrowdStrike", "Information Technology"),
    ("CDNS", "Cadence", "Information Technology"), ("SNPS", "Synopsys", "Information Technology"),
    ("MAR", "Marriott", "Consumer Discretionary"), ("ORLY", "O'Reilly Auto", "Consumer Discretionary"),
    ("CTAS", "Cintas", "Industrials"), ("PYPL", "PayPal", "Financials"),
    ("PDD", "PDD Holdings", "Consumer Discretionary"), ("ABNB", "Airbnb", "Consumer Discretionary"),
    ("WDAY", "Workday", "Information Technology"), ("FTNT", "Fortinet", "Information Technology"),
    ("DDOG", "Datadog", "Information Technology"),
]


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._cell, self._in = [], None, False
    def handle_starttag(self, tag, attrs):
        if tag == "table": self.tables.append([])
        elif tag == "tr" and self.tables: self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables and self.tables[-1]:
            self._in, self._cell = True, []
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in:
            self.tables[-1][-1].append("".join(self._cell).strip()); self._in = False
    def handle_data(self, data):
        if self._in: self._cell.append(data)


def from_wikipedia():
    html = http_text("https://en.wikipedia.org/wiki/Nasdaq-100", timeout=25)
    p = _Tables(); p.feed(html)
    for tbl in p.tables:
        rows = [r for r in tbl if r]
        if not rows:
            continue
        hdr = [c.lower() for c in rows[0]]
        if len(hdr) >= 3 and hdr[0] == "ticker" and "company" in hdr[1]:   # the components table
            out = []
            for r in rows[1:]:
                if len(r) >= 3 and re.fullmatch(r"[A-Z.]{1,6}", r[0]):
                    out.append((r[0], r[1], ICB_MAP.get(r[2], r[2])))
            if len(out) >= 90:
                return out
    return []


def get_universe():
    cached = None
    if CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cached = None
    u = []
    try:
        u = from_wikipedia()
    except Exception as e:
        print(f"  ! Wikipedia fetch failed ({e!r})")
    if len(u) >= 90:
        if cached:
            churn = {t for t, _, _ in cached["names"]} ^ {t for t, _, _ in u}
            if len(churn) > max(8, len(cached["names"]) // 10):
                print(f"  ⚠ universe churn vs cache {cached['date']}: {len(churn)} names "
                      f"({', '.join(sorted(churn)[:10])}…) — verify the Wikipedia parse")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "names": u}),
                         encoding="utf-8")
        return u, "Wikipedia (live)"
    if cached and len(cached.get("names", [])) >= 90:
        return [tuple(x) for x in cached["names"]], f"cache ({cached['date']})"
    return FALLBACK, "built-in fallback"


# ---------------- S&P 500 constituents (Plan A live universe) ----------------
GICS = {"Information Technology", "Communication Services", "Consumer Discretionary",
        "Consumer Staples", "Health Care", "Financials", "Industrials", "Energy",
        "Utilities", "Materials", "Real Estate"}
SP500_CACHE = CACHE.parent / "universe_cache_sp500.json"


def _sp_from_wikipedia(url):
    """[(ticker, name, GICS-sector)] from any S&P components table (500/400/600 share
       the same shape). Columns: Symbol · Security · GICS Sector · … — identified by a
       GICS sector cell; the company name is the column right after the Symbol."""
    html = http_text(url, timeout=25)
    p = _Tables(); p.feed(html)
    best = []
    for tbl in p.tables:
        out = []
        for r in [r for r in tbl if r]:
            cells = [c.strip() for c in r]
            ti = next((i for i, c in enumerate(cells[:2])
                       if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", c)), None)
            sec = next((c for c in cells if c in GICS), None)
            if ti is None or not sec:
                continue
            tick = cells[ti]
            name = cells[ti + 1] if ti + 1 < len(cells) and cells[ti + 1] != sec else tick
            out.append((tick.replace(".", "-"), name, sec))
        if len(out) > len(best):
            best = out
    return best


def sp500_from_wikipedia():
    return _sp_from_wikipedia("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")


# S&P components: (Wikipedia URL, minimum plausible parse count, cache file). The
# 400/600 pages share the S&P 500 table shape, so one parser serves all three.
SP_INDEXES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 450, SP500_CACHE),
    "sp400": ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", 350,
              CACHE.parent / "universe_cache_sp400.json"),
    "sp600": ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", 550,
              CACHE.parent / "universe_cache_sp600.json"),
}


def _sp_constituents(uid):
    """Live S&P 400/500/600 with a cache fallback + churn guard (get_universe honesty)."""
    url, floor, cache_path = SP_INDEXES[uid]
    cached = None
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cached = None
    u = []
    try:
        u = _sp_from_wikipedia(url)
    except Exception as e:
        print(f"  ! {uid} fetch failed ({e!r})")
    if len(u) >= floor:
        if cached:
            churn = {t for t, _, _ in cached["names"]} ^ {t for t, _, _ in u}
            if len(churn) > max(20, len(cached["names"]) // 10):
                print(f"  ⚠ {uid} churn vs cache {cached['date']}: {len(churn)} names — verify parse")
        cache_path.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "names": u}),
                              encoding="utf-8")
        return u, "Wikipedia (live)"
    if cached and len(cached.get("names", [])) >= floor:
        return [tuple(x) for x in cached["names"]], f"cache ({cached['date']})"
    raise SystemExit(f"{uid} constituents unavailable (no live parse, no cache)")


def sp500_constituents():
    return _sp_constituents("sp500")


def sp1500_constituents():
    """S&P Composite 1500 = 500 (large) ∪ 400 (mid) ∪ 600 (small), deduped by ticker
       (large-cap name/sector wins on the rare cross-listing). ~1500 names — the broad
       screening universe where mid/small-cap cross-sectional value evidence lives."""
    seen, out, srcs = {}, [], []
    for uid in ("sp500", "sp400", "sp600"):
        lst, src = _sp_constituents(uid)
        srcs.append(f"{uid}:{len(lst)}")
        for tk, nm, sec in lst:
            if tk not in seen:
                seen[tk] = True
                out.append((tk, nm, sec))
    return out, f"Wikipedia ({' + '.join(srcs)})"


def load_constituents(uid):
    """Dispatch by universe id -> ([(ticker, name, sector)], source)."""
    if uid == "ndx":
        return get_universe()
    if uid == "sp1500":
        return sp1500_constituents()
    if uid in SP_INDEXES:
        return _sp_constituents(uid)
    raise SystemExit(f"unknown universe id {uid!r}")


# Universes whose sector column is authoritative GICS (vs the Nasdaq page's coarse ICB
# mapping, which mislabels e.g. PayPal as Industrials). GICS wins for overlap names.
GICS_SOURCES = {"sp500", "sp400", "sp600", "sp1500"}


def build_union(uids):
    """Merge several universes into one ingest list, deduped by ticker, recording each
       ticker's set of universes. -> (rows [(ticker,name,sector)], membership {ticker:set(uid)}, srcs).
       First universe to name a ticker wins name; GICS sources override ICB-mapped sectors."""
    rows, membership, srcs, sec_src = {}, {}, {}, {}
    for uid in uids:
        lst, src = load_constituents(uid)
        srcs[uid] = f"{len(lst)} [{src}]"
        for tk, nm, sec in lst:
            if tk not in rows:
                rows[tk] = (tk, nm, sec); sec_src[tk] = uid
            elif uid in GICS_SOURCES and sec_src.get(tk) not in GICS_SOURCES:
                rows[tk] = (rows[tk][0], rows[tk][1], sec); sec_src[tk] = uid   # GICS wins
            membership.setdefault(tk, set()).add(uid)
    return list(rows.values()), membership, srcs


if __name__ == "__main__":
    u, src = get_universe()
    print(f"Nasdaq-100: {len(u)} names  [{src}]")
    s, ssrc = sp500_constituents()
    print(f"S&P 500:    {len(s)} names  [{ssrc}]")
    rows, mem, srcs = build_union(["ndx", "sp500"])
    print(f"Union:      {len(rows)} distinct  · sources {srcs}")
