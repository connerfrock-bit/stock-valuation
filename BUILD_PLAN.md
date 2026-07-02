# Build Plan — Fair Value (Nasdaq-100) Valuation Engine

> Living checklist. We tick these off one by one. Order reflects the locked decisions below.

## Locked decisions
- **Scope:** Nasdaq-100 first (~100 names), expand to NYSE later.
- **Stack:** Python (FastAPI) backend for data + valuation engines · React + TypeScript + Vite frontend (built later).
- **Build order:** **Data/engine first.** The existing `.dc.html` prototype is the visual reference; the UI port happens after the engine produces real numbers.
- **North-star contract:** the backend produces one `Company` record per ticker (shape below). The prototype already binds to this shape — when our API emits real `Company` records, the UI swaps mock→real with no redesign.

## Repo structure (target)
```
stock valuation project/
├─ BLUEPRINT.md · UI_SPEC.md · VALUATION_DEFAULTS_SPEC_1.md · BUILD_PLAN.md
├─ Stock valuations dashboard/        # design handoff (reference only)
├─ backend/                           # Python — built first
│  ├─ requirements.txt
│  ├─ config/assumptions.yaml         # lifted from VALUATION_DEFAULTS_SPEC
│  ├─ fairvalue/
│  │  ├─ contract.py                  # Company pydantic model (the contract)
│  │  ├─ universe/                    # L0  constituents
│  │  ├─ ingest/  edgar.py prices.py macro.py   # L1
│  │  ├─ store/                       # L2  SQLite, point-in-time
│  │  ├─ metrics/                     # L4  ratios, quality, safety
│  │  ├─ classify/                    # L5  archetype router
│  │  ├─ engines/ dcf.py reverse_dcf.py rim.py epv.py warranted.py ddm.py  # L6
│  │  ├─ synthesize/                  # L8 triangulate · L9 trap gate
│  │  └─ api/                         # FastAPI — emits Company records
│  └─ tests/
└─ frontend/                          # React/TS/Vite — built later
```

## The `Company` contract (what the engine must output)
`ticker, name, sector, price, mcapB, quality(0-100), growth5y, divYield, negBook`
· derived: `low, mid, high, upside`
· `methods[]` = `{key, name, note, value|null, applicable}` for DCF·RIM·EPV·Warranted·DDM
· `conf(1-5), within` · `impliedGrowth, trailingG` (reverse-DCF)
· `pe, evebitda, fcfy` · `flags[]` · `altmanZ, piotroski, roic, gm, nde` · 8-yr trend series.
Honesty rules: never a single fair value without its range · agreement always beside upside · trap flags always visible · missing → `n/a` (never `0`) · excluded methods shown as excluded.

---

## Phase 1 — Foundation
- [x] Confirm toolchains — Python 3.14.6 + Git present; Node deferred to Phase 6
- [~] Scaffold `backend/` — `ingest_v1.py` live (stdlib-only: urllib/json/sqlite3, no venv needed yet)
- [x] Encode `assumptions.toml` from VALUATION_DEFAULTS_SPEC §1 (read via stdlib `tomllib`)
- [ ] Define `contract.py` — the `Company` model

## Phase 2 — Data pipeline (L0–L2)
- [x] Universe — full Nasdaq-100 live from Wikipedia (101 names, GOOG/GOOGL deduped by CIK)
- [x] EDGAR `companyfacts` ingestion + **XBRL tag-mapping** (merge-across-tags; 76 names ≥11/12)
- [x] **Share-count resolver** — freshest of dei cover / point-in-time / weighted-avg-basic,
      with multi-class undercount guard (fixed META, ABNB, SHOP, WDAY, GOOGL, splits)
- [x] Price ingestion — Yahoo chart API primary (proven); proper fallback (Tiingo) TBD
- [x] Macro — regression betas live (Blume-adj, 5y monthly vs S&P 500); FRED `DGS10` flaky (falls back 4.3%)
- [~] SQLite store — basic schema live; upgrade to full **point-in-time** (as-reported + filing dates)
- [x] **Milestone A:** real financials + prices in SQLite ✅ (now 100 companies, ~15.7k datapoints)
- [x] **Data-trust pass** ✅
      · tag gaps closed: ADP/EA capex (`…OtherPropertyPlantAndEquipment`), ADP ebit (pretax
        fallback), FANG capex (oil&gas development), CMCSA long_debt (`…AndCapitalLeaseObligations`
        — was missing **$93B of debt**), LITE dep (`Depreciation`)
      · 20-F/40-F form support → unlocks ARM/ASML/PDD/NBIS (they file us-gaap tags in 20-Fs)
      · currency-aware unit selection (PDD files CNY+USD in parallel) + IFRS map (TRI/CCEP/FER)
        + spot-FX conversion to USD (disclosed via `finCurrency`)
      · `sanity.py`: external mcap cross-check vs Yahoo (crumb-auth quote API) — >15% divergence
        auto-patches shares_out from Yahoo marketCap (the only reliably total-across-classes field)
- [x] Version control: git repo initialized, initial commit `28280b2`

## Phase 3 — Metrics & classify (L4–L5)
- [x] Quality score — cross-sectional percentile composite (margin·ROE·**ROIC**·growth·FCF-margin·leverage) ✅
- [x] **Normalized FCF base** — avg 5y FCF margin × current revenue (fixes cyclical peak/trough bias) ✅
- [x] **Safety metrics** ✅ — 6 balance-sheet concepts ingested (assets, current A/L, retained,
      liabilities, gross profit; 97 names ≥15/18 coverage) → real **ROIC**, **Altman-Z**,
      **Piotroski F** (scored over evaluable signals, needs ≥5)
      ⚠ original Altman-Z is calibrated for manufacturers — harsh on capital-intensive names (FANG); Z″ variant is a refinement
- [x] Data-driven **cyclicality flag** (YoY revenue-growth σ > 18%) + **VIE/ADR structure** flag (PDD) ✅
- [~] Archetype router — RIM/DDM gates live; full bank/REIT/cyclical classifier TBD (needed for NYSE)

## Phase 4 — Valuation engines (L6) — per VALUATION_DEFAULTS_SPEC
- [~] Assumption resolver — global layer live; archetype + per-company override log TBD
- [x] **Reverse DCF** — anchor; market-implied growth per name ✅
- [x] DCF + Monte Carlo (P10/P50/P90), normalized-FCF base ✅
- [x] RIM — Ohlson AR(1), router-gated ✅
- [x] EPV — explicit floor (low bound, never in mid) ✅
- [x] **Warranted multiple v2** ✅ — sector-anchored (fixed-effects): company gets its SECTOR
      median EV/EBIT (global median for sectors <3 names), residual regression on within-sector
      growth/margin with sign-guarded coefficients, **anchor capped at 28× EV/EBIT** so the
      relative engine cannot inherit market froth. β removed (belongs in the discount rate).
      Note: with the cap, the sign guard zeroed the growth adj this run → pure capped-sector-median
      engine; revisit features when subsector data exists (TECH is too heterogeneous: semis vs software).
- [x] DDM — consciously replaced by warranted multiple for this universe (spec §6 note)
- [x] **Milestone B: all engines live on the full universe** ✅

## Phase 5 — Synthesis + output (L8–L10)
- [x] Triangulate → range + agreement (EPV=floor, mid=weighted growth engines) ✅
- [x] Value-trap flags — declining rev · negative FCF · leverage · neg book · accruals · suspect shares · stale ✅
- [x] Composite score + ranked board — upside × conf × quality × trap-penalty ✅
- [x] **`data/output.json`** — Company-contract records (the artifact the dashboard binds to) ✅
- [x] **`data/report.html`** — self-contained dark QA dashboard (KPIs, search, sort, range bars) ✅
- [ ] FastAPI (or stdlib http.server) serving output.json → **Milestone C** formal API

## Phase 6 — Frontend port (React/TS) — swap mock→real
- [x] Scaffold Vite + React + TS (Node 24.18 via winget); strict TS, clean build ✅
- [x] Port design tokens + components (RangeBar ⭐, ConfMeter, Quality gauges, FlagChips,
      SectorTag, FilterRail, Sparkline, floating Tooltip) + all 4 screens ✅
- [x] Dead buttons wired: **Export CSV** (real download), **watchlist** (localStorage),
      **EDGAR filing links** (per-CIK), settings→Methodology, '/' focuses search ✅
- [x] Data source = `public/output.json`, auto-synced by value.py; contract enriched with
      `cik` + real 8-yr `trends` (revenue, op margin, FCF, book equity — as filed) ✅
- [x] Honest additions beyond the prototype: backtest shown as "not yet run" (no fake curve),
      FX-at-spot disclosure on non-USD filers, excluded names listed with reasons ✅
- [x] **Milestone D: the dashboard runs on real numbers** ✅  (`frontend/dev.cmd` → localhost:5173)

## Phase 7 — Backtest (L11) ✅ COMPLETE — VERDICT: NO EDGE DEMONSTRATED
- [x] `membership.py` — survivorship-free universe from Wikipedia's change log: 46 quarterly
      snapshots 2015→2026, 202 distinct names (102 past members), 2 parse anomalies / 225 changes
- [x] `prices.py` — 15y monthly close+adjclose+splits for all historical members + ^GSPC + ^TNX
      (169/204 symbols; 35 delisted names unavailable — quantified, not hidden)
- [x] `pit.py` — POINT-IN-TIME store: every annual vintage keyed by SEC `filed` date
      (~100k rows, 161 names); non-USD + no-CIK excluded and counted
- [x] `backtest.py` — quarterly rebalance 2016→2026, PIT signals (rolling betas, ^TNX risk-free
      at each date, PIT warranted cross-section), top-quintile vs equal-weight, per-method
      reliability, coverage stats → backtest.json (synced to dashboard)
- [x] Methodology screen renders the real results — **including the negative verdict**
- **RESULT: composite 12.6%/yr vs 18.0%/yr equal-weight · 39% hit rate · all engines'
  excess ≤ 0.** Value-tilted selection underperformed in the 2016–2026 growth-led Nasdaq-100
  — consistent with the documented value-factor drought in exactly this universe/period.
  Relative engines degraded least (warranted 49% hit / −0.31%/q); absolute cheapness (DCF,
  EPV) degraded most. THE TOOL IS A RESEARCH AID; NO PROVEN ALPHA. Known softeners: ~77%
  avg coverage (survivorship residue), rf fallback 2.5% after mid-2024 (^TNX gap), signal
  designed after the sample.

## Phase 8 — Universe expansion ✅ (S&P 500 backtest) — VERDICT: MARKET-MATCHING, NO EDGE
- [x] Harness generalized (membership/prices/pit/backtest all take a universe arg; incremental fetches)
- [x] S&P 500 survivorship-free membership: 46 snapshots, 720 distinct names (220 past members),
      GICS sectors captured → real sector anchors for the warranted engine
- [x] Data: +475 price series (106k month-rows) · +459 PIT names (415k total vintage rows)
      · 117 price-missing + 126 no-CIK delisted names quantified (incl. SIVB/FRC — the 2023
      bank failures are ABSENT, which flatters financials results; disclosed)
- [x] **RIM added to the backtest signal** (router-gated) — finally applicable in a bank-rich universe
- [x] Dashboard: universe toggle (NASDAQ-100 / S&P 500) + dynamic honest verdict banner
- **RESULT (2016–2026): 13.49% vs 13.39% — market-matching.** Same signal that lost −5.3%/yr
  in the Nasdaq is neutral in the value-richer S&P 500 → the universe hypothesis was right
  directionally, but still NO deployable alpha. Coherent method pattern: **RIM 54% hit /
  +0.15%/q and Reverse-DCF gap 54% / +0.11%/q are the only >50% methods** — the two most
  theoretically-grounded engines. Deep cheapness (EPV −0.30%/q) still doesn't pay.
- [ ] Later: full-NYSE *live screening* universe (backtest stays constituent-based for honesty)
      · daily refresh/caching · per-company QA panel · signal research (RIM+revDCF-weighted
      composite, quality-within-value, momentum overlay) using this harness as the lab

## Phase 9 — Hardening & correction sprints (post-review plans, worked one at a time)
- [x] **Plan 1: safety net** ✅ — engine unit tests (30 goldens+invariants, `backend/tests/`,
      stdlib unittest: Gordon-reduction golden, reverse-DCF inverts the kernel, RIM(ROE=Re)=book,
      EPV floor never in mid, anchor cap, N/A-never-guessed) · append-only **`snapshots`** table
      (every value.py run keeps its full ranked output — the before/after diff surface for all
      future changes + Plan-4 ledger foundation) · **`run_stats` coverage guard** in ingest
      (>5% per-concept drop vs previous run warns loudly = silent-XBRL-tag-change detector)
      · fixed nondeterministic MC seed (`hash()` is process-salted → crc32; identical runs
      now produce identical snapshots — the diff caught it on the first try)
- [x] **Plan 2: input correctness** ✅ — 5 new XBRL concepts (short debt, op leases,
      interest exp, tax exp, pretax; 30.4k datapoints); borrowings = long+short in all
      valuation math; leases in RISK debt only (engines discount post-rent flows — EV-bridge
      leases would double-count); Rd = interest/borrowings [rf+0.5%, 15%]; effective tax
      3-yr mean [10%, 35%]; EPV maintenance-capex param was dead code since inception — wired.
      Model v1.1; isolated snapshot diff: median |Δmid| 0.3%, movers all leverage stories
      (WDC −6%, CMCSA +5.5%), SBUX/INTC/KDP/MDLZ gained the leverage flag (leases). See WORKLOG.md.
- [x] **Plan 3: evidence-aligned scoring** ✅ — backtest refactored into a variant harness
      (signals built once, scored per variant); 3 variants × fit/holdout/full × both
      universes. **Adopted v2w** (weights DCF .10/RIM .35/W .30, 0.85^n flag decay,
      growth out of quality): beats v1 in 5/6 cells, NDX full −5.27 → −0.99pp.
      **Rejected the revDCF-gap blend** — holdout winner but fit-window loser = value-regime
      loading, not signal; stays displayed, never scored. MC DCF deleted (deterministic).
      Altman-Z gated off for FINL/REIT. Model v2; median |Δmid| 13.2%. See WORKLOG.md.
- [ ] Plan 4: forward paper-trading ledger — freeze model tag, track basket returns live
- [ ] Plan 5: TTM fundamentals from 10-Qs (staleness fix)
- [ ] Plan 6: momentum (12-1) + L7 sector-neutral V+Q+M cross-section — the research sprint
- [ ] Plan 7: robustness — Wikipedia parse caching/diff-guard, FRED DGS10 history for the
      backtest rf, de-scope FastAPI, un-hardcode Nasdaq constants
