import { C, MONO, confColor, qColor } from '../theme';

/** Confidence meter — 5 segments; encodes method AGREEMENT, not profit certainty. */
export function ConfMeter({ score, size = 5 }: { score: number; size?: number }) {
  const col = confColor(score);
  const gap = size > 5 ? 3 : 2;
  return (
    <span style={{ display: 'inline-flex', gap }}>
      {[1, 2, 3, 4, 5].map(i => (
        <span key={i} style={{
          width: size * 2.6, height: size * 1.4, borderRadius: 2,
          background: i <= score ? col : '#1c2230',
        }} />
      ))}
    </span>
  );
}

/** Compact quality gauge — 5px track + mono number. */
export function QualityGauge({ q }: { q: number }) {
  const col = qColor(q);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, width: '100%' }}>
      <span style={{
        flex: 1, height: 5, borderRadius: 3, background: '#161b24',
        position: 'relative', overflow: 'hidden', minWidth: 40,
      }}>
        <span style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${q}%`, background: col, borderRadius: 3,
        }} />
      </span>
      <span style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: col, width: 20, textAlign: 'right' }}>
        {q}
      </span>
    </span>
  );
}

/** Radial ¾-circle quality gauge (Deep-Dive). */
export function BigGauge({ q }: { q: number }) {
  const col = qColor(q);
  const r = 26, circ = 2 * Math.PI * r;
  return (
    <svg width={72} height={72} viewBox="0 0 72 72">
      <circle cx={36} cy={36} r={r} fill="none" stroke="#161b24" strokeWidth={7}
        strokeDasharray={`${circ * 0.75} ${circ}`} transform="rotate(135 36 36)" strokeLinecap="round" />
      <circle cx={36} cy={36} r={r} fill="none" stroke={col} strokeWidth={7}
        strokeDasharray={`${circ * 0.75 * (q / 100)} ${circ}`} transform="rotate(135 36 36)" strokeLinecap="round" />
    </svg>
  );
}

/** Mini horizontal ratio bar for the Deep-Dive quality panel. */
export function RatioBar({ pct, color }: { pct: number; color: string }) {
  const w = Math.max(4, Math.min(100, pct * 100));
  return (
    <span style={{
      width: 42, height: 4, borderRadius: 3, background: '#1a1f2a',
      position: 'relative', overflow: 'hidden', display: 'inline-block',
    }}>
      <span style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: `${w}%`, background: color, borderRadius: 3,
      }} />
    </span>
  );
}

export { C, MONO };
