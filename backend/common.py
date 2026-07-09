"""Shared helpers for the valuation engines (stdlib only)."""
import json, sqlite3, sys, time, tomllib, urllib.error, urllib.request
from pathlib import Path

try:                              # Windows console is cp1252; our output uses β → · –
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE       = Path(__file__).resolve().parent
DB_PATH    = BASE / "data" / "fairvalue.db"
_TOML      = tomllib.load(open(BASE / "assumptions.toml", "rb"))
CFG        = _TOML["global"]
# L5/L6 manual overrides (Phase 1.3): {"archetype": {ticker: arch}, "subsector": {ticker: bucket}}
OVERRIDES  = _TOML.get("overrides", {})
# SIC → subsector default layer (Phase 2): fires for IT names with no hand-map entry.
SUBSECTOR_BY_SIC = _TOML.get("subsector_by_sic", {})

# Live-screener universes (Plan A). [[universe]] array keyed by id; ACTIVE is the default
# for the bare output.json/ledger.json artifacts.
UNIVERSES  = {u["id"]: u for u in _TOML.get("universe", [])} or \
             {"ndx": {"id": "ndx", "name": "Nasdaq-100", "source": "ndx", "min_mcap": 15e9}}
ACTIVE     = _TOML.get("active_universe", next(iter(UNIVERSES)))

def resolve_universe(uid):
    """Universe config by id -> {id, name, source, min_mcap}. Unknown id falls back to ACTIVE."""
    return UNIVERSES.get(uid, UNIVERSES[ACTIVE])

UCFG       = resolve_universe(ACTIVE)                 # back-compat: the active universe's config
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SEC_UA     = {"User-Agent": "FairValue research conner.frock@gmail.com"}  # SEC requires a descriptive UA


def http_text(url, timeout=15):
    req = urllib.request.Request(url, headers=BROWSER_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_json(url, headers=None, timeout=25, retries=4):
    """GET JSON with exponential backoff on throttling/transient errors. At universe
       scale (~500 names) EDGAR intermittently 429s a contiguous burst — without a
       retry those names silently vanished from the screener."""
    headers = headers or SEC_UA
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502, 504) and attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt)); continue
            raise


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

def roe_stability(ni, equity, years=6, min_obs=3):
    """Stdev of annual ROE over the last `years` overlapping FYs (equity > 0 only).
       Lower = steadier bank/insurer earnings power; None below `min_obs` observations."""
    yrs = sorted(set(ni) & set(equity))[-years:]
    rs = [ni[y] / equity[y] for y in yrs if equity[y] > 0]
    if len(rs) < min_obs:
        return None
    m = sum(rs) / len(rs)
    return (sum((x - m) ** 2 for x in rs) / len(rs)) ** 0.5

def equity_to_assets(equity, assets, years=3):
    """Mean equity/assets over the last `years` overlapping FYs — the capital cushion.
       The honest leverage measure for balance-sheet businesses (banks/insurers/REITs),
       where net-debt/EBITDA is meaningless."""
    yrs = sorted(set(equity) & set(assets))[-years:]
    rs = [equity[y] / assets[y] for y in yrs if assets[y] > 0]
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

def size_premium(mcap, bands):
    """Incremental cost-of-equity premium for smaller companies (added to rf + beta·ERP).
       bands = [[min_mcap, premium], ...]; returns the premium of the first band (largest
       min_mcap first) whose threshold mcap clears. 0 when no bands or no mcap. CRSP-decile
       size premia scaled down — beta already captures part of the small-cap effect."""
    if not mcap or not bands:
        return 0.0
    for min_mcap, prem in sorted(bands, key=lambda b: -b[0]):
        if mcap >= min_mcap:
            return prem
    return 0.0


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


REINVEST_CAP = 0.90        # reinvestment can't exceed 90% of NOPAT — stream stays FCF-positive

def ev_present_value_nopat(nopat0, roic, wacc, term_g, g1, horizon, stage1):
    """Enterprise PV of a value-DRIVER FCFF stream (McKinsey form): each year's FCFF is
       normalized NOPAT grown at g_t MINUS the reinvestment that growth requires,
       rr = g/ROIC. Reinvestment falls as growth fades to term_g, so a heavy reinvestor is
       no longer valued as if its depressed current FCF margin were permanent (the Amazon
       problem: trailing FCF-margin × revenue counts growth capex as if it were lost cash).
       rr is clamped to [0, REINVEST_CAP] so the stream stays FCF-positive and a low-ROIC,
       high-growth name can't imply a negative perpetual cash flow. ROIC must be > 0 and
       wacc − term_g > 0 (caller-guarded)."""
    pv, nopat = 0.0, nopat0
    for t in range(1, horizon + 1):
        g = g1 if t <= stage1 else g1 + (term_g - g1) * (t - stage1) / (horizon - stage1)
        nopat *= (1 + g)
        rr = max(0.0, min(REINVEST_CAP, g / roic))
        pv += nopat * (1 - rr) / (1 + wacc) ** t
    rr_t = max(0.0, min(REINVEST_CAP, term_g / roic))
    tv = nopat * (1 + term_g) * (1 - rr_t) / (wacc - term_g)
    return pv + tv / (1 + wacc) ** horizon


# ---------- formatting ----------
def money(v):
    if v is None: return "n/a"
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"

def pct(x):
    return "n/a" if x is None else f"{x*100:+.1f}%"
