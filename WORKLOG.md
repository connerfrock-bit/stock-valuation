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

---

## Plan 7 — Robustness & de-scoping (2026-07-02) ✅

**1. Risk-free history fixed — and the backtest's biggest silent input error with it.**
`^TNX` (and the whole CBOE yield family on Yahoo) has a feed hole from 2024-06 to
2026-06; the backtest had been filling those ~8 quarters with a 2.5% constant while the
real 10Y sat near 4.3% — flattering every fair value in exactly the holdout window.
New `rf_monthly` table (`prices.refresh_rf`): FRED DGS10 first (authoritative; retried
every run — self-heals when reachable), Yahoo `^TNX` re-fetch as fallback, and
last-observation-carried-forward across feed-gap months (disclosed in caveats; LOCF at
~4.3% is honest, the 2.5% constant was not). 215 months loaded through 2026-07.
**Re-validated all scoring variants under corrected rf: the v2w adoption HOLDS on both
universes** (NDX: v2w −1.03 full / +1.53 holdout, still the fit-window winner; SPX: v2w
+0.52 full / +3.41 holdout at 88% hit — strengthened). Plans 3 and 6 are rf-robust.

**2. Wikipedia hardening.** `universe.py`: every good parse cached to
`data/universe_cache.json`; on fetch failure the cache is used (a stale-but-real 101-name
list beats the 50-name built-in fallback); churn >max(8, 10%) vs cache warns loudly
(parse-drift detector). `membership.py`: parse-shrink guard vs `membership_cache.json` —
a Wikipedia table-format change now announces itself before corrupting the backtest's
membership walk-back.

**3. Universe un-hardcoded.** `[universe]` section in assumptions.toml (name, min_mcap);
`MIN_N100_MCAP` gone from value.py; `meta.universe` flows from config; both dashboard
badges render `meta.universe` (verified: zero hardcoded literals in the built bundle).
The live screener is now one toml edit away from a different universe.

**4. De-scoped.** Milestone C (FastAPI) formally CANCELLED in BUILD_PLAN — static JSON +
the share build serve the actual use case; a server is surface area with no benefit.
The warranted engine's OLS was reviewed and KEPT (not zombie code: the sign guard zeroes
coefficients only when the cross-section disagrees with the prior — data-dependent, and
the S&P universe can activate it). Loss-maker coverage (revenue-based reverse-DCF for
the excluded GAAP loss-makers) explicitly deferred to a future feature plan — it needs
design care, not hygiene-sprint leftovers.

**State at close: 54 tests green · model v2.1 · 12 runs in snapshot history · ledger
armed · all Phase-9 plans complete.**

---

# Phase 10 — Universe expansion (CEO roadmap: A → B → C → D)

Roadmap set 2026-07-03 after the "are the methods reliable / how far can we expand"
review. Staged by value-per-effort: **A** S&P 500 live screener (methods work best there;
nearly free — universe already un-hardcoded) · **B** extend S&P backtest to ~2012-13
(cheap truth, XBRL floor is 2009) · **C** momentum overlay research (the only green
signal we ever found) · **D** NYSE large+mid $2B+ (real work: archetype router, SIC
mapping, size buckets). Declined: micro-caps + pre-2009 backtest (free-data quality
makes honest numbers impossible; that's the paid-data gate, not an engineering gate).

## Plan A — S&P 500 live screener (2026-07-03) — IN PROGRESS

**Goal:** run the S&P 500 as a second LIVE screener alongside Nasdaq-100 (dashboard
toggle, mirroring the existing backtest toggle). The one non-negotiable: a financial-
archetype router so banks/insurers/REITs get RIM-only + honest N/A, never garbage
DCF/EV-EBITDA fair values. Method: ultracode workflows — Understand (seam map) → Design
(judge panel on data model + router) → implement inline → adversarial Review.

**Understand (workflow, 4 parallel readers):** mapped every seam — no universe column +
ingest DROPs (data-loss hazard); snapshots colliding PK; sp500 parser/GICS reusable;
DCF/EPV/Warranted run unconditionally (garbage for banks).

**Design (2 judge panels):** (a) superset + `universe_membership` junction — ingest the
UNION once into universe-agnostic tables (betas/sanity untouched), filter per universe,
snapshots/run_stats PKs gain universe, NYSE = one more config block. (b) pure
`archetype_of(GICS)` + static `ARCHETYPE_GATES` forcing DCF/EPV/Warranted/revDCF→None for
financials/REITs before triangulate — one seam gates the engine AND flips applicable AND
needs no weight override; no sub-classification (we lack FFO/NIM).

**Implemented (backend):** [[universe]] config; S&P parser + build_union (GICS overrides
Nasdaq ICB); union ingest + junction; archetype router in value.py; per-universe artifacts
+ universes.json manifest; snapshots/run_stats PK migrations; model v2.2; 10 archetype tests.
**Frontend:** activated the universe dropdown (universes.json → swap output_<id>.json); clean build.

**Bugs the router surfaced at universe scale (all fixed, re-ingesting):**
1. **EDGAR throttling** silently dropped 187/517 names (no retry) → exponential-backoff
   retry in http_json + resume mode that re-fetches low-coverage names (GS ingested with
   1 concept during a throttle window; naive resume had skipped it).
2. **Banks tag annual net income as `ProfitLoss`**, not `NetIncomeLoss` (PNC/GS have ZERO
   annual NetIncomeLoss points) → added ProfitLoss + to-common fallbacks. The L1c/L3
   bank-XBRL divergence the blueprint predicted for expansion.
3. **PayPal mislabeled Industrials** by Nasdaq ICB (GICS: Financials) → build_union lets
   the GICS source win for overlap names.
4. **Asset-light financials** (Visa/MA/Moody's/exchanges) fail RIM's book gate but are FCF
   businesses, not banks → principled exception (reuses rim_ok + positive FCF, no new
   threshold): a Financials name where RIM is inapplicable on book but FCF is clean → valued
   as standard.

**Adversarial Review (workflow, 4 hunters + verifiers):** the hunt surfaced one genuine
**blocker** — AMP (Ameriprise) had been asset-light→FCF-routed and produced a $1,528 DCF
at 3× price, conf 5. Ameriprise is a float-funded annuity/asset-manager whose "clean FCF"
is inflated by separate-account flows. Fix: a **float-guard** on the asset-light exception —
only FCF-route a financial whose normalized FCF yield ≤ 6% (above that = float/lending
distortion; AMP 13%, Amex 7%). Clean separation: AMP/AXP → RIM-gated/excluded; the 8 real
fee/network names (V/MA/MCO/AON/MSCI/BX/ARES/HOOD, fcfy ≤ 4.2%) keep FCF valuation. Also
nulled the EV/FCF display metrics (fcfy, ev/ebitda, nd/ebitda) for RIM-gated financials —
a "19% FCF yield" on a bank is misleading even as a display column. The other ~24 hunted
findings were REFUTED by design intent (reviewers flagging correctly-RIM-gated banks or
honestly-excluded REITs as "should be priced"). Verify phase hit the session token limit;
triaged the raw findings manually.

**FINAL STATE (model v2.2):**
- **Nasdaq-100: 96 covered** (PYPL now correctly Financials→RIM-only; median |Δmid| vs
  v2.1 just 0.5% — standard names byte-stable). **S&P 500: 479 covered / 20 excluded.**
- Router working: banks/insurers → RIM-only (JPM/GS/BAC, conf 2, no garbage DCF);
  asset-light fee/network → FCF (V −3% · MA +11% · MCO −29%, sane); REITs → RIM if
  book-clean else honestly excluded; the ~75% standard universe unchanged.
- 20 S&P exclusions all honest: 6 tower/data-center/storage REITs (need FFO/NAV, negative
  book), 8 custom-capex-extension names (NEE/DTE/PSX — utilities/energy tagging tail),
  2 Wikipedia spinoff placeholders (FDXF/HONA), AMP/AXP (float-distorted), IBKR, AXON.
- Verified no financial has >80% upside and no RIM-gated name shows EV/FCF metrics.
- Dashboard toggle live (universes.json manifest → output_<id>.json); clean TS build;
  share build 432 KB. 34 tests green (10 new archetype).

**Known limitations (documented, not blocking):** utility/energy custom-capex-extension
names (~6) honestly excluded; PYPL and fintechs-with-book get conservative RIM (the safe
choice — an FCF-clean rule would mis-route real regional banks to garbage DCF, verified);
asset-light insurers use a 6% fcfy float-guard (a data-sanity clamp, not a fitted class
boundary). Backtest still uses its own engine stack (no archetype gate) — the live/backtest
divergence is pre-existing and documented; adding the router to the S&P backtest is a
future refinement that would require re-validating the v2w adoption.

## Plan B — Extend the S&P backtest to ~2012 (2026-07-06) — IN PROGRESS

**Goal:** the backtest starts 2016; the XBRL floor is ~2009 and our PIT store already holds
vintages from 2009-10, prices from 2011-08, rf from 2006. Extend the start to 2012 to
(a) re-validate v2w over 14 years instead of 10, and (b) — the real prize — test v2w on
**2012-2015, a window that predates the model's design** (v2w was motivated by 2016-2026
per-method stats), so it is genuinely out-of-sample. Honest cost: survivorship grows the
further back we reach (delisted names Yahoo/EDGAR no longer serve) — quantify per year.

**Pre-flight (data already reaches back):** Wikipedia S&P change log parses 402 changes
1976→2026 (walk-back to 2012 well-supported); PIT filed 2009-10→2026-07 (620 names);
prices 2011-08→2026-07 (535 names ≤2012-06); rf 2006-08→2026-07. Only the membership
SNAPSHOTS stop at 2015 (quarter_ends start_year=2015). Known softener: rolling betas need
25+ months of price history, so 2012-2013 signals fall back to β≈1.0 until history accrues.

**Executed:** membership.py quarter_ends 2015→2012 (regenerated both universes: sp500 58
snapshots / 771 distinct / 271 past members, ndx 58 / 220 / 120); pit.py + prices.py
incremental (survivorship residue surfaced: 162 pre-2016 sp500 past members are delisted
with no findable CIK, 147 missing prices — the honest cost of reaching back); backtest.py
START 2016→2012 + a new **pre2012-15 validation window** (predates the v2w design = OOS).

**RESULTS (excess CAGR vs equal-weight bench · hit rate):**

| window | NDX v1 | NDX v2w | SPX v1 | SPX v2w |
|---|---|---|---|---|
| full 2012-26      | −3.73/53% | −1.74/49% | +0.09/51% | +0.03/56% |
| **pre2012-15 (OOS)** | **−2.55/53%** | **−3.98/53%** | **−0.59/47%** | **−1.36/47%** |
| fit2016-21        | −6.84/48% | −2.47/39% | −0.23/39% | −1.39/39% |
| holdout2022-26    | −0.54/59% | +1.53/59% | +1.07/71% | +3.16/88% |

Full-sample CAGR: NDX 15.7% vs 17.4% bench · SPX 13.7% vs 13.7% bench (57 quarters).

**VERDICT — v2w does NOT robustly generalize; v1≈v2w is the honest read.** On 2012-2015,
the one window that genuinely predates the v2w design, **v2w UNDERPERFORMS v1 in BOTH
universes** (NDX −3.98 vs −2.55, SPX −1.36 vs −0.59). v2w's advantage is entirely a
post-2016 phenomenon — exactly the period whose per-method stats motivated its design.
On the full 14 years v2w edges v1 on NDX (−1.74 vs −3.73) and ties on SPX, but neither
shows a durable edge (both flat-to-negative). This TEMPERS the Plan-3 adoption: v2w is not
a proven improvement, just a post-2016-regime fit.

**Kept v2w as ADOPTED (no revert).** Reverting to fit the 2012-2015 window would itself be
curve-fitting — and that window is the LEAST trustworthy: pre-2016 coverage is only ~54%
(vs ~90% recently), so the missing delisted losers flatter every variant and the
variant-to-variant differences there are noise-dominated. v2w still wins the full sample
(NDX) and carries the theoretically-sound Plan-3 changes (flag decay, growth-out-of-quality,
Altman gating) beyond the weights. But the framing is now honest: v1≈v2w, no clear winner,
no proven alpha — the forward ledger remains the only clean test.

**Published honestly:** backtest.json extended to 2012 with the pre2012-15 validation row
and 3 new/updated caveats (survivorship grows to ~54% pre-2016; the KEY FINDING that v2w
underperforms OOS; betas fall back to ~1.0 in 2012-2013 as Yahoo price history starts
2011-08). Dashboard + share render them. This is the project's 4th published humbling result.

## Plan C — Momentum overlay study (2026-07-06) — IN PROGRESS

**Goal:** momentum is the ONLY green number the lab ever produced (Plan 6: standalone 12-1
topped the per-method table, NDX +2.03%/q, but the fixed-weight z-blend v3/v3m FAILED split
validation). The lead was: quarterly rebalance is too blunt for momentum; test it MONTHLY,
standalone + as an overlay/filter, with a crash-protection regime filter, on the extended
2012-2026 data with the pre2012-15 OOS window. Momentum is price-only (no PIT/engines), so
a dedicated monthly backtest is cleaner than retrofitting the quarterly harness.

**Built:** `momentum.py` — 12-1 momentum, monthly rebalance, top-quintile, equal-weight,
vs equal-weight benchmark, on the survivorship-aware membership + price_monthly. Variants:
gross, net 10bp/side, net 25bp/side, and a market-trend crash filter (MOM+trend). Four
windows incl. pre2012-15 (OOS) and 2022-2026 (highest coverage ~87% = least survivorship).
6 tests. Also wired a LIVE per-name 12-1 momentum + within-universe percentile into
output.json (from price_monthly, calendar-based so relistings yield None not a bogus ratio).

**RESULTS (excess CAGR vs equal-weight bench, NET of 10bp/side · hit rate):**

| window | NDX | SPX |
|---|---|---|
| full 2012-26        | **+5.61pp/53%** | +1.17pp/52% |
| **pre2012-15 (OOS)**| **+6.08pp/58%** | +3.23pp/56% |
| 2016-2021           | +3.25pp/50% | **−3.46pp/43%** |
| 2022-2026 (hi-cov)  | **+8.22pp/54%** | +5.68pp/59% |

Turnover only ~25%/month (winners persist). At a conservative 25bp/side, NDX full is still
+4.53pp/yr. The MOM+trend crash filter did NOT help (long-only momentum isn't the classic
crash victim) — dropped it from the headline.

**VERDICT — POSITIVE (the project's FIRST demonstrated edge), on the growth universe.**
On the Nasdaq-100, momentum is real and robust: net-of-cost positive in ALL FOUR windows,
including the 2012-2015 window that PREDATES all our signal design (true OOS, +6.08pp) and
the 2022-2026 window that has the LEAST survivorship (+8.22pp — the strongest evidence it
is not a survivorship artifact; a survivorship-driven result would concentrate in the
low-coverage early years, not the clean recent ones). On the S&P 500 momentum is weak and
regime-dependent (+1.2pp full but −3.5pp in 2016-2021) — it pays in the trendier growth
universe, not the broad market. This is consistent with the entire academic literature:
momentum is the most robust anomaly, and it lives in trending universes.

**What we did with it — displayed factor, NOT blended.** Per-name 12-1 momentum + percentile
now render on the board and a Methodology "Momentum factor" panel presents the study honestly.
It is deliberately NOT folded into the fair-value composite (Plan 6 proved dilution destroys
it; the live model stays v2.2, value-based). Momentum and value are orthogonal strategies —
surfaced side by side, not averaged.

**Caveats (foregrounded):** momentum is well-known/crowded (no proprietary edge); −20% to
−33% drawdowns are real; early-year survivorship still flatters it (mitigated but not
eliminated by the strong hi-coverage-window result); costs beyond spread (market impact,
borrow) not modelled; the live per-name score reads price_monthly, which the incremental
prices.py does not advance for existing names — it is fresh now but a betas-piggybacked
monthly refresh is the robust follow-on. Net: a real edge, honestly bounded — not a
free lunch, and not blended into the honest fair-value screen.

---

## Review pass — Fable-5 audit of Plans A/B/C (2026-07-07) ✅

Requested review of the Opus-era work (Plans A/B/C + per-ticker momentum). Verified the
worklog claims against the code and data; overall verdict: **architecture and honesty
discipline held up well — no correctness errors in the router, ledger, or momentum math.**
Five real misses found and fixed (three user-facing):

1. **Deep Dive method-weight column stale since Plan 3** (pre-dates Opus — my own miss:
   the Plan-3 sweep grepped Methodology.tsx but not DeepDive.tsx). The "Weight" column
   showed the OLD blend (DCF 25/RIM 20/W 25) while engines.py has used DCF 10/RIM 35/W 30
   since v2. Every ticker page displayed wrong weights for four model versions. Fixed +
   sync comment.
2. **RIM-gated financials displayed garbage om/ROIC** (85/90 names — e.g. HBAN "op margin
   172%", which is a net-interest-income ratio, not an operating margin; ROIC on
   deposits/float is meaningless). Same honesty rule that nulls fcfy/EV-EBITDA/ND-EBITDA
   now covers om/roic; FCF-routed asset-light names (V/MA) correctly keep theirs.
3. **`FYundefined–FYundefined`** rendered in the Deep Dive trends header for SYF/TFC
   (no mapped annual series) — guarded.
4. **Live momentum would silently stale**: momPct reads price_monthly, which the REFRESH
   flow never advanced. betas.py (already fetching 5y monthly bars per live ticker every
   refresh) now upserts close+adjclose into price_monthly (incl. ^GSPC) — live momentum
   self-refreshes with zero extra network.
5. **Methodology ledger panel always showed the Nasdaq ledger** regardless of the universe
   toggle — now fetches ledger_<id>.json per universe (share build still embeds default-only).

Minor tidy: dead `rf` threading removed from momentum.py. **Noted, deliberately NOT
churned:** (a) quality percentiles for gated financials still ingest the raw om/roic/lowlev
dims (contained — banks are conf-2 RIM names; a proper "bank quality" composite is a future
refinement, not a hotfix); (b) the backtest engine stack still lacks the archetype gate
(pre-existing, documented divergence — re-validating v2w with the router is real work);
(c) frontend WEIGHTS duplicates backend CENTRAL_WEIGHTS by hand — exporting weights via
meta would kill this class of drift; deferred. Also: prior commit messages said "44 tests";
the true count was 64 (now 70). All 70 green; outputs regenerated; share rebuilt.

---

## Design audit — correctness floor + system enforcement (2026-07-07)

Senior-designer pass over the dashboard: taste baseline derived from BLUEPRINT/UI_SPEC/
handoff ("a calibrated instrument: one semantic color system doing all the talking,
honesty visible but not shouting"), then all four screens walked in a real browser at
1440px and at a 720px CSS viewport (= 200% zoom). Six commits, each isolated and
revertible; UI_SPEC + handoff README amended where the docs themselves were the problem.

**Floor (fixed unconditionally):**
1. **Keyboard/AT access was near-zero** — 3 focusable elements in the whole app (search
   + 2 sliders, and the sliders suppressed their outline). Every control was a div
   onClick. Now: real buttons with roles everywhere (nav aria-current, sector checkboxes,
   mcap/agreement radiogroups, hide-traps switch, watch-star aria-pressed, menu items),
   header/nav/main/aside landmarks, h1 per screen, global :focus-visible, search is a
   real combobox (arrows/Enter/Escape), table rows tabbable (Enter opens Deep-Dive),
   universe menu closes on Escape/outside-click. 30+ focusable per screen.
2. **Contrast** — dim #626b7a (3.6:1) and dim2 #525c6b (2.9:1) failed WCAG AA at the
   9-10px sizes they labeled; raised to #7d8798/#727c8d (>=4.5:1) preserving hierarchy.
   Type floor 10px (was 8.5-9.5 in tags/chips/labels).
3. **200% zoom broke Deep-Dive** ($196.08 overflowed the hero card; top-bar timestamp
   spilled over the KPI strip). Top bar wraps; dd-grid/mt-* grids collapse <=1080px;
   KPI strip auto-fits; body never scrolls horizontally.
4. **Scatter lied at the edges** — fixed [-45%,+55%] domain piled the -80% tail onto the
   -45% edge. Domain now fits the data (zero line + money zone always in view).
   Empty-filter state added. Tooltip now clamps vertically (flips above cursor).
5. Missing specced states added: stale-data banner (>24h), scatter empty state, CSV
   disabled at 0 rows, row hover (specced in handoff, never built), preset chips now
   show active state.

**System enforcement (the app violated its own UI_SPEC §2):** fairly-valued (+-4%) was
amber = caution -> now neutral; momentum wore Communication Services' exact #b58cf0 ->
neutral value + blue bar; sparklines used green/sector-purple/staples-teal -> one
informational blue; range-bar mid tick dimmed so the price line is the sole protagonist;
sort arrows green -> blue (interactive accent); two ghost gradients flattened.

**Deliberately NOT done (L3, needs owner sign-off):** shares-outstanding trend sparkline
(payload lacks the series — backend value.py change; UI_SPEC C calls it out as the
dilution watch); ratio-bar denominators (roic/0.3, om/0.6) present fixed scalings as if
sector-relative — real sector percentiles are a backend feature; Deep-Dive "why cheap"
bear-case line is boilerplate (only two variants) — either template real drivers or cut;
card titles as h2s; dot-level keyboard access on the scatter (Screener is the documented
keyboard path). Share build rebuilt post-audit.

---

## L3 proposals implemented (2026-07-07, afternoon)

All four audit proposals green-lit and landed, one commit each:

1. **Shares-outstanding trend** (`c461f24`) — value.py emits `trends.sharesM` (same
   annual series Piotroski #7 reads); Deep-Dive gains the fifth sparkline from the
   handoff with inverted delta color (falling count = buybacks = green). Optional in
   the type contract: pre-refresh payloads render n/a.
2. **Real percentile ratio bars** (`9faf3e6`) — ROIC / op-margin / growth bars now rank
   within covered sector peers (>=5 names, else whole universe, basis labeled under the
   panel, exact percentile on hover). Kills the roic/0.3-style fixed scalings that
   painted a 26% margin red. Frontend-only: the universe is already client-side.
3. **Evidence-based bear/bull case** (`91d0877`) — the canned two-variant sentence in
   "Why does the market disagree?" replaced with drivers the pipeline measured:
   reverse-DCF gap (respecting bound operators), momentum percentile, quality tier,
   agreement. Honest fallback when nothing measured explains the gap. Verified live:
   AAPL bull case cites 23% implied vs 9% trailing + 69th-pct momentum + Q82.
4. **Hash routing** (`fd98bfb`) — `#/deep/GILD` deep links, Back/Forward, refresh keeps
   place; first sync replaceState (file:// fallback for the share build); invalid
   hash/ticker falls back gracefully. Verified: deep-link -> screener -> Back -> MSFT.

**Incident, resolved:** a user-initiated REFRESH DATA.cmd (ingest_v1.py, started 12:44)
drops+rebuilds companies/financials first — my `value.py all` (run for sharesM) raced
the half-rebuilt DB and overwrote the tracked outputs with 34-39-name partials, and
backend/data/output.json (share source) likewise. Restored all outputs from git/public
(Jul 06, 96 names); share rebuilt at 96. Four partial snapshots (34/38/39 names,
13:14-13:19) remain in the append-only history by design — ignore them when diffing.
The running refresh will regenerate everything, now including sharesM, when it
completes. Lesson encoded here: don't run value.py while an ingest is mid-flight.

---

## CEO batch — meta v2, tape preset, windowing, phase plan (2026-07-07 evening)

Follow-through on the approved action plan, after the ingest race resolved (user's
REFRESH completed 17:52 — full 96/482 coverage, first sharesM payloads; the partial
13:xx snapshots stay in history as honest records of runs against a half-built DB).

- **meta v2 (`0d7e460`)**: value.py now emits `weights` (CENTRAL_WEIGHTS, single
  source of truth — the frontend hand-mirror that drifted once is demoted to
  fallback) and `changes` — a digest vs the last comparable PRIOR-DAY snapshot
  (coverage ≥80%, same model; same-day dev reruns never become the baseline).
  Zone entries/exits, flag adds/clears (INFO_FLAGS excluded), conf jumps ≥2,
  upside swings ≥15pp, coverage joins/drops. Overview renders it as a strip under
  the KPIs. First live diff (Jul 06→07): MNST conf 5→3, NBIS +190→+227%, CSX −27→−51%.
- **Tape preset + windowing (`115a097`)**: minMom filter + "Value confirmed by
  tape" preset (the only intersection our own studies support). Full-SPX result
  today: 3 names — GILD, LMT, AMGN. Row windowing >150 rows (~35 rendered of 482,
  honest scrollbar); found+fixed en route: the table wrap was never the real
  scroller (root grew under minHeight), so sticky header/toolbar now pin properly.
- **Ops**: BUILD_PLAN phase roadmap (gates before universe growth); weekly
  scheduled refresh Sundays 09:00 via `/auto` flag, logged to backend/data/refresh.log.
- Share rebuilt from the audited frontend + fresh data. Backend suite 70/70.

---

## Phase 1.1 — financials archetype: banks scored as banks (2026-07-07, v2.3)

**The problem:** 90 covered financials/REITs (SPX) carried quality scores built from
NII-ratio "operating margins" (HBAN 172%), deposit-book "leverage," and meaningless
FCF margins — and those garbage values sat in every standard name's percentile pool
too. JPM wore a false "Piotroski 2/9" trap flag (current-ratio/leverage signals are
undefined for banks — the same validity problem Altman-Z already gated).

**The fix (v2.3):** L5 routing hoisted above scoring (decided once, stashed on the
row, consumed by quality AND the engine loop — no drift seam). Quality is now
archetype-aware: financials/REITs rank on ROE level, ROE stability (population stdev,
≤6 FY, ≥3 obs), and equity/assets (3-FY mean capital cushion) among covered financial
peers; pools under 5 emit None, never a fake rank. Standard names keep the original
five dims with cleaned pools (median |Δquality| = 2pts across 380 movers; the big
moves are financials getting first honest scores: APO −46, SCHW −39, MET −37, VTR +51).
Piotroski n/a for fin/reit. Payload gains archetype/roe/roeStd/eqAssets; Deep-Dive
shows the bank panel (ROE, stability inverted-percentile, equity/assets) and swaps the
strip to equity/assets · ROE · stability · div yield.

**Gate (passed):** JPM 15.4% ROE / ±2.3pp / 8.4% eq-assets · BAC 10.0%/9.0% ·
GS 12.4% volatile / 7.1% dealer-thin · USB/PNC regional ~11.5%/9-10% · PGR 22.5%
/±11.4pp/23.9% — all match public reality. V/MA/PYPL stay standard-routed (Q91/94/n-a).

**RIM Re-sensitivity (measured, 90 names):** ±100bp of Re moves the mid only ∓2.2%,
uniformly — the ω=0.62 fade dominates and values are book-anchored. Consequence
stated on the RIM Methodology card: financial-sector "overvalued" is an expectations
meter, not a short signal (JPM at 2.4× book can never screen cheap under a 5y
excess-return fade). ω deliberately untouched — no model change without time-split
validation (standing rule).

**Logged, not fixed here:** CSGP (CoStar) is GICS Real Estate → routed reit → RIM on
book for what is really a data/software business; seeded as the first Phase-1.3
override-table entry. REIT quality uses the interim bank dims until FFO/NAV lands
(Phase 1.2). Tests 70 → 78 green; share rebuilt.

---

## Phase 1.2 — REIT P/FFO engine: RIM-on-book retired (2026-07-07, v2.4)

**The problem:** all REITs were RIM-priced on historical-cost book — systematically
wrong for the asset class — and six of the biggest (AMT, CCI, EQIX, IRM, SBAC, SPG:
negative or distorted book) were unpriceable-excluded entirely.

**The fix (v2.4):** FFO = NI + D&A − property-sale gains + RE impairments (NAREIT
shape). The gains/impairment tags are wired into the ingest map (RE-specific tags
only) and land with the next scheduled refresh; until then each name's method note
discloses its basis (NI+D&A) — never silently mixed. Value = capped covered-median
P/FFO × FFO/share (8–20×; None under 5 peers → legacy RIM path, e.g. NDX). FFO
replaces RIM for priced REITs; REIT_RIM_FLAG retired for them (1 legacy holdout).

**Gate (passed):** anchor 15.6× on 31 SPX REITs = 6.4% FFO yield, dead-center of
historical REIT territory; median REIT upside +1% (a relative engine must center);
AMT −5%, O −6% read plausibly. Coverage 482 → 488.

**Instructive tails, logged:** SPG +44%/VICI +52% (malls/gaming trade below-median
street multiples) and EQIX −47% (data centers above) are the flat-anchor artifact —
same bucket-limitation as TECH in the warranted engine; folded into the Phase-1.3
override/split work. CCI −47% additionally proved the impairment add-back matters
(its fiber writedown halves computed FFO) — tag wired, test added for the shape.

Tests 78 → 84 green. AMT deep-dive verified live: P/FFO $156.72 carries the mid at
100% weight, RIM row reads "replaced by P/FFO", no REIT flag. Share rebuilt.

---

## Phase 1.3 — warranted TECH split + the override table (2026-07-07, v2.5)

**The problem:** one TECH bucket mixed 13× services with 35× software — every anchor
was a compromise — and the v2.3 audit had already caught GICS misrouting CSGP (a
data/software business) into the REIT engine.

**The fix (v2.5):** `assumptions.toml [overrides]` — the manual-override table
BLUEPRINT L1c promised. Archetype override corrects CSGP → standard; a 78-name
subsector hand-map splits TECH into semis/software/hardware. `assign_buckets()`
enforces ≥8 FITTED names per split bucket, else members roll back to the parent
sector (NDX hardware, 5 names, rolls back; SPX holds 23/20/23). Unmapped names stay
in the parent on purpose — a wrong bucket is worse than a coarse one. Precedence:
override > SIC map > sector; the SIC default layer is deferred to Phase 2's bulk
submissions.zip, where it's one download instead of 513 throttled calls.

**What the data said (gate passed):** software anchors at 23.7× (uncapped); semis
AND hardware sit AT the 28× cap — the 2026 AI-hardware bid is real and the froth
cap is doing exactly its job. The biggest honesty win is the leftover IT-services
bucket at 13.7×: CDW/CTSH/ACN/IT had been riding the whole-TECH froth anchor and
gave back 47–87pp of upside (CDW −87pp). CSGP now prices on FCF engines at conf 5
(warranted honestly N/A — EBIT too thin), and its exit purified the REIT pool
(31→30, anchor 15.6→15.4×). Coefficients refit on cleaner bucket-centered
residuals → broad sub-2pp ripples across standard names, by design.

Tests +6 → suite green. Share rebuilt. Phase 1 remaining: 1.4 point-in-time SPX
membership + survivorship re-test (the product-positioning decision gate).

---

## Phase 1.4 — survivorship measured; the decision gate closes (2026-07-07)

**What 1.4 turned out to be:** membership was already point-in-time (membership.py
walks Wikipedia change tables backward; 58 quarterly member sets per universe) and
the backtest already consumed it. The real residual was members we cannot price —
delisted names EDGAR/Yahoo no longer serve — absent from BOTH strategy and
benchmark, labeled "direction unknown" in the caveats. That unknown is now a number.

**The measurement:** covered equal-weight pool vs the real equal-weight index funds
(RSP for SPX, QQQE for NDX — like-for-like weighting isolates coverage bias from
cap-vs-equal effects), on identical quarters, from 15y of monthly TR history now in
price_monthly (betas.py keeps SPY/QQQ/RSP/QQQE fresh weekly).

| window | SPX gap vs RSP | NDX gap vs QQQE |
|---|---|---|
| full 2012-26 | +1.4pp/yr | +2.8pp/yr |
| pre2012-15 | +1.3pp | +3.5pp |
| fit2016-21 | +1.9pp | +2.5pp |
| holdout2022-26 | +0.8pp | +2.1pp |

The gap shrinks exactly where coverage is best (2022-26) — the mechanism is what we
said it was. Emitted as backtest meta.survivorship, a measured caveat (replacing
"direction unknown"), a printed table, and a Methodology block.

**DECISION GATE, closed:** the composite's nominal excess (+0.03pp SPX; negative in
most variants/windows) sits far inside the measured +1.4pp tailwind. After honest
accounting there is no demonstrated edge. The positioning is now WRITTEN in the
Methodology verdict box: **expectations meter + trap gate + momentum overlay — not
an alpha signal.** Momentum's excess is computed within the same covered pool on
both sides (+0.50%/q SPX, +1.63%/q NDX top-quintile), so the universe-level haircut
doesn't erase it — it remains the one evidence-backed overlay, with its own caveats.

Phase 1 complete: 1.1 financials ✅ · 1.2 REITs ✅ · 1.3 TECH split + overrides ✅ ·
1.4 survivorship + gate ✅. Next: Phase 2 (bulk EDGAR/price plumbing) — where the
delisted-name data gap this measurement quantified can actually be closed.

---

## Phase 2 — plumbing for scale: bulk EDGAR transport (2026-07-08)

**The headline:** the SEC's nightly `companyfacts.zip` (~1.4GB, 20k XBRL filers) +
`submissions.zip` (~1.6GB, 976k filer headers) replace ~520 throttled per-ticker
API calls. **Full union ingest: ~5h → 120s** (515/518 names, 0 API calls, coverage
guard green). Gate ("<10 min after download") PASSED by 5×. `bulk.py` handles
conditional download (If-Modified-Since + atomic .part rename), random-access member
reads, and a `filers` scan. The scan reads ONLY the header prefix of each submission
member (everything before the multi-MB `"filings"` object — unambiguous since that
byte sequence can't occur inside a JSON string) → ~15k filers/s, whole corpus in 27s.

**Delisted CIK recovery (the session's stated hope) — measured, half-closed.** The
gap the 1.4 survivorship number quantified has TWO halves; bulk EDGAR closes exactly
one:
- **Fundamentals half — CLOSED.** `pit_meta` no_cik **170 → ~55** (recovered ~115
  delisted names). The SEC BLANKS the `tickers` field on deregistration (SVB, First
  Republic read `tickers:[]`), so a dead ticker maps to its CIK only by NAME. The
  filers scan stores each filer's normalized current+former names; `resolve_delisted`
  two-tiers exact→unique-substring against them. Spot-checked all 75 first-pass
  recoveries by hand — every one correct, including hard renames (ADS→Bread Financial,
  RIMM→BlackBerry, JDSU→Viavi, NLOK→Gen Digital, DV→Covista via the CIK's own
  `formerNames` "DEVRY EDUCATION GROUP").
- **Price half — NOT closeable (honest negative).** Yahoo 404s every delisted name
  (SIVB/FRC/ATVI/TWTR/DISH); Stooq (the specced alternative) is now access-restricted
  (bulk zip HTTP-401, per-symbol CSV behind a SHA-256 proof-of-work then "Access
  denied"). Of the ~115 recovered fundamentals, only **~7** also have prices, so only
  7 became usable in the backtest. The +1.4pp/+2.8pp survivorship haircut therefore
  STANDS — it is price-bound, and closing it needs a paid delisted-price source
  (CRSP), exactly as the Phase-8 note foresaw. Documented, not papered over.

**Latent correctness bug FOUND + FIXED (the real prize).** Some delisted tickers get
REASSIGNED to new companies (Sprint's `S`→SentinelOne, Spectra's `SE`→Sea Ltd,
Pepco's `POM`→POMDoctor, DeVry's `DV`→DoubleVerify). The current-ticker map — used by
BOTH the old API path and the new bulk map — silently resolved these to the NAMESAKE,
injecting the wrong company's fundamentals into the backtest's PIT store. Fix:
`pit.py` now name-validates every DELISTED member (active constituents keep the
authoritative live ticker). `cik_name_matches` uses spaceless-containment
(`SIRIUSXM`⊂`SIRIUS XM`, `VF`⊂`V F` accept; `PEPCOHOLDINGS`⊄`POMDOCTOR` rejects) so
renames pass and namesakes are rejected to an honest no_cik. Verified: POM→Pepco,
S→Sprint, SE→Spectra all now resolve to the RIGHT CIK or reject.

**Bulk prices — kept Yahoo (correctness over a minor speedup).** Yahoo's batched
`spark` endpoint returns close-only (no adjclose/splits) — a raw close across a split
date is a fake −50% return, unsafe for betas/backtest. The proven per-symbol
`v8/chart` path (adjclose+splits, already incremental) stays. EDGAR was the 5h
bottleneck; prices/betas were always ~8min. Stooq unavailability documented.

**L0 hygiene — visible exclusions (BUILD_PLAN honesty law).** `hygiene_reason` in
value.py: sub-$1 price, SPAC/blank-check (SIC 6770), and instrument-class names
(warrant/right/preferred/depositary). Deliberately high-precision — ticker-suffix
guessing (…W/…U) is avoided (Wayfair, Unity), and "Unit Corporation" must not trip.
No-op on the current clean large-caps (0 fired), the gate for the broad universes.

**SIC subsector defaults (Phase-1.3 deferral, now free from bulk).** SIC codes land in
`companies.sic` at ingest; `assumptions.toml [subsector_by_sic]` maps only the
NON-conflicting codes (3674→semis, 7372→software, 3571/72/76→hardware). Precedence
override > SIC > sector; SIC fires only inside Information Technology. Standalone SIC
reproduces the 78-name hand-map for **54/54 = 100%** of names it has an opinion on;
the 24 conflicting/parent-SIC names (QCOM 3663 vs MSI 3663; FTNT/PANW under a
peripheral-hardware SIC) correctly defer to the hand-map. S&P split nudged 23/20/23 →
24/21/24 as the default auto-buckets uncovered IT names.

**S&P 1500 dry run — the NYSE go/no-go, PASSED.** New `dataquality.py` ingests the
S&P 500+400+600 union (1503 names) via the bulk path WITHOUT touching the live picker,
measuring coverage + per-concept tag-fallback rate. **Coverage 99.1% (1490/1503,
≥15/25 concepts) in 62s → GATE PASS (≥90%).** Highest tag-fallback concepts surfaced
(interest_exp 85%, short_debt 80% rely on non-primary tags — where the map thins on
smaller filers). Emitted `data_quality.json` → a live Methodology data-quality panel
(GATE PASS badge + stat tiles + fallback chips), verified rendering in the browser.

**Refresh + tests.** `REFRESH DATA.cmd` gains step 0 (bulk download + scan) and step 7
(dataquality gate). Tests 93 → 112 (`test_bulk.py`: normalization, name-match/namesake
guard, header-prefix parse, hygiene, SIC precedence). Both Phase-2 gates PASSED:
ingest <10min AND S&P 1500 ≥90% coverage — the two conditions for Phase 3 (widen).

---

## Phase 3 — widen: S&P 1500 live in the picker (2026-07-08)

Both Phase-2 gates passed (ingest <10min, S&P 1500 dry-run 99.1%), so the broad
universe goes live. `universe.py` gains an `sp1500` source (500 ∪ 400-mid ∪ 600-small,
deduped) and a `[[universe]]` block (min_mcap 0.3e9 — a small-cap FLAG threshold, not
a filter). The junction + `value.py all` + `ledger.py all` machinery already fan out
per-universe, so scoring and the forward ledger came almost for free.

**Pipeline at scale (all bulk-backed):** ingest 1510/1518 names in 348s (0 API calls);
betas 1492; 447k datapoints; coverage guard green. **value.py scored 1444 S&P 1500
records.** The widening delivered exactly the promised "statistical teeth": the
warranted anchor now fits on **989 names across 12 sector anchors** (was ~400), the
TECH split runs deep (semis 42 · software 55 · hardware 33), and the REIT P/FFO anchor
sits on **105 REITs**. Archetype router at scale: standard 1095 · financial 244 ·
reit 105. Top picks are now mid-caps (EXEL, BKE, QLYS, BAH) — the mid/small-cap
cross-section the large-cap-only board never surfaced.

**L0 hygiene fired 0 times** on the S&P 1500 — correct, not a bug: the S&P selection
committee already excludes sub-$1 names, SPACs, warrants and units. Hygiene is the gate
for the *full-NYSE* universe (below), where those instruments actually appear.

**Screening-only honesty (the load-bearing UX).** The S&P 1500 publishes NO backtest,
by design — a credible survivorship-free curve needs delisted-member price history, and
that gap is WORST for small-caps (they delist most; no free source serves their prices —
see [[delisted-price-gap]]). Methodology now:
- shows a context-aware toggle (defaults to the board's universe) with an "S&P 1500 ·
  screen" marker;
- renders a "Screening universe — no backtest by design" panel explaining the price-gap
  reason instead of faking a curve;
- keeps the **forward paper-trading ledger** as the broad universe's own evidence
  (ledger_sp1500.json, inception today) — "cannot be flattered: the picks were committed
  before the returns existed."
The NASDAQ-100 / S&P 500 backtests (constituent-based, survivorship measured) still
render exactly as before — regression-verified in the browser.

**Scatter outlier fix (the real density problem).** At 1500 names the universe-map
axis auto-scaled to the single most extreme upside — a distorted small-cap at **+23000%**
blew the X-axis out and crushed every real name onto the left edge. Fixed with a ROBUST
domain: the upper bound tracks the ~96th percentile (not the max), capped at +250% for
readability; the ~62 outliers clamp to the right edge and are COUNTED honestly ("62
names beyond axis (clamped) →") — never a silent crop. Axis now reads [-50%, +100%];
1450 SVG circles render fine, so canvas wasn't needed. Verified in the browser.

**Deferred honestly — full NYSE as a screening universe.** The third Phase-3 bullet
(all NYSE large+mid) is the next increment, not done here: it needs a SIC→sector map for
the thousands of non-S&P filers (no clean Wikipedia constituent list) and would put L0
hygiene to real work. The S&P 1500 is the gated, ready deliverable; NYSE builds on this
same plumbing when we take it.

Tests 112 → 115 (sp1500 universe config). Frontend prod build + share rebuilt.

---

## Single-method honesty — presentation fix (2026-07-08)

**The complaint (real):** at S&P 1500 scale, many names show a lone valuation method,
and the UI read that as low confidence ("2/5 agreement"). Investigated: it is NOT a
data gap. Of 380 single-mid-engine names, **261 are financials (RIM-only) and 98 are
REITs (P/FFO-only) — single-method BY DESIGN** (DCF/EV-multiples are meaningless for
balance-sheet businesses); only **21/1444 (1.5%)** are standard names dropping an
engine, and those are legitimately un-valuable inputs (negative/buyback-distorted
book), not un-ingested data. Bulk EDGAR coverage is fine.

**Root cause of the bad read:** `triangulate` returns `conf = 2` for BOTH "a single
engine applies (can't demonstrate agreement)" AND "multiple engines disagree" — the UI
then labeled everything conf≥2 as "moderate", so a solid single-method REIT looked as
shaky as a broken standard name, and genuine disagreement was hidden.

**Fix (display-only — no scoring change, no validation burden):**
- value.py emits `nMethods` (= applicable growth engines) alongside conf.
- New `agreement(conf, nMethods)` helper: `nMethods≤1` → "single method (by design)"
  (neutral, not a misleading /5); else conf≥4 high · conf 3 moderate · conf 2 **low**.
- Applied on the Deep-Dive (subtitle, the "why soft" note, the Method-agreement card
  now explains "Only RIM applies… N/A by design… no cross-engine agreement to measure"),
  the scatter tooltip, and the Screener column ("1 method" instead of a 2/5 meter).
- Verified live: JPM/REITs read "single method (by design)"; AAPL reads "low agreement ·
  2/5" (0 of 2 engines within ±10% — the honest read the old "moderate" hid).

Side effect worth flagging: ~900 multi-method names now read "low agreement" where they
used to say "moderate" — because their engines genuinely diverge >10%. That's honest
information (wide fair-value ranges), not a regression; the underlying divergence is what
the DDM plan below and future model work address. Tests 115 (unchanged — display-only).

**Queued next (the substance): DDM reactivation.** DDM is one of the seven canonical
engines but is hardcoded off for every name ("few payers" — true for the NDX, false for
the S&P 1500 where 299 of the single-method names pay dividends). Banks and REITs are
dividend machines (REITs must distribute 90% of taxable income). Building a conservative
multi-stage DDM and activating it for dividend-paying archetypes gives banks RIM+DDM and
REITs P/FFO+DDM — a real second triangulation point, using an existing engine (not an
eighth). It is a MODEL change, so per the standing rules it must beat v2.2 in a
time-split backtest on NDX/SPX before it ships. Scoped as the next plan.

---

## Phase 3.1 — RIM scoped + DDM reactivated (2026-07-08, model v2.6)

**Trigger:** the S&P 1500 board read "low agreement" on ~900 names. Diagnosed (data,
not vibes): 69% of multi-engine names had estimates >2× apart, and **RIM was the low
outlier 78% of the time / a garbage-low outlier (<60% of the next engine) 61% of the
time** on standard names. RIM is a book-anchored FINANCIALS engine; on buyback-heavy /
asset-light firms (ACN RIM $71 vs DCF $323 / Warr $437) book understates value, and at
the highest blend weight (.35) it dragged the mid AND manufactured false 3-way
disagreement. Even without RIM, DCF-vs-Warranted still differ ~1.7× median — real
intrinsic-vs-relative divergence, not a bug.

**The fix (v2.6):**
- **RIM scoped to financials/REITs.** `rim_ps` enters the mid only for
  `eff_arch != "standard"`; standard names show it N/A-with-reason. Halved the ">2×
  apart" names (725→343) and doubled the tight-agreement ones.
- **DDM reactivated** (an existing engine, hardcoded off since the NDX's "few payers" —
  false for the S&P 1500 where 299 single-method names pay dividends). Multi-stage
  Gordon, discounted at Re. Guards: meaningful yield ≥1%, payout covered by earnings
  (REITs exempt — pay from FFO), and **dividend growth clamped to [0,8%]** (raw
  revenue-CAGR overstated acquisitive REITs — O $148→$76 — and let a bank's declining-g
  compound the dividend to ~zero). Fixed a real data bug on the way: BAC (and peers)
  drop `PaymentsOfDividendsCommonStock` after ~2013 for `DividendsCommonStockCash` —
  added the tag, so DDM runs on the current dividend, not a stale $0.24.
- Result: banks get RIM+DDM, REITs P/FFO+DDM, standard payers DCF+Warranted+DDM.
  **Single-method 26%→11%.** Most names now triangulate on 2–3 methods that mean
  something.
- **Agreement reframed (display).** Dropped the "/5" denominator — 5 was never the
  target. `agreement(conf, nMethods)` reads relative to the APPLICABLE set: "single
  method (by design)" for one; else Strong/Fair/Wide-range among the methods that apply.
  A REIT on P/FFO+DDM that agree reads Strong, not "2 of 5, low". 5-dot meters gone.

**The honest part — it does NOT beat v2.2 in the backtest.** Added variants v2r
(RIM-scoped) and v2rd (+DDM); ran both universes, all windows:

| variant | SPX full | NDX full |
|---|---|---|
| v2w (was adopted) | +0.03pp | −1.94pp |
| v2rd (shipped) | −0.94pp | −3.83pp |

v2rd loses ~1–2pp. The garbage-low RIM was, perversely, an accidental cheapness proxy
that helped the RANKING. **Shipped v2rd anyway** (user decision, with my recommendation):
the composite is not an alpha signal (Phase 1.4 verdict), the gap sits inside the
measured +1.4/+2.8pp survivorship band — i.e. two edge-less signals, one 1pp prettier —
and shipping v2w would mean knowingly showing ACN=$71 because a broken number ranks
marginally better. Honesty over the prettier curve. `ADOPTED` switched v2w→v2rd so the
published curve matches what ships; the **forward ledger is the real arbiter** from here.
Tests +5 (DDM goldens). Model v2.6.

---

## Phase 3.2 — model strengthening from external critique (2026-07-08, model v2.7 → v2.8)

**Trigger:** two independent AI reviews of the "how each engine values a company" +
"global assumptions" methodology. Both graded it professional-grade; both led with the
same headline fix (adaptive/Bayesian engine weights). The useful move was to ground every
suggestion against the actual code first — **~half their headline fixes already shipped**
(live FRED risk-free, terminal g capped at rf, RIM gating, the quality score, extensive
backtesting, sector buckets). One was simply **wrong**: "single WACC/beta is the biggest
weakness" — per-name Blume-adjusted 5y betas have been live in `betas.py` since Phase 3;
`beta_default=1.0` is only the missing-data fallback (its "PLACEHOLDER" comment was stale,
now fixed). The **adaptive-weights** headline was declined: the archetype router already
does the coarse, defensible version (engine sets on/off by business type), and continuous
per-name weights add a pile of unvalidatable free parameters — exactly the overfit trap
Phase 1.4 warns against. What survived as genuinely additive became Tier 1 + Tier 2.

### Tier 1 — DCF base + cyclical normalization (model v2.7)

**The Amazon defect.** The DCF/reverse-DCF base was `avg 5y FCF-margin × revenue`, which
counts growth capex as if it were lost cash and so structurally undervalues any reinvestor.
Measured, it was worse than "undervalues" — **AMZN got NO DCF at all** (its normalized FCF
came out unusable), and the semis showed DCF as an absurd low outlier (TXN $40 vs mid $127)
with ~40% implied growth.

**Fix:** base = **normalized NOPAT − the reinvestment growth requires** (`FCFFₜ =
NOPATₜ·(1 − gₜ/ROIC)`, McKinsey value-driver form). Reinvestment fades as g fades, so the
depressed current FCF margin is no longer treated as permanent. DCF now shares EPV's
earnings base; falls back to the old FCF base when ROIC is unusable (nothing breaks).
Reinvestment clamped to [0, 0.90] so the stream stays FCF-positive.
- **Cyclical normalization:** `om`/FCF margins normalize over **10y when rev-vol > 0.18**
  (the *same* threshold that raises the Cyclical flag — one definition), else 5y. 31/94
  NDX names trip it (semis, energy, travel, hypergrowth).
- **Guards that fell out of it, each a real edge case:** non-positive DCF → N/A (debt-heavy
  low-margin names like XEL produced negative per-share DCFs; now match triangulate's own
  `v>0` rule); reverse-DCF implied growth → n/a when **ROIC ≤ WACC** (the capped kernel is
  non-monotone in g there, so the solve is degenerate — 20 names); and the EPV "floor" note
  turns honest when EPV > mid (3 names, all conf-2: at ROIC<WACC the no-growth value is a
  ceiling, not a floor).

**Impact:** every standard name now has a DCF (93/93). Median mid change **3%** (DCF is 10%
weight); 11 names moved >20%, **all conf-2 cyclical/distressed**. FANG collapsed +604% → −83%
— the *old* number was the broken one (peak-oil extrapolation); the 10y window + reinvestment
charge correctly refuse to annualize peak margins, and the engines now openly disagree (conf 2)
at the cyclical peak (MU: DCF $107 vs Warranted $1,459) rather than printing false confidence.

### Tier 2 — three adaptivity upgrades (model v2.8)

- **Size premium** added to Re (`rf + β·ERP + size_prem`), CRSP-decile bands in
  `assumptions.toml` (+0/+0.3/+0.8/+1.5%). **0 across the NDX** (all >$10B, correct); built
  to bite on the S&P 1500 small caps where the cross-sectional value evidence lives.
- **ROIC is now a third within-bucket driver of the warranted multiple** (sign-guarded ≥0,
  alongside growth/margin). A 35%-ROIC name earns a higher multiple than an 8%-ROIC peer.
  This is the main mid mover: median **4%**, 23 names >10%, and the direction is a clean
  sanity check — high-ROIC franchises rise (ORLY +26, ROST +26, SBUX +27, AAPL +22, IDXX +24,
  ADBE +28), low-ROIC/levered fall (MCHP −25, LITE −21). In the live fit **ROIC absorbed the
  margin signal** (`+27.7·Δg +0.0·Δmargin +21.2·ΔROIC`) — it is the better value driver.
- **Quality widens the range.** A config-driven band (±10% top-quality → ~±50% low-quality
  cyclical) sets a *minimum* low↔high half-width, unioned with engine dispersion. It never
  touches `within`/`conf` — engine agreement stays a pure function of dispersion; this is
  **business predictability, a separate axis**. Binds the high for 68/94 and the low for 20.
  **Known nuance:** on this growth-heavy universe the EPV floor (median 0.33×mid) dominates
  the *low* side, so the band's visible effect is mostly the high side + value names. Whether
  EPV should become a separate floor marker (so quality drives the low too) is a philosophy
  change to the "EPV sets the LOW bound" convention — left as an open call, not decided here.

**Backtest — synced, still no edge (as expected).** `backtest.py` uses the identical v2.7
base + size premium + ROIC-warranted (no-op size premium on its large-cap universes).
Regenerated both: **NDX 15.2% vs 17.7%, SPX 12.7% vs 13.6%** — the composite remains
edge-less, consistent with the Phase 1.4 verdict. Per the standing rule these ship anyway:
they fix correctness/honesty/sensibility defects in the *valuations* (undervalued reinvestors,
peak-cycle extrapolation, ROIC-blind multiples), and the incumbent has no real edge to protect.
**Forward ledger arbitrates.** Also corrected three stale/false methodology surfaces in
passing: the `beta_default` "PLACEHOLDER" comment, the DDM card (still claimed "replaced —
few payers"; false since v2.6), and the DCF/EPV/reverse-DCF cards. Tests **115 → 139**.
