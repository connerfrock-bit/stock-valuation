import { useEffect, useRef, useState } from 'react';
import { C, MONO, upColor } from '../theme';
import { fmtPrice, fmtPct, fmtMcapB, na } from '../format';
import { FilterRail } from '../components/FilterRail';
import { RangeBar } from '../components/RangeBar';
import { ConfMeter, QualityGauge } from '../components/Meters';
import { FlagChips } from '../components/FlagChips';
import { SectorTag } from '../components/SectorTag';
import type { Company, Filters, SortKey } from '../types';

const PRESETS: [string, Partial<Filters>][] = [
  ['Deep value', { upside: 25, minConf: 3, hideTraps: false }],
  ['Quality compounders', { minQ: 78, upside: 0, hideTraps: true }],
  ['Clean & cheap', { upside: 10, minQ: 65, hideTraps: true }],
  // the one intersection the project's own backtests support: cheap by the
  // model AND confirmed by the tape (momentum is the sole factor with a
  // demonstrated edge — see Methodology → Momentum factor)
  ['Value confirmed by tape', { upside: 15, minConf: 3, hideTraps: true, minMom: 50 }],
];

export function Screener(props: {
  rows: Company[];
  filters: Filters;
  setFilters: (f: Filters) => void;
  allSectors: string[];
  sortKey: SortKey; sortDir: 'asc' | 'desc';
  setSort: (k: SortKey) => void;
  showMultiples: boolean; setShowMultiples: (b: boolean) => void;
  watch: Record<string, boolean>; toggleWatch: (t: string) => void;
  selected: string | null;
  openDeep: (t: string) => void;
}) {
  const { rows, filters, setFilters, allSectors, sortKey, sortDir, setSort,
    showMultiples, setShowMultiples, watch, toggleWatch, selected, openDeep } = props;

  // Row windowing above 150 rows (S&P-scale universes; NDX renders in full).
  // Fixed row-height estimate + generous overscan absorbs the few taller
  // wrapped-flag rows. Spacer rows keep the scrollbar honest.
  const ROW_H = 46.5, OVERSCAN = 15;
  const virtual = rows.length > 150;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [win, setWin] = useState({ top: 0, h: 900 });
  useEffect(() => {
    const el = scrollRef.current;
    if (el) setWin(w => (w.h === el.clientHeight ? w : { ...w, h: el.clientHeight }));
  }, [virtual]);
  const start = virtual ? Math.max(0, Math.floor(win.top / ROW_H) - OVERSCAN) : 0;
  const end = virtual ? Math.min(rows.length, Math.ceil((win.top + win.h) / ROW_H) + OVERSCAN) : rows.length;
  const visible = rows.slice(start, end);
  const colCount = 9 + (showMultiples ? 3 : 0);

  const exportCsv = () => {
    const head = ['ticker', 'name', 'sector', 'price', 'low', 'mid', 'high', 'upside',
      'confidence', 'quality', 'momentumPct', 'momentum12_1', 'impliedGrowth', 'trailingGrowth',
      'pe', 'evEbitda', 'fcfYield', 'mcapB', 'flags', 'score'];
    const lines = rows.map(c => [
      c.ticker, `"${c.name}"`, `"${c.sector}"`, c.price, c.low, c.mid, c.high,
      (c.upside * 100).toFixed(1) + '%', c.conf, c.quality,
      c.momPct ?? '', c.mom12 == null ? '' : (c.mom12 * 100).toFixed(1) + '%',
      c.impliedGrowth === null ? '' : (c.impliedGrowth * 100).toFixed(1) + '%',
      c.trailingG === null ? '' : (c.trailingG * 100).toFixed(1) + '%',
      c.pe ?? '', c.evebitda ?? '', c.fcfy === null ? '' : (c.fcfy * 100).toFixed(1) + '%',
      c.mcapB, `"${c.flags.join('; ')}"`, c.score,
    ].join(','));
    const blob = new Blob([head.join(',') + '\n' + lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'fairvalue_screen.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const th = (label: string, key: SortKey | null, align: 'left' | 'right' = 'right', extra?: React.CSSProperties, title?: string) => (
    <th key={label} scope="col" title={title}
      aria-sort={key && sortKey === key ? (sortDir === 'desc' ? 'descending' : 'ascending') : undefined}
      style={{
        textAlign: align, padding: 0, borderBottom: `1px solid ${C.border}`,
        whiteSpace: 'nowrap', background: C.panel, ...extra,
      }}>
      <button onClick={key ? () => setSort(key) : undefined} disabled={!key} tabIndex={key ? 0 : -1}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, padding: '10px 12px',
          fontSize: 10, letterSpacing: '.05em', textTransform: 'uppercase',
          color: C.dim, fontWeight: 600, cursor: key ? 'pointer' : 'default', userSelect: 'none',
        }}>
        {label}
        <span style={{ color: C.blue, fontSize: 9 }}>
          {key && sortKey === key ? (sortDir === 'desc' ? '▼' : '▲') : ''}
        </span>
      </button>
    </th>
  );

  return (
    // height:100% (not minHeight) so the table wrap below is the real vertical
    // scroller — row windowing and the sticky header both depend on that.
    <div style={{ height: '100%', display: 'flex' }}>
      <FilterRail filters={filters} setFilters={setFilters} allSectors={allSectors} />
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {/* toolbar */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '11px 18px',
          borderBottom: `1px solid ${C.border}`, flexWrap: 'wrap',
        }}>
          <h1 style={{ fontSize: 14, fontWeight: 600, margin: '0 4px 0 0' }}>Screener</h1>
          <div style={{ fontFamily: MONO, fontSize: 11, color: C.dim, marginRight: 6 }} aria-live="polite">
            {rows.length} matches
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {PRESETS.map(([label, patch]) => {
              const active = Object.entries(patch).every(
                ([k, v]) => filters[k as keyof Filters] === v);
              return (
                <button key={label} className="chipbtn" aria-pressed={active}
                  onClick={() => setFilters({ ...filters, ...patch })}>{label}</button>
              );
            })}
          </div>
          <div style={{ flex: 1 }} />
          <button className="chipbtn" aria-pressed={showMultiples}
            onClick={() => setShowMultiples(!showMultiples)}>
            {showMultiples ? 'Hide' : 'Show'} multiples
          </button>
          <button className="chipbtn" disabled={rows.length === 0} onClick={exportCsv}
            title={rows.length === 0 ? 'Nothing to export — no rows match' : undefined}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              ...(rows.length === 0 ? { opacity: 0.55, cursor: 'default' } : { color: C.sec }),
            }}>
            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" /><line x1={12} y1={15} x2={12} y2={3} />
            </svg>
            Export CSV
          </button>
        </div>

        {/* table */}
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflow: 'auto' }}
          onScroll={virtual ? e => {
            const el = e.currentTarget;
            setWin({ top: el.scrollTop, h: el.clientHeight });
          } : undefined}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 5 }}>
              <tr>
                {th('Company', 'ticker', 'left', { paddingLeft: 16 })}
                {th('Price', 'price')}
                {th('Fair-value range', null, 'left')}
                {th('Upside', 'upside')}
                {th('Agreement', 'conf', 'left')}
                {th('Quality', 'quality', 'left')}
                {th('Mom', 'momPct', 'right', undefined,
                  '12-1 price-momentum percentile within this universe (displayed factor — not in the fair-value blend)')}
                {th('Flags', null, 'left')}
                {showMultiples && th('P/E', 'pe', 'right', { background: C.inset })}
                {showMultiples && th('EV/EBITDA', null, 'right', { background: C.inset })}
                {showMultiples && th('FCF yield', null, 'right', { background: C.inset })}
                {th('Mkt cap', 'mcapB', 'right', { paddingRight: 16 })}
              </tr>
            </thead>
            <tbody>
              {virtual && start > 0 && (
                <tr aria-hidden style={{ height: start * ROW_H }}>
                  <td colSpan={colCount} style={{ padding: 0, border: 'none' }} />
                </tr>
              )}
              {visible.map(c => {
                const starred = !!watch[c.ticker];
                return (
                  <tr key={c.ticker} className="rowlink" tabIndex={0}
                    onClick={() => openDeep(c.ticker)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        if (e.target === e.currentTarget) { e.preventDefault(); openDeep(c.ticker); }
                      }
                    }}
                    aria-label={`${c.ticker} — open deep dive`}
                    style={{
                      borderBottom: `1px solid ${C.rowBorder}`,
                      background: selected === c.ticker ? 'rgba(68,147,248,0.06)' : undefined,
                    }}>
                    <td style={{ padding: '7px 10px 7px 16px', borderRight: `1px solid ${C.rowBorder}` }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                        <button onClick={e => { e.stopPropagation(); toggleWatch(c.ticker); }}
                          aria-pressed={starred} aria-label={`${starred ? 'Remove' : 'Add'} ${c.ticker} ${starred ? 'from' : 'to'} watchlist`}
                          style={{
                            color: starred ? C.amber : C.dim, fontSize: 13, lineHeight: 1,
                            padding: 4, margin: -4,
                          }}>
                          {starred ? '★' : '☆'}
                        </button>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                            <span style={{ fontFamily: MONO, fontWeight: 600, fontSize: 12.5 }}>{c.ticker}</span>
                            <SectorTag sector={c.sector} label={c.sectorShort} />
                            {c.finCurrency !== 'USD' && (
                              <span style={{ fontSize: 9.5, color: C.dim }}>{c.finCurrency}→USD</span>
                            )}
                          </div>
                          <div style={{
                            fontSize: 10.5, color: C.dim3, marginTop: 1, overflow: 'hidden',
                            textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160,
                          }}>{c.name}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: MONO }}>{fmtPrice(c.price)}</td>
                    <td style={{ padding: '7px 12px', width: 180 }}><RangeBar c={c} /></td>
                    <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: MONO, fontWeight: 600, color: upColor(c.upside) }}>
                      {fmtPct(c.upside)}
                    </td>
                    <td style={{ padding: '7px 12px' }}><ConfMeter score={c.conf} /></td>
                    <td style={{ padding: '7px 12px', width: 96 }}><QualityGauge q={c.quality} /></td>
                    <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: MONO, fontWeight: 600,
                      color: c.momPct == null ? C.dim : C.sec }}
                      title={c.mom12 == null ? '' : `12-1 return ${fmtPct(c.mom12)}`}>
                      {c.momPct == null ? 'n/a' : c.momPct}
                    </td>
                    <td style={{ padding: '7px 12px' }}><FlagChips flags={c.flags} /></td>
                    {showMultiples && (
                      <>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid, background: C.inset }}>
                          {na(c.pe, v => v.toFixed(1))}
                        </td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid, background: C.inset }}>
                          {na(c.evebitda, v => v.toFixed(1))}
                        </td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: MONO, color: C.mid, background: C.inset }}>
                          {na(c.fcfy, v => (v * 100).toFixed(1) + '%')}
                        </td>
                      </>
                    )}
                    <td style={{ padding: '7px 16px 7px 12px', textAlign: 'right', fontFamily: MONO, color: C.mid }}>
                      {fmtMcapB(c.mcapB)}
                    </td>
                  </tr>
                );
              })}
              {virtual && end < rows.length && (
                <tr aria-hidden style={{ height: (rows.length - end) * ROW_H }}>
                  <td colSpan={colCount} style={{ padding: 0, border: 'none' }} />
                </tr>
              )}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div style={{ padding: 60, textAlign: 'center', color: C.dim, fontSize: 13 }}>
              No stocks match — loosen filters.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
