// The Company contract — mirrors backend/value.py output.json exactly.

export interface Method {
  key: string;
  name: string;
  value: number | null;
  applicable: boolean;
  note: string;
}

export interface Trends {
  years: number[];
  revenueB: (number | null)[];
  opMargin: (number | null)[];
  fcfB: (number | null)[];
  equityB: (number | null)[];
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
  conf: number;
  within: number;
  impliedGrowth: number | null;
  impliedOp: string | null;
  trailingG: number | null;
  pe: number | null;
  evebitda: number | null;
  fcfy: number | null;
  om: number | null;
  roic: number | null;
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
  hideTraps: boolean;
}

export const DEFAULT_FILTERS: Filters = {
  sectors: null, mcap: 'all', minQ: 0, minConf: 1, upside: -100, hideTraps: false,
};

export type SortKey =
  | 'score' | 'ticker' | 'price' | 'upside' | 'conf' | 'quality' | 'mcapB' | 'pe' | 'momPct';
