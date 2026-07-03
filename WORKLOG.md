# Work Log — Phase 9 hardening sprints

> One entry per plan, updated as the work happens. What changed, what was measured,
> what was deliberately deferred. BUILD_PLAN.md holds the checklist; this holds the record.

---

## Plan 1 — Safety net (2026-07-02) ✅ commit `9ca7ce9`

**Goal:** tests + run history + coverage guard, so every later change is diffable and guarded.

- Added `backend/tests/test_engines.py` — 30 stdlib-unittest tests, all passing.
  Goldens hand-derived from the spec (Gordon reduction of the 2-stage kernel = exactly
  `fcf0·(1+g)/(wacc−g)` when g1=g; explicit H=2 two-stage arithmetic; RIM at H=1;
  EPV 76.0/86.0 cases). Invariants: reverse-DCF inverts the kernel to 1e-6; RIM(ROE=Re)=book;
  EPV floor never averaged into the mid; single engine ⇒ conf 2; 28× anchor cap holds;
  every engine returns None (never a guess) on bad inputs.
- Added append-only `snapshots` table (`value.py`): every run keeps its full ranked output
  keyed by `run_date` + `MODEL_VERSION` tag. This is the before/after diff surface for all
  future model changes and the foundation for the Plan-4 forward ledger.
- Added `run_stats` coverage guard (`ingest_v1.py`): per-concept ticker coverage recorded
  each ingest, loud warning on >5% drop vs the previous run (silent-XBRL-tag-change
  detector). Verified by simulation: clean pass reports "all 18 concepts within 5%";
  a simulated revenue-tag break (120→100 tickers) trips the warning block.
- **Bug found by the new tooling on day one:** back-to-back runs on identical data
  differed ~1% because the DCF Monte Carlo was seeded with `hash(ticker)` — Python
  salts `hash()` per process. Fixed with `zlib.crc32`; runs 3 and 4 now byte-identical
  (0 of 94 names differ).

---

## Plan 2 — Input correctness (2026-07-02) ✅

**Goal:** fix inputs that are wrong today — net debt completeness, cost of debt from
interest expense, effective tax rate from filings, real maintenance capex in EPV.

**Method (isolated diff):** re-ingested with the new tags, snapshotted the OLD model on
the new data (run `14:15:05`, tag v1), then applied the new model (v1.1) and diffed the
two snapshots — same data, same fallback rf (4.30%) in both, so the diff is pure methodology.

**Ingest — 5 new XBRL concepts** (both us-gaap and ifrs-full maps, `ingest_v1.py`):
- `short_debt` (DebtCurrent > LongTermDebtCurrent > ShortTermBorrowings > CommercialPaper) — 77 tickers
- `op_leases` (OperatingLeaseLiability, …Noncurrent) — 100 tickers
- `interest_exp` (InterestExpenseDebt > InterestExpense > …Nonoperating) — 86 tickers
- `tax_exp` / `pretax` for the effective rate — 100 / 99 tickers
- 30,386 datapoints (was ~15.7k). Coverage guard's first real run: clean, 23 concepts within 5%.
- *Caveat:* the tag-merge machinery picks ONE tag per FY (can't sum components), so
  short_debt prefers the total (`DebtCurrent`) and understates names that file only the
  components separately. Better than the prior zero.

**Model v1.1** (`value.py`, `common.py` helpers, `assumptions.toml` knobs):
- **Borrowings = long + short debt** everywhere in the valuation math (WACC weights,
  every engine's net-debt bridge, warranted EV, EV/EBITDA).
- **Leases → risk debt only** (leverage flag, ND/EBITDA, quality low-leverage dim), NOT
  the engine bridges — deliberate: every engine discounts post-rent flows (CFO and EBIT
  are after lease expense), so leases in the EV bridge would double-count lease costs.
  Knob: `include_op_leases`.
- **Rd = interest expense / borrowings**, floored rf+0.5%, capped 15% (`cost_of_debt()` in
  common.py). Live distribution: median 4.80% (= floor — mega-cap tech borrows cheap),
  max hit the 15% cap (debt shrank mid-year), ~24 names on the rf+1% fallback.
- **Effective tax** = 3-yr mean of tax expense / pretax income, loss/benefit years skipped,
  clamped [10%, 35%] (`effective_tax()`). Live: median 21.0%, full range 10–35%, ~11 on fallback.
  Used in WACC, EPV NOPAT, ROIC.
- **EPV maintenance capex finally wired** — `epv(..., dna, capex)` was called with
  `capex=None` since inception, so the `dna − min(capex, dna)` adjustment was dead code.
- 8 new tests (effective_tax, cost_of_debt) → suite at 38, all green.

**Measured effect (v1 → v1.1 snapshot diff, 94 names):**
- 77 mids moved, median |Δmid| 0.3% — debt-light mega-tech barely moved, as it should.
- Top movers all leverage stories: WDC −6.0%, CMCSA +5.5%, HON −4.6%, KHC +3.8%,
  CCEP +3.2%, BKNG −3.1%, TMUS +2.5%.
- High-leverage flags 8 → 12: INTC, KDP, MDLZ, SBUX gained — SBUX is the textbook
  operating-lease case; exactly the intended catch.
- Determinism re-verified: two v1.1 runs → 0 of 94 names differ.

**Deferred (logged, not forgotten):**
- Backtest/PIT still uses old inputs — pit.py picks up the new concepts automatically but
  only for newly fetched names; historical backfill = full EDGAR refetch, deferred until
  the backtest signal actually consumes them (Plan 3/6 decision).
- betas not re-run (table persists; new universe entrants fall back to β=1.0).
- IFRS tag choices for the 3 foreign filers are best-effort; verify if TRI/CCEP/FER
  numbers look off.

---

## Plan 3 — Evidence-aligned scoring (2026-07-02) ✅

**Goal:** make the product consistent with its own backtest evidence — but only adopt
changes that survive a time-split validation, not a fit to the full sample.

**Harness:** backtest.py refactored — `build_quarter()` now returns raw PIT signals
(the expensive part, computed once); `compose(sigs, variant)` scores them per variant;
`triangulate()` takes a weights override. Three variants × three windows × two universes:

| variant | what it is |
|---|---|
| v1  | shipped composite (weights DCF .25 / RIM .20 / W .25, binary 0.55 flag penalty, growth in quality) |
| v2w | weights DCF .10 / RIM .35 / W .30 · 0.85^n flag decay (cyclical informational) · growth out of quality |
| v2  | v2w + reverse-DCF gap rank-blended into the composite at 0.4 |

**Results (excess CAGR vs equal-weight bench · hit rate):**

| | NDX full | NDX fit 16-21 | NDX holdout 22-26 | SPX full | SPX fit 16-21 | SPX holdout 22-26 |
|---|---|---|---|---|---|---|
| v1  | −5.27pp · 51% | −6.84 · 48% | −2.53 · 59% | +0.10 · 49% | −0.41 · 35% | +0.85 · 71% |
| v2w | **−0.99 · 46%** | **−2.47 · 39%** | **+1.62 · 59%** | **+0.19 · 54%** | −1.35 · 39% | **+2.61 · 76%** |
| v2  | −3.39 · 49% | −6.94 · 35% | +1.49 · 71% | +0.17 · 56% | −2.14 · 39% | +3.18 · 76% |

Sanity: v1 full-window reproduces the published Phase 7/8 numbers exactly (refactor faithful).

**Decision — adopt v2w, reject the gap blend.** v2w beats v1 in 5 of 6 cells (NDX full
−5.27 → −0.99pp) and is positive on both holdouts. v2's gap blend wins the 2022-26
holdout (+3.18pp SPX) but LOSES to v1 on 2016-21 (−6.94pp NDX): the reverse-DCF-gap
tilt is a value-factor loading that got crushed pre-2022 and paid after — regime, not
signal. Trying intermediate gap weights would be curve-fitting; the gap stays displayed
("impl vs trail" on the board), not scored. **Honesty note:** the v2w weights were
motivated by full-sample per-method stats from Phase 7/8, so this "holdout" is not fully
out-of-sample — the real test is the Plan-4 forward ledger.

**Live changes (model v2):**
- `CENTRAL_WEIGHTS` → DCF .10 / RIM .35 / Warranted .30 (engines.py).
- **Monte Carlo DCF deleted** — it perturbed g1/WACC/terminal-g in a narrow band but never
  the FCF base (the dominant uncertainty), so P50 tracked the deterministic value while
  implying rigor the backtest never rewarded. `dcf()` is now the deterministic kernel.
- Flag penalty: binary ×0.55 cliff → `0.85^n`; "Cyclical revenue" reclassified as
  informational (shown, never penalized).
- Growth removed from the quality composite (quality = profitability/stability/leverage).
- Altman-Z gated off for Financials/Real Estate (calibrated for industrials; n/a, no flag).
- backtest.json contract: + `meta.scoring`, + `validation` (all variants × windows),
  caveats refreshed. Frontend needed no change (no hardcoded weights; additive JSON keys).

**Measured live effect (v1.1 → v2 snapshot diff, 94 names, same data):** median |Δmid|
13.2% — big, as a reweighting should be. Movers all follow the mechanism: warranted-rich
cyclicals up (MU +47%, STX +45%, WDC +41%), DCF-propped names down (FANG −49%, WBD −47%,
PDD −40%). Biggest rank moves: ODFL +27 places, WBD −22. Tests: 38/38 green.

---

## Plan 4 — Forward paper-trading ledger (2026-07-02) ✅

**Goal:** the only test with no in-sample escape hatch — freeze the model's top-quintile
basket at every refresh, then measure forward returns vs the equal-weight universe.
The backtest's fatal caveat ("the signal's design postdates the sample") does not apply:
the picks are committed before the returns exist.

**Built:**
- `backend/ledger.py` — reads the append-only `snapshots` table (Plan 1's foundation,
  now paying off): one basket per (model, calendar day), last run of the day wins;
  k = max(10, n//5) matching the backtest's quintile rule; every basket marked to the
  latest run's prices; benchmark = equal-weight of all names present in both runs.
  Pure `build_ledger()` core → 6 new tests (44 total, all green): forward-return math,
  age-0 baskets excluded from the summary, same-day rerun collapse, excluded names
  dropped-and-counted, per-model tracking.
- Honest-by-design choices: price-only returns on BOTH legs (no dividends — disclosed);
  models tracked separately (only the current tag is the live test); an explicit caveat
  that <90 days of forward data is noise.
- Output `data/ledger.json` (+ synced to frontend/public; embedded in the share build
  as `__FV_LEDGER__`).
- Dashboard: "Forward ledger — the live test" card on Methodology (frozen date, model,
  age, coverage, basket/bench/excess per basket; summary line once baskets age;
  honest inception state until then). Verified rendering in the dev server.
- `REFRESH DATA.cmd` now has step 5/5: `python ledger.py` — the ledger accrues
  automatically with every routine refresh.
- Stale text fixed while in there: Methodology's DCF card no longer claims a Monte
  Carlo (retired in Plan 3); tax assumption cell now says effective-from-filings (Plan 2).

**Inception state (2026-07-02):** three baskets frozen (v1, v1.1, v2 — one per model tag
that ran today), 18 names each, age 0, returns 0 — exactly as an inception should look.
The v2 basket is the live test from here forward.

**What would make this meaningful:** refreshes. Each run of REFRESH DATA.cmd adds a
basket; after ~one quarter the first real forward numbers exist; after ~a year the
hit rate starts to mean something. Consider a weekly scheduled refresh.

---

## Plan 5 — TTM fundamentals (2026-07-02) ✅

**Goal:** valuations were running on annual filings up to ~15 months stale. Pull the
10-Qs already sitting in the same EDGAR companyfacts JSON (no extra network) and value
off trailing-twelve-month flows + the freshest quarterly balance sheet.

**Ingest — the TTM stitcher** (`ingest_v1.py`, 10 new tests):
- `TTM = FY + post-FY chain − prior-year mirror`. Handles YTD reporters (one 9-month
  point) and QTD-chain reporters; prefers YTD over QTD at the same end date; chain links
  and year-mirrors tolerate ±5–10 days (52/53-week fiscal calendars). Any missing mirror
  → honest `fy` fallback, never a guess. US 10-Q/10-K only (foreign 6-K interims → FY).
- Balance-sheet concepts take the freshest quarterly instant instead.
- New `financials_now` table: 1,977 rows — 944 TTM flows, 88 fy-fallbacks, 945 instants.
  Revenue: 89/93 names on true TTM, thru-dates median 2026-03-31, newest 2026-05-29
  (the annual-only view was up to 15 months older).

**Model v2.1** (`value.py`): every "now" input upgraded — rev_now/ebit_now/ni_now/cfo_now/
dna/dividends/interest (TTM), borrowings/leases/cash/equity + Altman-Z balance-sheet
inputs (fresh instants), fcf_last = TTM FCF, EPV maintenance capex = TTM capex. Annual
series remain the history (margins, CAGR, ROE, quality, trends). Accrual flag now
compares NI and CFO on the same TTM basis. Staleness = no filing covering the last ~9
months. Contract gains `finThru` (data-as-of date per company). Coverage 94 → 96
(TTM basis rescued LITE and SNDK).

**The audit that mattered** — MU showed +562% mid, too big to trust. Pulled raw EDGAR
durations: the stitch is exact (37.4B FY + 79.0B YTD − 26.1B mirror = 90.3B), and MU's
quarterly revenue really went 9.3B → 41.5B/q into the 2026 memory supercycle — the
annual view was valuing pre-boom numbers 9 months stale. META −36% is the fresh
quarterly balance sheet carrying the new AI-capex debt the annual bridge missed. All
big movers explained by mechanism, none by bug.

**Pre-existing annual-pipeline bug found and fixed:** `pick_annual` accepted partial-year
durations filed with fp=FY — MPWR's "FY2025 revenue" was a Q4-only point (0.64B vs the
real 2.79B), corrupting its margins/CAGR/quality. Added a 350–380-day span guard
(instants unaffected). On the re-ingest, **the Plan-1 coverage guard fired its first
real alert** (gross_profit 64 → 59 tickers) — verified all five drops were correctly
rejected partial-year garbage (impact limited to one Piotroski signal that has a
fallback pair). The safety net caught the side effect of its own fix, as designed.

**Final isolated diff (v2 → v2.1, same data, same rf):** median |Δmid| 5.5%.
Movers: MU +559% (supercycle), MPWR +358% (annual-corruption fix), STX +69%, WDC +63%,
CEG +55%, FANG +49% — cyclicals whose TTM inflected. 54 tests total, all green.

**Known trade-off (logged for Plan 6):** TTM cures staleness but capitalizes cyclical
peaks — the warranted engine now multiplies MU's peak EBIT. Counterweights in place:
normalized-margin DCF base, EPV floor on 5-yr average margins, the cyclical flag, the
28× anchor cap. A future refinement: normalized EBIT for the warranted engine on
cyclical-flagged names.

**Deferred:** PIT/backtest stays on annual vintages (quarterly PIT = a Plan 6 decision;
the backtest's quarterly rebalance on annual data remains internally consistent).

---

## Plan 6 — Momentum + L7 cross-section (2026-07-02) ✅ — VERDICT: REJECTED, v2w STANDS

**Goal:** the blueprint's most empirically-supported unbuilt layer — L7 sector-neutral
Value/Quality/Momentum z-scores — tested under the same split discipline as Plan 3.
Two candidates declared a priori (no weight search): v3 = equal V/Q/M, v3m = momentum-
tilted (.25/.25/.50). Value legs = warranted upside + revDCF gap; Quality = the v2
quality percentile; Momentum = 12-1 from adjclose (skip-month, splits+dividends handled).

**Built (backtest.py):** `month_add`, 12-1 momentum in `signal()`, winsorized
sector-neutral z machinery (`_winsor`, `_sector_z`, thin sectors → global stats,
z clamped ±3, missing factors renormalize), L7 blend branch in `compose()`,
"Momentum 12-1" added to the per-method reliability table (auto-renders on the
dashboard's Methodology screen).

**Results (excess CAGR vs bench · hit rate):**

| | NDX full | NDX fit 16-21 | NDX holdout 22-26 | SPX full | SPX fit 16-21 | SPX holdout 22-26 |
|---|---|---|---|---|---|---|
| v2w (adopted) | −0.99 · 46% | −2.47 · 39% | +1.62 · 59% | +0.19 · 54% | −1.35 · 39% | +2.61 · 76% |
| v3  | −2.53 · 51% | −3.52 · 48% | −0.47 · 59% | −1.19 · 54% | −3.62 · 39% | +2.66 · 76% |
| v3m | −1.14 · 46% | −4.49 · 48% | +3.18 · **47%** | −0.16 · 54% | −2.62 · 48% | +4.01 · 65% |

**Decision — reject both, v2w remains ADOPTED.** Both L7 variants lose to v2w on the
fit window in both universes and on the full sample; they only outperform on the
2022-26 holdout — the identical regime signature that got the gap blend rejected in
Plan 3 (momentum's 2023-25 AI run flatters exactly that window). v3m's NDX holdout
(+3.18pp) comes with a 47% hit rate — a few huge quarters, not a reliable signal.
The declared rule (adopt only what wins both windows) says no. **No live model change;
v2.1 stands. No curve-fitting rescue attempts.**

**The interesting residual, logged as a future lead:** STANDALONE momentum now tops the
per-method table — NDX +2.03%/q excess (≈8%/yr!) at only 51% hit, SPX +0.61%/q at 54%.
The signal is real but lumpy and regime-concentrated, and diluting it into a fixed-weight
z-blend destroyed its value. If it's ever pursued: monthly rebalance (quarterly is blunt
for momentum), overlay/filter designs rather than z-blends, and a fresh out-of-sample
window. Until then it stays what it is — a displayed diagnostic, not a scored input.

**Meta-note:** this is the third honest negative verdict this project has published
(Phase 7 no-edge, Plan 3 gap rejection, now L7). The harness is doing its job:
cheap to test, hard to fool, and the dashboard renders whatever the evidence says.
