// Design tokens — from the design handoff (fixed semantic meanings, never reused).

export const C = {
  bg: '#0a0c10',
  panel: '#0e1117',
  chrome: '#0c0f15',
  rail: '#0b0e13',
  inset: '#0b0e13',
  code: '#0a0c10',
  border: '#1d222d',
  rowBorder: '#14181f',
  borderHi: '#2a3140',
  hi: '#e6e9ef',
  sec: '#cfd6e2',
  mid: '#9aa3b2',
  // dim/dim2 lightened from #626b7a/#525c6b (3.6:1 / 2.9:1 on bg — WCAG AA fail
  // at the 10px label sizes they're used for) to ≥4.5:1 while keeping the
  // hi > sec > mid > dim3 > dim > dim2 hierarchy readable.
  dim: '#7d8798',
  dim2: '#727c8d',
  dim3: '#8a93a3',
  green: '#3fb950',
  red: '#f85149',
  amber: '#d29922',
  blue: '#4493f8',
  greenZone: 'rgba(63,185,80,0.09)',
  redZone: 'rgba(248,81,73,0.08)',
} as const;

export const MONO = "'JetBrains Mono',Consolas,monospace";

export const SECTOR_COLORS: Record<string, string> = {
  'Information Technology': '#6ea8fe',
  'Communication Services': '#b58cf0',
  'Consumer Discretionary': '#f0879b',
  'Consumer Staples': '#4fc3c9',
  'Health Care': '#8d80e6',
  'Industrials': '#c0a062',
  'Financials': '#d98a5b',
  'Real Estate': '#c98fc0',
  'Materials': '#9aa86b',
  'Energy': '#cf8f6a',
  'Utilities': '#6fb1a0',
};

export function sectorColor(sector: string): string {
  return SECTOR_COLORS[sector] ?? '#9aa3b2';
}

export function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Fairly-valued (±4%) is a no-signal state → neutral, per the semantic color
// law (UI_SPEC §2). Amber is reserved for caution (traps, low confidence).
export const upColor = (u: number) => (u > 0.04 ? C.green : u < -0.04 ? C.red : C.sec);
export const qColor = (q: number) => (q >= 70 ? C.green : q >= 48 ? C.amber : C.red);
export const confColor = (c: number) => (c >= 4 ? C.green : c >= 2 ? C.amber : C.red);

// Honest agreement read. A single applicable engine (REIT→P/FFO, bank→RIM) CANNOT
// demonstrate agreement — that's "single method, by design", NOT low confidence, and
// must not be shown as a misleading "2/5". Only score low/moderate/high when >=2
// growth engines actually triangulate.
export function agreement(conf: number, nMethods?: number): {
  word: string; detail: string; color: string; single: boolean;
} {
  const n = nMethods ?? 2;
  // Never "/5" — the denominator is the APPLICABLE method set, not a fixed 5. A name
  // valued on its by-design set that agree is strong, not "2 of 5, low".
  if (n <= 1)
    return { word: 'Single method', detail: 'by design', color: C.mid, single: true };
  if (conf >= 4) return { word: 'Strong', detail: `${n} methods agree`, color: C.green, single: false };
  if (conf >= 3) return { word: 'Fair', detail: `${n} methods, partial`, color: C.amber, single: false };
  return { word: 'Wide range', detail: `${n} methods diverge`, color: C.amber, single: false };
}

// Flags matching this pattern render red (distress-type); others amber.
export const DISTRESS_RE = /distress|cut|Declining|opacity|Negative|Suspect|VIE|Piotroski/;
