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


if __name__ == "__main__":
    u, src = get_universe()
    print(f"Universe: {len(u)} names  [{src}]\n")
    for tk, nm, sc in u:
        print(f"  {tk:6} {sc:24} {nm}")
