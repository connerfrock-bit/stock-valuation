import { C, MONO, upColor, qColor, hexA, agreement } from '../theme';
import { fmtPrice, fmtPct, fmtMcapB, na } from '../format';
import { RangeBar } from '../components/RangeBar';
import { BigGauge, RatioBar } from '../components/Meters';
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

// Fallback only — live weights arrive in meta.weights (value.py emits
// engines.py CENTRAL_WEIGHTS since 2026-07-07; the hand mirror drifted once).
const FALLBACK_WEIGHTS: Record<string, number> = { dcf: 0.10, rim: 0.35, warranted: 0.30, ddm: 0.10 };

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

export function DeepDive({ c, meta, peers, all, watch, toggleWatch, openDeep }: {
  c: Company;
  meta: Meta;
  peers: Company[];
  all: Company[];
  watch: Record<string, boolean>;
  toggleWatch: (t: string) => void;
  openDeep: (t: string) => void;
}) {
  const starred = !!watch[c.ticker];
  const agree = agreement(c.conf, c.nMethods);
  const verdict =
    (c.upside > 0.04 ? `Undervalued ~${Math.abs(Math.round(c.upside * 100))}% to mid`
      : c.upside < -0.04 ? `Overvalued ~${Math.abs(Math.round(c.upside * 100))}% to mid`
      : 'Fairly valued')
    + ' · ' + (agree.single ? 'single method (by design)' : agree.detail);

  // ----- reverse-DCF callout -----
  const ig = c.impliedGrowth, tg = c.trailingG;
  const igStr = ig === null ? null
    : c.impliedOp === '<' ? `less than ${Math.round(ig * 100)}%`
    : c.impliedOp === '>' ? `more than ${Math.round(ig * 100)}%`
    : `~${Math.round(ig * 100)}%`;
  const revVerdict = ig === null || tg === null ? null
    : ig > tg + 0.04 ? 'optimistic' : ig < Math.max(-0.3, tg - 0.04) ? 'pessimistic' : 'roughly in line';
  const revColor = revVerdict === 'optimistic' ? C.red : revVerdict === 'pessimistic' ? C.green : C.sec;

  // ----- method weights (live from meta; fallback for pre-emit payloads) -----
  const WEIGHTS = meta.weights ?? FALLBACK_WEIGHTS;
  const growthApplicable = c.methods.filter(m => m.applicable && m.key !== 'epv');
  const wsum = growthApplicable.reduce((s, m) => s + (WEIGHTS[m.key] ?? 0.1), 0);
  const weightOf = (key: string, applicable: boolean) =>
    key === 'epv' ? 'floor'
      : !applicable || wsum === 0 ? '—'
      : Math.round(((WEIGHTS[key] ?? 0.1) / wsum) * 100) + '%';

  const whyPoints = c.flags.map(f => ({ tag: f, text: explain(f) }));

  // The counter-case is assembled from measured drivers, never boilerplate —
  // flags are already itemized above, so this only cites the non-flag signals.
  const counterCase = (() => {
    const d: string[] = [];
    if (c.upside > 0.04) {
      if (igStr !== null && tg !== null && ig !== null && ig < tg - 0.04)
        d.push(`the price only implies ${igStr}/yr growth vs ${Math.round(tg * 100)}% trailing — the market is betting on deceleration`);
      if (c.momPct != null && c.momPct <= 35)
        d.push(`momentum sits at the ${c.momPct}th percentile — the market is still marking it down`);
      if (c.quality < 48)
        d.push(`quality screens ${c.quality}/100, so part of the discount is earned`);
      if (agree.single)
        d.push(`a single valuation method applies here (by design for this archetype) — there is no cross-engine agreement to lean on, so weight the one method's own caveats`);
      else if (c.conf <= 2)
        d.push(`only ${c.conf}/5 engine agreement — the applicable engines disagree, so the fair-value range itself is soft`);
      return {
        tag: 'Bear case:',
        text: d.length
          ? d.join('; ') + '.'
          : 'no measured driver in coverage — the discount rests on factors outside this model (litigation, pipeline, regulation, sentiment). Read the filings before trusting it.',
      };
    }
    if (c.upside < -0.04) {
      if (igStr !== null && tg !== null && ig !== null && ig > tg + 0.04)
        d.push(`the price underwrites ${igStr}/yr growth vs ${Math.round(tg * 100)}% trailing — the market believes in acceleration this model won't assume`);
      if (c.momPct != null && c.momPct >= 65)
        d.push(`momentum is strong (${c.momPct}th percentile) and the market keeps paying up`);
      if (c.quality >= 70)
        d.push(`quality is ${c.quality}/100 — compounding beyond the 10-yr model horizon is the standard justification`);
      return {
        tag: 'Bull case:',
        text: d.length
          ? d.join('; ') + '.'
          : 'no measured driver in coverage — the premium rests on expectations this model doesn\'t capture.',
      };
    }
    return {
      tag: 'At fair value:',
      text: 'model and market roughly agree — the band brackets the price, so there is no valuation edge here either way.',
    };
  })();

  // Balance-sheet businesses get balance-sheet metrics: Altman-Z, Piotroski,
  // ND/EBITDA and FCF yield are all invalid for banks/insurers/REITs (v2.3
  // gates them at the source), so the strip swaps to the honest set.
  const isFin = c.archetype === 'financial' || c.archetype === 'reit';
  const leverage = isFin ? [
    { label: 'Equity / assets', value: na(c.eqAssets, v => (v * 100).toFixed(1) + '%'), color: (c.eqAssets ?? 1) < 0.04 ? C.amber : C.hi },
    { label: 'ROE (5y avg)', value: na(c.roe, v => (v * 100).toFixed(1) + '%'), color: C.hi },
    { label: 'ROE stability', value: na(c.roeStd, v => '±' + (v * 100).toFixed(1) + 'pp'), color: C.hi },
    { label: 'Div yield', value: na(c.divYield, v => (v * 100).toFixed(1) + '%'), color: C.hi },
  ] : [
    { label: 'Net debt / EBITDA', value: na(c.nde, v => v.toFixed(1) + 'x'), color: (c.nde ?? 0) > 2 ? C.amber : C.hi },
    { label: 'Altman-Z', value: na(c.altmanZ, v => v.toFixed(1)), color: c.altmanZ === null ? C.dim : c.altmanZ < 1.81 ? C.red : c.altmanZ < 3 ? C.amber : C.green },
    { label: 'Piotroski-F', value: c.piotroski === null ? `n/a (${c.piotroskiN} signals)` : `${c.piotroski}/9`, color: c.piotroski === null ? C.dim : c.piotroski >= 7 ? C.green : c.piotroski >= 4 ? C.amber : C.red },
    { label: 'FCF yield', value: na(c.fcfy, v => (v * 100).toFixed(1) + '%'), color: C.hi },
  ];

  // Ratio bars are TRUE percentiles within covered sector peers (or the whole
  // covered universe when the sector is too thin to rank against) — the old
  // fixed denominators (roic/0.3, om/0.6) painted a 26% margin red while
  // presenting as sector-relative. UI_SPEC §3.5 promises the real thing.
  const sectorPool = all.filter(p => p.sector === c.sector);
  const pool = sectorPool.length >= 5 ? sectorPool : all;
  const poolLabel = sectorPool.length >= 5
    ? `${sectorPool.length} covered ${c.sectorShort} names`
    : `${all.length} covered names (sector too small to rank)`;
  const pctile = (get: (x: Company) => number | null, lowerBetter = false): number | null => {
    const v = get(c);
    if (v === null) return null;
    const vals = pool.map(get).filter((x): x is number => x !== null);
    if (vals.length < 5) return null;
    return lowerBetter
      ? vals.filter(x => x >= v).length / vals.length
      : vals.filter(x => x <= v).length / vals.length;
  };

  const ratios = isFin ? [
    { label: 'ROE (5y avg)', value: na(c.roe, v => (v * 100).toFixed(1) + '%'), pct: pctile(x => x.roe ?? null) },
    { label: 'ROE stability', value: na(c.roeStd, v => '±' + (v * 100).toFixed(1) + 'pp'), pct: pctile(x => x.roeStd ?? null, true) },
    { label: 'Equity / assets', value: na(c.eqAssets, v => (v * 100).toFixed(1) + '%'), pct: pctile(x => x.eqAssets ?? null) },
    { label: 'Quality rank', value: `${c.quality}/100`, pct: c.quality / 100 },
  ] : [
    { label: 'ROIC', value: na(c.roic, v => Math.round(v * 100) + '%'), pct: pctile(x => x.roic) },
    { label: 'Op margin (5y avg)', value: na(c.om, v => Math.round(v * 100) + '%'), pct: pctile(x => x.om) },
    { label: 'Rev growth (5y)', value: na(c.growth5y, v => fmtPct(v, 0)), pct: pctile(x => x.growth5y) },
    { label: 'Quality rank', value: `${c.quality}/100`, pct: c.quality / 100 },
  ];

  const t = c.trends;
  const delta = (s: (number | null)[]) => {
    const v = s.filter((x): x is number => x !== null);
    return v.length >= 2 && v[0] !== 0 ? v[v.length - 1] / v[0] - 1 : null;
  };
  // One informational color for all trend lines: green/purple/teal here leaked
  // semantic and sector meanings (UI_SPEC §2 fixes both); the delta % already
  // carries the up/down signal. Shares outstanding is the dilution watch
  // (UI_SPEC §C) — falling share count is the good direction.
  const trendDefs: { label: string; series: (number | null)[]; goodWhenDown?: boolean }[] = [
    { label: 'Revenue ($B)', series: t.revenueB },
    { label: 'Operating margin', series: t.opMargin },
    { label: 'Free cash flow ($B)', series: t.fcfB },
    { label: 'Shares out (M)', series: t.sharesM ?? [], goodWhenDown: true },
    { label: 'Book equity ($B)', series: t.equityB },
  ];

  const edgarUrl = `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${c.cik}&type=10-K&dateb=&owner=include&count=40`;

  return (
    <div style={{ paddingBottom: 40 }}>
      {/* header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, rowGap: 8, flexWrap: 'wrap',
        padding: '16px 24px', borderBottom: `1px solid ${C.border}`, background: C.chrome,
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

      <div className="dd-grid" style={{ padding: '20px 24px' }}>
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
            background: C.panel,
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
              <Point color={C.mid} tag={counterCase.tag} text={counterCase.text} />
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
              {ratios.map(rt => {
                const col = rt.pct === null ? C.dim : qColor(Math.max(0, Math.min(1, rt.pct)) * 100);
                return (
                  <div key={rt.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ color: C.dim3 }}>{rt.label}</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                      title={rt.pct === null ? undefined : `${Math.round(rt.pct * 100)}th percentile`}>
                      <span style={{ fontFamily: MONO, fontWeight: 600, color: col }}>{rt.value}</span>
                      <RatioBar pct={rt.pct ?? 0} color={col} />
                    </span>
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 10, color: C.dim, marginTop: 11, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
              Bars: percentile within {poolLabel}.
            </div>
          </div>

          <div style={{ ...card, padding: '18px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 6 }}>Method agreement</div>
            <div style={{ fontSize: 11.5, color: C.dim3, marginBottom: 13 }}>
              {agree.single ? (
                <>Only <b style={{ color: C.sec }}>{growthApplicable.length === 1 ? growthApplicable[0].name : 'one method'}</b> applies
                  to this business — the other engines are N/A by design (see the method notes), so there is no
                  cross-engine agreement to measure. The number rests on that single method's own assumptions.</>
              ) : (
                <><b style={{ color: C.sec }}>{c.within} of {growthApplicable.length}</b> applicable engines land within
                  ±10% of the mid. Agreement is judged against the methods that apply to this business — not a fixed five.</>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
                fontSize: 12.5, fontWeight: 700, padding: '4px 11px', borderRadius: 6,
                color: agree.color, background: hexA(agree.color, 0.13),
              }}>{agree.word}</span>
              <span style={{ fontSize: 12, color: C.dim }}>{agree.single ? 'by design' : agree.detail}</span>
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
                      <div style={{ height: '100%', width: `${c.momPct}%`, background: C.blue, borderRadius: 4 }} />
                    </div>
                  </div>
                  <span style={{ fontFamily: MONO, fontSize: 18, fontWeight: 700, color: C.hi, lineHeight: 1 }}>
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
                const good = d !== null && (td.goodWhenDown ? d <= 0 : d > 0);
                return (
                  <div key={td.label}>
                    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 11.5, color: C.mid }}>{td.label}</span>
                      <span style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: d === null ? C.dim : good ? C.green : C.red }}
                        title={td.goodWhenDown ? 'Falling share count = buybacks (good); rising = dilution' : undefined}>
                        {d === null ? 'n/a' : fmtPct(d, 0)}
                      </span>
                    </div>
                    <Sparkline series={td.series} color={C.blue} />
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
                  {(() => { const a = agreement(p.conf, p.nMethods); return (
                    <span title={a.single ? 'single method (by design)' : `${a.word} — ${a.detail}`}
                      style={{ width: 9, height: 9, borderRadius: '50%', background: a.color, flexShrink: 0 }} />
                  ); })()}
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
