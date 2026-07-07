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

export const upColor = (u: number) => (u > 0.04 ? C.green : u < -0.04 ? C.red : C.amber);
export const qColor = (q: number) => (q >= 70 ? C.green : q >= 48 ? C.amber : C.red);
export const confColor = (c: number) => (c >= 4 ? C.green : c >= 2 ? C.amber : C.red);

// Flags matching this pattern render red (distress-type); others amber.
export const DISTRESS_RE = /distress|cut|Declining|opacity|Negative|Suspect|VIE|Piotroski/;
