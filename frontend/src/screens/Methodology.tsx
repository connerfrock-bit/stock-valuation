import { C, MONO, hexA } from '../theme';
import type { Meta } from '../types';

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

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

export function Methodology({ meta }: { meta: Meta }) {
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

      {/* backtest — honest empty state */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 18, marginBottom: 18 }}>
        <div style={{ ...card, padding: '18px 20px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 10 }}>Backtest equity curve</div>
          <div style={{
            border: `1px dashed ${C.borderHi}`, borderRadius: 9, padding: '38px 20px',
            textAlign: 'center', color: C.dim, fontSize: 12.5, lineHeight: 1.7,
          }}>
            <div style={{ fontSize: 13, color: C.mid, fontWeight: 600, marginBottom: 4 }}>Backtest not yet run</div>
            An honest backtest needs a point-in-time, survivorship-free store (Phase 7).<br />
            Until it exists, no performance claims are shown — anything else would be fiction.
          </div>
        </div>
        <div style={{ ...card, padding: '18px 20px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>Data quality</div>
          {[
            { label: 'Universe coverage', value: `${meta.covered} / ${meta.covered + meta.excluded.length}`, color: C.green },
            { label: 'Excluded (honest)', value: String(meta.excluded.length), color: C.amber },
            { label: 'Data as of', value: meta.asOf.split('·')[0].trim(), color: C.hi },
            { label: 'Risk-free source', value: meta.riskFreeSource.includes('live') ? 'FRED live' : 'fallback', color: meta.riskFreeSource.includes('live') ? C.green : C.amber },
            { label: 'Share counts', value: 'Yahoo x-checked', color: C.green },
          ].map(dq => (
            <div key={dq.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, marginBottom: 12 }}>
              <span style={{ color: C.dim3 }}>{dq.label}</span>
              <span style={{ fontFamily: MONO, fontWeight: 600, color: dq.color }}>{dq.value}</span>
            </div>
          ))}
        </div>
      </div>

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
