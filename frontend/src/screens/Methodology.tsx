import { useEffect, useState } from 'react';
import { C, MONO, hexA } from '../theme';
import type { Meta } from '../types';

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

interface SurvWindow {
  label: string; coveredEW: number; indexEwTR: number; indexCapTR?: number; gapPP: number;
}
interface Backtest {
  meta: { ranAt: string; start: string; end: string; rebalance: string;
    portfolio: string; benchmark: string; avgCoverage: number; caveats: string[];
    survivorship?: { ewProxy: string; capProxy: string; windows: SurvWindow[] } | null };
  curve: { d: string; strat: number; bench: number }[];
  stats: { quarters: number; years: number; stratCAGR: number; benchCAGR: number;
    hitRate: number; stratSharpe: number; benchSharpe: number;
    stratMaxDD: number; benchMaxDD: number; avgTurnover: number | null; avgNames: number };
  perMethod: { method: string; hitRate: number; avgExcessQ: number; quarters: number }[];
}

interface LedgerBasket {
  model: string; date: string; runDate: string; ageDays: number;
  k: number; covered: number; missing: number; names: string[];
  basketRet: number | null; benchRet: number | null; excess: number | null;
}
interface Ledger {
  meta: { generatedAt: string; latestRun: string; caveats: string[] };
  baskets: LedgerBasket[];
  summary: Record<string, { baskets: number; aged: number; oldestDays: number;
    hitRate: number | null; avgExcess: number | null }>;
}

interface MomStat { excess: number; hitRate: number; stratCAGR: number; benchCAGR: number;
  stratSharpe: number; stratMaxDD: number; avgTurnover: number }
interface Momentum {
  meta: { universe: string; signal: string; start: string; end: string };
  variants: Record<string, Record<string, MomStat>>;
}

interface DataQuality {
  universe: string; generated: string; names: number; no_cik: number; no_facts: number;
  ingestable: number; core_min: number; core_covered: number; coverage_pct: number;
  gate_pass: boolean; elapsed_s: number;
  concepts: { concept: string; have: number; have_pct: number; fallback: number; fallback_pct: number }[];
}

function EquityCurve({ bt }: { bt: Backtest }) {
  const W = 560, H = 220, pl = 40, pr = 12, pt = 14, pb = 24;
  const pts = bt.curve;
  const maxV = Math.max(...pts.map(p => Math.max(p.strat, p.bench)));
  const X = (i: number) => pl + (i / (pts.length - 1)) * (W - pl - pr);
  const Y = (v: number) => pt + (1 - v / maxV) * (H - pt - pb);
  const path = (key: 'strat' | 'bench') =>
    'M' + pts.map((p, i) => `${X(i).toFixed(1)},${Y(p[key]).toFixed(1)}`).join(' L');
  const yearTicks = pts.filter((p, i) => i > 0 && p.d.slice(5, 7) === '12' && +p.d.slice(0, 4) % 2 === 1);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      {[1, maxV / 2, maxV].map((v, i) => (
        <g key={i}>
          <line x1={pl} y1={Y(v)} x2={W - pr} y2={Y(v)} stroke={C.rowBorder} />
          <text x={pl - 6} y={Y(v) + 3} textAnchor="end" fill={C.dim} fontSize={9} fontFamily={MONO}>
            {v.toFixed(1)}x
          </text>
        </g>
      ))}
      {yearTicks.map(p => (
        <text key={p.d} x={X(pts.indexOf(p))} y={H - 6} textAnchor="middle" fill={C.dim}
          fontSize={9} fontFamily={MONO}>{p.d.slice(0, 4)}</text>
      ))}
      <path d={path('bench')} fill="none" stroke={C.dim} strokeWidth={1.6} />
      <path d={path('strat')} fill="none" stroke={C.green} strokeWidth={2} />
    </svg>
  );
}

interface Engine {
  name: string; discount: string; bestFor?: string;
  answers: string; formula: string[]; gotcha: string;
}

const ENGINES: Engine[] = [
  {
    name: 'DCF', discount: 'WACC',
    answers: 'Intrinsic value on a NORMALIZED NOPAT base — earnings power grown at g, minus the reinvestment that growth requires (g / ROIC, the McKinsey value-driver form). This replaced a trailing-FCF-margin base that counted growth capex as lost cash and undervalued reinvestors (Amazon literally got no DCF). Deterministic; the backtest demoted DCF to the lowest engine weight.',
    formula: ['NOPAT = normalized op margin × revenue × (1 − tax)',
      'FCFFₜ = NOPATₜ · (1 − gₜ/ROIC)   — reinvestment fades as g fades',
      'Value = Σ FCFFₜ /(1+WACC)ᵗ + PV(TV) − NetDebt'],
    gotcha: 'Terminal value is 60–80% of the answer; growth is trailing CAGR capped at 20%. Falls back to the trailing-FCF base when ROIC is unusable. When ROIC < WACC growth destroys value, so the DCF can fall below the no-growth EPV — that inversion is itself the signal.',
  },
  {
    name: 'Reverse DCF', discount: 'WACC held', bestFor: 'the anchor',
    answers: 'Inverts the DCF — what stage-1 growth does today’s price already imply?',
    formula: ['Solve  g₁  such that', '     DCF(g₁) = Current Price', '(WACC, horizon, terminal g held at defaults)'],
    gotcha: 'The only assumption-light engine — and the curve-fit guard for every manual override. Implied growth is N/A when ROIC ≤ WACC: growth destroys value there, so the solve is degenerate rather than a number worth trusting.',
  },
  {
    name: 'RIM — Residual Income', discount: 'Re', bestFor: 'banks · financials',
    answers: 'Book equity plus the present value of returns earned above the cost of equity.',
    formula: ['Value = B₀ + Σ PV[ (ROEₜ − Re)·Bₜ₋₁ ]', 'ROE fades toward Re · persistence ω = 0.62'],
    gotcha: 'Marked N/A when book value ≤ 0 or buyback-distorted (most of this universe) — never forced to emit a number. Measured sensitivity (v2.3, 90 S&P financials): ±100bp of Re moves the mid only ∓2.2% — the ω-fade dominates, so values are book-anchored and deliberately conservative for franchise banks that sustain high ROE. Read financial-sector "overvalued" as an expectations meter, not a short signal.',
  },
  {
    name: 'EPV — Earnings Power', discount: 'WACC',
    answers: 'Value of current earnings power assuming zero growth — the explicit FLOOR of the range, never averaged into the mid.',
    formula: ['Normalized EBIT = avg margin (5y · 10y for cyclicals) × revenue', 'EPV(ops) = NOPAT / WACC', 'EPV(equity) = EPV(ops) + Cash − Debt'],
    gotcha: 'EPV < current EV means the market is paying for growth — the gap is itself the signal. When ROIC < WACC the no-growth EPV can sit ABOVE the growth cases: there it is a ceiling, not a floor (shown on the card).',
  },
  {
    name: 'Warranted multiple v2', discount: 'relative',
    answers: 'Bucket-median EV/EBIT anchor (fixed-effects), adjusted within bucket for growth, margin AND ROIC, applied to this company’s EBIT. TECH splits into semis / software / hardware (hand-mapped override table; ≥8 fitted names per bucket or it rolls back to the sector).',
    formula: ['anchor = bucket median EV/EBIT, capped at 28×', 'mult = anchor + b_g·Δg + b_m·Δmargin + b_r·ΔROIC   (all sign-guarded ≥ 0)', 'Value = (mult × EBIT − Debt + Cash) / shares'],
    gotcha: 'A 35%-ROIC name earns a higher multiple than an 8%-ROIC peer in the same bucket — in the live fit ROIC absorbed the margin signal (it is the better value driver). The 28× cap stops the anchor from inheriting market froth (semis and hardware sit AT the cap — the AI bid is real). Overrides live in assumptions.toml; unmapped names stay in the parent bucket on purpose.',
  },
  {
    name: 'DDM — Dividend Discount', discount: 'Re',
    answers: 'Value of the dividend stream, as a multi-stage Gordon model.',
    formula: ['V = Σ PV(Dₜ) + PV(terminal)', 'dividend growth faded to terminal g'],
    gotcha: 'Live for meaningful dividend payers (yield ≥ 1%, payout covered by earnings; REITs exempt — they pay from FFO). Stage-1 growth is clamped to a [0, 8%] dividend band so an unsustainable payout can’t compound to a silly number.',
  },
  {
    name: 'P/FFO', discount: 'relative', bestFor: 'REITs',
    answers: 'REIT cash earnings at the covered-REIT median multiple — replaces RIM-on-book, whose historical-cost book misprices REITs (and made negative-book towers/logistics unpriceable).',
    formula: ['FFO = NI + D&A − property-sale gains + RE impairments',
      'anchor = median covered-REIT P/FFO, capped 8–20×',
      'Value = anchor × FFO / share'],
    gotcha: 'One flat anchor across sub-sectors (malls ~12× vs data centers ~20× street) — same known bucket-limitation as TECH in the warranted engine. Gains/impairment tags land at the next data refresh; until then the basis is disclosed per name (NI+D&A).',
  },
];

// [id, backtest file ('' = screening-only, no credible backtest), label]
const UNIVERSES: [string, string, string][] = [
  ['ndx', 'backtest.json', 'NASDAQ-100'],
  ['sp500', 'backtest_sp500.json', 'S&P 500'],
  ['sp1500', '', 'S&P 1500'],
  ['nyse', '', 'NYSE $1B+'],
];

export function Methodology({ meta }: { meta: Meta }) {
  const [bts, setBts] = useState<Record<string, Backtest | null>>({});
  const [ledgers, setLedgers] = useState<Record<string, Ledger | null>>({});
  const [moms, setMoms] = useState<Record<string, Momentum | null>>({});
  const [dq, setDq] = useState<DataQuality | null>(null);
  // default the backtest/ledger toggle to the universe the board is showing, so
  // opening Methodology from the S&P 1500 board lands on its (screening-only) view
  const [uni, setUni] = useState(
    UNIVERSES.some(([k]) => k === meta.universeId) ? meta.universeId! : 'ndx');
  useEffect(() => {
    const w = window as unknown as { __FV_BT__?: Record<string, Backtest>;
      __FV_LEDGER__?: Ledger | null; __FV_MOM__?: Record<string, Momentum>;
      __FV_DQ__?: DataQuality | null };
    if (w.__FV_BT__) {                                // single-file share build
      setBts(w.__FV_BT__);
      setLedgers({ ndx: w.__FV_LEDGER__ ?? null });   // share embeds the default universe only
      setMoms(w.__FV_MOM__ ?? {});
      setDq(w.__FV_DQ__ ?? null);
      return;
    }
    fetch(`${import.meta.env.BASE_URL}data_quality.json`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => setDq(d))
      .catch(() => {});
    for (const [k, f] of UNIVERSES) {
      if (f) fetch(`${import.meta.env.BASE_URL}${f}`)     // '' = screening-only, no backtest
        .then(r => (r.ok ? r.json() : null))
        .then(d => setBts(p => ({ ...p, [k]: d })))
        .catch(() => {});
      fetch(`${import.meta.env.BASE_URL}momentum${k === 'ndx' ? '' : '_' + k}.json`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => setMoms(p => ({ ...p, [k]: d })))
        .catch(() => {});
      fetch(`${import.meta.env.BASE_URL}ledger_${k}.json`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => setLedgers(p => ({ ...p, [k]: d })))
        .catch(() => {});
    }
  }, []);
  const bt = bts[uni] ?? null;
  const mom = moms[uni] ?? null;
  const ledger = ledgers[uni] ?? null;

  const assumptions = [
    { label: 'Risk-free (10Y)', value: (meta.riskFree * 100).toFixed(2) + '%', src: meta.riskFreeSource },
    { label: 'Equity risk prem.', value: (meta.erp * 100).toFixed(1) + '%', src: 'Damodaran implied' },
    { label: 'Terminal growth', value: (meta.terminalG * 100).toFixed(1) + '%', src: '≤ risk-free ceiling' },
    { label: 'Tax rate', value: 'effective', src: 'filings, 3y mean, 10–35% clamp' },
    { label: 'Forecast horizon', value: '10 yr', src: '2-stage fade' },
    { label: 'SBC treatment', value: 'Expensed', src: 'subtract from FCF' },
    { label: 'Beta', value: 'Blume-adj', src: '5y monthly vs S&P 500' },
    { label: 'Size premium', value: 'CRSP bands', src: '+0–1.5% to Re, small caps only' },
    { label: 'Range width', value: 'quality-scaled', src: '+10→+50% upside band; low = EPV floor' },
    { label: 'Scenarios', value: 'Bear/Base/Bull', src: 'DCF driver shifts · 25/50/25 weighted' },
    { label: 'Capital panel', value: 'ROIC − WACC', src: 'economic spread · incremental ROIC' },
    { label: 'Share counts', value: 'xchecked', src: 'Yahoo mcap, >15% patched' },
  ];

  return (
    <div style={{ padding: '22px 24px 50px', maxWidth: 1180 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0 }}>Methodology &amp; Backtest</h1>
        <div style={{ fontSize: 12, color: C.mid, marginTop: 3 }}>
          Live pipeline: SEC EDGAR (XBRL, as-filed) + market prices → five engines → triangulated range.
          A research aid, not a recommendation.
        </div>
      </div>

      {/* backtest — real results (honest even when negative) or empty state */}
      <div className="mt-main">
        <div style={{ ...card, padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, gap: 10, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Backtest equity curve</div>
              {UNIVERSES.filter(([k, f]) => bts[k] || ledgers[k] || !f).map(([k, f, label]) => (
                <button key={k} onClick={() => setUni(k)} aria-pressed={uni === k} title={f ? 'constituent-based backtest' : 'screening-only — forward ledger evidence'} style={{
                  fontSize: 10.5, borderRadius: 5, padding: '3px 9px',
                  border: `1px solid ${uni === k ? hexA(C.blue, 0.4) : C.borderHi}`,
                  background: uni === k ? 'rgba(68,147,248,0.15)' : undefined,
                  color: uni === k ? '#fff' : C.mid, fontWeight: 600,
                }}>{label}{!f && <span style={{ color: C.dim, fontWeight: 400 }}> · screen</span>}</button>
              ))}
            </div>
            {bt && (
              <div style={{ display: 'flex', gap: 14, fontSize: 11 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 16, height: 3, background: C.green, borderRadius: 2 }} />Top-quintile basket
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 16, height: 3, background: C.dim, borderRadius: 2 }} />Equal-weight universe
                </span>
              </div>
            )}
          </div>
          {bt ? (
            <>
              <EquityCurve bt={bt} />
              <div style={{
                marginTop: 12, padding: '10px 13px', borderRadius: 8, fontSize: 12, lineHeight: 1.6,
                background: hexA(C.amber, 0.08), border: `1px solid ${hexA(C.amber, 0.35)}`, color: '#e8c98a',
              }}>
                <b>Honest verdict: {bt.stats.stratCAGR - bt.stats.benchCAGR < -0.01
                  ? 'no edge — value-tilted selection underperformed this growth-led universe.'
                  : bt.stats.stratCAGR - bt.stats.benchCAGR > 0.01
                  ? 'modest outperformance — but within the noise and coverage caveats; not proof of alpha.'
                  : 'market-matching — the signal neither helped nor hurt here; no edge demonstrated.'}</b>{' '}
                Over {bt.meta.start.slice(0, 4)}–{bt.meta.end.slice(0, 4)}, the composite top-quintile returned{' '}
                {(bt.stats.stratCAGR * 100).toFixed(1)}%/yr vs {(bt.stats.benchCAGR * 100).toFixed(1)}%/yr
                for equal-weight. Treat every screen as a research aid, not a signal with proven alpha.
                {bt.meta.survivorship && (
                  <>{' '}<b>Decision gate (Phase 1.4):</b> with survivorship now measured at{' '}
                  {bt.meta.survivorship.windows[0].gapPP >= 0 ? '+' : ''}{bt.meta.survivorship.windows[0].gapPP}pp/yr
                  of covered-pool tailwind, the composite has no demonstrated edge — this product is an{' '}
                  <b>expectations meter + trap gate + momentum overlay</b>, not an alpha signal.</>
                )}
              </div>
              {bt.meta.survivorship && (
                <div style={{
                  marginTop: 10, padding: '10px 13px', borderRadius: 8,
                  border: `1px solid ${C.border}`, background: C.inset ?? undefined,
                }}>
                  <div style={{ fontSize: 11, fontWeight: 650, color: C.sec, marginBottom: 6 }}>
                    Survivorship, measured{' '}
                    <span style={{ fontWeight: 400, color: C.dim }}>
                      — covered equal-weight pool vs {bt.meta.survivorship.ewProxy} (real equal-weight index, total return).
                      The gap is the flattery bound: delisted members we can't price are missing from both
                      strategy and benchmark.
                    </span>
                  </div>
                  {bt.meta.survivorship.windows.map(w => (
                    <div key={w.label} style={{
                      display: 'flex', gap: 14, fontFamily: MONO, fontSize: 11,
                      color: C.mid, lineHeight: 1.8, flexWrap: 'wrap',
                    }}>
                      <span style={{ width: 110, color: C.dim }}>{w.label}</span>
                      <span>covered {(w.coveredEW * 100).toFixed(1)}%/yr</span>
                      <span>{bt.meta.survivorship!.ewProxy} {(w.indexEwTR * 100).toFixed(1)}%/yr</span>
                      <span style={{ fontWeight: 650, color: w.gapPP > 0 ? C.amber : C.green }}>
                        gap {w.gapPP >= 0 ? '+' : ''}{w.gapPP.toFixed(1)}pp/yr
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : UNIVERSES.find(([k]) => k === uni)?.[1] === '' ? (
            <div style={{
              borderRadius: 9, padding: '20px 20px', fontSize: 12.5, lineHeight: 1.75,
              background: hexA(C.blue, 0.06), border: `1px solid ${hexA(C.blue, 0.28)}`, color: C.sec,
            }}>
              <div style={{ fontSize: 13, fontWeight: 650, marginBottom: 5 }}>
                Screening universe — no backtest by design
              </div>
              <span style={{ color: C.dim3 }}>
                The S&amp;P 1500 is a broad SCREENING universe. We deliberately publish no
                equity curve for it: a credible, survivorship-free backtest needs delisted-member
                PRICE history, and that gap is worst exactly here — small-caps delist most and no
                free source serves their prices (needs CRSP). Claiming a backtest we can't stand
                behind would violate the honesty law. The backtested evidence lives under
                NASDAQ-100 and S&amp;P 500 (constituent-based, survivorship measured); the{' '}
                <b style={{ color: C.sec }}>forward paper-trading ledger below</b> is this
                universe's own out-of-sample test, accruing from inception.
              </span>
            </div>
          ) : (
            <div style={{
              border: `1px dashed ${C.borderHi}`, borderRadius: 9, padding: '38px 20px',
              textAlign: 'center', color: C.dim, fontSize: 12.5, lineHeight: 1.7,
            }}>
              <div style={{ fontSize: 13, color: C.mid, fontWeight: 600, marginBottom: 4 }}>Backtest not yet run</div>
              An honest backtest needs a point-in-time, survivorship-free store (Phase 7).<br />
              Run backend/backtest.py — no performance claims are shown until it exists.
            </div>
          )}
        </div>
        <div style={{ ...card, padding: '18px 20px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>
            {bt ? 'Performance' : 'Data quality'}
          </div>
          {bt ? (
            <>
              {[
                { label: 'CAGR', s: (bt.stats.stratCAGR * 100).toFixed(1) + '%', b: (bt.stats.benchCAGR * 100).toFixed(1) + '%', color: bt.stats.stratCAGR >= bt.stats.benchCAGR ? C.green : C.red },
                { label: 'Hit rate', s: (bt.stats.hitRate * 100).toFixed(0) + '%', b: '—', color: bt.stats.hitRate >= 0.5 ? C.green : C.red },
                { label: 'Sharpe', s: String(bt.stats.stratSharpe), b: String(bt.stats.benchSharpe), color: C.hi },
                { label: 'Max drawdown', s: (bt.stats.stratMaxDD * 100).toFixed(0) + '%', b: (bt.stats.benchMaxDD * 100).toFixed(0) + '%', color: C.red },
                { label: 'Turnover', s: bt.stats.avgTurnover === null ? '—' : (bt.stats.avgTurnover * 100).toFixed(0) + '%/q', b: '—', color: C.mid },
                { label: 'Avg names', s: String(bt.stats.avgNames), b: '', color: C.mid },
                { label: 'Coverage', s: (bt.meta.avgCoverage * 100).toFixed(0) + '%', b: '', color: bt.meta.avgCoverage > 0.8 ? C.green : C.amber },
              ].map(s => (
                <div key={s.label} style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
                  <span style={{ fontSize: 11.5, color: C.dim3 }}>{s.label}</span>
                  <span style={{ display: 'flex', gap: 14, alignItems: 'baseline' }}>
                    <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 600, color: s.color }}>{s.s}</span>
                    <span style={{ fontFamily: MONO, fontSize: 11, color: C.dim, width: 44, textAlign: 'right' }}>{s.b}</span>
                  </span>
                </div>
              ))}
            </>
          ) : (
            [
              { label: 'Universe coverage', value: `${meta.covered} / ${meta.covered + meta.excluded.length}`, color: C.green },
              { label: 'Excluded (honest)', value: String(meta.excluded.length), color: C.amber },
              { label: 'Data as of', value: meta.asOf.split('·')[0].trim(), color: C.hi },
            ].map(dq => (
              <div key={dq.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, marginBottom: 12 }}>
                <span style={{ color: C.dim3 }}>{dq.label}</span>
                <span style={{ fontFamily: MONO, fontWeight: 600, color: dq.color }}>{dq.value}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {bt && (
        <div className="mt-half">
          <div style={{ ...card, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, fontSize: 13, fontWeight: 600, color: C.sec }}>
              Per-method reliability <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>top quintile vs benchmark, quarterly</span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: C.dim, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <th style={{ textAlign: 'left', padding: '8px 20px', fontWeight: 500 }}>Method</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Hit rate</th>
                  <th style={{ textAlign: 'right', padding: '8px 20px', fontWeight: 500 }}>Avg excess / q</th>
                </tr>
              </thead>
              <tbody>
                {bt.perMethod.map(p => (
                  <tr key={p.method} style={{ borderTop: `1px solid ${C.rowBorder}` }}>
                    <td style={{ padding: '10px 20px', fontWeight: 600 }}>{p.method}</td>
                    <td style={{ padding: '10px 10px', textAlign: 'right', fontFamily: MONO, color: p.hitRate >= 0.5 ? C.green : C.red }}>
                      {(p.hitRate * 100).toFixed(0)}%
                    </td>
                    <td style={{ padding: '10px 20px', textAlign: 'right', fontFamily: MONO, color: p.avgExcessQ >= 0 ? C.green : C.red }}>
                      {(p.avgExcessQ * 100).toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 10 }}>Backtest caveats — read before believing anything</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11.5, color: C.dim3, lineHeight: 1.8 }}>
              {bt.meta.caveats.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </div>
        </div>
      )}

      {/* forward paper-trading ledger — the live out-of-sample test */}
      {ledger && ledger.baskets.length > 0 && (() => {
        const curModel = ledger.baskets[ledger.baskets.length - 1].model;
        const s = ledger.summary[curModel];
        const rows = [...ledger.baskets].reverse().slice(0, 10);
        const fp = (v: number | null) => (v === null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`);
        return (
          <div style={{ ...card, marginBottom: 18, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Forward ledger — the live test</span>
              <span style={{
                fontFamily: MONO, fontSize: 10, color: C.mid,
                border: `1px solid ${C.borderHi}`, borderRadius: 4, padding: '2px 7px',
              }}>model {curModel}</span>
              <span style={{ fontSize: 10.5, color: C.dim }}>
                baskets frozen at each refresh, marked to the latest run — no in-sample escape hatch
              </span>
            </div>
            <div style={{ padding: '12px 20px', fontSize: 11.5, lineHeight: 1.6, color: C.dim3, borderBottom: `1px solid ${C.border}` }}>
              {s && s.aged > 0 ? (
                <>Model <b style={{ color: C.sec }}>{curModel}</b>: {s.aged} aged basket{s.aged > 1 ? 's' : ''} over {s.oldestDays} days ·
                  avg excess <b style={{ color: (s.avgExcess ?? 0) >= 0 ? C.green : C.red }}>{fp(s.avgExcess)}</b> ·
                  hit rate <b style={{ color: C.sec }}>{s.hitRate === null ? '—' : `${(s.hitRate * 100).toFixed(0)}%`}</b>.
                  {s.oldestDays < 90 && ' Under ~90 days of forward data this is noise, not evidence.'}</>
              ) : (
                <>Ledger inception <b style={{ color: C.sec }}>{ledger.baskets[0].date}</b> — no aged baskets yet.
                  Forward returns accrue from here; this needs quarters, not days, before it means anything.
                  Unlike the backtest, this test cannot be flattered: the picks were committed before the returns existed.</>
              )}
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: C.dim, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <th style={{ textAlign: 'left', padding: '8px 20px', fontWeight: 500 }}>Frozen</th>
                  <th style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 500 }}>Model</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Age</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Names</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Basket</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Bench</th>
                  <th style={{ textAlign: 'right', padding: '8px 20px', fontWeight: 500 }}>Excess</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(b => (
                  <tr key={b.runDate} style={{ borderTop: `1px solid ${C.rowBorder}` }}>
                    <td style={{ padding: '9px 20px', fontFamily: MONO }}>{b.date}</td>
                    <td style={{ padding: '9px 10px', fontFamily: MONO, color: b.model === curModel ? C.sec : C.dim }}>{b.model}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid }}>{b.ageDays}d</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, color: b.missing ? C.amber : C.mid }}>
                      {b.covered}/{b.k}
                    </td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO }}>{fp(b.basketRet)}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid }}>{fp(b.benchRet)}</td>
                    <td style={{
                      padding: '9px 20px', textAlign: 'right', fontFamily: MONO, fontWeight: 600,
                      color: b.excess === null ? C.dim : b.excess >= 0 ? C.green : C.red,
                    }}>{fp(b.excess)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '10px 20px', fontSize: 10.5, color: C.dim, lineHeight: 1.7, borderTop: `1px solid ${C.border}` }}>
              {ledger.meta.caveats.join(' · ')}
            </div>
          </div>
        );
      })()}

      {/* momentum factor study — the one signal with a real (net-of-cost, OOS) edge */}
      {mom && (() => {
        const net = mom.variants['MOM (net 10bp)'] ?? {};
        const wins = ['full 2012-26', 'pre2012-15 (OOS)', '2016-2021', '2022-2026 (hi-cov)'];
        const fp = (v: number | undefined) => (v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}pp`);
        const strong = uni === 'ndx';
        return (
          <div style={{ ...card, marginBottom: 18, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Momentum factor — the one signal with a real edge</span>
              <span style={{ fontSize: 10.5, color: C.dim }}>12-1 price momentum · monthly rebalance · top quintile · net of 10bp/side cost · excess vs equal-weight</span>
            </div>
            <div style={{ padding: '12px 20px', fontSize: 11.5, lineHeight: 1.6, color: C.dim3, borderBottom: `1px solid ${C.border}` }}>
              {strong ? (
                <>On the <b style={{ color: C.sec }}>Nasdaq-100</b>, momentum is the first factor to show a durable edge —
                  positive in <b style={{ color: C.green }}>all four windows</b> including the 2012-2015 window that
                  predates any of our signal design (genuinely out-of-sample) and the high-coverage 2022-2026 window
                  (least survivorship). Turnover is only ~25%/mo, so it survives realistic costs.</>
              ) : (
                <>On the <b style={{ color: C.sec }}>S&P 500</b>, momentum is <b style={{ color: C.amber }}>weak and
                  regime-dependent</b> — modestly positive full-sample and out-of-sample, but it <b style={{ color: C.red }}>lost
                  in 2016-2021</b>. Momentum pays in the trendier growth universe, not the broad market.</>
              )}
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: C.dim, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <th style={{ textAlign: 'left', padding: '8px 20px', fontWeight: 500 }}>Window</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Excess/yr</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Hit</th>
                  <th style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 500 }}>Sharpe</th>
                  <th style={{ textAlign: 'right', padding: '8px 20px', fontWeight: 500 }}>MaxDD</th>
                </tr>
              </thead>
              <tbody>
                {wins.map(w => {
                  const s = net[w];
                  return (
                    <tr key={w} style={{ borderTop: `1px solid ${C.rowBorder}` }}>
                      <td style={{ padding: '9px 20px', color: w.includes('OOS') ? C.sec : C.mid, fontWeight: w.includes('OOS') ? 600 : 400 }}>{w}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, fontWeight: 600, color: (s?.excess ?? 0) >= 0 ? C.green : C.red }}>{fp(s?.excess)}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid }}>{s ? `${(s.hitRate * 100).toFixed(0)}%` : '—'}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid }}>{s ? s.stratSharpe : '—'}</td>
                      <td style={{ padding: '9px 20px', textAlign: 'right', fontFamily: MONO, color: C.red }}>{s ? `${(s.stratMaxDD * 100).toFixed(0)}%` : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div style={{ padding: '10px 20px', fontSize: 10.5, color: C.dim, lineHeight: 1.7, borderTop: `1px solid ${C.border}` }}>
              Momentum is shown as a <b>displayed factor</b> (per-name percentile on the board) — it is deliberately NOT
              blended into the fair-value composite (Plan 6 showed dilution destroys it). Caveats: momentum is well-known
              and crowded; −20% to −33% drawdowns are real; early-year survivorship still flatters it (mitigated by the
              strong 2022-2026 result); costs beyond spread (impact) not modelled.
            </div>
          </div>
        );
      })()}

      {/* engines */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>How each engine values a company</div>
          <div style={{ fontSize: 11, color: C.dim }}>L6 · run only where applicable</div>
        </div>
        <div className="mt-engines">
          {ENGINES.map(fm => (
            <div key={fm.name} style={{ ...card, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>{fm.name}</span>
                <span style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
                  {fm.bestFor && (
                    <span style={{
                      fontSize: 10, fontWeight: 600, color: '#8d80e6',
                      background: hexA('#8d80e6', 0.13), border: `1px solid ${hexA('#8d80e6', 0.32)}`,
                      borderRadius: 4, padding: '2px 7px', whiteSpace: 'nowrap',
                    }}>{fm.bestFor}</span>
                  )}
                  <span style={{
                    fontFamily: MONO, fontSize: 10, color: C.mid,
                    border: `1px solid ${C.borderHi}`, borderRadius: 4, padding: '2px 7px', whiteSpace: 'nowrap',
                  }}>@ {fm.discount}</span>
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: C.mid, lineHeight: 1.5 }}>{fm.answers}</div>
              <div style={{
                background: C.code, border: '1px solid #1a1f29', borderRadius: 8,
                padding: '11px 13px', fontFamily: MONO, fontSize: 11.5, color: C.sec,
                lineHeight: 1.85, overflowX: 'auto',
              }}>
                {fm.formula.map((ln, i) => <div key={i} style={{ whiteSpace: 'nowrap' }}>{ln}</div>)}
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7, marginTop: 'auto' }}>
                <span style={{ color: C.amber, fontSize: 11, lineHeight: 1.5, flex: '0 0 auto' }}>⚠</span>
                <span style={{ fontSize: 11, color: C.dim3, lineHeight: 1.5 }}>{fm.gotcha}</span>
              </div>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 14, background: C.panel,
          border: `1px solid ${C.border}`, borderRadius: 11, padding: '16px 20px',
          display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.sec, flex: '0 0 auto' }}>L8 · Triangulate → range</div>
          <div style={{
            fontFamily: MONO, fontSize: 11.5, color: C.sec, background: C.code,
            border: '1px solid #1a1f29', borderRadius: 7, padding: '9px 13px', lineHeight: 1.85,
          }}>
            <div style={{ whiteSpace: 'nowrap' }}>mid = weight-blended growth engines · EPV sets the FLOOR</div>
            <div style={{ whiteSpace: 'nowrap' }}>agreement = engines within ±10% of mid → confidence 1–5</div>
          </div>
          <div style={{ fontSize: 11.5, color: C.dim3, flex: 1, minWidth: 220, lineHeight: 1.55 }}>
            The spread of applicable estimates <span style={{ color: C.sec }}>is</span> the range; method agreement{' '}
            <span style={{ color: C.sec }}>is</span> the confidence score. Engines the router deems inapplicable
            (greyed N/A) are never averaged in.
          </div>
        </div>
      </div>

      {/* assumptions */}
      <div style={{ ...card, padding: '18px 20px', marginBottom: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>
          Global assumptions <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>version-controlled config (assumptions.toml)</span>
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 1,
          background: C.border, border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden',
        }}>
          {assumptions.map(a => (
            <div key={a.label} style={{ background: C.chrome, padding: '13px 15px' }}>
              <div style={{ fontSize: 10, color: C.dim, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6 }}>{a.label}</div>
              <div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 600, color: C.sec }}>{a.value}</div>
              <div style={{ fontSize: 10, color: C.dim, marginTop: 4 }}>{a.src}</div>
            </div>
          ))}
        </div>
      </div>

      {/* data-quality dry run — the S&P 1500 coverage gate for universe expansion */}
      {dq && (
        <div style={{ ...card, padding: '18px 20px', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4, gap: 10, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>
              Data-quality dry run <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>bulk-EDGAR coverage on the broad S&amp;P 1500 — the universe-expansion gate</span>
            </div>
            <span style={{
              fontFamily: MONO, fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 6,
              color: dq.gate_pass ? C.green : C.red,
              background: hexA(dq.gate_pass ? C.green : C.red, 0.13),
            }}>{dq.gate_pass ? 'GATE PASS' : 'GATE FAIL'}</span>
          </div>
          <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', margin: '10px 0 4px' }}>
            {[
              [`${dq.coverage_pct}%`, `coverage (≥${dq.core_min}/25 concepts)`],
              [`${dq.core_covered} / ${dq.names}`, 'names covered'],
              [`${dq.ingestable}`, 'ingestable (CIK + facts)'],
              [`${dq.elapsed_s}s`, 'bulk ingest time'],
            ].map(([v, l]) => (
              <div key={l}>
                <div style={{ fontFamily: MONO, fontSize: 18, fontWeight: 600, color: C.sec }}>{v}</div>
                <div style={{ fontSize: 10, color: C.dim, marginTop: 2 }}>{l}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: C.dim3, lineHeight: 1.7, marginTop: 8 }}>
            Where a concept leans on a non-primary XBRL tag — the seams that widen on smaller filers:
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {[...dq.concepts].filter(c => c.have >= 50).sort((a, b) => b.fallback_pct - a.fallback_pct).slice(0, 6).map(c => (
              <div key={c.concept} style={{ background: C.chrome, border: `1px solid ${C.border}`, borderRadius: 7, padding: '7px 11px' }}>
                <div style={{ fontFamily: MONO, fontSize: 11.5, color: C.mid, fontWeight: 600 }}>{c.concept}</div>
                <div style={{ fontSize: 10, color: C.dim, marginTop: 3 }}>
                  <span style={{ color: c.fallback_pct > 50 ? C.amber : C.dim3 }}>{c.fallback_pct}% fallback</span> · {c.have_pct}% present
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: C.dim, marginTop: 10, lineHeight: 1.6 }}>
            {dq.names} names measured in {dq.elapsed_s}s via one nightly download (was ~5h of throttled per-ticker calls).
            Coverage counts raw concept presence; the live board applies stricter per-name value gates. {dq.no_cik} no-CIK · {dq.no_facts} no-facts. Generated {dq.generated}.
          </div>
        </div>
      )}

      {/* excluded */}
      <div style={{ ...card, padding: '18px 20px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 10 }}>
          Excluded names <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>shown as excluded, never silently dropped</span>
        </div>
        <div style={{ fontSize: 11.5, color: C.dim3, lineHeight: 1.9 }}>
          {meta.excluded.map(e => (
            <span key={e.ticker} style={{ marginRight: 14 }}>
              <span style={{ fontFamily: MONO, fontWeight: 600, color: C.mid }}>{e.ticker}</span>
              <span style={{ color: C.dim }}> — {e.why}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
