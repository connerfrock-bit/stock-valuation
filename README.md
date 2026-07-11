# Fair Value

**A stock-valuation pipeline and dashboard covering four US universes — Nasdaq-100, S&P 500, S&P 1500, and NYSE ≥ $1B (≈2,200 companies, ~594k datapoints) — built entirely from free, keyless public data.**

Six valuation engines are routed by business archetype (standard / financial / REIT), triangulated into a fair-value **range**, and scored by how much the engines **agree**. A React dashboard puts ranges, scenario cones, quality gates, capital-allocation history, and forward paper-trading ledgers on one screen.

> **This is a research tool, not investment advice.** Every number is an estimate built on inspectable assumptions — start with [`backend/assumptions.toml`](backend/assumptions.toml), where every knob lives under version control.

**Live dashboard (last committed data snapshot):** https://connerfrock-bit.github.io/stock-valuation/

---

## Design stance

Three ideas run through the whole build:

1. **Ranges, not points.** A DCF point estimate is false precision — most of it is terminal-value assumption. Fair value is reported as low / mid / high, and the spread of independent estimates *is* the uncertainty.
2. **Agreement = confidence.** Cash-flow, earnings-power, book-anchored, dividend, and multiple-based methods agreeing is evidence; disagreement is a warning. The confidence score is engine agreement, not enthusiasm. Business quality and cyclicality widen the displayed range separately — predictability and agreement are different axes.
3. **Honest data discipline.** Financials are stored point-in-time as originally filed (no restatement overwrites). Where a limitation can't be engineered away — e.g. delisted-ticker price history for a fully survivorship-free backtest — it is documented, and forward paper-trading ledgers accumulate out-of-sample evidence from each universe's inception instead.

## What's inside

| Piece | What it does |
|---|---|
| [`backend/bulk.py`](backend/bulk.py) | One nightly ~2.9 GB SEC bulk download (companyfacts + submissions zips) replaces ~500 throttled per-ticker API calls — full-universe ingest drops from hours to ~2 minutes |
| [`backend/universe.py`](backend/universe.py) | Universe definitions: Wikipedia constituent lists (NDX, S&P 500/400/600) with cache + churn guards, and an SEC-filings-native NYSE ≥ $1B census (class filters, domestic check, SIC sector map) |
| [`backend/ingest_v1.py`](backend/ingest_v1.py) | EDGAR XBRL → SQLite, point-in-time, with a US-GAAP/IFRS tag-mapping layer and per-universe market-cap floors |
| [`backend/prices.py`](backend/prices.py) / [`sanity.py`](backend/sanity.py) | Daily prices (Yahoo chart API) plus a share-count cross-check against quoted market caps |
| [`backend/betas.py`](backend/betas.py) | Real equity betas: 5-yr monthly regressions vs the S&P 500, Blume-adjusted, clamped |
| [`backend/engines.py`](backend/engines.py) | The engines: DCF, reverse DCF, EPV, RIM, DDM, warranted-multiple regression — plus scenario blending and triangulation. Pure functions, golden-value tested |
| [`backend/value.py`](backend/value.py) | Archetype routing, normalization (TTM, owner earnings, effective tax), quality/value-trap gates, scenarios, capital-allocation panel — writes the dashboard JSON |
| [`backend/ledger.py`](backend/ledger.py) | Forward paper-trading ledgers per universe — the honest out-of-sample track record, from inception |
| [`backend/backtest.py`](backend/backtest.py) / [`momentum.py`](backend/momentum.py) | Point-in-time backtest (survivorship caveat documented) and a momentum factor study |
| [`backend/dataquality.py`](backend/dataquality.py) | Coverage gates a universe must pass before going live |
| [`backend/share.py`](backend/share.py) | Bakes the entire dashboard into a single offline HTML file for sharing |
| [`frontend/`](frontend/) | React 19 + TypeScript + Vite dashboard |

## The stack is deliberately boring

- **Backend: pure Python standard library.** Zero pip installs — `urllib`, `sqlite3`, `zipfile`, `tomllib`, `html.parser`. Nothing to break, nothing to audit.
- **Storage: one SQLite file**, point-in-time discipline throughout.
- **Frontend: React + Vite** — the only `npm install` in the project.

## Data sources — all free, all keyless

| Data | Source | Notes |
|---|---|---|
| Financial statements | [SEC EDGAR](https://www.sec.gov/) bulk zips + API | Official, permanent, no key; requires a User-Agent header |
| Daily & monthly prices | Yahoo Finance v8 chart API | Unofficial endpoint — cross-checked, cached, rate-limited |
| Risk-free rate | [FRED](https://fred.stlouisfed.org/) DGS10 CSV | Live 10-year Treasury |
| Index constituents | Wikipedia | NDX + S&P lists (cached, churn-guarded); the NYSE universe comes from SEC filings directly |

## Run it

Requirements: **Python 3.11+** and **Node 20+**. First data refresh downloads the ~2.9 GB SEC bulk zips (subsequent runs skip unchanged zips via `If-Modified-Since`).

```bash
cd backend
python bulk.py download   # SEC bulk zips (nightly-rebuilt)
python bulk.py scan       # filers scan for the NYSE universe
python ingest_v1.py       # financials + prices → SQLite (~2 min from the zips)
python ingest_v1.py --resume
python sanity.py          # share-count cross-check
python betas.py           # ~8 min of Yahoo monthly bars
python value.py all       # every engine, every universe → frontend/public/*.json
python ledger.py all      # forward ledgers
python momentum.py        # optional: momentum study
```

```bash
cd frontend
npm install
npm run dev               # dashboard at http://localhost:5173
```

On Windows there are two double-click helpers: `REFRESH DATA.cmd` (the full pipeline above, with a `/auto` flag for scheduled runs) and `OPEN DASHBOARD.cmd`.

The dashboard JSONs under `frontend/public/` are committed, so the UI (and the hosted demo) works immediately with the last committed snapshot — refresh to get current numbers.

## Tests

```bash
cd backend
python -m unittest discover -s tests -v    # 161 tests, stdlib runner
```

Golden values and invariants for every engine (they're pure functions — a silent regression would corrupt every number downstream), plus archetype routing, TTM/FFO construction, universe filters, ledger semantics, and bucket logic.

## Deeper docs

- [`BLUEPRINT.md`](BLUEPRINT.md) — the full system design (L0–L12), with per-step **build** vs **signal** confidence ratings and the anti-pattern list
- [`WORKLOG.md`](WORKLOG.md) — dated engineering log: every phase, gate, and deliberate deferral
- [`VALUATION_DEFAULTS_SPEC_1.md`](VALUATION_DEFAULTS_SPEC_1.md) / [`UI_SPEC.md`](UI_SPEC.md) — assumption-layer and dashboard specs

## License

[MIT](LICENSE). Data remains subject to its sources' terms (SEC data is public domain; Yahoo endpoints are unofficial).
