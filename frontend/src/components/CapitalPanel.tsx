import { C, MONO } from '../theme';
import type { Company } from '../types';

const card: React.CSSProperties = {
  background: C.panel, border: `1px solid ${C.border}`, borderRadius: 11,
};

const pct1 = (v: number) => (v * 100).toFixed(1) + '%';

/**
 * Capital efficiency — the DCF's value-creation engine: normalized ROIC, the
 * economic spread (ROIC − WACC), the g/ROIC reinvestment assumption, and the
 * incremental return on the last dollars actually deployed. `capital` is null
 * for financials/REITs (no DCF) → renders nothing. A null incRoic means the
 * firm returned capital rather than deploying it — shown as n/a, not a blank.
 */
export function CapitalPanel({ c }: { c: Company }) {
  const k = c.capital;
  if (!k) return null;

  const spreadColor = k.spread > 0 ? C.green : k.spread < 0 ? C.red : C.sec;
  const tiles: { label: string; value: string; sub: string; color: string; title: string }[] = [
    {
      label: 'ROIC', value: pct1(k.roic), sub: 'normalized', color: C.hi,
      title: 'Normalized return on invested capital.',
    },
    {
      label: 'Economic spread',
      value: (k.spread >= 0 ? '+' : '') + (k.spread * 100).toFixed(1) + 'pp',
      sub: 'ROIC − WACC', color: spreadColor,
      title: 'ROIC minus WACC. Positive → each reinvested dollar creates value; negative → growth destroys it.',
    },
    {
      label: 'Reinvestment', value: pct1(k.reinvest), sub: 'g ÷ ROIC assumption', color: C.hi,
      title: 'Share of NOPAT the DCF assumes is reinvested to fund growth (g ÷ ROIC).',
    },
    {
      label: 'Incremental ROIC',
      value: k.incRoic === null ? 'n/a' : pct1(k.incRoic),
      sub: k.incRoic === null ? 'net capital returner' : 'ΔNOPAT ÷ Δcapital',
      color: k.incRoic === null ? C.dim : C.hi,
      title: k.incRoic === null
        ? 'Returned more capital (buybacks/dividends) than it deployed — incremental ROIC is undefined here.'
        : 'Return on the last dollars actually deployed (ΔNOPAT ÷ Δinvested capital).',
    },
  ];

  return (
    <div style={{ ...card, padding: '18px 20px' }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: C.sec, marginBottom: 12 }}>
        Capital efficiency{' '}
        <span style={{ fontSize: 10, color: C.dim, fontWeight: 400 }}>the DCF&rsquo;s value-creation engine</span>
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1,
        background: C.border, border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden',
      }}>
        {tiles.map(t => (
          <div key={t.label} title={t.title} style={{ background: C.chrome, padding: '12px 14px' }}>
            <div style={{ fontSize: 10, color: C.dim, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6 }}>
              {t.label}
            </div>
            <div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 600, color: t.color }}>{t.value}</div>
            <div style={{ fontSize: 10, color: C.dim, marginTop: 4 }}>{t.sub}</div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 10.5, color: C.dim, lineHeight: 1.5, marginTop: 11, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
        Growth creates value only when the spread is positive — the reinvestment rate is what the
        DCF assumes it costs to fund that growth.
      </div>
    </div>
  );
}
