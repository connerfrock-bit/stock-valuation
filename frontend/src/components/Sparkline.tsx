import { useId } from 'react';

/** Mini area sparkline over a (number|null)[] series — nulls are skipped. */
export function Sparkline({ series, color, w = 120, h = 30 }:
  { series: (number | null)[]; color: string; w?: number; h?: number }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');
  const pts: [number, number][] = [];
  const vals = series.filter((v): v is number => v !== null);
  if (vals.length < 2) {
    return <div style={{ height: h, fontSize: 10, color: '#525c6b' }}>n/a</div>;
  }
  const min = Math.min(...vals), max = Math.max(...vals);
  const rng = max - min || 1;
  series.forEach((v, i) => {
    if (v !== null) {
      pts.push([(i / (series.length - 1)) * w, h - ((v - min) / rng) * h]);
    }
  });
  const d = 'M' + pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L');
  const area = `${d} L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.22} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
