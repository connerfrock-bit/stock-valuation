import { C, MONO, upColor, qColor, confColor, hexA } from '../theme';
import { fmtPrice, fmtPct, fmtMcapB, na } from '../format';
import { RangeBar } from '../components/RangeBar';
import { ConfMeter, BigGauge, RatioBar } from '../components/Meters';
import { SectorTag } from '../components/SectorTag';
import { Sparkline } from '../components/Sparkline';
import type { Company, Meta } from '../types';

const FLAG_EXPLAIN: [RegExp, string][] = [
  [/^Altman-Z: distress/, 'Balance-sheet stress signal — the bankruptcy-risk model reads in the distress zone (note: harsh on capital-intensive businesses).'],
  [/^Piotroski/, 'Weak fundamental momentum — few of the nine improvement signals (profitability, leverage, efficiency) are passing.'],
  [/^Declining revenue 3y/, 'Top line has shrunk over three years; the market is extrapolating the decline.'],
  [/^Negative FCF/, 'The business consumes cash after capex and stock-comp — no positive base for cash-flow valuation.'],
  [/^High leverage/, 'Net debt above 3.5× EBITDA; equity value is highly sensitive to the debt load.'],
  [/^Negative book value/, 'Buybacks have driven book equity negative — book-anchored methods are undefined here.'],
  [/^High accruals/, 'Earnings are running ahead of cash — lower-quality, often mean-reverting.'],
  [/^Cyclical revenue/, 'Revenue growth is highly volatile — normalized figures may misstate mid-cycle economics in either direction.'],
  [/^VIE\/ADR structure/, 'Ownership runs through a VIE/ADR structure — legal claim on the assets is weaker than the numbers suggest.'],
  [/^Suspect share count/, 'Computed market cap is implausibly small — share count may be wrong; verify before acting.'],
  [/^Stale filings/, 'Latest annual filing is more than a year old — figures may not reflect the current business.'],
];

const explain = (f: string) =>
  FLAG_EXPLAIN.find(([re]) => re.test(f))?.[1] ?? '';

// mirror of engines.py CENTRAL_WEIGHTS (v2 reweight, Plan 3) — keep in sync
const WEIGHTS: Record<string, number> = { dcf: 0.10, rim: 0.35, warranted: 0.30, ddm: 0.10 };

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

export function DeepDive({ c, meta, peers, watch, toggleWatch, openDeep }: {
  c: Company;
  meta: Meta;
  peers: Company[];
  watch: Record<string, boolean>;
  toggleWatch: (t: string) => void;
  openDeep: (t: string) => void;
}) {
  const starred = !!watch[c.ticker];
  const verdict =
    (c.upside > 0.04 ? `Undervalued ~${Math.abs(Math.round(c.upside * 100))}% to mid`
      : c.upside < -0.04 ? `Overvalued ~${Math.abs(Math.round(c.upside * 100))}% to mid`
      : 'Fairly valued')
    + ' · ' + (c.conf >= 4 ? 'high' : c.conf >= 2 ? 'moderate' : 'low') + ' agreement';

  // ----- reverse-DCF callout -----
  const ig = c.impliedGrowth, tg = c.trailingG;
  const igStr = ig === null ? null
    : c.impliedOp === '<' ? `less than ${Math.round(ig * 100)}%`
    : c.impliedOp === '>' ? `more than ${Math.round(ig * 100)}%`
    : `~${Math.round(ig * 100)}%`;
  const revVerdict = ig === null || tg === null ? null
    : ig > tg + 0.04 ? 'optimistic' : ig < Math.max(-0.3, tg - 0.04) ? 'pessimistic' : 'roughly in line';
  const revColor = revVerdict === 'optimistic' ? C.red : revVerdict === 'pessimistic' ? C.green : C.amber;

  // ----- method weights (mirror of the L8 blend) -----
  const growthApplicable = c.methods.filter(m => m.applicable && m.key !== 'epv');
  const wsum = growthApplicable.reduce((s, m) => s + (WEIGHTS[m.key] ?? 0.1), 0);
  const weightOf = (key: string, applicable: boolean) =>
    key === 'epv' ? 'floor'
      : !applicable || wsum === 0 ? '—'
      : Math.round(((WEIGHTS[key] ?? 0.1) / wsum) * 100) + '%';

  const whyPoints = c.flags.map(f => ({ tag: f, text: explain(f) }));

  const leverage = [
    { label: 'Net debt / EBITDA', value: na(c.nde, v => v.toFixed(1) + 'x'), color: (c.nde ?? 0) > 2 ? C.amber : C.hi },
    { label: 'Altman-Z', value: na(c.altmanZ, v => v.toFixed(1)), color: c.altmanZ === null ? C.dim : c.altmanZ < 1.81 ? C.red : c.altmanZ < 3 ? C.amber : C.green },
    { label: 'Piotroski-F', value: c.piotroski === null ? `n/a (${c.piotroskiN} signals)` : `${c.piotroski}/9`, color: c.piotroski === null ? C.dim : c.piotroski >= 7 ? C.green : c.piotroski >= 4 ? C.amber : C.red },
    { label: 'FCF yield', value: na(c.fcfy, v => (v * 100).toFixed(1) + '%'), color: C.hi },
  ];

  const ratios = [
    { label: 'ROIC', value: na(c.roic, v => Math.round(v * 100) + '%'), pct: (c.roic ?? 0) / 0.3 },
    { label: 'Op margin (5y avg)', value: na(c.om, v => Math.round(v * 100) + '%'), pct: (c.om ?? 0) / 0.6 },
    { label: 'Rev growth (5y)', value: na(c.growth5y, v => fmtPct(v, 0)), pct: Math.max(0, (c.growth5y ?? 0) / 0.5) },
    { label: 'Quality rank', value: `${c.quality}/100`, pct: c.quality / 100 },
  ];

  const t = c.trends;
  const delta = (s: (number | null)[]) => {
    const v = s.filter((x): x is number => x !== null);
    return v.length >= 2 && v[0] !== 0 ? v[v.length - 1] / v[0] - 1 : null;
  };
  const trendDefs: { label: string; series: (number | null)[]; color: string }[] = [
    { label: 'Revenue ($B)', series: t.revenueB, color: C.blue },
    { label: 'Operating margin', series: t.opMargin, color: C.green },
    { label: 'Free cash flow ($B)', series: t.fcfB, color: '#b58cf0' },
    { label: 'Book equity ($B)', series: t.equityB, color: '#4fc3c9' },
  ];

  const edgarUrl = `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${c.cik}&type=10-K&dateb=&owner=include&count=40`;

  return (
    <div style={{ paddingBottom: 40 }}>
      {/* header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, padding: '16px 24px',
        borderBottom: `1px solid ${C.border}`, background: C.chrome,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <h1 style={{ display: 'flex', alignItems: 'baseline', gap: 11, margin: 0, fontWeight: 400 }}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24, letterSpacing: '.01em' }}>{c.ticker}</span>
          <span style={{ fontSize: 14, color: C.sec }}>{c.name}</span>
        </h1>
        <SectorTag sector={c.sector} label={c.sector} size={10} />
        {c.finCurrency !== 'USD' && (
          <span style={{ fontSize: 10, color: C.dim }}>reports in {c.finCurrency} · FX @ spot</span>
        )}
        <div style={{ flex: 1 }} />
        <div style={{ textAlign: 'right', lineHeight: 1.15 }}>
          <div style={{ fontSize: 10, color: C.dim2, textTransform: 'uppercase', letterSpacing: '.06em' }}>Price</div>
          <div style={{ fontFamily: MONO, fontSize: 20, fontWeight: 600 }}>{fmtPrice(c.price)}</div>
        </div>
        <div style={{ textAlign: 'right', lineHeight: 1.15 }}>
          <div style={{ fontSize: 10, color: C.dim2, textTransform: 'uppercase', letterSpacing: '.06em' }}>Mkt Cap</div>
          <div style={{ fontFamily: MONO, fontSize: 20, fontWeight: 600, color: C.sec }}>{fmtMcapB(c.mcapB)}</div>
        </div>
        <button onClick={() => toggleWatch(c.ticker)}
          aria-pressed={starred} aria-label={`${starred ? 'Remove' : 'Add'} ${c.ticker} ${starred ? 'from' : 'to'} watchlist`}
          style={{
            width: 34, height: 34, border: `1px solid ${C.borderHi}`, borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: starred ? C.amber : C.mid, fontSize: 16,
          }}>
          {starred ? '★' : '☆'}
        </button>
      </div>

      <div style={{ padding: '20px 24px', display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
        {/* LEFT column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
          {/* hero */}
          <div style={{ ...card, padding: '20px 22px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Fair-value range</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: upColor(c.upside) }}>{verdict}</div>
            </div>
            <RangeBar c={c} full />
          </div>

          {/* reverse DCF */}
          <div style={{
            background: 'linear-gradient(180deg,#0f1117,#0c0f15)',
            border: `1px solid ${hexA(revColor, 0.3)}`, borderRadius: 11, padding: '18px 22px',
          }}>
            <div style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: C.dim, marginBottom: 10 }}>
              Reverse DCF · market-implied expectations
            </div>
            <div style={{ fontSize: 18, lineHeight: 1.5, fontWeight: 500 }}>
              {igStr === null
                ? `A market-implied growth rate can't be computed for ${c.ticker} — no positive free-cash-flow base.`
                : <>At {fmtPrice(c.price)}, the market is pricing in {igStr}/yr growth for 5 years,
                    fading to {(meta.terminalG * 100).toFixed(1)}% terminal.
                    {tg !== null && <> {c.ticker}&rsquo;s trailing 5-yr revenue CAGR is {Math.round(tg * 100)}%.</>}</>}
            </div>
            {revVerdict && (
              <div style={{
                marginTop: 12, display: 'inline-flex', alignItems: 'center', gap: 7,
                fontSize: 12, fontWeight: 600, color: revColor,
                background: hexA(revColor, 0.13), borderRadius: 6, padding: '5px 11px',
              }}>
                Market is {revVerdict} vs. history
              </div>
            )}
          </div>

          {/* method breakdown */}
          <div style={{ ...card, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, fontSize: 13, fontWeight: 600, color: C.sec }}>
              Method breakdown
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: C.dim, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <th style={{ textAlign: 'left', padding: '9px 20px', fontWeight: 500 }}>Method</th>
                  <th style={{ textAlign: 'right', padding: '9px 12px', fontWeight: 500 }}>Estimate</th>
                  <th style={{ textAlign: 'right', padding: '9px 12px', fontWeight: 500 }}>Weight</th>
                  <th style={{ textAlign: 'left', padding: '9px 20px', fontWeight: 500 }}>Key assumption</th>
                </tr>
              </thead>
              <tbody>
                {c.methods.map(m => (
                  <tr key={m.key} style={{ borderTop: `1px solid ${C.rowBorder}`, opacity: m.applicable ? 1 : 0.45 }}>
                    <td style={{ padding: '10px 20px', fontWeight: 600, color: m.applicable ? C.hi : C.dim }}>{m.name}</td>
                    <td style={{
                      padding: '10px 12px', textAlign: 'right', fontFamily: MONO, fontWeight: 600,
                      color: !m.applicable || m.value === null ? C.dim : m.value > c.price ? C.green : C.red,
                    }}>
                      {m.applicable && m.value !== null ? fmtPrice(m.value) : 'N/A'}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: MONO, color: C.dim3 }}>
                      {weightOf(m.key, m.applicable)}
                    </td>
                    <td style={{ padding: '10px 20px', color: C.dim3, fontSize: 11.5 }}>{m.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* why disagree */}
          <div style={{ ...card, padding: '18px 22px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>
              Why does the market disagree?
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
              {whyPoints.length === 0 && (
                <Point color={C.green} tag="No trap flags."
                  text="Clean across the value-trap gate — the discount looks like mispricing, not distress." />
              )}
              {whyPoints.map(w => (
                <Point key={w.tag} color={/Altman|Negative|Declining|VIE|Suspect|Piotroski/.test(w.tag) ? C.red : C.amber}
                  tag={w.tag + ' —'} text={w.text} />
              ))}
              <Point color={C.mid} tag="Bear case:"
                text={c.upside > 0.05
                  ? 'skeptics argue growth decelerates faster than the model assumes and the discount is deserved.'
                  : 'bulls argue current multiples already bake in the premium; little margin of safety left.'} />
            </div>
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              {leverage.map(lv => (
                <div key={lv.label}>
                  <div style={{ fontSize: 10, color: C.dim, textTransform: 'uppercase', letterSpacing: '.05em' }}>{lv.label}</div>
                  <div style={{ fontFamily: MONO, fontSize: 14, fontWeight: 600, color: lv.color, marginTop: 3 }}>{lv.value}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14, paddingTop: 13, borderTop: `1px solid ${C.border}` }}>
              <a href={edgarUrl} target="_blank" rel="noreferrer" style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11,
                color: C.sec, border: `1px solid ${C.borderHi}`, borderRadius: 5, padding: '4px 9px',
              }}>
                <span style={{ fontFamily: MONO, fontWeight: 600 }}>EDGAR</span>
                View {c.ticker} filings (CIK {c.cik}) ↗
              </a>
            </div>
          </div>
        </div>

        {/* RIGHT column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>Quality &amp; safety</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
              <BigGauge q={c.quality} />
              <div>
                <div style={{ fontSize: 10, color: C.dim, textTransform: 'uppercase', letterSpacing: '.05em' }}>Quality score</div>
                <div style={{ fontFamily: MONO, fontSize: 26, fontWeight: 700, color: qColor(c.quality), lineHeight: 1.1 }}>{c.quality}</div>
                <div style={{ fontSize: 11, color: C.dim3 }}>
                  {c.quality >= 70 ? 'High quality' : c.quality >= 48 ? 'Average' : 'Low quality'}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {ratios.map(rt => (
                <div key={rt.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12 }}>
                  <span style={{ color: C.dim3 }}>{rt.label}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontFamily: MONO, fontWeight: 600, color: qColor(Math.max(0, Math.min(1, rt.pct)) * 100) }}>{rt.value}</span>
                    <RatioBar pct={rt.pct} color={qColor(Math.max(0, Math.min(1, rt.pct)) * 100)} />
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 6 }}>Method agreement</div>
            <div style={{ fontSize: 11.5, color: C.dim3, marginBottom: 13 }}>
              {c.within} of {growthApplicable.length} growth engines within ±10% of mid —{' '}
              {c.conf >= 4 ? 'high' : c.conf >= 2 ? 'moderate' : 'low'} agreement.
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ConfMeter score={c.conf} size={7} />
              <span style={{ fontSize: 13, fontWeight: 600, color: confColor(c.conf) }}>
                {(c.conf >= 4 ? 'High' : c.conf >= 2 ? 'Moderate' : 'Low') + ' · ' + c.conf + '/5'}
              </span>
            </div>
          </div>

          {/* momentum — a DISPLAYED factor, orthogonal to the value/quality story */}
          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Momentum</span>
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.dim }}>12-1, price factor</span>
            </div>
            {c.momPct == null ? (
              <div style={{ fontSize: 11.5, color: C.dim3, marginTop: 8 }}>
                No 12-month price history — momentum n/a for {c.ticker}.
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ height: 7, borderRadius: 4, background: '#161b24', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${c.momPct}%`, background: '#b58cf0', borderRadius: 4 }} />
                    </div>
                  </div>
                  <span style={{ fontFamily: MONO, fontSize: 18, fontWeight: 700, color: '#b58cf0', lineHeight: 1 }}>
                    {c.momPct}
                  </span>
                  <span style={{ fontSize: 10.5, color: C.dim }}>/100</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginTop: 10, fontSize: 12 }}>
                  <span style={{ color: C.dim3 }}>Trailing 12-1 return</span>
                  <span style={{ fontFamily: MONO, fontWeight: 600, color: (c.mom12 ?? 0) >= 0 ? C.green : C.red }}>
                    {c.mom12 == null ? 'n/a' : fmtPct(c.mom12, 0)}
                  </span>
                </div>
                <div style={{ fontSize: 10.5, color: C.dim, lineHeight: 1.5, marginTop: 10, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
                  Percentile rank within this universe. A displayed factor only —
                  <b> not</b> blended into the fair-value estimate (see Methodology → Momentum factor).
                </div>
              </>
            )}
          </div>

          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 14 }}>
              Financial trends{' '}
              <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>
                {t.years.length ? `FY${t.years[0]}–FY${t.years[t.years.length - 1]} · as filed`
                  : 'no mapped annual series'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
              {trendDefs.map(td => {
                const d = delta(td.series);
                return (
                  <div key={td.label}>
                    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 11.5, color: C.mid }}>{td.label}</span>
                      <span style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: d === null ? C.dim : d > 0 ? C.green : C.red }}>
                        {d === null ? 'n/a' : fmtPct(d, 0)}
                      </span>
                    </div>
                    <Sparkline series={td.series} color={td.color} />
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 12 }}>Sector peers</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {peers.map(p => (
                <button key={p.ticker} onClick={() => openDeep(p.ticker)} className="hoverrow"
                  aria-label={`Open ${p.ticker} deep dive`} style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '6px 4px',
                    width: '100%', borderRadius: 6, fontSize: 12,
                  }}>
                  <span style={{ fontFamily: MONO, fontWeight: 600, width: 54, textAlign: 'left' }}>{p.ticker}</span>
                  <span style={{ flex: 1, fontFamily: MONO, fontWeight: 600, textAlign: 'right', color: upColor(p.upside) }}>
                    {fmtPct(p.upside)}
                  </span>
                  <span style={{ width: 42, textAlign: 'right', fontFamily: MONO, color: C.dim3 }}>Q{p.quality}</span>
                  <ConfMeter score={p.conf} size={3} />
                </button>
              ))}
              {peers.length === 0 && <div style={{ fontSize: 11.5, color: C.dim }}>No covered peers in this sector.</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Point({ color, tag, text }: { color: string; tag: string; text: string }) {
  return (
    <div style={{ display: 'flex', gap: 11, alignItems: 'flex-start' }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, marginTop: 6, flex: '0 0 6px' }} />
      <span style={{ fontSize: 12.5, lineHeight: 1.55, color: '#c2c9d6' }}>
        <span style={{ fontWeight: 600, color }}>{tag}</span> {text}
      </span>
    </div>
  );
}
