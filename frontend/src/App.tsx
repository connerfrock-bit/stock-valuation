import { useEffect, useMemo, useRef, useState } from 'react';
import { C, MONO, upColor } from './theme';
import { fmtPct } from './format';
import { TipProvider } from './components/Tooltip';
import { Overview } from './screens/Overview';
import { Screener } from './screens/Screener';
import { DeepDive } from './screens/DeepDive';
import { Methodology } from './screens/Methodology';
import type { Company, Filters, Payload, Screen, SortKey, UniverseInfo } from './types';
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
  const [searchIdx, setSearchIdx] = useState(-1);
  const searchRef = useRef<HTMLInputElement>(null);
  const uniRef = useRef<HTMLDivElement>(null);
  const [watch, setWatch] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem(WATCH_KEY) ?? '{}'); } catch { return {}; }
  });
  const [universes, setUniverses] = useState<UniverseInfo[]>([]);
  const [universe, setUniverse] = useState<string>('');   // '' until manifest resolves
  const [uniOpen, setUniOpen] = useState(false);
  const embedded = (window as unknown as { __FV_DATA__?: Payload }).__FV_DATA__;

  useEffect(() => {
    if (embedded) {                                   // single-file share build: one universe, no toggle
      setData(embedded);
      if (embedded.companies.length) setSelected(embedded.companies[0].ticker);
      return;
    }
    fetch(`${import.meta.env.BASE_URL}universes.json`)
      .then(r => (r.ok ? r.json() : []))
      .then((list: UniverseInfo[]) => {
        setUniverses(list);
        setUniverse((list.find(u => u.default) ?? list[0])?.id ?? 'ndx');
      })
      .catch(() => setUniverse('ndx'));                // pre-manifest builds → bare output.json
  }, [embedded]);

  useEffect(() => {
    if (embedded || !universe) return;
    const file = universes.length ? `output_${universe}.json` : 'output.json';
    fetch(`${import.meta.env.BASE_URL}${file}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((p: Payload) => {
        setData(p);
        setSelected(p.companies.length ? p.companies[0].ticker : null);
      })
      .catch(e => setError(String(e)));
  }, [embedded, universe, universes.length]);

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

  useEffect(() => {
    if (!uniOpen) return;
    const onDown = (e: MouseEvent) => {
      if (uniRef.current && !uniRef.current.contains(e.target as Node)) setUniOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setUniOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [uniOpen]);

  const toggleWatch = (t: string) => {
    setWatch(w => {
      const next = { ...w, [t]: !w[t] };
      localStorage.setItem(WATCH_KEY, JSON.stringify(next));
      return next;
    });
  };

  const q = search.trim().toLowerCase();
  const matches = q
    ? (data?.companies ?? []).filter(c =>
        c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)).slice(0, 7)
    : [];

  const openDeep = (t: string) => {
    setSelected(t);
    setScreen('deep');
    setSearch('');
    setSearchFocus(false);
    setSearchIdx(-1);
  };

  const onSearchKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSearchIdx(i => Math.min(i + 1, matches.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSearchIdx(i => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      const m = matches[searchIdx] ?? matches[0];
      if (m) openDeep(m.ticker);
    } else if (e.key === 'Escape') {
      setSearch('');
      setSearchIdx(-1);
      searchRef.current?.blur();
    }
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
        case 'momPct': return c.momPct ?? -1e18;
        default: return c.score;
      }
    };
    return [...filtered].sort((a, b) => {
      const x = kf(a), y = kf(b);
      if (typeof x === 'string' && typeof y === 'string') return x.localeCompare(y) * dir;
      return ((x as number) - (y as number)) * dir;
    });
  }, [filtered, sortKey, sortDir]);

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

  const asOfMs = Date.parse(data.meta.asOf.replace('·', ''));
  const staleH = Number.isNaN(asOfMs) ? null : Math.floor((Date.now() - asOfMs) / 3.6e6);
  const stale = staleH !== null && staleH >= 24;

  const sel = companies.find(c => c.ticker === selected) ?? companies[0];
  const peers = sel
    ? companies.filter(p => p.sector === sel.sector && p.ticker !== sel.ticker)
        .sort((a, b) => b.mcapB - a.mcapB).slice(0, 5)
    : [];

  const navItem = (s: Screen, label: string, icon: React.ReactNode, right?: React.ReactNode) => {
    const active = screen === s;
    return (
      <button onClick={() => setScreen(s)} className="navitem" aria-current={active ? 'page' : undefined}
        style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px', width: '100%',
          borderRadius: 8, fontSize: 13, fontWeight: active ? 600 : 500,
          marginBottom: 2, color: active ? '#fff' : C.mid,
          background: active ? 'rgba(68,147,248,0.13)' : undefined,
          borderLeft: active ? `2px solid ${C.blue}` : '2px solid transparent',
        }}>
        {icon}<span style={{ flex: 1 }}>{label}</span>{right}
      </button>
    );
  };

  return (
    <TipProvider>
      <div style={{
        height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: C.bg, color: C.hi,
      }}>
        {/* ===== top bar ===== */}
        <header style={{
          minHeight: 52, flex: '0 0 auto', display: 'flex', alignItems: 'center',
          gap: 18, rowGap: 4, flexWrap: 'wrap', padding: '4px 18px',
          borderBottom: `1px solid ${C.border}`, background: C.chrome, zIndex: 30,
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
              fontFamily: MONO, fontSize: 10, letterSpacing: '.1em', color: C.mid,
              border: `1px solid ${C.borderHi}`, borderRadius: 4, padding: '2px 6px',
            }}>{data.meta.universe.toUpperCase().replace('-', '·')}</div>
          </div>

          {/* search */}
          <div style={{ position: 'relative', flex: '1 1 160px', minWidth: 160, maxWidth: 440 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, height: 32, padding: '0 11px',
              background: '#11151d', border: `1px solid ${searchFocus ? C.blue : C.border}`, borderRadius: 7,
            }}>
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={C.dim} strokeWidth={2}>
                <circle cx={11} cy={11} r={7} /><line x1={21} y1={21} x2={16.5} y2={16.5} />
              </svg>
              <input ref={searchRef} value={search}
                onChange={e => { setSearch(e.target.value); setSearchIdx(-1); }}
                onFocus={() => setSearchFocus(true)}
                onBlur={() => setTimeout(() => setSearchFocus(false), 150)}
                onKeyDown={onSearchKey}
                placeholder="Search ticker or company…"
                role="combobox" aria-expanded={searchFocus && q.length > 0}
                aria-controls="ticker-results" aria-autocomplete="list"
                aria-activedescendant={searchIdx >= 0 && matches[searchIdx] ? `opt-${matches[searchIdx].ticker}` : undefined}
                style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: C.hi, fontSize: 12.5 }} />
              <span style={{
                fontFamily: MONO, fontSize: 10, color: C.dim2,
                border: `1px solid ${C.borderHi}`, borderRadius: 3, padding: '1px 4px',
              }}>/</span>
            </div>
            {searchFocus && q.length > 0 && (
              <div id="ticker-results" role="listbox" aria-label="Matching tickers" style={{
                position: 'absolute', top: 38, left: 0, right: 0, background: '#11151d',
                border: `1px solid ${C.borderHi}`, borderRadius: 8,
                boxShadow: '0 12px 32px rgba(0,0,0,.55)', overflow: 'hidden', zIndex: 50,
              }}>
                {matches.map((m, i) => (
                  <div key={m.ticker} id={`opt-${m.ticker}`} role="option"
                    aria-selected={i === searchIdx}
                    onMouseDown={() => openDeep(m.ticker)}
                    onMouseEnter={() => setSearchIdx(i)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                      cursor: 'pointer', borderBottom: '1px solid #161b24',
                      background: i === searchIdx ? 'rgba(68,147,248,0.10)' : 'transparent',
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

          <div ref={uniRef} style={{ position: 'relative' }}>
            <button onClick={() => !embedded && universes.length > 1 && setUniOpen(o => !o)}
              aria-haspopup="menu" aria-expanded={uniOpen}
              disabled={embedded !== undefined || universes.length <= 1}
              style={{
                display: 'flex', alignItems: 'center', gap: 7, height: 30, padding: '0 11px',
                border: `1px solid ${uniOpen ? C.blue : C.borderHi}`, borderRadius: 7, fontSize: 11.5,
                color: C.sec, cursor: (!embedded && universes.length > 1) ? 'pointer' : 'default',
              }} title="Live-screener universe">
              <span style={{ fontWeight: 600 }}>{data.meta.universe.toUpperCase()}</span>
              {!embedded && universes.length > 1 && (
                <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke={C.dim} strokeWidth={3}
                  style={{ transform: uniOpen ? 'rotate(180deg)' : 'none' }} aria-hidden>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              )}
            </button>
            {uniOpen && (
              <div role="menu" aria-label="Universe" style={{
                position: 'absolute', top: 36, right: 0, minWidth: 172, background: '#11151d',
                border: `1px solid ${C.borderHi}`, borderRadius: 8,
                boxShadow: '0 12px 32px rgba(0,0,0,.55)', overflow: 'hidden', zIndex: 50,
              }}>
                {universes.map(u => (
                  <button key={u.id} role="menuitemradio" aria-checked={u.id === universe}
                    onClick={() => { setUniverse(u.id); setUniOpen(false); }} style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                      width: '100%', padding: '9px 12px', borderBottom: '1px solid #161b24',
                      background: u.id === universe ? 'rgba(68,147,248,0.10)' : 'transparent',
                    }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: u.id === universe ? '#fff' : C.mid }}>{u.name}</span>
                    <span style={{ fontFamily: MONO, fontSize: 10, color: C.dim }}>{u.covered ?? '—'}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', lineHeight: 1.25, whiteSpace: 'nowrap' }}>
            <span style={{ fontSize: 10, letterSpacing: '.08em', color: C.dim2, textTransform: 'uppercase' }}>Data as of</span>
            <span style={{ fontFamily: MONO, fontSize: 11, color: C.mid }}>{data.meta.asOf}</span>
          </div>
          <button onClick={() => setScreen('methodology')} title="Assumptions & methodology"
            aria-label="Assumptions and methodology" style={{
              width: 30, height: 30, border: `1px solid ${C.borderHi}`, borderRadius: 7,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={C.mid} strokeWidth={2}>
              <circle cx={12} cy={12} r={3} />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </header>

        {stale && (
          <div role="status" style={{
            padding: '7px 18px', fontSize: 11.5, color: '#e8c98a',
            background: '#33291a', borderBottom: `1px solid ${C.amber}`,
          }}>
            <b>Stale data</b> — last refresh {data.meta.asOf} ({staleH}h ago).
            Prices and rankings may be out of date; run REFRESH DATA.cmd.
          </div>
        )}

        {/* ===== body ===== */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* left nav */}
          <nav aria-label="Screens" style={{
            width: 188, flex: '0 0 188px', borderRight: `1px solid ${C.border}`,
            background: C.chrome, display: 'flex', flexDirection: 'column', padding: '12px 10px',
          }}>
            <div style={{
              fontSize: 10, letterSpacing: '.14em', color: C.dim2,
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
          </nav>

          {/* main */}
          <main style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', position: 'relative' }}>
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
          </main>
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
