"""Shared helpers for the valuation engines (stdlib only)."""
import sqlite3, sys, tomllib, urllib.request
from pathlib import Path

try:                              # Windows console is cp1252; our output uses β → · –
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE       = Path(__file__).resolve().parent
DB_PATH    = BASE / "data" / "fairvalue.db"
_TOML      = tomllib.load(open(BASE / "assumptions.toml", "rb"))
CFG        = _TOML["global"]
UCFG       = _TOML.get("universe", {"name": "Universe", "min_mcap": 0.0})
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def http_text(url, timeout=15):
    req = urllib.request.Request(url, headers=BROWSER_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_risk_free(retries=3):
    """Live 10Y UST from FRED's keyless CSV endpoint -> decimal. Retries, then falls back."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
    for _ in range(retries):
        try:
            last = None
            for line in http_text(url, timeout=12).strip().splitlines()[1:]:
                v = line.split(",")[-1].strip()
                if v and v != ".":
                    last = float(v)
            if last is not None:
                return last / 100.0, "FRED DGS10 (live)"
        except Exception:
            continue
    return CFG["risk_free_fallback"], "fallback (FRED unavailable)"


# ---------- db access ----------
def load_company(con, ticker):
    name, price = con.execute("SELECT name, price FROM companies WHERE ticker=?", (ticker,)).fetchone()
    fins = {}
    for concept, fy, val in con.execute(
            "SELECT concept, fiscal_year, value FROM financials WHERE ticker=?", (ticker,)):
        fins.setdefault(concept, {})[fy] = val
    return name, price, fins

def latest(series):
    return series[max(series)] if series else None

def cagr(series, years=5):
    if not series or len(series) < 2: return None
    yrs = sorted(series)
    a = yrs[0] if len(yrs) <= years else yrs[-1 - years]
    b = yrs[-1]
    # both endpoints must be positive — a negative ratio to a fractional power
    # yields a COMPLEX number (insurers can report negative annual revenue)
    if b - a <= 0 or series[a] <= 0 or series[b] <= 0: return None
    return (series[b] / series[a]) ** (1 / (b - a)) - 1

def avg_margin(ebit, revenue, years=7):
    """Mean operating margin over the most recent overlapping `years`."""
    common = sorted(set(ebit) & set(revenue))[-years:]
    ms = [ebit[y] / revenue[y] for y in common if revenue[y]]
    return sum(ms) / len(ms) if ms else None

def avg_roe(ni, equity, years=5):
    """Mean ROE over the most recent overlapping `years` (equity > 0 only)."""
    yrs = sorted(set(ni) & set(equity))[-years:]
    rs = [ni[y] / equity[y] for y in yrs if equity[y] > 0]
    return sum(rs) / len(rs) if rs else None

def effective_tax(tax_s, pretax_s, years=3, floor=0.10, cap=0.35, fallback=0.21):
    """Mean effective tax rate over recent overlapping years, clamped to [floor, cap].
       Years with non-positive pretax income or a net tax benefit are skipped (a loss
       year's 'rate' is meaningless); falls back to the statutory default when nothing
       is measurable."""
    yrs = sorted(set(tax_s) & set(pretax_s))[-years:]
    rs = [tax_s[y] / pretax_s[y] for y in yrs
          if pretax_s[y] and pretax_s[y] > 0 and tax_s[y] is not None and tax_s[y] > 0]
    if not rs:
        return fallback
    return max(floor, min(cap, sum(rs) / len(rs)))

def cost_of_debt(interest, debt, rf, spread, cap=0.15):
    """Effective Rd = interest expense / total borrowings, floored at rf+0.5% and
       capped (the ratio explodes when debt shrank mid-year). Falls back to
       rf + spread when interest expense or debt is unmeasurable."""
    if interest and debt and debt > 0 and interest > 0:
        return max(rf + 0.005, min(cap, interest / debt))
    return rf + spread


# ---------- shared DCF kernel ----------
def ev_present_value(fcf0, wacc, term_g, g1, horizon, stage1):
    """Enterprise PV of a 2-stage FCFF stream (explicit g1, linear fade to term_g, Gordon TV)."""
    pv, fcf = 0.0, fcf0
    for t in range(1, horizon + 1):
        g = g1 if t <= stage1 else g1 + (term_g - g1) * (t - stage1) / (horizon - stage1)
        fcf *= (1 + g)
        pv += fcf / (1 + wacc) ** t
    tv = fcf * (1 + term_g) / (wacc - term_g)
    return pv + tv / (1 + wacc) ** horizon


# ---------- formatting ----------
def money(v):
    if v is None: return "n/a"
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"

def pct(x):
    return "n/a" if x is None else f"{x*100:+.1f}%"
