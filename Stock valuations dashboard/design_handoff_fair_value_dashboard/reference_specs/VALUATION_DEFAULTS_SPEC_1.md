# Valuation Engines — Defaults & Assumptions Spec

> Purpose: define every assumption the five valuation engines are *forced* to make,
> with a sane default, a knob range, the reliable source to update it from, and the
> override behavior. The data is pullable; **these defaults are the actual spec.**
>
> Design principle: the engines transform data, but a fair value is a function of
> *assumptions*. This document is the assumption layer. Treat it as version-controlled
> config, not constants buried in code.

---

## 0 · How assumptions resolve (read this first)

Assumptions resolve in **three layers**, bottom to top. A higher layer overrides a lower one for that company only.

1. **Global defaults** — the table in §1. Apply to every company unless overridden.
2. **Archetype overrides** — keyed off the L5 classifier (bank / REIT / cyclical / growth / mature). E.g. banks force FCFE + cost-of-equity discounting; software forces SBC-as-expense.
3. **Per-company overrides** — manual, and **every one carries a `source` and `date`**. This log is the spine of the per-company thesis feature.

**Provenance rule:** an override without a recorded source is a bug, not a feature. Store `{field, old_value, new_value, source, date, note}` per change.

**Anti-curve-fit rule:** the UI must show *default value* and *overridden value* side by side, plus the **reverse-DCF implied growth** for the same company, so any manual tweak is visible against (a) the baseline and (b) what the market is already pricing. You should never be able to move an assumption without seeing how far you moved it.

---

## 1 · Global assumptions (the shared layer)

These cut across multiple engines. Getting these ~8 right matters more than any single engine's internals.

| Assumption | Default | Knob range | Reliable source to update from | Notes |
|---|---|---|---|---|
| **Risk-free rate** | **Live 10Y UST, pulled daily** — do **not** hardcode | n/a (live) | FRED series `DGS10` | Recent years have sat roughly in the 4% area; pull live, don't trust that sentence. |
| **Equity risk premium (ERP)** | **5.0%** | 4.0–6.0% | **Damodaran implied ERP** (published monthly, free) | Single most consequential input. Implied (~5%) ≠ historical realized (~6–7%); use implied. |
| **Beta** | 5-yr monthly regression vs. S&P 500, **Blume-adjusted** (`0.67·raw + 0.33·1.0`), clamped to [0.5, 2.0] | swap for Damodaran industry beta | Damodaran industry betas (bottom-up) | Raw single-stock betas are noisy; shrink toward 1.0. Industry beta is often the better default. |
| **Cost of equity (Re)** | CAPM: `rf + β·ERP` | — | derived | Drives RIM, DDM; component of WACC. |
| **Cost of debt (Rd)** | `interest expense / total debt`, floored at `rf + 0.5%` | or `rf + rating-proxy spread` | filings | If interest expense is ~0 or debt ~0, fall back to `rf + spread`. |
| **Tax rate** | **21%** (US federal statutory, forward) | effective, or 25% blended w/ state | filings (effective rate) | Forward-looking ≠ trailing effective. Flag big gaps. |
| **WACC** | market-value weighted: `E/V·Re + D/V·Rd·(1−tax)` | — | derived | Use market cap for E, book (or market) for D. |
| **Terminal growth (g)** | **2.5%**, hard ceiling = `rf` | 1.5–3.0% | long-run nominal GDP | Damodaran rule: terminal g must not exceed the risk-free rate. Enforce the ceiling in code. |
| **Forecast horizon** | **10 yrs, 2-stage** (yrs 1–5 explicit, yrs 6–10 linear fade to g) | 1-stage / 3-stage | — | — |
| **Initial growth** | trailing 5-yr revenue CAGR, winsorized, **cap 20% / floor 0%** | blend w/ consensus if available | filings; optional analyst consensus | The weakest mechanized input. Cap hard to stop absurd extrapolation. |
| **SBC treatment** | **Expense it** (subtract SBC from FCF) | add-back / dilution-adjust | — | See §7. Default to the conservative, defensible stance. |
| **Maintenance capex** | `min(capex, D&A)` | D&A proxy / Greenwald split | filings | Total capex overstates the maintenance burden for growers. |

---

## 2 · DCF (multi-stage, Monte Carlo)

**What it answers:** intrinsic value from projected free cash flow.
**Discount at:** WACC (FCFF) — subtract net debt at the end to get equity value.

| Input | Default |
|---|---|
| Cash flow base | FCFF = CFO − capex, with SBC stance applied (§7) |
| Horizon | 10 yrs, 2-stage |
| Stage-1 growth (yrs 1–5) | global "initial growth" default |
| Stage-2 (yrs 6–10) | linear fade from stage-1 growth → terminal g |
| Terminal value | Gordon: `FCF₁₀·(1+g) / (WACC − g)`; cross-check vs. exit EV/EBIT multiple |
| Discount rate | WACC |

**Monte Carlo (not a point estimate):** draw from distributions, 10k runs, report 10th/50th/90th percentile fair value.

| Variable | Distribution (default) |
|---|---|
| Stage-1 growth | triangular, mode = default, ±3 pp |
| Operating margin | normal, ±2 pp |
| Terminal g | triangular, ±0.5 pp (respect rf ceiling) |
| WACC | normal, ±1.0 pp |

**Gotchas:** terminal value is 60–80% of the answer — surface that share explicitly in the UI. If `WACC − g < 1.5%` the model explodes; clamp and warn.

---

## 3 · Reverse DCF (the anchor — prioritize this)

**What it answers:** what growth does *today's price* already imply?
**Method:** hold WACC, horizon, and terminal g fixed; solve for the stage-1 growth rate that makes DCF fair value = current price.

| Input | Default |
|---|---|
| Target | current market cap (or EV) |
| Free variable solved for | stage-1 growth (yrs 1–5), terminal g fixed at default |
| Everything else | global defaults |

**Output:** "price implies X% growth for 5 yrs, fading to g." Compare X to the company's own trailing growth and to consensus. This is the **only assumption-light engine** — it inverts the hard part — and it doubles as the curve-fit guard for every manual override elsewhere.

---

## 4 · RIM — Residual Income Model

**What it answers:** value as book equity plus the present value of returns above the cost of equity.
**Best for:** banks, insurers, financials. **Discount at:** Re (cost of equity).

```
Value = BookValue + Σ PV[ (ROEₜ − Re) · Bookₜ₋₁ ]
```

| Input | Default |
|---|---|
| Book value | current common equity (per share) |
| Forecast ROE | trailing 5-yr avg ROE, **faded toward Re** over the horizon (excess returns compete away) |
| Persistence ω (Ohlson) | **0.62** |
| Discount rate | Re |

**Critical Nasdaq-100 gotcha:** heavy buybacks can drive **book value negative** (treasury stock exceeds equity). RIM is undefined or nonsense there — detect `BookValue ≤ 0` and mark **N/A**, don't emit a number. This will hit several large caps in your universe.

---

## 5 · EPV — Earnings Power Value

**What it answers:** value of current earnings power assuming **zero growth** — a conservative anchor.
**Discount at:** WACC.

```
EPV (operations) = normalized NOPAT / WACC
EPV (equity)     = EPV(operations) + cash − debt
```

| Input | Default |
|---|---|
| Normalized EBIT | avg operating margin over **7 yrs** × current revenue |
| Normalization window | 7 yrs (knob 5–10) |
| → NOPAT | normalized EBIT × (1 − tax) |
| Maintenance capex adj. | add back D&A, subtract maintenance capex (§1) |
| Discount rate | WACC |

**Read:** `EPV < current EV` means the market is paying for growth. The **EPV-to-EV gap is itself a signal** — show it. EPV is your "what if growth is worth nothing" floor.

---

## 6 · DDM — Dividend Discount Model

**What it answers:** value of the dividend stream. **Discount at:** Re.

| Input | Default |
|---|---|
| Form | multi-stage Gordon: `V = Σ PV(Dₜ) + PV(terminal)` |
| Dividend growth | trailing 5-yr dividend CAGR, faded to g |
| Discount rate | Re |

**N/A trigger:** payout ratio < ~5% or no dividend → mark **N/A**, never force it.

> ⚠️ **For the Nasdaq 100, DDM is N/A for the large majority of names.** Consider swapping it for a **warranted-multiple regression** as your 5th engine: regress a justified multiple (P/E or EV/EBIT) on quality + growth + risk across peers, winsorize inputs, and value off the fitted multiple. It's more useful for this universe and still transparent. Spec it if you want and it becomes engine #5 in place of DDM for non-payers.

---

## 7 · Universe-specific traps (Nasdaq 100)

- **Stock-based comp dominates.** GAAP adds SBC back as non-cash in CFO, so naive `FCF = CFO − capex` *overstates* free cash flow and ignores real dilution. **Default: expense it** (subtract SBC from FCF). Offer two alternatives as knobs — add-back, or model share-count dilution directly — and show how much the choice moves fair value. For SBC-heavy names this single toggle can swing the answer by a third.
- **Negative book value** from buybacks breaks RIM (see §4). Detect and N/A.
- **Few dividend payers** make DDM mostly dead weight (see §6).
- **Concentration:** a handful of mega-caps dominate the index. When you eventually expand to NYSE, the per-name QA that catches a bad XBRL tag or sign error at 100 names doesn't survive at 2,000 — bad inputs become invisible. Keep a per-company sanity panel (margins, growth, every assumption) that you can eyeball.

---

## 8 · What Claude Code needs to pull (data → assumption map)

| Pulled (backward-looking) | Feeds |
|---|---|
| Income statement (rev, EBIT, net income, interest exp, tax), 7–10 yrs | growth, margins, normalization, Rd, tax |
| Cash flow statement (CFO, capex, D&A, SBC, dividends) | FCF, maintenance capex, SBC stance, DDM |
| Balance sheet (equity, debt, cash, shares) | book value, WACC weights, net debt, RIM |
| Daily price → market cap / EV | reverse DCF target, equity weighting |
| 10Y UST (FRED `DGS10`) | risk-free |
| Damodaran ERP / industry beta / industry margins | ERP, beta, sector overrides |

Everything else in this doc is an **assumption you impose**, not a field you fetch. That set of impositions — and the override log on top of it — is the real product.
