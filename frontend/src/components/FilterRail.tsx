import { C, hexA, SECTOR_COLORS } from '../theme';
import type { Filters } from '../types';
import { DEFAULT_FILTERS } from '../types';

/** Shared 228px filter rail (Overview + Screener). Filters are shared app state. */
export function FilterRail({ filters, setFilters, allSectors }: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  allSectors: string[];
}) {
  const patch = (p: Partial<Filters>) => setFilters({ ...filters, ...p });
  const active = new Set(filters.sectors === null ? allSectors : filters.sectors);

  const toggleSector = (sec: string) => {
    const cur = new Set(filters.sectors === null ? allSectors : filters.sectors);
    if (cur.has(sec)) cur.delete(sec); else cur.add(sec);
    patch({ sectors: [...cur] });
  };

  const seg = (on: boolean) => ({
    flex: 1, textAlign: 'center' as const, fontSize: 11, padding: '5px 0',
    borderRadius: 5, cursor: 'pointer',
    background: on ? 'rgba(68,147,248,0.15)' : C.panel,
    color: on ? '#fff' : C.mid,
    border: `1px solid ${on ? hexA(C.blue, 0.4) : C.border}`,
  });

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div style={{ marginBottom: 18 }}>
      <div style={{
        fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase',
        color: C.dim, marginBottom: 9, fontWeight: 600,
      }}>{title}</div>
      {children}
    </div>
  );

  return (
    <div style={{
      width: 228, flex: '0 0 228px', borderRight: `1px solid ${C.border}`,
      background: C.rail, padding: 16, overflowY: 'auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: C.hi }}>Filters</span>
        <span onClick={() => setFilters({ ...DEFAULT_FILTERS })}
          style={{ fontSize: 10.5, color: C.blue, cursor: 'pointer' }}>Reset</span>
      </div>

      <Section title="Sector">
        {allSectors.map(sec => {
          const on = active.has(sec);
          const col = SECTOR_COLORS[sec] ?? '#9aa3b2';
          return (
            <div key={sec} onClick={() => toggleSector(sec)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px', cursor: 'pointer', opacity: on ? 1 : 0.4 }}>
              <span style={{
                width: 11, height: 11, borderRadius: 3,
                background: on ? col : 'transparent', border: `1.5px solid ${col}`,
              }} />
              <span style={{ fontSize: 11.5, color: on ? C.hi : C.mid, flex: 1 }}>{sec}</span>
            </div>
          );
        })}
      </Section>

      <Section title="Market cap">
        <div style={{ display: 'flex', gap: 4 }}>
          {([['all', 'All'], ['mega', 'Mega'], ['large', 'Large'], ['mid', 'Mid']] as const).map(([v, l]) => (
            <div key={v} onClick={() => patch({ mcap: v })} style={seg(filters.mcap === v)}>{l}</div>
          ))}
        </div>
      </Section>

      <Section title={`Min quality · ${filters.minQ}`}>
        <input type="range" min={0} max={100} step={5} value={filters.minQ}
          onChange={e => patch({ minQ: +e.target.value })} />
      </Section>

      <Section title="Min agreement">
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 2, 3, 4, 5].map(n => (
            <div key={n} onClick={() => patch({ minConf: n })}
              style={{ ...seg(filters.minConf === n), fontFamily: "'JetBrains Mono',monospace" }}>{n}</div>
          ))}
        </div>
      </Section>

      <Section title={`Min upside · ${filters.upside}%`}>
        <input type="range" min={-100} max={50} step={5} value={filters.upside}
          onChange={e => patch({ upside: +e.target.value })} />
      </Section>

      <div onClick={() => patch({ hideTraps: !filters.hideTraps })}
        style={{ display: 'flex', alignItems: 'center', gap: 9, cursor: 'pointer', padding: '4px 2px' }}>
        <span style={{
          width: 32, height: 18, borderRadius: 10, position: 'relative',
          background: filters.hideTraps ? C.green : '#222835', transition: 'background .15s',
        }}>
          <span style={{
            position: 'absolute', top: 2, left: filters.hideTraps ? 16 : 2,
            width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left .15s',
          }} />
        </span>
        <span style={{ fontSize: 11.5, color: C.hi }}>Hide trap-flagged</span>
      </div>
    </div>
  );
}
