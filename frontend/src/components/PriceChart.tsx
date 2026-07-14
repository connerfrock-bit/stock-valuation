import { useEffect, useMemo, useRef, useState } from 'react';
import { C, MONO, hexA } from '../theme';
import { fmtPrice, fmtPct } from '../format';
import type { PriceFile } from '../types';

// Lazy-load prices_<uid>.json once per universe (module-cached across deep-dives).
const cache = new Map<string, Promise<PriceFile | null>>();
function loadPrices(uid: string): Promise<PriceFile | null> {
  if (!cache.has(uid)) {
    const url = `${import.meta.env.BASE_URL}prices_${uid}.json`;
    cache.set(uid, fetch(url).then(r => (r.ok ? r.json() : null)).catch(() => null));
  }
  return cache.get(uid)!;
}

type RangeKey = '1M' | '6M' | 'YTD' | '1Y' | '5Y' | 'MAX';
const RANGES: RangeKey[] = ['1M', '6M', 'YTD', '1Y', '5Y', 'MAX'];
// Ranges up to 1Y read the daily block; longer ranges read monthly.
const DAILY_RANGE: Record<RangeKey, boolean> = { '1M': true, '6M': true, YTD: true, '1Y': true, '5Y': false, MAX: false };

/** Trailing cutoff (inclusive) as an ISO prefix, computed from the latest datapoint. */
function cutoffFor(range: RangeKey, lastISO: string): string {
  const last = new Date(lastISO + 'T00:00:00Z');
  const d = new Date(last);
  if (range === 'YTD') return `${last.getUTCFullYear()}-01-01`;
  const days: Record<string, number> = { '1M': 30, '6M': 182, '1Y': 365, '5Y': 1826 };
  d.setUTCDate(d.getUTCDate() - (days[range] ?? 0));
  return d.toISOString().slice(0, 10);
}

function labelFor(iso: string, monthly: boolean): string {
  // iso is 'YYYY-MM-DD' or 'YYYY-MM'
  const [y, m, dd] = iso.split('-');
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+m - 1];
  return monthly ? `${mon} ’${y.slice(2)}` : `${mon} ${+dd}, ${y}`;
}

export function PriceChart({ ticker, uid, spot }: { ticker: string; uid: string; spot: number }) {
  const [file, setFile] = useState<PriceFile | null | undefined>(undefined);
  const [range, setRange] = useState<RangeKey>('1Y');
  const [hover, setHover] = useState<number | null>(null);
  const [w, setW] = useState(600);
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => { let live = true; loadPrices(uid).then(f => live && setFile(f)); return () => { live = false; }; }, [uid]);

  // Measure width responsively.
  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(es => { for (const e of es) setW(Math.max(280, e.contentRect.width)); });
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // Build the (label, value) points for the selected range. Ranges <= 1Y read daily,
  // but fall back to monthly when a name has no daily series yet (pre-backfill).
  const { pts, isMonthly } = useMemo(() => {
    if (!file) return { pts: [] as { label: string; v: number }[], isMonthly: false };
    const useMonthly = !(DAILY_RANGE[range] && file.daily.series[ticker]);
    if (useMonthly) {
      const raw = file.monthly.series[ticker];
      return { pts: raw ? sliceRange(file.monthly.months ?? [], raw, range, true) : [], isMonthly: true };
    }
    return { pts: sliceRange(file.daily.dates ?? [], file.daily.series[ticker]!, range, false), isMonthly: false };
  }, [file, ticker, range]);

  const last = pts.length ? pts[pts.length - 1].v : spot;
  const first = pts.length ? pts[0].v : spot;
  const chg = first ? last / first - 1 : 0;
  const up = chg >= 0;
  const col = up ? C.green : C.red;

  const H = 200, padL = 46, padR = 10, padT = 10, padB = 22;
  const plotW = w - padL - padR, plotH = H - padT - padB;
  const vals = pts.map(p => p.v);
  const min = vals.length ? Math.min(...vals) : 0, max = vals.length ? Math.max(...vals) : 1;
  const rng = max - min || 1;
  const x = (i: number) => padL + (pts.length < 2 ? plotW / 2 : (i / (pts.length - 1)) * plotW);
  const y = (v: number) => padT + (1 - (v - min) / rng) * plotH;

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
  const area = pts.length >= 2
    ? `${line}L${x(pts.length - 1).toFixed(1)},${padT + plotH}L${x(0).toFixed(1)},${padT + plotH}Z` : '';
  const gid = `pcg-${ticker}-${range}`.replace(/[^a-zA-Z0-9-]/g, '');

  // y gridlines (4 bands)
  const yticks = [0, 0.25, 0.5, 0.75, 1].map(f => min + f * rng);
  // x labels (up to 5, evenly spaced)
  const xIdx = pts.length <= 1 ? [] :
    Array.from({ length: Math.min(5, pts.length) }, (_, k) =>
      Math.round((k / (Math.min(5, pts.length) - 1)) * (pts.length - 1)));

  function onMove(e: React.MouseEvent) {
    if (!svgRef.current || pts.length < 2) return;
    const rect = svgRef.current.getBoundingClientRect();
    const rx = e.clientX - rect.left;
    const i = Math.round(((rx - padL) / plotW) * (pts.length - 1));
    setHover(Math.max(0, Math.min(pts.length - 1, i)));
  }

  return (
    <div ref={wrap} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11, padding: '16px 18px' }}>
      {/* header: price + change over range + range toggle */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: C.dim }}>Price history</div>
          {pts.length >= 2 && (
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontFamily: MONO, fontSize: 17, fontWeight: 600, color: col }}>
                {up ? '▲' : '▼'} {fmtPct(chg, 1)}
              </span>
              <span style={{ fontFamily: MONO, fontSize: 12, color: C.dim }}>
                {fmtPrice(first)} → {fmtPrice(last)} · {range}
              </span>
            </div>
          )}
        </div>
        <div role="tablist" aria-label="Price range" style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          {RANGES.map(r => {
            const on = r === range;
            return (
              <button key={r} role="tab" aria-selected={on} onClick={() => { setRange(r); setHover(null); }}
                style={{
                  fontFamily: MONO, fontSize: 11, fontWeight: 600, padding: '4px 9px', borderRadius: 6,
                  border: `1px solid ${on ? hexA(C.blue, 0.5) : 'transparent'}`,
                  background: on ? hexA(C.blue, 0.12) : 'transparent',
                  color: on ? C.blue : C.mid, cursor: 'pointer',
                }}>{r}</button>
            );
          })}
        </div>
      </div>

      {/* chart */}
      {file === undefined ? (
        <div style={{ height: H, display: 'flex', alignItems: 'center', color: C.dim, fontFamily: MONO, fontSize: 12 }}>loading price history…</div>
      ) : pts.length < 2 ? (
        <div style={{ height: H, display: 'flex', alignItems: 'center', color: C.dim, fontFamily: MONO, fontSize: 12 }}>
          {file === null ? 'price history unavailable' : `not enough ${range} history for ${ticker}`}
        </div>
      ) : (
        <svg ref={svgRef} width={w} height={H} style={{ display: 'block', marginTop: 8 }}
          onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={col} stopOpacity={0.20} />
              <stop offset="100%" stopColor={col} stopOpacity={0} />
            </linearGradient>
          </defs>
          {/* y gridlines + labels */}
          {yticks.map((v, k) => (
            <g key={k}>
              <line x1={padL} x2={w - padR} y1={y(v)} y2={y(v)} stroke={C.border} strokeWidth={1} />
              <text x={padL - 6} y={y(v) + 3} textAnchor="end" fontFamily={MONO} fontSize={9.5} fill={C.dim}>
                {v >= 1000 ? Math.round(v) : v.toFixed(v < 10 ? 2 : 1)}
              </text>
            </g>
          ))}
          {/* x labels */}
          {xIdx.map((i, k) => (
            <text key={k} x={Math.max(padL + 12, Math.min(w - padR - 12, x(i)))} y={H - 6}
              textAnchor={k === 0 ? 'start' : k === xIdx.length - 1 ? 'end' : 'middle'}
              fontFamily={MONO} fontSize={9.5} fill={C.dim}>{labelFor(pts[i].label, isMonthly)}</text>
          ))}
          <path d={area} fill={`url(#${gid})`} />
          <path d={line} fill="none" stroke={col} strokeWidth={1.6} />
          {/* hover crosshair */}
          {hover !== null && pts[hover] && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + plotH} stroke={C.borderHi} strokeWidth={1} />
              <circle cx={x(hover)} cy={y(pts[hover].v)} r={3.2} fill={col} stroke={C.panel} strokeWidth={1.5} />
              <g transform={`translate(${Math.max(padL, Math.min(w - padR - 96, x(hover) - 48))},${padT})`}>
                <rect width={96} height={30} rx={5} fill={C.chrome} stroke={C.borderHi} strokeWidth={1} />
                <text x={6} y={12} fontFamily={MONO} fontSize={9} fill={C.dim}>{labelFor(pts[hover].label, isMonthly)}</text>
                <text x={6} y={24} fontFamily={MONO} fontSize={11} fontWeight={600} fill={C.hi}>{fmtPrice(pts[hover].v)}</text>
              </g>
            </g>
          )}
        </svg>
      )}
    </div>
  );
}

/** Slice an aligned (axis,series) to a range, dropping nulls; monthly uses last-N for 5Y. */
function sliceRange(axis: string[], raw: (number | null)[], range: RangeKey, monthly: boolean):
  { label: string; v: number }[] {
  const paired: { label: string; v: number }[] = [];
  for (let i = 0; i < axis.length; i++) {
    const v = raw[i];
    if (v !== null && v !== undefined) paired.push({ label: axis[i], v });
  }
  if (!paired.length) return [];
  const lastISO = paired[paired.length - 1].label;
  if (range === 'MAX') return paired;
  if (monthly && range === '5Y') return paired.slice(-60);
  // daily/YTD/1M/6M/1Y: filter by cutoff prefix (works for monthly too via string compare)
  const cut = cutoffFor(range, monthly ? lastISO + '-01' : lastISO);
  const cutKey = monthly ? cut.slice(0, 7) : cut;
  return paired.filter(p => p.label >= cutKey);
}
