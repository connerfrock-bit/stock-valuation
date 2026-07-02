"""Valuation engines (VALUATION_DEFAULTS_SPEC). Each returns a fair value PER SHARE,
except reverse_dcf which returns the market-IMPLIED growth. stdlib only."""
import random, statistics
from common import CFG, ev_present_value


def cost_of_equity(rf, beta, erp):
    return rf + beta * erp

def wacc_of(equity, debt, re_, rd, tax):
    v = equity + debt
    return (equity / v * re_ + debt / v * rd * (1 - tax)) if v > 0 else re_


# ---------- §3 Reverse DCF (the anchor) ----------
def reverse_dcf(fcf0, wacc, term_g, net_debt, target_equity, H, S1, lo=-0.30, hi=0.80):
    if fcf0 is None or fcf0 <= 0 or wacc - term_g < CFG["min_wacc_minus_g"]:
        return None, None
    eq = lambda g: ev_present_value(fcf0, wacc, term_g, g, H, S1) - net_debt
    if eq(lo) > target_equity: return lo, "<"
    if eq(hi) < target_equity: return hi, ">"
    for _ in range(64):
        mid = (lo + hi) / 2
        if eq(mid) > target_equity: hi = mid
        else: lo = mid
    return (lo + hi) / 2, "="


# ---------- §2 DCF (multi-stage, Monte Carlo) ----------
def dcf(fcf0, wacc, term_g, net_debt, shares, g1, H, S1, draws=3000, seed=0):
    """Returns P10/P50/P90 fair value per share from a Monte Carlo over g1, WACC, terminal g."""
    if fcf0 is None or fcf0 <= 0 or not shares:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        gg = rng.triangular(g1 - 0.03, g1 + 0.03, g1)
        ww = max(rng.gauss(wacc, 0.01), term_g + CFG["min_wacc_minus_g"])
        tg = min(rng.triangular(term_g - 0.005, term_g + 0.005, term_g),
                 ww - CFG["min_wacc_minus_g"])
        ev = ev_present_value(fcf0, ww, tg, gg, H, S1)
        out.append((ev - net_debt) / shares)
    out.sort()
    q = lambda p: out[int(p * (len(out) - 1))]
    return {"p10": q(0.10), "p50": q(0.50), "p90": q(0.90)}


# ---------- §5 EPV (Earnings Power Value — no-growth floor) ----------
def epv(norm_ebit, tax, wacc, cash, debt, shares, dna=None, capex=None):
    if norm_ebit is None or norm_ebit <= 0 or not shares:
        return None
    nopat = norm_ebit * (1 - tax)
    adj = (dna - min(capex, dna)) if (dna is not None and capex is not None) else 0.0
    epv_ops = (nopat + adj) / wacc
    return (epv_ops + cash - debt) / shares


# ---------- §4 RIM — Residual Income (Ohlson, persistence ω) ----------
def rim(book_ps, roe, re_, H, omega=0.62):
    """Book value + PV of residual income, RI decaying by ω each year (Ohlson AR(1))
       plus a decaying continuing value. Applicability (neg / buyback-distorted book)
       is gated by the caller — the L5 router, not here."""
    ri, pv = (roe - re_) * book_ps, 0.0
    for t in range(1, H + 1):
        pv += ri / (1 + re_) ** t
        ri *= omega                       # excess returns compete away
    tv = ri / (1 + re_ - omega)           # ri is now RI_{H+1}; decaying perpetuity
    return book_ps + pv + tv / (1 + re_) ** H


# ---------- §6-alt Warranted multiple v2 (sector-anchored regression) ----------
# Replaces DDM for this universe (VALUATION_DEFAULTS_SPEC §6 note). v1 regressed the
# whole cross-section and its coefficients absorbed SECTOR COMPOSITION (+β from rich
# semis, −margin from cheap cash cows) — inflating names like CMCSA. v2 anchors each
# company to its SECTOR mean multiple and only adjusts for within-sector growth/margin
# differences, with sign-guarded coefficients (economic prior: both raise the multiple).

def ols(X, y):
    """Least squares via normal equations + Gaussian elimination. -> coeffs or None."""
    n, k = len(X), len(X[0])
    if n <= k:
        return None
    XtX = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    Xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    A = [XtX[i] + [Xty[i]] for i in range(k)]
    for col in range(k):                                  # partial pivoting
        piv = max(range(col, k), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-10:
            return None
        A[col], A[piv] = A[piv], A[col]
        for r in range(k):
            if r != col:
                f = A[r][col] / A[col][col]
                A[r] = [a - f * b for a, b in zip(A[r], A[col])]
    return [A[i][k] / A[i][i] for i in range(k)]


def _wclamp(y, g, m):
    return (max(5.0, min(60.0, y)), max(0.0, min(0.30, g)), max(0.0, min(0.60, m)))


def warranted_fit(rows, min_sector=3):
    """rows: (sector, ev_ebit, growth, margin). Fixed-effects fit: center within sector
       (global anchors for sectors with < min_sector names), regress the residual multiple
       on centered growth/margin, zero any coefficient that violates the economic prior.
       Anchors are MEDIANS — a mean anchor gets dragged by the winsorize-capped rich tail
       (semis at 60×) and then inflates every name that falls back to the global anchor.
       -> (sector_medians, global_medians, coefs)"""
    data = [(s,) + _wclamp(y, g, m) for s, y, g, m in rows]
    if not data:
        return None
    # Anchor cap: a "warranted" multiple must not inherit market froth — when the whole
    # universe trades above ~28× EV/EBIT (3.5% earnings yield), the anchor stays at 28.
    ANCHOR_CAP = 28.0
    med = lambda v: statistics.median(v)
    cap = lambda t: (min(t[0], ANCHOR_CAP),) + t[1:]
    cols = list(zip(*[(y, g, m) for _, y, g, m in data]))
    gmed = cap(tuple(med(list(c)) for c in cols))
    by = {}
    for s, y, g, m in data:
        by.setdefault(s, []).append((y, g, m))
    smeds = {s: cap(tuple(med(list(c)) for c in zip(*v)))
             for s, v in by.items() if len(v) >= min_sector}
    X, Y = [], []
    for s, y, g, m in data:
        my, mg, mm = smeds.get(s, gmed)
        X.append([g - mg, m - mm]); Y.append(y - my)
    coef = ols(X, Y) or [0.0, 0.0]
    coef = [max(0.0, c) for c in coef]                    # sign guard (prior: positive)
    return smeds, gmed, coef


def warranted_value(fit, sector, g, margin, ebit, cash, debt, shares):
    """Sector-anchored 'justified' EV/EBIT applied to this company's EBIT -> $/share."""
    if not fit or ebit is None or ebit <= 0 or not shares:
        return None
    smeans, gmean, coef = fit
    my, mg, mm = smeans.get(sector, gmean)
    _, gc, mc = _wclamp(0, g, margin)
    mult = my + coef[0] * (gc - mg) + coef[1] * (mc - mm)
    mult = max(4.0, min(40.0, mult))
    return (mult * ebit - debt + cash) / shares


# ---------- §L8 Triangulate -> range + confidence ----------
# EPV is a no-growth FLOOR, not a central estimate — it sets the low bound and is shown
# separately, never averaged into the mid. The mid is a weight-blended central value from
# the growth-aware engines; agreement is measured among those engines only.
CENTRAL_WEIGHTS = {"DCF": 0.25, "RIM": 0.20, "Warranted": 0.25, "DDM": 0.10}

def triangulate(growth, floor, price):
    """growth: {engine_name: per-share value} for applicable growth engines.
       floor:  EPV per-share value (or None)."""
    g  = {k: v for k, v in growth.items() if v is not None and v > 0}
    fl = floor if (floor is not None and floor > 0) else None
    if not g and fl is None:
        return None
    if g:
        tw  = sum(CENTRAL_WEIGHTS.get(k, 0.10) for k in g)
        mid = sum(v * CENTRAL_WEIGHTS.get(k, 0.10) for k, v in g.items()) / tw
    else:
        mid = fl                          # only the floor is available
    allvals    = list(g.values()) + ([fl] if fl else [])
    low, high  = min(allvals), max(allvals)
    within     = sum(1 for v in g.values() if abs(v / mid - 1) <= 0.10)
    n          = len(g)
    frac       = within / n if n else 0
    conf = (2 if n < 2 else               # a single engine can't demonstrate agreement
            5 if frac >= 0.99 else 4 if frac >= 0.66 else 3 if frac >= 0.5 else 2)
    return {"low": low, "mid": mid, "high": high, "upside": mid / price - 1,
            "within": within, "n": n, "conf": conf, "floor": fl}
