import { C, MONO, upColor } from '../theme';
import { fmtPrice, fmtPct } from '../format';
import { useTip } from './Tooltip';
import type { Company } from '../types';

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

/**
 * Scenario Cone — Bear/Base/Bull DCF cases vs. what the market is paying,
 * plus the expected-return readout. A deliberate sibling of RangeBar (same
 * track / zones / band / price-line language), but the band here is ONE
 * engine — the DCF re-run under pessimistic and optimistic growth, margins
 * and WACC — not the cross-method spread. The hollow dot marks the
 * probability-weighted value (bear/base/bull @ 25/50/25). Renders nothing
 * for archetypes with no DCF (financials/REITs): `scenario` is null there
 * by design, not missing data.
 */
export function ScenarioCone({ c }: { c: Company }) {
  const { setTip, clearTip } = useTip();
  const s = c.scenario;
  if (!s) return null;

  const tMin = Math.min(s.bear, c.price) * 0.90;
  const tMax = Math.max(s.bull, c.price) * 1.10;
  const pos = (v: number) => clamp(((v - tMin) / (tMax - tMin)) * 100, 0, 100);
  const bearP = pos(s.bear), bullP = pos(s.bull), baseP = pos(s.base), pwP = pos(s.pw), priceP = pos(c.price);
  const vColor = upColor(s.expBase);
  const barH = 12;

  const stats: { label: string; val: string; sub: string; color: string }[] = [
    { label: 'Exp. return · base', val: fmtPct(s.expBase), sub: 'if price → base case', color: upColor(s.expBase) },
    { label: 'Exp. return · PW', val: fmtPct(s.expPW), sub: `PW value ${fmtPrice(s.pw)}`, color: upColor(s.expPW) },
    ...(s.annPW !== null
      ? [{ label: 'Annualized · PW', val: fmtPct(s.annPW) + '/yr', sub: '~5y convergence', color: upColor(s.annPW) }]
      : []),
  ];

  return (
    <div style={{ ...card, padding: '18px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: C.sec }}>Scenario cone</span>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.dim }}>bear / base / bull · 25 / 50 / 25</span>
      </div>

      <div style={{ position: 'relative', height: barH + 8, margin: '26px 0 8px' }}>
        {/* track */}
        <div style={{
          position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)',
          height: barH, borderRadius: barH / 2, background: '#161b24', overflow: 'hidden',
        }} />
        {/* green / red zones — price below the bear case / above the bull case */}
        <div style={{
          position: 'absolute', left: 0, width: `${bearP}%`, top: '50%', transform: 'translateY(-50%)',
          height: barH, background: C.greenZone, borderRadius: barH / 2,
        }} />
        <div style={{
          position: 'absolute', left: `${bullP}%`, right: 0, top: '50%', transform: 'translateY(-50%)',
          height: barH, background: C.redZone, borderRadius: barH / 2,
        }} />
        {/* scenario band bear→bull */}
        <div style={{
          position: 'absolute', left: `${bearP}%`, width: `${bullP - bearP}%`, top: '50%',
          transform: 'translateY(-50%)', height: barH + 2, borderRadius: 3,
          background: 'rgba(154,163,178,0.30)', border: '1px solid rgba(154,163,178,0.4)',
        }} />
        {/* base tick — dim, like RangeBar's mid: the protagonist is PRICE vs the cone */}
        <div style={{
          position: 'absolute', left: `${baseP}%`, top: '50%', transform: 'translate(-50%,-50%)',
          width: 2, height: barH + 8, background: C.dim, borderRadius: 2,
        }} />
        {/* probability-weighted marker (hover → value tooltip) */}
        <div
          onMouseEnter={e => setTip({
            x: e.clientX, y: e.clientY, title: 'Probability-weighted',
            lines: [
              { label: 'PW value', val: fmtPrice(s.pw), color: '#fff' },
              { label: 'vs price', val: fmtPct(s.expPW), color: upColor(s.expPW) },
            ],
            foot: 'bear/base/bull weighted 25/50/25',
          })}
          onMouseLeave={clearTip}
          style={{
            position: 'absolute', left: `${pwP}%`, top: '50%',
            transform: 'translate(-50%,-50%)', width: 9, height: 9, borderRadius: '50%',
            background: C.bg, border: '2px solid #cfd6e2', cursor: 'pointer', zIndex: 3,
          }} />
        {/* current price line */}
        <div style={{
          position: 'absolute', left: `${priceP}%`, top: -4, bottom: -4,
          transform: 'translateX(-50%)', width: 2, background: vColor, borderRadius: 2,
          zIndex: 4, boxShadow: '0 0 0 2px rgba(10,12,16,0.9)',
        }} />
        <div style={{
          position: 'absolute', left: `${priceP}%`, top: -22, transform: 'translateX(-50%)',
          fontFamily: MONO, fontSize: 10, fontWeight: 600, color: vColor, whiteSpace: 'nowrap',
        }}>
          price {fmtPrice(c.price)}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, fontFamily: MONO, fontSize: 12 }}>
        <div style={{ color: C.mid }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>BEAR</div>
          {fmtPrice(s.bear)}
        </div>
        <div style={{ textAlign: 'center', color: '#fff', fontWeight: 600 }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>BASE (MID)</div>
          {fmtPrice(s.base)}
        </div>
        <div style={{ textAlign: 'right', color: C.mid }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>BULL</div>
          {fmtPrice(s.bull)}
        </div>
      </div>

      {/* expected-return readout */}
      <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        {stats.map(st => (
          <div key={st.label}>
            <div style={{ fontSize: 10, color: C.dim, textTransform: 'uppercase', letterSpacing: '.05em' }}>{st.label}</div>
            <div style={{ fontFamily: MONO, fontSize: 15, fontWeight: 600, color: st.color, marginTop: 3 }}>{st.val}</div>
            <div style={{ fontSize: 10, color: C.dim, marginTop: 2 }}>{st.sub}</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10.5, color: C.dim, lineHeight: 1.5, marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
        Bull and bear re-run the DCF with optimistic / pessimistic growth, margins and WACC — the
        cone is wider for lower-quality or cyclical names, and is capped at 1.65× / 0.55× of base
        (the most volatile names pin at the caps). Annualized assumes ~5-yr convergence
        to the probability-weighted value.
      </div>
    </div>
  );
}
