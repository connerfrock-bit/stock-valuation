import { useEffect, useMemo, useRef, useState } from 'react';
import { C, MONO, upColor } from './theme';
import { fmtPct } from './format';
import { TipProvider } from './components/Tooltip';
import { Overview } from './screens/Overview';
import { Screener } from './screens/Screener';
import { DeepDive } from './screens/DeepDive';
import { Methodology } from './screens/Methodology';
import type { Company, Filters, Payload, Screen, SortKey } from './types';
import { DEFAULT_FILTERS } from './types';

const WATCH_KEY = 'fairvalue.watchlist';

export default function App() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>('overview');
  const [selected, setSelected] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({ ...DEFAULT_FILTERS });
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [showMultiples, setShowMultiples] = useState(false);
  const [search, setSearch] = useState('');
  const [searchFocus, setSearchFocus] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const [watch, setWatch] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem(WATCH_KEY) ?? '{}'); } catch { return {}; }
  });

  useEffect(() => {
    const embedded = (window as unknown as { __FV_DATA__?: Payload }).__FV_DATA__;
    if (embedded) {                                   // single-file share build
      setData(embedded);
      if (embedded.companies.length) setSelected(embedded.companies[0].ticker);
      return;
    }
    fetch(`${import.meta.env.BASE_URL}output.json`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((p: Payload) => {
        setData(p);
        if (p.companies.length) setSelected(p.companies[0].ticker);
      })
      .catch(e => setError(String(e)));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const toggleWatch = (t: string) => {
    setWatch(w => {
      const next = { ...w, [t]: !w[t] };
      localStorage.setItem(WATCH_KEY, JSON.stringify(next));
      return next;
    });
  };

  const openDeep = (t: string) => {
    setSelected(t);
    setScreen('deep');
    setSearch('');
    setSearchFocus(false);
  };

  const setSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    else { setSortKey(k); setSortDir('desc'); }
  };

  const companies = data?.companies ?? [];
  const allSectors = useMemo(
    () => [...new Set(companies.map(c => c.sector))].sort(), [companies]);

  const filtered = useMemo(() => {
    const active = filters.sectors === null ? null : new Set(filters.sectors);
    return companies.filter(c => {
      if (active && !active.has(c.sector)) return false;
      if (filters.mcap === 'mega' && c.mcapB < 200) return false;
      if (filters.mcap === 'large' && (c.mcapB < 10 || c.mcapB >= 200)) return false;
      if (filters.mcap === 'mid' && c.mcapB >= 10) return false;
      if (c.quality < filters.minQ) return false;
      if (c.conf < filters.minConf) return false;
      if (c.upside * 100 < filters.upside) return false;
      if (filters.hideTraps && c.flags.length > 0) return false;
      return true;
    });
  }, [companies, filters]);

  const sorted = useMemo(() => {
    const dir = sortDir === 'desc' ? -1 : 1;
    const kf = (c: Company): number | string => {
      switch (sortKey) {
        case 'ticker': return c.ticker;
        case 'price': return c.price;
        case 'upside': return c.upside;
        case 'conf': return c.conf;
        case 'quality': return c.quality;
        case 'mcapB': return c.mcapB;
        case 'pe': return c.pe ?? -1e18;
        default: return c.score;
      }
    };
    return [...filtered].sort((a, b) => {
      const x = kf(a), y = kf(b);
      if (typeof x === 'string' && typeof y === 'string') return x.localeCompare(y) * dir;
      return ((x as number) - (y as number)) * dir;
    });
  }, [filtered, sortKey, sortDir]);

  const q = search.trim().toLowerCase();
  const matches = q
    ? companies.filter(c =>
        c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)).slice(0, 7)
    : [];

  if (error) {
    return (
      <Center>
        <div style={{ color: C.red, fontFamily: MONO, fontSize: 13 }}>Failed to load output.json — {error}</div>
        <div style={{ color: C.dim, fontSize: 12, marginTop: 8 }}>
          Run the backend pipeline: ingest_v1.py → sanity.py → betas.py → value.py
        </div>
      </Center>
    );
  }
  if (!data) return <Center><span style={{ color: C.dim, fontFamily: MONO }}>loading universe…</span></Center>;

  const sel = companies.find(c => c.ticker === selected) ?? companies[0];
  const peers = sel
    ? companies.filter(p => p.sector === sel.sector && p.ticker !== sel.ticker)
        .sort((a, b) => b.mcapB - a.mcapB).slice(0, 5)
    : [];

  const navItem = (s: Screen, label: string, icon: React.ReactNode, right?: React.ReactNode) => {
    const active = screen === s;
    return (
      <div onClick={() => setScreen(s)} style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px',
        borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 500,
        marginBottom: 2, color: active ? '#fff' : C.mid,
        background: active ? 'rgba(68,147,248,0.13)' : 'transparent',
        borderLeft: active ? `2px solid ${C.blue}` : '2px solid transparent',
      }}>
        {icon}<span style={{ flex: 1 }}>{label}</span>{right}
      </div>
    );
  };

  return (
    <TipProvider>
      <div style={{
        height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: C.bg, color: C.hi,
      }}>
        {/* ===== top bar ===== */}
        <div style={{
          height: 52, flex: '0 0 52px', display: 'flex', alignItems: 'center', gap: 18,
          padding: '0 18px', borderBottom: `1px solid ${C.border}`, background: C.chrome, zIndex: 30,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, flex: '0 0 auto' }}>
            <div style={{
              width: 22, height: 22, borderRadius: 5,
              background: 'linear-gradient(135deg,#3fb950,#2a8d3c)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{ width: 9, height: 9, borderRadius: 2, background: C.bg }} />
            </div>
            <div style={{ fontWeight: 700, letterSpacing: '.16em', fontSize: 13 }}>FAIR&nbsp;VALUE</div>
            <div style={{
              fontFamily: MONO, fontSize: 9.5, letterSpacing: '.1em', color: C.mid,
              border: `1px solid ${C.borderHi}`, borderRadius: 4, padding: '2px 6px',
            }}>NASDAQ·100</div>
          </div>

          {/* search */}
          <div style={{ position: 'relative', flex: '1 1 auto', maxWidth: 440 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, height: 32, padding: '0 11px',
              background: '#11151d', border: `1px solid ${searchFocus ? C.blue : C.border}`, borderRadius: 7,
            }}>
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={C.dim} strokeWidth={2}>
                <circle cx={11} cy={11} r={7} /><line x1={21} y1={21} x2={16.5} y2={16.5} />
              </svg>
              <input ref={searchRef} value={search}
                onChange={e => setSearch(e.target.value)}
                onFocus={() => setSearchFocus(true)}
                onBlur={() => setTimeout(() => setSearchFocus(false), 150)}
                placeholder="Search ticker or company…"
                style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: C.hi, fontSize: 12.5 }} />
              <span style={{
                fontFamily: MONO, fontSize: 9, color: C.dim2,
                border: `1px solid ${C.borderHi}`, borderRadius: 3, padding: '1px 4px',
              }}>/</span>
            </div>
            {searchFocus && q.length > 0 && (
              <div style={{
                position: 'absolute', top: 38, left: 0, right: 0, background: '#11151d',
                border: `1px solid ${C.borderHi}`, borderRadius: 8,
                boxShadow: '0 12px 32px rgba(0,0,0,.55)', overflow: 'hidden', zIndex: 50,
              }}>
                {matches.map(m => (
                  <div key={m.ticker} onMouseDown={() => openDeep(m.ticker)} style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                    cursor: 'pointer', borderBottom: '1px solid #161b24',
                  }}>
                    <span style={{ fontFamily: MONO, fontWeight: 600, fontSize: 12, width: 54 }}>{m.ticker}</span>
                    <span style={{
                      flex: 1, fontSize: 12, color: C.mid, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{m.name}</span>
                    <span style={{ fontFamily: MONO, fontSize: 11, color: upColor(m.upside) }}>{fmtPct(m.upside)}</span>
                  </div>
                ))}
                {matches.length === 0 && (
                  <div style={{ padding: '11px 12px', fontSize: 12, color: C.dim }}>No match in coverage.</div>
                )}
              </div>
            )}
          </div>

          <div style={{ flex: 1 }} />

          <div style={{
            display: 'flex', alignItems: 'center', gap: 7, height: 30, padding: '0 11px',
            border: `1px solid ${C.borderHi}`, borderRadius: 7, fontSize: 11.5, color: C.sec, cursor: 'default',
          }} title="NYSE expansion is Phase 8">
            <span style={{ fontWeight: 600 }}>NASDAQ&nbsp;100</span>
            <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke={C.dim} strokeWidth={3}>
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', lineHeight: 1.25 }}>
            <span style={{ fontSize: 9, letterSpacing: '.08em', color: C.dim2, textTransform: 'uppercase' }}>Data as of</span>
            <span style={{ fontFamily: MONO, fontSize: 11, color: C.mid }}>{data.meta.asOf}</span>
          </div>
          <div onClick={() => setScreen('methodology')} title="Assumptions & methodology" style={{
            width: 30, height: 30, border: `1px solid ${C.borderHi}`, borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          }}>
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={C.mid} strokeWidth={2}>
              <circle cx={12} cy={12} r={3} />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </div>
        </div>

        {/* ===== body ===== */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* left nav */}
          <div style={{
            width: 188, flex: '0 0 188px', borderRight: `1px solid ${C.border}`,
            background: C.chrome, display: 'flex', flexDirection: 'column', padding: '12px 10px',
          }}>
            <div style={{
              fontSize: 9, letterSpacing: '.14em', color: C.dim2,
              textTransform: 'uppercase', padding: '6px 10px 8px',
            }}>Navigate</div>
            {navItem('overview', 'Overview',
              <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <circle cx={6.5} cy={15} r={2} /><circle cx={13} cy={8} r={2} /><circle cx={18.5} cy={13} r={2} />
              </svg>)}
            {navItem('screener', 'Screener',
              <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <line x1={4} y1={7} x2={20} y2={7} /><line x1={4} y1={12} x2={20} y2={12} /><line x1={4} y1={17} x2={20} y2={17} />
              </svg>)}
            {navItem('deep', 'Deep-Dive',
              <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <circle cx={11} cy={11} r={7} /><line x1={21} y1={21} x2={16.5} y2={16.5} />
              </svg>,
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.dim }}>{selected}</span>)}
            {navItem('methodology', 'Methodology',
              <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M4 19V5" /><path d="M4 19h16" /><polyline points="7 14 11 9 14 12 19 6" />
              </svg>)}
            <div style={{ flex: 1 }} />
            <div style={{ borderTop: `1px solid ${C.border}`, padding: '11px 10px 4px', marginTop: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: data.meta.riskFreeSource.includes('live') ? C.green : C.amber,
                }} />
                <span style={{ fontSize: 10.5, color: C.mid }}>
                  {data.meta.covered} names live
                </span>
              </div>
              <div style={{ fontSize: 10, color: C.dim2, lineHeight: 1.5 }}>
                EDGAR + Yahoo · real filings<br />rf {(data.meta.riskFree * 100).toFixed(2)}% · {data.meta.riskFreeSource.includes('live') ? 'FRED live' : 'fallback'}
              </div>
            </div>
          </div>

          {/* main */}
          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', position: 'relative' }}>
            {screen === 'overview' && (
              <Overview all={companies} filtered={filtered} filters={filters}
                setFilters={setFilters} allSectors={allSectors} openDeep={openDeep} />
            )}
            {screen === 'screener' && (
              <Screener rows={sorted} filters={filters} setFilters={setFilters}
                allSectors={allSectors} sortKey={sortKey} sortDir={sortDir} setSort={setSort}
                showMultiples={showMultiples} setShowMultiples={setShowMultiples}
                watch={watch} toggleWatch={toggleWatch} selected={selected} openDeep={openDeep} />
            )}
            {screen === 'deep' && sel && (
              <DeepDive c={sel} meta={data.meta} peers={peers}
                watch={watch} toggleWatch={toggleWatch} openDeep={openDeep} />
            )}
            {screen === 'methodology' && <Methodology meta={data.meta} />}
          </div>
        </div>
      </div>
    </TipProvider>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      height: '100vh', display: 'flex', flexDirection: 'column', gap: 4,
      alignItems: 'center', justifyContent: 'center', background: C.bg,
    }}>
      {children}
    </div>
  );
}
