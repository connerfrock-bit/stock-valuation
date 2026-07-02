# Handoff: Fair Value — Nasdaq 100 Valuation Dashboard

## Overview
A research-grade equity valuation dashboard for a single power-user analyst. It takes the user
from "100 Nasdaq-100 stocks" → "a short list of cheap-and-good candidates" → "understand why each
one is mispriced," in as few clicks as possible. Each company is valued with multiple methods and
surfaced as a **fair-value range vs. current price**, with honest confidence (method-agreement)
signals and value-trap flags — never false precision.

Scope for v1 is the **Nasdaq 100** universe (the design ships with ~50 representative names as mock
data). The product is dark-mode, desktop-first, information-dense — Bloomberg-terminal seriousness,
not consumer-fintech gloss.

## About the Design Files
The files in this bundle are **design references created in HTML** — a working prototype showing the
intended look, layout, and behavior. **They are not production code to copy directly.**

The single source file `Fair Value - Nasdaq 100.dc.html` is a "Design Component": an HTML file with a
template plus a `class Component` logic block, rendered by the bundled `support.js` runtime. **Do not
ship `support.js` or the `.dc.html` format.** Treat the file as an executable spec — open it in a
browser to see the real interactions, and read its `class Component` to see exactly how every number
is derived.

The task is to **recreate these designs in the target codebase's existing environment** (React, Vue,
Svelte, etc.) using its established patterns, component library, and data layer. If no frontend
environment exists yet, **React + TypeScript** is the recommended choice for this app (dense tables,
SVG charts, lots of derived state). Charts (scatter, range bar, sparklines, gauges, equity curve) are
hand-rolled inline SVG in the prototype — you may keep them as lightweight custom SVG components or
swap in a charting lib (visx / Recharts / D3), but match the visual spec below precisely.

A critical companion: the real data/valuation logic is specified in `reference_specs/` —
`BLUEPRINT.md` (the L0–L12 data pipeline), `UI_SPEC.md` (the original screen spec), and
`VALUATION_DEFAULTS_SPEC_1.md` (every valuation assumption + default). The dashboard is the UI layer
(L12); those docs define the engine behind it.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, density, and interactions are all
intentional. Recreate the UI pixel-for-pixel using the codebase's libraries. The mock dataset and the
fabricated valuation numbers are **placeholders** — replace them with the real pipeline output
(EDGAR financials + prices → the engines in `VALUATION_DEFAULTS_SPEC_1.md`). The *shape* of the data
model below is what the UI binds to.

---

## Global Chrome (persistent on every screen)

### Top bar — height **52px**, bg `#0c0f15`, bottom border `1px solid #1d222d`
- **Left:** logo mark (22px rounded square, gradient `135deg #3fb950→#2a8d3c` with a 9px `#0a0c10`
  notch) · wordmark `FAIR VALUE` (Inter 700, 13px, letter-spacing .16em) · pill `NASDAQ·100`
  (JetBrains Mono 9.5px, border `1px #2a3140`, radius 4px).
- **Center:** global ticker search — 32px tall, bg `#11151d`, border `1px #1d222d` (→ `#4493f8` on
  focus), radius 7px, magnifier icon + input + `/` keyboard hint chip. Type-ahead dropdown (see
  Interactions). Placeholder "Search ticker or company…".
- **Right:** universe selector pill `NASDAQ 100 ▾` · a two-line "Data as of" block (label 9px
  uppercase `#525c6b` / value `Jun 27 2026 · 16:00 ET` JetBrains Mono 11px `#9aa3b2`) · 30px settings
  gear button (border `1px #2a3140`, radius 7px).

### Left nav — width **188px**, bg `#0c0f15`, right border `1px solid #1d222d`, padding 12px 10px
- Section label "NAVIGATE" (9px uppercase `#525c6b`).
- Four items, each 13px, padding 9px 11px, radius 8px, icon (15px stroke SVG) + label:
  **Overview** (3-dot scatter icon) · **Screener** (3 lines) · **Deep-Dive** (magnifier; shows the
  active ticker in JetBrains Mono 10px on the right) · **Methodology** (line-chart icon).
- **Active state:** color `#fff`, weight 600, bg `rgba(68,147,248,0.13)`, `2px solid #4493f8`
  left border. Inactive: color `#9aa3b2`, transparent left border.
- **Footer:** a green dot + "Data fresh" and two dim lines "EDGAR · 6h ago / yfinance · 14h ago".

---

## Screens / Views

### Screen A — Universe Overview (landing)
**Purpose:** bird's-eye "where is the cheap-and-good cluster right now."
**Layout:** KPI strip across the top → below it a row of `[228px filter rail] [scatter, flex:1]`.

- **KPI strip:** 5 equal cells in a `grid-template-columns: repeat(5,1fr)` with `1px` gaps over a
  `#1d222d` background (hairline dividers), each cell bg `#0c0f15`, padding 14px 18px. Each cell:
  uppercase 10px label `#626b7a` / 23px JetBrains Mono 600 value / 10.5px sub `#626b7a`.
  Values: **Covered** (count, `#e6e9ef`) · **Undervalued** (>15% upside, green `#3fb950`) ·
  **Pass quality** (≥70) · **Median upside** (green/red by sign) · **Trap-flagged** (amber `#d29922`).
- **Filter rail** (shared with Screener — see Components → Filter Rail).
- **Scatter ("Universe map"):** title + subtitle ("Upside to fair value × quality. Dot size =
  market cap, color = sector. **Top-right = cheap & good**.") + `N / M shown` counter, then a
  responsive SVG (`viewBox 0 0 1000 540`, max-height 62vh).
  - **x-axis** = upside to fair value, domain `[-0.45, +0.55]`, ticks at ±40/±20/0 (JetBrains Mono
    11px). Bold `1.5px #2a3140` vertical **zero line** labeled "fairly valued". Axis title
    "← overvalued · upside to fair value · undervalued →".
  - **y-axis** = quality score `[0,100]`, gridlines at 0/25/50/75/100 (`#14181f`), rotated title
    "quality score →".
  - **dot radius** = `clamp(sqrt(mcapB)/sqrt(3500)*30 + 4, 4, 30)`; **fill** = sector color at 0.62
    alpha (0.95 on hover), **stroke** = sector color (`2px` on hover).
  - **Money zone** (toggleable): dashed `rgba(63,185,80,0.25)` rect over upside>0.15 & quality>70,
    fill `rgba(63,185,80,0.06)`, label "▲ cheap & good".
  - Hover → floating tooltip (price, fair mid, upside, quality, agreement + trap-flag footer).
    Click dot → Deep-Dive for that ticker.
- **States:** stale-data banner (bg `#33291a`, border `#d29922`) if last refresh >24h; the scatter
  simply shows fewer dots as filters tighten.

### Screen B — Screener Table (the workhorse)
**Purpose:** the ranked, sortable, filterable list the analyst lives in.
**Layout:** `[228px filter rail] [main, flex:1 column]`. Main = toolbar row + scrolling table.

- **Toolbar** (padding 11px 18px, bottom border `#1d222d`): title "Screener" · `N matches` ·
  **preset chips** ("Deep value", "Quality compounders", "Clean & cheap") · spacer · "Show/Hide
  multiples" toggle · "Export CSV" button (download icon). Chips/buttons: 11px, border `1px #2a3140`,
  radius 6px, padding 5px 10px.
- **Table** (font 12px, `border-collapse: collapse`):
  - **Sticky header** (`position:sticky; top:0`), bg `#0e1117`, cells 10px uppercase `#626b7a` 600,
    bottom border `#1d222d`. Every data column is click-to-sort; the active column shows a green
    `▼`/`▲`. Sort keys: ticker, price, upside, conf, quality, mcap.
  - **Columns:** 1) star toggle + ticker (JetBrains Mono 600 12.5px) + sector tag + company name
    (10.5px `#8a93a3`, ellipsis, max 160px); 2) Price (mono, right); 3) Fair-value range (compact
    Range Bar, ~180px); 4) Upside (mono 600, green/red); 5) Agreement (5-seg confidence meter);
    6) Quality (compact gauge, ~96px); 7) Flags (chips or `—`); 8) optional P/E · EV/EBITDA · FCF
    yield group (mono, `#9aa3b2`, on a `#0b0e13` tint, shown only when "multiples" toggled);
    9) Mkt cap (mono, right).
  - **Rows:** bottom border `#14181f`, `cursor:pointer`, hover/selected bg `rgba(68,147,248,0.06)`,
    row height tight (~7px vertical padding). Click row → Deep-Dive. Star click `stopPropagation`s
    and toggles watchlist (filled `★` amber `#d29922` / hollow `☆` `#626b7a`).
  - **Default sort:** `score` desc, where
    `score = (clamp(upside,-0.5,0.6)+0.5) · (conf/5) · (quality/100) · (hasTrapFlags ? 0.55 : 1)`.
  - **Empty state:** centered "No stocks match — loosen filters."

### Screen C — Stock Deep-Dive
**Purpose:** everything about one ticker — is it really cheap, and *why* does the market disagree?
**Layout:** sticky header, then a `grid-template-columns: 1fr 360px` body (gap 18px), padding 20px
24px. Left column = the analysis stack; right column = quality / agreement / trends / peers.

- **Header** (sticky, bg `#0c0f15`, bottom border `#1d222d`, padding 16px 24px): ticker (JetBrains
  Mono 700 24px) · name (14px `#cfd6e2`) · sector tag · spacer · Price block · Mkt Cap block ·
  watchlist star button (34px, border `1px #2a3140`).
- **Hero — Fair-value range** (card bg `#0e1117`, border `#1d222d`, radius 11px, padding 20px 22px):
  header "Fair-value range" + verdict ("Undervalued ~15% to mid · high agreement", colored
  green/red/amber). Below it the **full Range Bar** (see Components).
- **Reverse-DCF callout** (gradient card, border tinted by verdict): label "REVERSE DCF ·
  MARKET-IMPLIED EXPECTATIONS", a big 18px statement
  ("At $178, the market is pricing in ~9%/yr revenue growth for 5 years, fading to 2.5% terminal.
  Alphabet's trailing 5-yr CAGR is 13%."), and a verdict chip ("Market is optimistic / pessimistic /
  roughly in line vs. history").
- **Method breakdown** (card with table): columns Method / Estimate / Weight / Key assumption. One
  row per engine. **Inapplicable engines are greyed (opacity .45) with the reason** (RIM →
  "Negative book value — buybacks exceed equity"; DDM → "No / negligible dividend"). Estimate colored
  green if above price, red if below.
- **"Why does the market disagree?"** (card): bulleted plain-language expansion of each trap flag
  (red dot for distress-type, amber otherwise), a "Bear case:" line, then a leverage strip
  (Net debt/EBITDA, Altman-Z, Piotroski-F, FCF yield — each color-graded) and recent EDGAR filing
  chips (10-Q / 8-K / 10-K).
- **Right column cards:**
  - **Quality & safety:** radial gauge (72px SVG, ¾-circle arc) + big quality number + tier label,
    then ratio rows (ROIC, Gross margin, Rev growth 5y, Quality rank) each with a mini bar.
  - **Method agreement:** "X of Y methods within ±10% of mid — high/moderate/low agreement" + a large
    5-segment confidence meter + label.
  - **Financial trends (8-yr):** five labeled sparklines — Revenue, Operating margin, Free cash flow,
    Shares outstanding, Book value/sh — each with a delta % (shares: down = green).
  - **Sector peers:** up to 5 same-sector names (ticker, upside, Q-score, mini confidence), click →
    that ticker's Deep-Dive.

### Screen D — Methodology & Backtest
**Purpose:** prove the tool earns trust; document how each number is computed.
**Layout:** max-width 1180px, padding 22px 24px. Header + caveat → `[equity curve | 300px perf
stats]` → `[reliability table | data-quality]` → **engine formulas section** → global assumptions.

- **Backtest equity curve:** card with legend (green = top-decile basket, gray = Nasdaq-100 EW) and
  a 560×220 SVG of two compounding curves (log-ish `Nx` y-labels, year x-labels).
- **Performance:** CAGR 16.2% / 11.8%, Hit rate 58%, Max DD −34% / −28%, Sharpe 0.92 / 0.71,
  Turnover 47%/yr (strategy value bold + benchmark value dim).
- **Per-method reliability** table: Method / Hit rate / Fwd 1y α / Weight (justifies the L8 blend).
- **Data quality:** coverage 100/100, missing financials 0, last EDGAR refresh, fallback usage, avg
  history depth.
- **⭐ "How each engine values a company"** (the formulas section): a `1fr 1fr` grid of 6 engine
  cards (DCF, Reverse DCF, RIM, EPV, Warranted multiple, DDM). Each card: name + discount/best-for
  tags, a one-line "what it answers", a **monospace formula block** on `#0a0c10`, and an amber ⚠
  gotcha. Below the grid, an **"L8 · Triangulate → range"** callout: `low=min · high=max · mid=median`
  and `agreement = methods within ±10% of mid → confidence`. (Exact formula text is in the source and
  in `VALUATION_DEFAULTS_SPEC_1.md`.)
- **Global assumptions:** a 4-col grid of config cards (Risk-free 4.3%, ERP 5.0%, Terminal g 2.5%,
  Tax 21%, Horizon 10yr, SBC Expensed, Maint. capex min(capex,D&A), Beta Blume-adj) — each with a
  source line. These mirror `VALUATION_DEFAULTS_SPEC_1.md §1`.

---

## Reusable Components

### Valuation Range Bar ⭐ (signature component)
A horizontal bar answering "what's it worth vs. what it costs."
- **Track** auto-scaled to `[min(low,price)·0.90, max(high,price)·1.10]`. `pos(v)` maps a dollar
  value to a 0–100% left offset (clamped).
- **Zones:** subtle green tint left of `low` (`rgba(63,185,80,0.09)`), subtle red tint right of
  `high` (`rgba(248,81,73,0.08)`).
- **Fair-value band** from `low`→`high` (`rgba(154,163,178,0.30)` fill, `1px rgba(154,163,178,0.4)`
  border); **mid** marked with a 2px `#cfd6e2` tick.
- **Method dots** (full variant only): one `9px` dot per *applicable* engine at its estimate
  (`#0a0c10` fill, `2px #cfd6e2` stroke); hover → tooltip (method name, estimate, vs-price %, the
  assumption note).
- **Current-price line:** vertical 2px line colored by verdict (green if upside>+4%, red if <−4%,
  else amber `#d29922`), with a 2px `#0a0c10` halo. Full variant labels it "price $X" above.
- **Full variant** adds a LOW / FAIR(MID) / HIGH label row beneath (JetBrains Mono 12px).
- **Compact variant** (table rows): band + mid + price line only, no dots, no labels.
- **Tweakable style** (3 variants, exposed as a prop in the prototype): `band` (default) ·
  `gradient` (red→green track gradient) · `ticks` (thinner band, dot-forward). Plus a
  `showMethodDots` toggle. Treat these as design options — pick one as the production default
  (recommend `band`) unless you want it user-configurable.

### Confidence Meter (method agreement)
5 segments; filled count = agreement score 1–5. Color: green `#3fb950` if ≥4, amber `#d29922` if
2–3, red `#f85149` if ≤1. Segment ~13×7px (large variant ~18×10px). Tooltip: "X of Y methods within
±10% — high agreement." **This encodes agreement, not profit certainty.**

### Quality Gauge
Compact: a `5px` track (`#161b24`) filled to `quality%` + a mono number. Radial (Deep-Dive): a
72px SVG ¾-circle arc. **Tier color:** green ≥70, amber 48–69, red <48.

### Trap-Flag Chips
Small chips from the L9 value-trap gate. **Distress-type** (matches `distress|cut|Declining|opacity|
Negative`) render red (`#f85149` on `rgba(248,81,73,0.12)`); others amber (`#d29922` on
`rgba(210,153,34,0.13)`). Table truncates to 2 + "+N". Zero flags → mono `—`. Examples:
`Altman-Z: distress`, `Piotroski 3/9`, `High accruals`, `Declining revenue 3y`, `Dividend cut risk`,
`Negative book value`.

### Sector Tag
Pill with a **fixed categorical** sector color (see tokens) — bg = color@0.13, border = color@0.33,
text = color. Short codes: TECH, COMM, DISC, STPL, HLTH, INDU, FINL, REIT, MATL, ENGY, UTIL.

### Filter Rail (228px, shared Overview + Screener)
bg `#0b0e13`, border-right `#1d222d`, padding 16px. Header "Filters" + "Reset". Sections:
- **Sector** — 11 toggle rows (color swatch + name; off = 0.4 opacity).
- **Market cap** — segmented All / Mega (≥$200B) / Large ($10–200B) / Mid (<$10B).
- **Min quality** — range slider 0–100 step 5 (label shows value).
- **Min agreement** — segmented 1–5.
- **Min upside** — range slider −60…+50 step 5 (label shows value%).
- **Hide trap-flagged** — toggle switch (track green when on).
Active segmented/slider accent: `rgba(68,147,248,0.15)` bg, `#4493f8` border. Filters are **shared
state** across Overview and Screener.

### Floating Tooltip
`position:fixed`, follows cursor (offset +16px, clamped to viewport), bg `#0c0f15`, border
`1px #2a3140`, radius 9px, shadow `0 14px 40px rgba(0,0,0,.6)`. Mono title + label/value rows +
optional footer (e.g. trap-flag list). `pointer-events:none`.

---

## Interactions & Behavior
- **Ticker search:** type-ahead, case-insensitive match on ticker OR name, top 7 results in a
  dropdown (mono ticker + name + colored upside). Click → Deep-Dive, clears search. Dropdown shows
  while focused with a non-empty query; "No match in coverage." otherwise. Blur is delayed 150ms so
  clicks register.
- **Navigation:** left nav switches screens; scatter dot / table row / peer row / search result all
  route to Deep-Dive and set the selected ticker. Deep-Dive nav item shows the active ticker.
- **Sorting:** click a column header to sort; click again to flip asc/desc; active column shows the
  arrow.
- **Filtering:** all controls update shared state and immediately re-filter both the scatter and the
  table. Presets patch the filter state.
- **Watchlist:** star toggles per ticker (table + Deep-Dive header), held in state (persist to user
  storage in production).
- **Hover:** scatter dots and Range Bar method dots raise the floating tooltip; rows highlight.
- **Multiples toggle / Export CSV:** toggle reveals the P/E·EV/EBITDA·FCF-yield column group; CSV
  export is stubbed in the prototype — wire to a real exporter.
- **Transitions:** subtle only — dot fill 0.1s, toggle knob/track 0.15s. No flashy animation.

## State Management
Single screen-level state object in the prototype; in production split into UI state + server data:
- `screen` ('overview' | 'screener' | 'deep' | 'methodology'), `selected` (ticker).
- `search`, `searchFocus`.
- `sortKey`, `sortDir`.
- `showMultiples`.
- `watch` (set/map of starred tickers — **persist**).
- `filters`: `{ sectors: string[]|null (null = all), mcap, minQ, minConf, upside, hideTraps }` —
  **shared across Overview ↔ Screener**.
- `hoverDot`, `tip` (transient hover/tooltip).
- **Data fetching:** the company universe + all valuation outputs come from the backend pipeline
  (`BLUEPRINT.md`). The UI should treat each company as a precomputed record (see Data Model) and
  also fetch per-ticker detail (method estimates, trend series, filings, peers) for the Deep-Dive.

## Data Model (what the UI binds to — replace mock derivation with real pipeline output)
Per company: `ticker, name, sector, price, mcapB, quality (0–100), growth5y, divYield, negBook`,
plus derived: `low, mid, high` fair values, `upside` (mid/price−1), `methods[]`
(`{key, name, note, value|null, applicable}` for DCF·RIM·EPV·Warranted·DDM), `conf` (1–5 agreement),
`within` (count within ±10% of mid), `impliedGrowth` & trailing `g` (reverse-DCF), `pe, evebitda,
fcfy`, `flags[]`, `altmanZ, piotroski, roic, gm, nde`, and 8-yr trend series. **In the prototype
these are fabricated deterministically; in production they are the engine outputs defined in
`VALUATION_DEFAULTS_SPEC_1.md`.** Honesty rules: never show a single fair value without its range;
always show agreement next to upside; trap flags always visible; missing data → `n/a` (never `0`);
"data as of" always on screen; excluded methods shown as excluded with reason.

---

## Design Tokens

### Color — neutrals / chrome
| Token | Hex |
|---|---|
| App background | `#0a0c10` |
| Panel / card | `#0e1117` |
| Panel (chrome: top bar, nav) | `#0c0f15` |
| Filter rail / inset tint | `#0b0e13` |
| Code/formula inset | `#0a0c10` (border `#1a1f29`) |
| Border (hairline) | `#1d222d` |
| Border (rows) | `#14181f` |
| Border (interactive) | `#2a3140` |
| Text — high | `#e6e9ef` |
| Text — secondary | `#cfd6e2` / `#9aa3b2` |
| Text — dim/labels | `#626b7a` / `#525c6b` / `#8a93a3` |

### Color — semantic (meaning is FIXED app-wide — never reuse for other purposes)
| Meaning | Hex |
|---|---|
| Undervalued / upside / pass | green `#3fb950` |
| Overvalued / downside / fail | red `#f85149` |
| Caution (trap flag, low quality/confidence) | amber `#d29922` |
| Interactive accent / selection / focus (NOT a value signal) | blue `#4493f8` |
| Green zone fill | `rgba(63,185,80,0.09)` |
| Red zone fill | `rgba(248,81,73,0.08)` |

### Color — sector (fixed categorical palette; sector-encoding ONLY)
Information Technology `#6ea8fe` · Communication Services `#b58cf0` · Consumer Discretionary `#f0879b`
· Consumer Staples `#4fc3c9` · Health Care `#8d80e6` · Industrials `#c0a062` · Financials `#d98a5b` ·
Real Estate `#c98fc0` · Materials `#9aa86b` · Energy `#cf8f6a` · Utilities `#6fb1a0`.
Tag usage: bg = color @ 13% alpha, border = color @ 33% alpha, text = color.

### Typography
- **UI / prose:** Inter (400/500/600/700). Headings 14–17px/600–700; body 11.5–13px; labels 9–10px
  uppercase with .05–.14em letter-spacing.
- **All numbers + tickers + formulas:** JetBrains Mono (400–700) — used everywhere figures must align
  (the financial-table tabular requirement). KPI values 23px; Deep-Dive ticker 24px/700.

### Spacing / radius / misc
- Card padding 16–22px; card radius **11px**; chip/control radius 5–7px; pill radius 4px.
- Top bar 52px; left nav 188px; filter rail 228px; Deep-Dive right column 360px.
- Table row vertical padding ~7px (compact). Gridlines `#14181f`/`#1d222d`.
- Shadows used sparingly: dropdown `0 12px 32px rgba(0,0,0,.55)`; tooltip `0 14px 40px rgba(0,0,0,.6)`.
- Custom scrollbars: thumb `#222835`, 10px, 2px track-colored border.

## Assets
- **Fonts:** Inter + JetBrains Mono via Google Fonts (swap to your app's bundled fonts; keep a
  tabular-figures mono for all numbers).
- **Icons:** simple inline stroke SVGs (search, gear, nav glyphs, export, chevrons) — replace with
  your icon library at the same ~13–15px sizes and 2px stroke.
- **No raster images or logos.** The logo mark is pure CSS. No third-party brand assets are used.
- **Mock data:** ~50 real Nasdaq-100 tickers with **fabricated** valuations — do not ship; replace
  with pipeline output.

## Files
- `Fair Value - Nasdaq 100.dc.html` — the design prototype (template + `class Component` logic). Open
  in a browser to interact; read the logic class for exact derivations (range-bar geometry, scatter
  scales, score formula, agreement bucketing, color helpers, reverse-DCF statement, etc.).
- `support.js` — the prototype's runtime **only** (do not ship; reference if you need to understand
  how the template binds).
- `reference_specs/UI_SPEC.md` — original screen-by-screen UI spec.
- `reference_specs/BLUEPRINT.md` — the L0–L12 data/valuation pipeline that feeds this UI.
- `reference_specs/VALUATION_DEFAULTS_SPEC_1.md` — every valuation engine's defaults, formulas, and
  assumptions (the real math behind the numbers).
