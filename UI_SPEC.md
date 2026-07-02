# Stock Valuation Dashboard — UI Specification

> Purpose: a design-tool-ready spec. Each screen lists layout regions, components,
> the exact data each component shows, interactions, and states. Paired with
> `BLUEPRINT.md` (the data/logic pipeline that feeds this UI).

---

## 1. Product frame

- **App name (working):** Fair Value — NYSE Screener
- **User:** a single analyst (you) doing research-grade screening; power-user, comfortable with dense data.
- **Platform:** web app, desktop-first (wide tables + charts). Responsive is secondary.
- **Core job:** go from "2,000 stocks" → "a short list of cheap-and-good candidates" → "understand why each one is mispriced" in as few clicks as possible.
- **Tone:** Bloomberg-terminal seriousness, not consumer-fintech gloss. Information density over whitespace. Trustworthy, calm, data-forward.

---

## 2. Visual language / design system

**Mode:** Dark by default (data-heavy, long sessions). Light mode optional later.

**Semantic color (the meaning of color is fixed across the whole app):**
- 🟢 Green = **undervalued / upside / pass** (price below fair value)
- 🔴 Red = **overvalued / downside / fail** (price above fair value)
- 🟡 Amber = **caution** (value-trap flag, low data quality, low confidence)
- ⚪ Neutral gray = informational / no signal
- Sector colors = a fixed categorical palette (11 GICS-style sectors), used only for sector encoding (scatter, tags) — never reused for value/risk meaning.

**Typography:**
- UI text: clean sans-serif (Inter / system).
- **All numbers use tabular / monospaced figures** so columns align — non-negotiable for a financial table.

**Density:** compact. Table row height tight. Tooltips carry detail rather than inflating cells.

**Global chrome (persistent on every screen):**
- **Top bar:** app name · **global ticker search** (type-ahead, jump to any stock's deep-dive) · universe selector (NYSE / +NASDAQ later) · **"data as of" timestamp** · settings.
- **Left nav (icon + label):** Overview · Screener · (Deep-Dive opens contextually) · Methodology/Backtest.

---

## 3. Reusable components (define once, used everywhere)

### 3.1 Valuation Range Bar ⭐ (the signature component)
A horizontal bar that visually answers "what's it worth vs. what it costs."
- **Track:** spans from min to max of all method estimates (auto-scaled).
- **Range band:** shaded low→high fair-value band; mid marked.
- **Method dots:** one dot per valuation method (DCF, revDCF, RIM, EPV, DDM, multiple, NCAV), positioned at that method's estimate. Tight cluster = agreement; spread = disagreement. Hover dot → method name + value + one-line assumption.
- **Current price marker:** a vertical line. Its position vs. the band is the whole story — left of band (in green zone) = undervalued; right (red zone) = overvalued.
- **Label:** "Fair value $42–$68 (mid $55) · Price $51 · +8% to mid".
- Compact variant (single-line, no dots) used inside table rows.

### 3.2 Confidence Badge
Encodes **method agreement** (from L8), not certainty of profit.
- Visual: 5-segment meter or dot scale. High = methods cluster tightly; Low = scattered.
- Always paired with a tooltip: "4 of 5 methods within ±10% — high agreement."

### 3.3 Trap-Flag Chips
Small amber/red chips surfacing the value-trap gate (L9). Examples: `Altman-Z: distress`, `Piotroski 2/9`, `High accruals`, `Declining revenue 3y`, `Dividend cut risk`. Zero chips = clean. Click → explanation.

### 3.4 Quality Score Gauge
0–100 composite (ROIC, margins, balance-sheet strength). Radial or compact bar. Color by tier (green/amber/red).

### 3.5 Metric Cell
Standard table/detail cell: value in tabular figures, optional sector-relative coloring (percentile within sector), optional sparkline for trend. Tooltip shows definition + raw inputs.

### 3.6 Sector Tag
Pill with fixed sector color + label.

---

## 4. Screens

### Screen A — Universe Overview (landing) ⭐
**Purpose:** the bird's-eye "where is the cheap-and-good cluster right now" view.

**Layout:**
- **Hero: scatter plot (full width).**
  - x-axis = **upside to fair value** (% above/below mid). Vertical zero line.
  - y-axis = **quality score** (0–100).
  - dot size = market cap. dot color = sector.
  - **The top-right quadrant (high upside + high quality) is the money zone** — visually emphasize it (subtle highlight/label).
  - Hover dot → mini-card (ticker, price, range, upside, quality, trap flags). Click → Deep-Dive.
- **Left rail filters:** sector (multi), market-cap band, min confidence, min quality, "hide trap-flagged", upside threshold.
- **Top KPI strip:** # stocks covered · # undervalued (>X% upside) · # passing quality gate · median market upside · data-freshness.

**States:** loading skeleton for scatter; empty state if filters exclude everything ("No stocks match — loosen filters"); stale-data warning banner if last refresh > 24h.

---

### Screen B — Screener Table (the workhorse)
**Purpose:** the ranked, sortable, filterable list you live in.

**Layout:**
- **Dense data table.** Default sort: best opportunity first (e.g. upside × confidence × quality, gated by traps).
- **Columns:**
  1. Ticker + company name + Sector Tag
  2. Price
  3. **Fair-Value Range** (compact Range Bar variant)
  4. **% Upside to mid** (green/red Metric Cell)
  5. **Confidence Badge** (agreement)
  6. **Quality Gauge**
  7. **Trap Flags** (chips, or "—" if clean)
  8. Key multiples (P/E, EV/EBITDA, FCF yield) — collapsible column group
  9. Market cap
- **Row interactions:** click → Deep-Dive; hover → highlight; star/watchlist toggle.
- **Toolbar:** same filter set as Overview + free-text search + column chooser + **export CSV** + saved-screen presets ("Deep value", "Quality compounders cheap", "Net-nets").
- **Sticky header**; sortable every column; paginated or virtualized for ~2,000 rows.

**States:** loading rows skeleton; empty ("no matches"); per-cell "insufficient data" treatment (gray `n/a`, never a misleading 0).

---

### Screen C — Stock Deep-Dive ⭐
**Purpose:** everything about one ticker — is it really cheap, and *why* does the market disagree?

**Layout (top → bottom):**
- **Header:** ticker · name · Sector Tag · price · market cap · "data as of" · watchlist star.
- **Hero: full Valuation Range Bar** (3.1, full version with all method dots + price line) + headline verdict ("Undervalued ~15% to mid · High agreement").
- **Method breakdown panel:** one row per valuation method → estimate, weight in blend, and the key assumption (e.g. DCF: "10% discount, 4% terminal"; revDCF: "price implies 11% rev growth 10y"). Greyed rows = methods the router deemed not applicable, with reason.
- **⭐ "Why is it cheap?" panel:** the differentiator. Trap-flag chips expanded into sentences · debt/leverage snapshot · recent EDGAR filings (links) · short interest (if available later) · the bear case in plain language.
- **Reverse-DCF callout:** big readable statement — "At $51, the market expects 11%/yr growth for 10 years. Historical 5y growth: 6%." → over/under-optimism verdict.
- **Quality & safety:** Quality Gauge + Altman-Z + Piotroski-F + key ratios, each sector-percentile-colored.
- **Financial trends:** mini-charts — revenue, margins, FCF, shares outstanding, book value (5–10y). Watch shares outstanding (dilution) and FCF especially.
- **Peer strip:** small table of sector peers with the same range/upside/quality columns for context.

**States:** loading per-panel skeletons; "limited data" notice for young/spun-off companies; explicit note when a method was excluded.

---

### Screen D — Methodology & Backtest (credibility)
**Purpose:** prove the tool earns trust; remember which methods have earned their weight.

**Layout:**
- **Backtest equity curve:** strategy (top-ranked basket) vs. benchmark (e.g. NYSE index), point-in-time, survivorship-free. Prominent caveat that this is historical and assumption-dependent.
- **Performance stats:** CAGR, hit rate, max drawdown, Sharpe, turnover.
- **Per-method reliability table:** which methods' "undervalued" calls actually preceded outperformance → justifies the L8 weights.
- **Data-quality dashboard:** coverage %, # tickers with missing financials, last refresh per source, fallback-source usage.
- **Assumptions & definitions:** discount-rate logic, normalization rules, every ratio defined. Transparency = trust.

**States:** "backtest not yet run" empty state (expected early on); running/progress indicator.

---

## 5. Cross-screen interactions

- **Ticker search** (top bar) → jumps to Deep-Dive from anywhere.
- **Scatter dot / table row** → Deep-Dive; back button returns with filters preserved.
- **Filters persist** across Overview ↔ Screener (shared filter state).
- **Watchlist** is a saved subset usable as a screener preset.
- **Every number is inspectable** — tooltip → definition + raw inputs (builds trust, aids debugging).

---

## 6. Honesty rules baked into the UI

These are product requirements, not decoration — they keep the tool from lying to you:

1. **Never show a single fair value without its range.** Precision is a lie; the band is the truth.
2. **Always show confidence (agreement) next to upside.** High upside + low agreement = "interesting, not actionable."
3. **Trap flags are always visible**, never buried — a cheap stock with distress flags must look different from a clean one at a glance.
4. **Missing data reads as `n/a`,** never as `0` or a default that masquerades as a real number.
5. **"Data as of" timestamp is always on screen** — stale data should never look live.
6. **Excluded methods are shown as excluded** (with reason), not silently dropped.

---

## 7. Suggested build order for the UI

1. **Screener Table (B)** — even ugly, it's the core utility; everything else is navigation around it.
2. **Stock Deep-Dive (C)** + the **Valuation Range Bar** component.
3. **Universe Overview (A)** scatter — the "wow" view, once data is flowing.
4. **Methodology & Backtest (D)** — last, but designed for from the start (it's why anyone trusts the rest).
