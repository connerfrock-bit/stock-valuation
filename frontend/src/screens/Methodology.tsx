import { useEffect, useState } from 'react';
import { C, MONO, hexA } from '../theme';
import type { Meta } from '../types';

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

interface Backtest {
  meta: { ranAt: string; start: string; end: string; rebalance: string;
    portfolio: string; benchmark: string; avgCoverage: number; caveats: string[] };
  curve: { d: string; strat: number; bench: number }[];
  stats: { quarters: number; years: number; stratCAGR: number; benchCAGR: number;
    hitRate: number; stratSharpe: number; benchSharpe: number;
    stratMaxDD: number; benchMaxDD: number; avgTurnover: number | null; avgNames: number };
  perMethod: { method: string; hitRate: number; avgExcessQ: number; quarters: number }[];
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
    answers: 'Intrinsic value from projected free cash flow — a 2,500-draw Monte Carlo (P10/P50/P90) on a NORMALIZED FCF base, not a point estimate.',
    formula: ['FCFF = CFO − Capex − SBC   (normalized: avg 5y FCF margin × revenue)',
      'TV = FCF₁₀·(1+g) / (WACC − g)',
      'Value = Σ FCFₜ /(1+WACC)ᵗ + PV(TV) − NetDebt'],
    gotcha: 'Terminal value is 60–80% of the answer; growth is trailing CAGR capped at 20% — deliberately conservative.',
  },
  {
    name: 'Reverse DCF', discount: 'WACC held', bestFor: 'the anchor',
    answers: 'Inverts the DCF — what stage-1 growth does today’s price already imply?',
    formula: ['Solve  g₁  such that', '     DCF(g₁) = Current Price', '(WACC, horizon, terminal g held at defaults)'],
    gotcha: 'The only assumption-light engine — and the curve-fit guard for every manual override.',
  },
  {
    name: 'RIM — Residual Income', discount: 'Re', bestFor: 'banks · financials',
    answers: 'Book equity plus the present value of returns earned above the cost of equity.',
    formula: ['Value = B₀ + Σ PV[ (ROEₜ − Re)·Bₜ₋₁ ]', 'ROE fades toward Re · persistence ω = 0.62'],
    gotcha: 'Marked N/A when book value ≤ 0 or buyback-distorted (most of this universe) — never forced to emit a number.',
  },
  {
    name: 'EPV — Earnings Power', discount: 'WACC',
    answers: 'Value of current earnings power assuming zero growth — the explicit FLOOR of the range, never averaged into the mid.',
    formula: ['Normalized EBIT = avg margin(5y) × revenue', 'EPV(ops) = NOPAT / WACC', 'EPV(equity) = EPV(ops) + Cash − Debt'],
    gotcha: 'EPV < current EV means the market is paying for growth — the gap is itself the signal.',
  },
  {
    name: 'Warranted multiple v2', discount: 'relative',
    answers: 'Sector-median EV/EBIT anchor (fixed-effects), adjusted within sector, applied to this company’s EBIT.',
    formula: ['anchor = sector median EV/EBIT, capped at 28×', 'mult = anchor + b·(g − ḡ_sector)   (sign-guarded)', 'Value = (mult × EBIT − Debt + Cash) / shares'],
    gotcha: 'The 28× cap stops the relative engine from inheriting market froth; TECH is still one bucket (semis vs software) — subsector split is a known refinement.',
  },
  {
    name: 'DDM — Dividend Discount', discount: 'Re',
    answers: 'Value of the dividend stream, as a multi-stage Gordon model.',
    formula: ['V = Σ PV(Dₜ) + PV(terminal)', 'dividend growth faded to terminal g'],
    gotcha: 'Consciously replaced by the warranted multiple for this universe — too few Nasdaq-100 names pay meaningful dividends.',
  },
];

const UNIVERSES: [string, string, string][] = [
  ['ndx', 'backtest.json', 'NASDAQ-100'],
  ['sp500', 'backtest_sp500.json', 'S&P 500'],
];

export function Methodology({ meta }: { meta: Meta }) {
  const [bts, setBts] = useState<Record<string, Backtest | null>>({});
  const [uni, setUni] = useState('ndx');
  useEffect(() => {
    for (const [k, f] of UNIVERSES) {
      fetch(`${import.meta.env.BASE_URL}${f}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => setBts(p => ({ ...p, [k]: d })))
        .catch(() => {});
    }
  }, []);
  const bt = bts[uni] ?? null;

  const assumptions = [
    { label: 'Risk-free (10Y)', value: (meta.riskFree * 100).toFixed(2) + '%', src: meta.riskFreeSource },
    { label: 'Equity risk prem.', value: (meta.erp * 100).toFixed(1) + '%', src: 'Damodaran implied' },
    { label: 'Terminal growth', value: (meta.terminalG * 100).toFixed(1) + '%', src: '≤ risk-free ceiling' },
    { label: 'Tax rate', value: '21%', src: 'US statutory fwd' },
    { label: 'Forecast horizon', value: '10 yr', src: '2-stage fade' },
    { label: 'SBC treatment', value: 'Expensed', src: 'subtract from FCF' },
    { label: 'Beta', value: 'Blume-adj', src: '5y monthly vs S&P 500' },
    { label: 'Share counts', value: 'xchecked', src: 'Yahoo mcap, >15% patched' },
  ];

  return (
    <div style={{ padding: '22px 24px 50px', maxWidth: 1180 }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 17, fontWeight: 600 }}>Methodology &amp; Backtest</div>
        <div style={{ fontSize: 12, color: C.mid, marginTop: 3 }}>
          Live pipeline: SEC EDGAR (XBRL, as-filed) + market prices → five engines → triangulated range.
          A research aid, not a recommendation.
        </div>
      </div>

      {/* backtest — real results (honest even when negative) or empty state */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 18, marginBottom: 18 }}>
        <div style={{ ...card, padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, gap: 10, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Backtest equity curve</div>
              {UNIVERSES.filter(([k]) => bts[k]).map(([k, , label]) => (
                <span key={k} onClick={() => setUni(k)} style={{
                  fontSize: 10.5, cursor: 'pointer', borderRadius: 5, padding: '3px 9px',
                  border: `1px solid ${uni === k ? hexA(C.blue, 0.4) : C.borderHi}`,
                  background: uni === k ? 'rgba(68,147,248,0.15)' : 'transparent',
                  color: uni === k ? '#fff' : C.mid, fontWeight: 600,
                }}>{label}</span>
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
              </div>
            </>
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
          <div style={{ ...card, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, fontSize: 13, fontWeight: 600, color: C.sec }}>
              Per-method reliability <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>top quintile vs benchmark, quarterly</span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: C.dim, fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '.05em' }}>
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

      {/* engines */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>How each engine values a company</div>
          <div style={{ fontSize: 11, color: C.dim }}>L6 · run only where applicable</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {ENGINES.map(fm => (
            <div key={fm.name} style={{ ...card, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>{fm.name}</span>
                <span style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
                  {fm.bestFor && (
                    <span style={{
                      fontSize: 9, fontWeight: 600, color: '#8d80e6',
                      background: hexA('#8d80e6', 0.13), border: `1px solid ${hexA('#8d80e6', 0.32)}`,
                      borderRadius: 4, padding: '2px 7px', whiteSpace: 'nowrap',
                    }}>{fm.bestFor}</span>
                  )}
                  <span style={{
                    fontFamily: MONO, fontSize: 9, color: C.mid,
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
          marginTop: 14, background: 'linear-gradient(180deg,#0f1117,#0c0f15)',
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
