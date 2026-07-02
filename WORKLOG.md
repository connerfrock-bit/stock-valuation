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
