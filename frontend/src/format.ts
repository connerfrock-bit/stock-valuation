export function fmtPrice(v: number): string {
  return '$' + (v >= 1000 ? Math.round(v).toLocaleString('en-US') : v.toFixed(2));
}

export function fmtMcapB(b: number): string {
  return b >= 1000 ? '$' + (b / 1000).toFixed(2) + 'T' : '$' + Math.round(b) + 'B';
}

export function fmtPct(x: number, digits = 1): string {
  return (x >= 0 ? '+' : '') + (x * 100).toFixed(digits) + '%';
}

export function fmtPctPlain(x: number): string {
  return Math.round(x * 100) + '%';
}

export function na<T>(v: T | null | undefined, f: (v: T) => string): string {
  return v === null || v === undefined ? 'n/a' : f(v);
}
