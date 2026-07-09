// The Company contract — mirrors backend/value.py output.json exactly.

export interface Method {
  key: string;
  name: string;
  value: number | null;
  applicable: boolean;
  note: string;
}

/** Tier 3 Bear/Base/Bull scenario cone. null for financials/REITs (no DCF base). */
export interface Scenario {
  bear: number;
  base: number;   // == the headline mid
  bull: number;
  pw: number;     // probability-weighted fair value (bear/base/bull @ 25/50/25)
  expBase: number; // base/price − 1 (== upside)
  expPW: number;   // pw/price − 1
  annPW: number | null; // annualized pw expected return over the convergence horizon
}

/** Tier 3 capital-efficiency panel. null for financials/REITs. */
export interface Capital {
  roic: number;
  spread: number;    // ROIC − WACC (economic spread)
  reinvest: number;  // the DCF's g/ROIC reinvestment assumption
  incRoic: number | null; // ΔNOPAT/Δinvested-capital; null for net capital-returners
}

export interface Trends {
  years: number[];
  revenueB: (number | null)[];
  opMargin: (number | null)[];
  fcfB: (number | null)[];
  equityB: (number | null)[];
  sharesM?: (number | null)[]; // absent in pre-2026-07-07 payloads
}

export interface Company {
  ticker: string;
  name: string;
  sector: string;
  sectorShort: string;
  finCurrency: string;
  price: number;
  mcapB: number;
  quality: number;
  growth5y: number | null;
  mom12?: number | null;
  momPct?: number | null;
  divYield: number | null;
  negBook: boolean;
  low: number;
  mid: number;
  high: number;
  upside: number;
  scenario?: Scenario | null;  // Tier 3 — standard names only
  capital?: Capital | null;    // Tier 3 — standard names only
  conf: number;
  within: number;
  nMethods?: number;              // applicable growth engines (mid); 1 = single-method by design
  impliedGrowth: number | null;
  impliedOp: string | null;
  trailingG: number | null;
  pe: number | null;
  evebitda: number | null;
  fcfy: number | null;
  om: number | null;
  roic: number | null;
  archetype?: 'standard' | 'financial' | 'reit'; // L5 route — emitted since v2.3
  roe?: number | null;      // financial/reit only: 5y avg ROE
  roeStd?: number | null;   // financial/reit only: ROE stdev (lower = steadier)
  eqAssets?: number | null; // financial/reit only: equity/assets capital cushion
  altmanZ: number | null;
  piotroski: number | null;
  piotroskiN: number;
  nde: number | null;
  flags: string[];
  score: number;
  cik: string;
  trends: Trends;
  methods: Method[];
}

export interface FlagChange { t: string; flags: string[] }
export interface ConfJump { t: string; from: number; to: number }
export interface BigMove { t: string; from: number; to: number }

/** "What changed" digest vs the last valid run from a prior calendar day. */
export interface Changes {
  since: string;
  enteredZone: string[];
  leftZone: string[];
  flagged: FlagChange[];
  cleared: FlagChange[];
  confJumps: ConfJump[];
  bigMoves: BigMove[];
  newNames: string[];
  dropped: string[];
}

export interface Meta {
  asOf: string;
  riskFree: number;
  riskFreeSource: string;
  erp: number;
  terminalG: number;
  universe: string;
  universeId?: string;
  covered: number;
  excluded: { ticker: string; why: string }[];
  weights?: Record<string, number>; // L8 blend — emitted by value.py since 2026-07-07
  changes?: Changes | null;
}

export interface UniverseInfo {
  id: string;
  name: string;
  covered: number | null;
  default: boolean;
}

export interface Payload {
  meta: Meta;
  companies: Company[];
}

export type Screen = 'overview' | 'screener' | 'deep' | 'methodology';

export interface Filters {
  sectors: string[] | null; // null = all
  mcap: 'all' | 'mega' | 'large' | 'mid';
  minQ: number;
  minConf: number;
  upside: number; // percent, -60..50
  minMom: number; // momentum percentile floor, 0 = off (names without momPct fail when > 0)
  hideTraps: boolean;
}

export const DEFAULT_FILTERS: Filters = {
  sectors: null, mcap: 'all', minQ: 0, minConf: 1, upside: -100, minMom: 0, hideTraps: false,
};

export type SortKey =
  | 'score' | 'ticker' | 'price' | 'upside' | 'conf' | 'quality' | 'mcapB' | 'pe' | 'momPct';
