import { C, MONO, hexA, sectorColor, upColor, qColor } from '../theme';
import { fmtPrice, fmtPct } from '../format';
import { useTip } from '../components/Tooltip';
import { FilterRail } from '../components/FilterRail';
import type { Company, Filters } from '../types';
import { useState } from 'react';

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

export function Overview({ all, filtered, filters, setFilters, allSectors, openDeep }: {
  all: Company[];
  filtered: Company[];
  filters: Filters;
  setFilters: (f: Filters) => void;
  allSectors: string[];
  openDeep: (t: string) => void;
}) {
  const undervalued = all.filter(c => c.upside > 0.15).length;
  const qpass = all.filter(c => c.quality >= 70).length;
  const medUp = [...all].sort((a, b) => a.upside - b.upside)[Math.floor(all.length / 2)]?.upside ?? 0;
  const flagged = all.filter(c => c.flags.length > 0).length;

  const kpis = [
    { label: 'Covered', value: String(all.length), sub: 'ranked names', color: C.hi },
    { label: 'Undervalued', value: String(undervalued), sub: '> 15% upside to mid', color: C.green },
    { label: 'Pass quality', value: String(qpass), sub: 'quality ≥ 70', color: C.hi },
    { label: 'Median upside', value: fmtPct(medUp), sub: 'market-wide, to mid', color: upColor(medUp) },
    { label: 'Trap-flagged', value: String(flagged), sub: 'L9 value-trap gate', color: C.amber },
  ];

  return (
    <div style={{ minHeight: '100%' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 1,
        background: C.border, borderBottom: `1px solid ${C.border}`,
      }}>
        {kpis.map(k => (
          <div key={k.label} style={{ background: C.chrome, padding: '14px 18px' }}>
            <div style={{ fontSize: 10, letterSpacing: '.06em', color: C.dim, textTransform: 'uppercase', marginBottom: 7 }}>{k.label}</div>
            <div style={{ fontFamily: MONO, fontSize: 23, fontWeight: 600, color: k.color, lineHeight: 1 }}>{k.value}</div>
            <div style={{ fontSize: 10.5, color: C.dim, marginTop: 5 }}>{k.sub}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'stretch' }}>
        <FilterRail filters={filters} setFilters={setFilters} allSectors={allSectors} />
        <div style={{ flex: 1, padding: '18px 22px', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
            <div>
              <h1 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Universe map</h1>
              <div style={{ fontSize: 11.5, color: C.mid, marginTop: 2 }}>
                Upside to fair value × quality. Dot size = market cap, color = sector.{' '}
                <span style={{ color: C.green, fontWeight: 600 }}>Top-right = cheap &amp; good.</span>
              </div>
            </div>
            <div style={{ fontFamily: MONO, fontSize: 11, color: C.dim }} aria-live="polite">
              {filtered.length} / {all.length} shown
            </div>
          </div>
          <Scatter list={filtered} openDeep={openDeep} />
        </div>
      </div>
    </div>
  );
}

function Scatter({ list, openDeep }: { list: Company[]; openDeep: (t: string) => void }) {
  const { setTip, moveTip, clearTip } = useTip();
  const [hover, setHover] = useState<string | null>(null);
  const W = 1000, H = 540, pl = 58, pr = 24, pt = 26, pb = 46;
  const xMin = -0.45, xMax = 0.55;
  const X = (u: number) => pl + ((clamp(u, xMin, xMax) - xMin) / (xMax - xMin)) * (W - pl - pr);
  const Y = (q: number) => pt + (1 - clamp(q, 0, 100) / 100) * (H - pt - pb);
  const R = (m: number) => clamp((Math.sqrt(m) / Math.sqrt(3500)) * 30 + 4, 4, 30);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', maxHeight: '62vh' }}
      role="img"
      aria-label={`Scatter of ${list.length} companies: upside to fair value versus quality score. The same companies are listed in the Screener table, which is keyboard accessible.`}>
      {/* money zone */}
      <rect x={X(0.15)} y={pt} width={X(xMax) - X(0.15)} height={Y(70) - pt}
        fill="rgba(63,185,80,0.06)" stroke="rgba(63,185,80,0.25)" strokeDasharray="4 4" rx={6} />
      <text x={X(xMax) - 10} y={pt + 18} textAnchor="end" fill="rgba(63,185,80,0.7)"
        fontSize={12} fontWeight={600} fontFamily="Inter">▲ cheap &amp; good</text>

      {/* grid + axes */}
      {[0, 25, 50, 75, 100].map(q => (
        <g key={q}>
          <line x1={pl} y1={Y(q)} x2={W - pr} y2={Y(q)} stroke={C.rowBorder} strokeWidth={1} />
          <text x={pl - 10} y={Y(q) + 4} textAnchor="end" fill={C.dim} fontSize={11} fontFamily={MONO}>{q}</text>
        </g>
      ))}
      {[-0.4, -0.2, 0, 0.2, 0.4].map(u => (
        <text key={u} x={X(u)} y={H - pb + 22} textAnchor="middle" fill={C.dim} fontSize={11} fontFamily={MONO}>
          {fmtPct(u, 0)}
        </text>
      ))}
      <line x1={X(0)} y1={pt} x2={X(0)} y2={H - pb} stroke={C.borderHi} strokeWidth={1.5} />
      <text x={X(0)} y={H - pb + 38} textAnchor="middle" fill={C.mid} fontSize={11} fontFamily="Inter">fairly valued</text>
      <text x={(pl + W - pr) / 2} y={H - 2} textAnchor="middle" fill={C.mid} fontSize={11.5} fontWeight={600} fontFamily="Inter">
        ← overvalued&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;upside to fair value&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;undervalued →
      </text>
      <text x={16} y={(pt + H - pb) / 2} textAnchor="middle" fill={C.mid} fontSize={11.5} fontWeight={600}
        fontFamily="Inter" transform={`rotate(-90 16 ${(pt + H - pb) / 2})`}>quality score →</text>

      {/* dots — largest first so small caps stay clickable */}
      {[...list].sort((a, b) => b.mcapB - a.mcapB).map(c => {
        const hov = hover === c.ticker;
        const col = sectorColor(c.sector);
        return (
          <circle key={c.ticker} cx={X(c.upside)} cy={Y(c.quality)} r={R(c.mcapB)}
            fill={hexA(col, hov ? 0.95 : 0.62)} stroke={col} strokeWidth={hov ? 2 : 1}
            style={{ cursor: 'pointer', transition: 'fill .1s' }}
            onMouseEnter={e => {
              setHover(c.ticker);
              setTip({
                x: e.clientX, y: e.clientY, title: `${c.ticker}  ·  ${c.name}`,
                lines: [
                  { label: 'Price', val: fmtPrice(c.price), color: '#fff' },
                  { label: 'Fair (mid)', val: fmtPrice(c.mid), color: '#fff' },
                  { label: 'Upside', val: fmtPct(c.upside), color: upColor(c.upside) },
                  { label: 'Quality', val: String(c.quality), color: qColor(c.quality) },
                  { label: 'Agreement', val: `${c.conf}/5`, color: C.mid },
                ],
                foot: c.flags.length ? '⚠ ' + c.flags.join(' · ') : 'No trap flags — clean.',
              });
            }}
            onMouseMove={e => moveTip(e.clientX, e.clientY)}
            onMouseLeave={() => { setHover(null); clearTip(); }}
            onClick={() => openDeep(c.ticker)}
            aria-label={`${c.ticker} · ${fmtPct(c.upside)} upside · quality ${c.quality}`} />
        );
      })}
    </svg>
  );
}
