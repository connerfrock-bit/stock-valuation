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
- [ ] Hardening: capex/CFO tag gaps (ADP, EA, FANG…) · IFRS map for foreign filers (ARM, ASML, PDD…) · per-name mcap sanity vs external source (CMCSA-style undercounts)

## Phase 3 — Metrics & classify (L4–L5)
- [x] Quality score — cross-sectional percentile composite (margin·ROE·growth·FCF-margin·leverage) ✅
- [x] **Normalized FCF base** — avg 5y FCF margin × current revenue (fixes cyclical peak/trough bias) ✅
- [~] Archetype router — RIM/DDM gates live; full bank/REIT/cyclical classifier TBD (needed for NYSE)
- [ ] roic / Altman-Z / Piotroski — need total-assets & current-liabilities concepts ingested

## Phase 4 — Valuation engines (L6) — per VALUATION_DEFAULTS_SPEC
- [~] Assumption resolver — global layer live; archetype + per-company override log TBD
- [x] **Reverse DCF** — anchor; market-implied growth per name ✅
- [x] DCF + Monte Carlo (P10/P50/P90), normalized-FCF base ✅
- [x] RIM — Ohlson AR(1), router-gated ✅
- [x] EPV — explicit floor (low bound, never in mid) ✅
- [x] Warranted multiple — stdlib OLS: EV/EBIT ~ g + margin + β across 78 names, winsorized+clamped ✅
      ⚠ v1 caveat: coefficient signs (−margin, +β) say it's absorbing sector/momentum effects — v2: within-sector fit + better features
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
- [ ] Scaffold Vite + React + TS; port design tokens + 10 components + 4 screens
- [ ] Wire the dead buttons (Export CSV, filing links, watchlist persistence, settings, universe picker)
- [ ] Point DataSource at the live API
- [ ] **Milestone D:** the dashboard runs on real numbers

## Phase 7 — Backtest (L11)
- [ ] Point-in-time, survivorship-free harness → real per-method reliability + weights
- [ ] Methodology screen goes real

## Phase 8 — Expand & harden
- [ ] Scale Nasdaq-100 → NYSE · daily refresh/caching · per-company QA sanity panel
