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
- [x] ~~FastAPI (or stdlib http.server) serving output.json → **Milestone C** formal API~~
      **CANCELLED (Plan 7):** static output.json + the share build serve the actual use
      case; a server adds surface area with zero benefit at this scale.

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
- [x] **Plan 4: forward paper-trading ledger** ✅ — `ledger.py` freezes the top-quintile
      basket per (model, day) from the snapshots table, marks to latest prices, benchmark
      = equal-weight covered universe; price-only returns disclosed; ledger.json → dashboard
      "Forward ledger" card (honest inception state) + share build; REFRESH DATA.cmd step
      5/5; 6 tests (44 total). Inception 2026-07-02: v1/v1.1/v2 baskets, 18 names each.
      The v2 basket is the live test — the one number the in-sample caveat can't touch.
      See WORKLOG.md.
- [x] **Plan 5: TTM fundamentals** ✅ — TTM stitcher (FY + post-FY chain − prior-year
      mirror; YTD + QTD reporters; fy-fallback when unmirrorable) + freshest quarterly
      instants → `financials_now` (944 TTM / 945 instants); model v2.1 values every "now"
      input fresh (median thru 2026-03 vs annual up to 15mo stale); coverage 94→96.
      MU +559% audited against raw EDGAR — real memory-supercycle inflection, not a bug.
      Found+fixed pre-existing `pick_annual` bug (partial-year fp=FY points; MPWR FY25
      rev was Q4-only) — the Plan-1 coverage guard fired its first real alert on the
      side effect. 54 tests. See WORKLOG.md.
- [x] **Plan 6: momentum + L7 cross-section** ✅ — VERDICT: REJECTED, v2w stands.
      12-1 momentum + winsorized sector-neutral V/Q/M z-blend (two a-priori variants);
      both lose to v2w on fit windows in both universes, win only the 2022-26 holdout =
      the same regime signature as the Plan-3 gap rejection. No live change; no weight
      search. Residual lead: STANDALONE momentum tops the per-method table (NDX +2.03%/q
      at 51% hit — real but lumpy); stays a displayed diagnostic. Third published
      negative verdict. See WORKLOG.md.
- [x] **Plan 7: robustness & de-scoping** ✅ — `rf_monthly` history (FRED-first, ^TNX
      fallback, LOCF across the 2024-06→2026-06 Yahoo feed hole that had the backtest
      silently using 2.5% while the real 10Y was ~4.3%); **v2w adoption re-validated
      under corrected rf — holds on both universes** (SPX holdout +3.41pp · 88% hit).
      Wikipedia parse caching + churn/shrink guards (universe + membership). Universe
      un-hardcoded to [universe] toml (badges data-driven, zero literals in bundle).
      Milestone C (FastAPI) formally cancelled. Warranted OLS reviewed and kept
      (data-dependent, not zombie). Loss-maker revDCF deferred to a future feature plan.
      See WORKLOG.md. **Phase 9 complete: 54 tests · model v2.1 · ledger armed.**

## Phase 10 — Universe expansion (CEO roadmap A→D)
- [x] **Plan A: S&P 500 live screener** ✅ (model v2.2) — superset ingest + `universe_membership`
      junction (both universes coexist; NYSE later = one config block); **L5 archetype router**:
      banks/insurers → RIM-only (no garbage DCF/EV), asset-light fee/network (Visa/MA/Moody's/
      exchanges) → FCF with a 6% fcfy float-guard, REITs → RIM-if-book-clean else honestly
      excluded, ~75% standard universe unchanged. Dashboard universe toggle live. **S&P: 479
      covered / 20 honestly excluded; Nasdaq: 96.** Found+fixed at scale: EDGAR-throttle retry,
      bank net-income (`ProfitLoss`) + broker-revenue tags, GICS-over-ICB sectors, sanity
      share-derivation. 4 workflows (understand/design/review). 44 tests. See WORKLOG.md.
- [x] **Plan B: extend backtest to 2012** ✅ — both universes 2012-2026 (57q); added a
      **pre2012-15 OOS window** (predates the v2w design). **VERDICT: v2w does NOT robustly
      generalize** — it underperforms v1 on 2012-2015 in BOTH universes; its edge is a
      post-2016 fit. Honest read now v1≈v2w, no durable edge. Kept v2w (reverting = fitting
      the ~54%-coverage early window). Survivorship grows to ~54% pre-2016 (quantified +
      caveated); betas fall back pre-2013. 4th published humbling result. See WORKLOG.md.
- [x] **Plan C: momentum study** ✅ — VERDICT: **POSITIVE (the project's first demonstrated
      edge)**, on the growth universe. `momentum.py`: 12-1, monthly, top-quintile, net-of-cost,
      4 windows. NDX momentum is net-positive in ALL four windows incl. OOS pre2012-15 (+6.1pp)
      and the low-survivorship 2022-26 (+8.2pp); ~25%/mo turnover. S&P weak/regime-dependent
      (+1.2pp full, −3.5pp 2016-21). Live per-name 12-1 momentum + percentile on the board +
      a Methodology study panel. Deliberately NOT blended into the value composite (Plan 6
      proved dilution kills it) — displayed as an orthogonal factor. 70 tests. See WORKLOG.md.
- [ ] Plan D: NYSE large+mid $2B+ (archetype router extends; SIC→sector map; size buckets)

---

## Phase plan — post-design-audit roadmap (2026-07-07, supersedes "Plan D" ordering)

> Sequence: finish in flight → make the model right on covered data → rebuild the
> plumbing for scale → only then widen the universe. Each phase has a go/no-go gate
> so we never scale a weakness. Full rationale in WORKLOG (design-audit entries).

### Phase 0 — housekeeping (done 2026-07-07)
- [x] Full refresh verified post-ingest-race (96 NDX / 482 SPX; first sharesM payloads)
- [x] `meta.weights` emitted by value.py — frontend hand-mirror demoted to fallback
- [x] `meta.changes` digest (vs last prior-day comparable snapshot) + Overview strip
- [x] "Value confirmed by tape" preset (upside≥15 · conf≥3 · clean · mom≥50)
- [x] Screener row windowing >150 rows (S&P-scale); table wrap is the real scroller
- [x] Weekly scheduled refresh (`REFRESH DATA.cmd /auto`, Sundays 09:00, logged)

### Phase 1 — model correctness on covered data (S&P 500 is the lab)
- [x] **Financials archetype** ✅ (v2.3, 2026-07-07) — bank quality = ROE level/stability +
      equity/assets, ranked among 90 covered financial peers; standard pools cleaned of
      gated garbage; Piotroski n/a for fin/reit (JPM's false flag gone). Gate PASSED:
      JPM/BAC/GS/USB/PNC/PGR match known reality. RIM Re-sensitivity measured: ±100bp Re
      → ∓2.2% mid (ω-fade dominates; book-anchored — documented on the RIM card, ω
      untouched). Discovered: CSGP misrouted reit (GICS) → override-table candidate below.
- [x] **REIT archetype** ✅ (v2.4, 2026-07-07) — P/FFO engine (FFO = NI+D&A−gains
      +RE-impairments; adjustment tags land next refresh, basis disclosed per name) at
      the capped covered-median multiple (live: 15.6× = 6.4% FFO yield — gate PASSED).
      Replaces RIM-on-book; flag retired; AMT/CCI/EQIX/IRM/SBAC/SPG recovered (482→488).
      Known: flat anchor across sub-sectors → fold into the 1.3 override/split work.
- [x] **Warranted TECH split + override table** ✅ (v2.5, 2026-07-07) — 78-name hand-map
      (semis/software/hardware) with the ≥8-fitted-names gate (SPX 23/20/23 hold; NDX
      hardware rolls back at 5). Live anchors: software 23.7×, semis/hardware AT the 28×
      cap, IT-services leftovers at their own 13.7× — CDW/CTSH/ACN dropped 62–87pp of
      froth-anchor upside. CSGP archetype-corrected (REIT pool 31→30, anchor purer).
      SIC-driven default split deferred to Phase 2's bulk submissions.zip (free there;
      513 throttled calls here). Gate PASSED.
- [x] **Survivorship measured** ✅ (2026-07-07) — membership was already PIT
      (membership.py, 58 quarterly member sets); the residual bias (unpriceable
      delisted members) is now MEASURED against the real equal-weight index funds:
      covered pool ran +1.4pp/yr hot vs RSP (SPX; +0.8pp in the best-covered window)
      and +2.8pp/yr vs QQQE (NDX; +3.5pp pre-2016). Emitted in backtest meta +
      caveats + a Methodology block. RSP/QQQE/SPY/QQQ kept fresh weekly via betas.py.
- [x] **DECISION GATE — CLOSED** ✅ (2026-07-07): composite nominal excess +0.03pp
      (SPX) vs a +1.4pp survivorship tailwind = no demonstrated edge after honest
      accounting. Positioning now WRITTEN on the Methodology page: expectations
      meter + trap gate + momentum overlay — not an alpha signal. Momentum stays
      the one live edge (within-pool: +0.50%/q SPX, +1.63%/q NDX).

### Phase 2 — plumbing for scale (before any universe growth) ✅ (2026-07-08)
- [x] **Bulk EDGAR transport** ✅ — `bulk.py`: nightly companyfacts.zip + submissions.zip
      (conditional download, header-prefix filers scan @ ~15k/s). Ingest **5h → 120s**
      (515 names, 0 API calls, coverage guard green). Gate PASSED 5×. Bonus: delisted
      CIK recovery via SEC formerNames (no_cik 170→~55, ~115 names, all hand-verified) —
      and it FOUND+FIXED a latent reassigned-ticker bug (Sprint's S→SentinelOne etc.
      were injecting namesake financials into the backtest). The delisted-name gap is
      now proven **price-bound**: fundamentals recover, but Yahoo 404s delisted prices
      and Stooq is access-gated → survivorship haircut stands (needs CRSP). See WORKLOG.
- [x] **Bulk prices** ✅ (decision: keep Yahoo) — spark batch is close-only (unsafe
      across splits); proven per-symbol v8/chart (adjclose+splits, incremental) kept.
      Stooq now PoW+401 gated → documented unavailable. EDGAR was the real bottleneck.
- [x] **L0 hygiene** ✅ — `hygiene_reason`: sub-$1, SPAC (SIC 6770), instrument names
      (warrant/right/preferred). High-precision (no …W/…U suffix guessing); 0 fired on
      the clean large-caps, the gate for broad universes. Visible in the excluded panel.
- [x] **S&P 1500 dry run** ✅ — `dataquality.py`: 1503 names via bulk in 62s,
      **coverage 99.1% (1490/1503) → GATE PASS (≥90%)**. Per-concept tag-fallback rate
      measured (interest_exp 85%, short_debt 80%) → live Methodology data-quality panel.
      This number is the NYSE go/no-go. **PASSED.** (SIC subsector defaults also landed:
      override>SIC>sector, 54/54=100% agreement with the hand-map where SIC opines.)

### Phase 3 — widen (BOTH Phase-2 gates PASSED: ingest <10min ✅ · S&P 1500 ≥90% ✅)
- [x] **S&P 1500 live in the universe picker** ✅ (2026-07-08) — `sp1500` source
      (500 ∪ 400 ∪ 600) + config (min_mcap 0.3e9 flag threshold). Scored **1444 names**;
      the warranted anchor now fits on **989 names / 12 sector anchors** (the promised
      statistical teeth), TECH split runs deep (42/55/33), 105 REITs. Top picks are
      mid-caps (EXEL/BKE/QLYS). Forward ledger extends to sp1500 (its evidence, since
      no backtest). Methodology shows a context-aware **screening-only** panel — no faked
      curve; the delisted-price gap is worst for small-caps. See WORKLOG.
- [x] **Scatter density** ✅ — the real problem was OUTLIER BLOWOUT (one +23000%
      small-cap auto-scaled the axis to uselessness), not raw count. Fixed with a
      percentile-based domain + honest clamp count ("N beyond axis →"); 1450 SVG dots
      render fine, canvas not needed. Axis reads [-50%, +100%].
- [ ] **Full NYSE as a SCREENING universe** — next increment (not done). Needs a
      SIC→sector map for non-S&P filers (no clean constituent list) + size buckets;
      L0 hygiene finally does real work here. Methodology already states credible
      backtesting stops at SPX (no delisted-price history without CRSP); the forward
      ledger is the broad universe's evidence. Builds on the S&P 1500 plumbing.

### Standing rules
- No new valuation engines (seven triangulate; an eighth is procrastination).
- No model change ships without beating v2.2 in a time-split backtest or the ledger.
- No silent universe filtering; every exclusion visible with a reason.
- Docs are law: UI changes either conform to UI_SPEC or amend it citing the trigger.
- Never run value.py while an ingest is rebuilding the DB (2026-07-07 race).
