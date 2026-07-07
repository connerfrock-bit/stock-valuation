import { C, MONO, upColor } from '../theme';
import { fmtPrice, fmtPct } from '../format';
import { useTip } from './Tooltip';
import type { Company } from '../types';

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/**
 * Valuation Range Bar ⭐ — "what's it worth vs. what it costs."
 * Track auto-scales to [min(low,price)·0.90, max(high,price)·1.10]; shaded band
 * low→high with a mid tick; the price line is colored by verdict. Full variant
 * adds per-engine method dots (hover → estimate tooltip) and LOW/FAIR/HIGH labels.
 */
export function RangeBar({ c, full = false }: { c: Company; full?: boolean }) {
  const { setTip, clearTip } = useTip();
  const tMin = Math.min(c.low, c.price) * 0.90;
  const tMax = Math.max(c.high, c.price) * 1.10;
  const pos = (v: number) => clamp(((v - tMin) / (tMax - tMin)) * 100, 0, 100);
  const lP = pos(c.low), hP = pos(c.high), mP = pos(c.mid), pP = pos(c.price);
  const vColor = upColor(c.upside);
  const barH = full ? 12 : 7;

  const bar = (
    <div style={{ position: 'relative', height: full ? barH + 8 : barH + 4, margin: full ? '26px 0 8px' : 0 }}>
      {/* track */}
      <div style={{
        position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)',
        height: barH, borderRadius: barH / 2, background: '#161b24', overflow: 'hidden',
      }} />
      {/* green / red zones */}
      <div style={{
        position: 'absolute', left: 0, width: `${lP}%`, top: '50%', transform: 'translateY(-50%)',
        height: barH, background: C.greenZone, borderRadius: barH / 2,
      }} />
      <div style={{
        position: 'absolute', left: `${hP}%`, right: 0, top: '50%', transform: 'translateY(-50%)',
        height: barH, background: C.redZone, borderRadius: barH / 2,
      }} />
      {/* fair-value band */}
      <div style={{
        position: 'absolute', left: `${lP}%`, width: `${hP - lP}%`, top: '50%',
        transform: 'translateY(-50%)', height: barH + 2, borderRadius: 3,
        background: 'rgba(154,163,178,0.30)', border: '1px solid rgba(154,163,178,0.4)',
      }} />
      {/* mid tick — deliberately dimmer than the price line: the bar's one
          protagonist is where PRICE sits vs the band */}
      <div style={{
        position: 'absolute', left: `${mP}%`, top: '50%', transform: 'translate(-50%,-50%)',
        width: 2, height: barH + 8, background: C.dim, borderRadius: 2,
      }} />
      {/* method dots (full variant) */}
      {full && c.methods.filter(m => m.applicable && m.value !== null).map(m => (
        <div key={m.key}
          onMouseEnter={e => setTip({
            x: e.clientX, y: e.clientY, title: m.name,
            lines: [
              { label: 'Estimate', val: fmtPrice(m.value!), color: '#fff' },
              { label: 'vs price', val: fmtPct(m.value! / c.price - 1), color: upColor(m.value! / c.price - 1) },
            ],
            foot: m.note,
          })}
          onMouseLeave={clearTip}
          style={{
            position: 'absolute', left: `${pos(m.value!)}%`, top: '50%',
            transform: 'translate(-50%,-50%)', width: 9, height: 9, borderRadius: '50%',
            background: C.bg, border: '2px solid #cfd6e2', cursor: 'pointer', zIndex: 3,
          }} />
      ))}
      {/* current price line */}
      <div style={{
        position: 'absolute', left: `${pP}%`, top: full ? -4 : -2, bottom: full ? -4 : -2,
        transform: 'translateX(-50%)', width: 2, background: vColor, borderRadius: 2,
        zIndex: 4, boxShadow: '0 0 0 2px rgba(10,12,16,0.9)',
      }} />
      {full && (
        <div style={{
          position: 'absolute', left: `${pP}%`, top: -22, transform: 'translateX(-50%)',
          fontFamily: MONO, fontSize: 10, fontWeight: 600, color: vColor, whiteSpace: 'nowrap',
        }}>
          price {fmtPrice(c.price)}
        </div>
      )}
    </div>
  );

  if (!full) return bar;

  return (
    <div>
      {bar}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, fontFamily: MONO, fontSize: 12 }}>
        <div style={{ color: C.mid }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>LOW</div>
          {fmtPrice(c.low)}
        </div>
        <div style={{ textAlign: 'center', color: '#fff', fontWeight: 600 }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>FAIR (MID)</div>
          {fmtPrice(c.mid)}
        </div>
        <div style={{ textAlign: 'right', color: C.mid }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: '.05em' }}>HIGH</div>
          {fmtPrice(c.high)}
        </div>
      </div>
    </div>
  );
}
