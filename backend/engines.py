"""Valuation engines (VALUATION_DEFAULTS_SPEC). Each returns a fair value PER SHARE,
except reverse_dcf which returns the market-IMPLIED growth. stdlib only."""
import statistics
from common import CFG, ev_present_value, ev_present_value_nopat


def cost_of_equity(rf, beta, erp, size_prem=0.0):
    return rf + beta * erp + size_prem


def _dcf_ev(fcf0, wacc, term_g, g1, H, S1, nopat0, roic):
    """Enterprise PV via the value-driver kernel (normalized NOPAT − g/ROIC reinvestment)
       when a positive NOPAT base + ROIC are supplied, else the trailing-FCF kernel.
       -> EV, or None when neither base is usable."""
    if nopat0 is not None and roic is not None and nopat0 > 0 and roic > 0:
        return ev_present_value_nopat(nopat0, roic, wacc, term_g, g1, H, S1)
    if fcf0 is not None and fcf0 > 0:
        return ev_present_value(fcf0, wacc, term_g, g1, H, S1)
    return None

def wacc_of(equity, debt, re_, rd, tax):
    v = equity + debt
    return (equity / v * re_ + debt / v * rd * (1 - tax)) if v > 0 else re_


# ---------- §3 Reverse DCF (the anchor) ----------
def reverse_dcf(fcf0, wacc, term_g, net_debt, target_equity, H, S1, lo=-0.30, hi=0.80,
                nopat0=None, roic=None):
    """Solve for the growth today's price implies. Uses the same value-driver base as the
       forward DCF when NOPAT + ROIC are supplied (so a heavy reinvestor's implied growth
       is no longer inflated by a depressed FCF base), else the trailing-FCF base."""
    if wacc - term_g < CFG["min_wacc_minus_g"]:
        return None, None
    # On the value-driver base, growth only CREATES value when ROIC > WACC; at ROIC ≤ WACC
    # the EV(g) curve isn't monotone (capped reinvestment makes it fall then rise), so
    # "what growth justifies today's price" is degenerate — report n/a rather than a number
    # bisection happened to land on.
    if nopat0 is not None and roic is not None and nopat0 > 0 and roic > 0 and roic <= wacc:
        return None, None
    def eq(g):
        ev = _dcf_ev(fcf0, wacc, term_g, g, H, S1, nopat0, roic)
        return None if ev is None else ev - net_debt
    e_lo, e_hi = eq(lo), eq(hi)
    if e_lo is None or e_hi is None:                     # no usable base
        return None, None
    if e_hi <= e_lo:                                     # defensive: any residual non-monotone
        return None, None                                # endpoint inversion → n/a
    if e_lo > target_equity: return lo, "<"
    if e_hi < target_equity: return hi, ">"
    for _ in range(64):
        mid = (lo + hi) / 2
        if eq(mid) > target_equity: hi = mid
        else: lo = mid
    return (lo + hi) / 2, "="


# ---------- §2 DCF (multi-stage, deterministic) ----------
# The Monte Carlo variant was removed (Plan 3): it perturbed g1/WACC/terminal-g in a
# narrow band around the point estimate but never the FCF base — the dominant
# uncertainty — so its P50 tracked the deterministic value while implying a rigor the
# backtest never rewarded (DCF degraded most of all engines). The honest range is L8's.
def dcf(fcf0, wacc, term_g, net_debt, shares, g1, H, S1, nopat0=None, roic=None):
    """Deterministic 2-stage FCFF DCF -> fair value per share (None when inapplicable).
       Prefers the value-driver base (normalized NOPAT − g/ROIC reinvestment) when a
       positive NOPAT + ROIC are supplied; falls back to trailing normalized FCF."""
    if not shares:
        return None
    if wacc - term_g < CFG["min_wacc_minus_g"]:          # TV explodes — refuse, don't emit
        return None
    ev = _dcf_ev(fcf0, wacc, term_g, g1, H, S1, nopat0, roic)
    if ev is None:
        return None
    ps = (ev - net_debt) / shares
    return ps if ps > 0 else None    # net debt swamps modeled ops → no positive equity value → N/A


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


def _wclamp(y, g, m, r):
    return (max(5.0, min(60.0, y)), max(0.0, min(0.30, g)),
            max(0.0, min(0.60, m)), max(0.0, min(0.50, r)))


def warranted_fit(rows, min_sector=3):
    """rows: (sector, ev_ebit, growth, margin, roic). Fixed-effects fit: center within sector
       (global anchors for sectors with < min_sector names), regress the residual multiple
       on centered growth/margin/ROIC, zero any coefficient that violates the economic prior
       (all three RAISE the warranted multiple — a 35%-ROIC name deserves a higher multiple
       than an 8%-ROIC peer in the same bucket). Anchors are MEDIANS — a mean anchor gets
       dragged by the winsorize-capped rich tail (semis at 60×) and then inflates every name
       that falls back to the global anchor. -> (sector_medians, global_medians, coefs);
       each *_medians tuple is (ev_ebit, growth, margin, roic)."""
    data = [(s,) + _wclamp(y, g, m, r) for s, y, g, m, r in rows]
    if not data:
        return None
    # Anchor cap: a "warranted" multiple must not inherit market froth — when the whole
    # universe trades above ~28× EV/EBIT (3.5% earnings yield), the anchor stays at 28.
    ANCHOR_CAP = 28.0
    med = lambda v: statistics.median(v)
    cap = lambda t: (min(t[0], ANCHOR_CAP),) + t[1:]
    cols = list(zip(*[(y, g, m, r) for _, y, g, m, r in data]))
    gmed = cap(tuple(med(list(c)) for c in cols))
    by = {}
    for s, y, g, m, r in data:
        by.setdefault(s, []).append((y, g, m, r))
    smeds = {s: cap(tuple(med(list(c)) for c in zip(*v)))
             for s, v in by.items() if len(v) >= min_sector}
    X, Y = [], []
    for s, y, g, m, r in data:
        my, mg, mm, mr = smeds.get(s, gmed)
        X.append([g - mg, m - mm, r - mr]); Y.append(y - my)
    coef = ols(X, Y) or [0.0, 0.0, 0.0]
    coef = [max(0.0, c) for c in coef]                    # sign guard (prior: all positive)
    return smeds, gmed, coef


def warranted_value(fit, sector, g, margin, roic, ebit, cash, debt, shares):
    """Sector-anchored 'justified' EV/EBIT (adjusted for within-bucket growth/margin/ROIC)
       applied to this company's EBIT -> $/share."""
    if not fit or ebit is None or ebit <= 0 or not shares:
        return None
    smeans, gmean, coef = fit
    my, mg, mm, mr = smeans.get(sector, gmean)
    _, gc, mc, rc = _wclamp(0, g, margin, roic or 0.0)
    mult = my + coef[0] * (gc - mg) + coef[1] * (mc - mm) + coef[2] * (rc - mr)
    mult = max(4.0, min(40.0, mult))
    return (mult * ebit - debt + cash) / shares


def ddm(div0_ps, re_, term_g, g1, horizon, stage1):
    """Multi-stage dividend discount value/share: D0 grown at g1 (linear fade to term_g
       over the horizon), discounted at the cost of EQUITY, Gordon terminal. The classic
       model for dividend-anchored businesses (banks, REITs) and a real second opinion for
       any dividend payer. None when there is no dividend or Re ≤ term_g (TV undefined).
       g1 is the same growth the DCF uses (capped upstream) so an unsustainable payout
       can't compound to a silly number; the caller also gates on payout coverage."""
    if not div0_ps or div0_ps <= 0 or re_ - term_g < 0.005:
        return None
    pv, d = 0.0, div0_ps
    for t in range(1, horizon + 1):
        g = g1 if t <= stage1 else g1 + (term_g - g1) * (t - stage1) / (horizon - stage1)
        d *= (1 + g)
        pv += d / (1 + re_) ** t
    tv = d * (1 + term_g) / (re_ - term_g)
    return pv + tv / (1 + re_) ** horizon


# ---------- §L8 Triangulate -> range + confidence ----------
# EPV is a no-growth FLOOR, not a central estimate — it sets the low bound and is shown
# separately, never averaged into the mid. The mid is a weight-blended central value from
# the growth-aware engines; agreement is measured among those engines only.
# Plan 3 (split-validated, both universes — see WORKLOG.md): DCF demoted, RIM/Warranted
# promoted — the engines the backtest ranked most reliable. The old weights (DCF .25,
# RIM .20, W .25) live on in backtest.py's V1_WEIGHTS for the variant comparison.
# Phase 3.1: FFO is the REIT anchor; DDM reactivated for dividend payers (banks/REITs get
# a real 2nd method). RIM is scoped to financials/REITs in value.py (a bank engine).
CENTRAL_WEIGHTS = {"DCF": 0.10, "RIM": 0.35, "Warranted": 0.30, "FFO": 0.30, "DDM": 0.10}

def blend_scenarios(base_mid, dcf_base, dcf_bull, dcf_bear, epv, price, probs, conv_years,
                    bull_cap=2.0, bear_floor=0.40):
    """Bear / Base / Bull fair values + a probability-weighted expected return.
       Base = the triangulated mid (the headline number); Bull/Bear scale it by the DCF's
       fundamental sensitivity to shifted drivers (dcf_bull/dcf_base, dcf_bear/dcf_base), so
       the cone is anchored on what the app already shows. The multiplier is capped to
       [bear_floor, bull_cap] — the value-driver DCF is convex, so an uncapped ratio produces
       absurd bull legs. Monotone (bear ≤ base ≤ bull); the bear leg is floored at the EPV
       no-growth value when that sits below base (v2.8.1: EPV is the downside floor), never
       below 0. Returns None when the DCF base is unusable. Annualized return assumes
       convergence over conv_years."""
    if not (dcf_base and dcf_base > 0 and base_mid and base_mid > 0 and price and price > 0):
        return None
    bull = base_mid * min(dcf_bull / dcf_base, bull_cap) if (dcf_bull and dcf_bull > 0) else base_mid
    bear = base_mid * max(dcf_bear / dcf_base, bear_floor) if (dcf_bear and dcf_bear > 0) else base_mid
    bull = max(bull, base_mid)                         # keep the cone monotone
    bear = min(bear, base_mid)
    if epv and 0 < epv < base_mid:
        bear = max(bear, epv)                          # no-growth floor bounds the downside
    bear = max(bear, 0.0)
    pb, p0, pu = probs
    pw = pb * bear + p0 * base_mid + pu * bull
    ann = ((pw / price) ** (1.0 / conv_years) - 1) if (pw > 0 and conv_years) else None
    return {"bear": bear, "base": base_mid, "bull": bull, "pw": pw,
            "expBase": base_mid / price - 1, "expPW": pw / price - 1, "annPW": ann}


def triangulate(growth, floor, price, weights=None, min_band=0.0):
    """growth: {engine_name: per-share value} for applicable growth engines.
       floor:  EPV per-share value (or None). weights: override CENTRAL_WEIGHTS
       (the backtest's variant harness passes historical weight sets).
       min_band: business-unpredictability band. Widens the HIGH of the range up to at
       least mid·(1+min_band) so a low-quality / cyclical name shows more upside uncertainty
       even when the engines agree. The LOW is deliberately NOT widened — it stays at the
       real EPV/engine floor, so the displayed downside is never synthesized below the
       no-growth value (EPV is the floor, by design). Never narrows a wider engine spread;
       never touches within/conf (agreement stays a pure function of engine dispersion)."""
    W  = weights or CENTRAL_WEIGHTS
    g  = {k: v for k, v in growth.items() if v is not None and v > 0}
    fl = floor if (floor is not None and floor > 0) else None
    if not g and fl is None:
        return None
    if g:
        tw  = sum(W.get(k, 0.10) for k in g)
        mid = sum(v * W.get(k, 0.10) for k, v in g.items()) / tw
    else:
        mid = fl                          # only the floor is available
    allvals    = list(g.values()) + ([fl] if fl else [])
    low, high  = min(allvals), max(allvals)
    within     = sum(1 for v in g.values() if abs(v / mid - 1) <= 0.10)
    n          = len(g)
    frac       = within / n if n else 0
    conf = (2 if n < 2 else               # a single engine can't demonstrate agreement
            5 if frac >= 0.99 else 4 if frac >= 0.66 else 3 if frac >= 0.5 else 2)
    if min_band > 0:                      # widen only the HIGH for unpredictability; the low
        high = max(high, mid * (1 + min_band))   # stays at the real EPV/engine floor — never
                                                  # synthesize a downside below the no-growth value
    return {"low": low, "mid": mid, "high": high, "upside": mid / price - 1,
            "within": within, "n": n, "conf": conf, "floor": fl}
