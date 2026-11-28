// Shared screener config + scoring. FUNDAMENTALS ARE THE SCORE: the composite
// return-potential RANK is a WEIGHTED PERCENTILE AVERAGE of the raw fundamental
// metrics — each metric percentile-ranked 0-100 in its GOOD direction across the
// loaded universe, blended by per-metric weights, renormalised over the metrics
// a stock actually has. No abstract sub-score layer.
import type { StockRow } from './screener';

export const MTF_RATE = 12; // %/yr assumed MTF interest
export const LTCG = 0.125; // 12.5% on the gain
export const MIN_PRESENT = 4; // need ≥N present metrics to rank; else last

// ---- the ~28 fundamental metrics: each has a filter band + a composite weight
export type MetricGroup = 'Valuation' | 'Quality' | 'Growth' | 'Health' | 'Momentum' | 'Ownership' | 'Analyst';
export interface Metric {
  key: string; label: string; group: MetricGroup;
  dir: 1 | -1;          // +1 = higher is better; -1 = lower is better (percentile flips)
  lo: number; hi: number; step: number; // slider band = data 1st–99th percentile
  fmt: (n: number) => string;
  key6?: boolean;       // always-visible key metric
  help?: string;
}
const x = (n: number) => n.toFixed(1) + 'x';
const n1 = (n: number) => n.toFixed(1);
const n2 = (n: number) => n.toFixed(2);
const cr = (n: number) => (n >= 100000 ? (n / 100000).toFixed(1) + 'L' : (n / 1000).toFixed(0) + 'k');

// lo/hi = 1st–99th data-percentile (computed from data/nifty_all_metrics.json),
// rounded so one outlier doesn't stretch the slider.
export const METRICS: Metric[] = [
  // Valuation — cheap is good (dir −1), except div_yield/mcap
  { key: 'pe', label: 'PE', group: 'Valuation', dir: -1, lo: 0, hi: 120, step: 1, fmt: x, key6: true, help: 'Price / earnings — lower cheaper' },
  { key: 'pb', label: 'PB', group: 'Valuation', dir: -1, lo: 0, hi: 20, step: 0.1, fmt: x, key6: true, help: 'Price / book — lower cheaper' },
  { key: 'ps', label: 'PS', group: 'Valuation', dir: -1, lo: 0, hi: 20, step: 0.1, fmt: x, help: 'Price / sales' },
  { key: 'ev_ebitda', label: 'EV/EBITDA', group: 'Valuation', dir: -1, lo: 0, hi: 80, step: 0.5, fmt: x },
  { key: 'p_fcf', label: 'P/FCF', group: 'Valuation', dir: -1, lo: 0, hi: 200, step: 1, fmt: x, help: 'Lower = higher FCF yield' },
  { key: 'peg', label: 'PEG', group: 'Valuation', dir: -1, lo: 0, hi: 10, step: 0.1, fmt: n2 },
  { key: 'div_yield', label: 'Div %', group: 'Valuation', dir: 1, lo: 0, hi: 8, step: 0.25, fmt: n1, key6: true, help: 'Slab-taxed — light weight by default' },
  { key: 'mcap', label: 'Mcap ₹cr', group: 'Valuation', dir: 1, lo: 500, hi: 400000, step: 500, fmt: cr, key6: true },
  // Quality — higher is better
  { key: 'roe', label: 'ROE %', group: 'Quality', dir: 1, lo: 0, hi: 60, step: 1, fmt: n1, key6: true },
  { key: 'roce', label: 'ROCE %', group: 'Quality', dir: 1, lo: 0, hi: 60, step: 1, fmt: n1 },
  { key: 'roa', label: 'ROA %', group: 'Quality', dir: 1, lo: -5, hi: 40, step: 1, fmt: n1 },
  { key: 'net_margin', label: 'Net mgn %', group: 'Quality', dir: 1, lo: 0, hi: 60, step: 1, fmt: n1 },
  { key: 'f_score', label: 'Piotroski', group: 'Quality', dir: 1, lo: 0, hi: 9, step: 1, fmt: (n) => n.toFixed(0), help: '9-pt health (enriched shortlist)' },
  // Growth — higher is better
  { key: 'eps_growth', label: 'EPS g %', group: 'Growth', dir: 1, lo: -80, hi: 200, step: 1, fmt: n1 },
  { key: 'rev_growth', label: 'Rev g %', group: 'Growth', dir: 1, lo: -40, hi: 120, step: 1, fmt: n1 },
  // Health — lower D/E, higher cover, lower pledge
  { key: 'de', label: 'D/E', group: 'Health', dir: -1, lo: 0, hi: 5, step: 0.1, fmt: n2, key6: true, help: 'Debt / equity — lower safer' },
  { key: 'int_cover', label: 'Int cover', group: 'Health', dir: 1, lo: 0, hi: 100, step: 1, fmt: n1 },
  { key: 'pledge', label: 'Pledge %', group: 'Health', dir: -1, lo: 0, hi: 50, step: 1, fmt: n1, help: 'Promoter share pledged — lower safer' },
  // Momentum — higher returns good; low off_52wh (near high) & low beta good
  { key: 'r_1m', label: '1M %', group: 'Momentum', dir: 1, lo: -25, hi: 45, step: 1, fmt: n1 },
  { key: 'r_6m', label: '6M %', group: 'Momentum', dir: 1, lo: -40, hi: 165, step: 1, fmt: n1 },
  { key: 'r_1y', label: '1Y %', group: 'Momentum', dir: 1, lo: -55, hi: 255, step: 1, fmt: n1 },
  { key: 'off_52wh', label: 'off 52wH %', group: 'Momentum', dir: -1, lo: 0, hi: 155, step: 1, fmt: n1, help: 'Distance below 52-week high — nearer high scores higher' },
  { key: 'off_52wl', label: 'off 52wL %', group: 'Momentum', dir: 1, lo: 0, hi: 330, step: 1, fmt: n1, help: 'Distance above 52-week low' },
  { key: 'beta', label: 'Beta', group: 'Momentum', dir: -1, lo: 0, hi: 2.5, step: 0.05, fmt: n2, help: 'Index sensitivity — lower = lower margin-call risk' },
  // Ownership — higher institutional / promoter skin
  { key: 'promoter', label: 'Promoter %', group: 'Ownership', dir: 1, lo: 0, hi: 90, step: 1, fmt: n1 },
  { key: 'fii', label: 'FII %', group: 'Ownership', dir: 1, lo: 0, hi: 45, step: 1, fmt: n1 },
  { key: 'dii', label: 'DII %', group: 'Ownership', dir: 1, lo: 0, hi: 45, step: 1, fmt: n1 },
  { key: 'fii_dii', label: 'FII+DII %', group: 'Ownership', dir: 1, lo: 0, hi: 70, step: 1, fmt: n1, help: 'Combined institutional stake' },
  // Analyst — higher upside good
  { key: 'upside_pct', label: 'Upside %', group: 'Analyst', dir: 1, lo: -55, hi: 370, step: 1, fmt: n1, help: 'Analyst target vs price (covered names)' },
];
export const METRIC_KEYS = METRICS.map((m) => m.key);
export const METRIC_GROUPS: MetricGroup[] = ['Valuation', 'Quality', 'Growth', 'Health', 'Momentum', 'Ownership', 'Analyst'];
export const KEY6 = METRICS.filter((m) => m.key6).map((m) => m.key);
const BY_KEY: Record<string, Metric> = Object.fromEntries(METRICS.map((m) => [m.key, m]));

export type Weights = Record<string, number>;

// DEFAULT = VALUE-HEAVY. value metrics heaviest, quality next, growth/momentum/
// analyst light. Keys not listed default to 0.
export const DEFAULT_WEIGHTS: Weights = {
  pe: 20, pb: 16, ps: 8, ev_ebitda: 12, p_fcf: 10, peg: 6, div_yield: 2, mcap: 2,
  roe: 10, roce: 8, roa: 3, net_margin: 4, f_score: 4,
  eps_growth: 4, rev_growth: 3,
  de: 8, int_cover: 3, pledge: 3,
  r_1m: 1, r_6m: 3, r_1y: 3, off_52wh: 2, off_52wl: 1, beta: 4,
  promoter: 2, fii: 2, dii: 2, fii_dii: 2,
  upside_pct: 4,
};
export const cloneWeights = (w: Weights): Weights => ({ ...w });
export const zeroWeights = (): Weights => Object.fromEntries(METRIC_KEYS.map((k) => [k, 0]));

const nn = (v: unknown): number | null => (typeof v === 'number' && isFinite(v) ? v : null);
export function metricVal(row: StockRow, key: string): number | null {
  if (key === 'fii_dii') {
    if (row.fii == null && row.dii == null) return null;
    return (nn(row.fii) ?? 0) + (nn(row.dii) ?? 0);
  }
  return nn(row[key]);
}

// ---- PERCENTILE ENGINE ----------------------------------------------------
// Build per-metric sorted value arrays ONCE from the universe, then rank any
// value 0-100 in its GOOD direction. dir −1 (lower better) ⇒ flip.
export type PctEngine = { pct: (key: string, v: number) => number };
export function buildPctEngine(rows: StockRow[]): PctEngine {
  const sorted: Record<string, number[]> = {};
  for (const m of METRICS) {
    const arr: number[] = [];
    for (const r of rows) { const v = metricVal(r, m.key); if (v !== null) arr.push(v); }
    arr.sort((a, b) => a - b);
    sorted[m.key] = arr;
  }
  const rankAsc = (arr: number[], v: number): number => {
    // fraction of universe ≤ v (binary search over sorted asc)
    let lo = 0, hi = arr.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] <= v) lo = mid + 1; else hi = mid; }
    return arr.length ? (lo / arr.length) * 100 : 50;
  };
  return {
    pct: (key, v) => {
      const arr = sorted[key];
      if (!arr || !arr.length) return 50;
      const p = rankAsc(arr, v);
      return BY_KEY[key]?.dir === -1 ? 100 - p : p; // flip for "lower is better"
    },
  };
}

/** Weighted-percentile composite (0-100), renormalised over present metrics. */
export function composite(row: StockRow, w: Weights, eng: PctEngine): number | null {
  let sum = 0, wsum = 0, present = 0;
  for (const m of METRICS) {
    const weight = w[m.key] || 0;
    if (weight <= 0) continue;
    const v = metricVal(row, m.key);
    if (v === null) continue;
    present++;
    sum += weight * eng.pct(m.key, v);
    wsum += weight;
  }
  if (present < MIN_PRESENT || wsum === 0) return null; // ranks last
  return sum / wsum;
}

/** Biggest positive contributors to a row's composite, for the driver strip. */
export function drivers(row: StockRow, w: Weights, eng: PctEngine): { key: string; label: string; group: MetricGroup; contrib: number }[] {
  let wsum = 0;
  const parts: { key: string; label: string; group: MetricGroup; pct: number; weight: number }[] = [];
  for (const m of METRICS) {
    const weight = w[m.key] || 0;
    if (weight <= 0) continue;
    const v = metricVal(row, m.key);
    if (v === null) continue;
    wsum += weight;
    parts.push({ key: m.key, label: m.label, group: m.group, pct: eng.pct(m.key, v), weight });
  }
  if (!wsum) return [];
  return parts
    .map((p) => ({ key: p.key, label: p.label, group: p.group, contrib: (p.weight / wsum) * p.pct }))
    .sort((a, b) => b.contrib - a.contrib)
    .slice(0, 6);
}

export function aftertax1y(row: StockRow): number | null {
  const r = nn(row.r_1y);
  if (r === null) return null;
  const afterInt = r - MTF_RATE;
  const tax = afterInt > 0 ? afterInt * LTCG : 0;
  return afterInt - tax;
}

// ---- PRESETS = SCANS (filter bands + weight profile + sort) ---------------
// Each preset sets filter bands, a weight profile, and a sort. Two-way synced
// with the sliders: pick one ⇒ bands+weights move; drag ⇒ switches to "custom".
export type PresetGroup = 'Featured' | 'Core' | 'Named' | 'Strategy';
export interface PresetFilter { field: string; op: '>=' | '<=' | '>' | '<' | 'between'; a: number; b?: number }
export interface PresetSort { id: string; desc: boolean }
export interface Preset {
  id: string; label: string; group: PresetGroup; blurb: string;
  featured?: boolean; flagship?: boolean;
  weights?: Weights;
  filters?: PresetFilter[];
  flags?: ('mtf_eligible' | 'n500' | 'quality_flag')[];
  sort?: PresetSort;
  variants?: { id: string; label: string; filters: PresetFilter[] }[]; // selectable scan variant
  defaultVariant?: string;
}

// weight-profile helpers (spread over the value-heavy default, then override)
const wp = (over: Weights): Weights => ({ ...DEFAULT_WEIGHTS, ...over });

export const DEFAULT_PRESET = 'best_rp';

export const PRESETS: Preset[] = [
  // ---- 3 FEATURED (headline) --------------------------------------------
  {
    id: 'deep_value', label: 'Deep Value', group: 'Featured', featured: true,
    blurb: 'PE < 6 and PB < 1.5 with a quality guard (ROE > 12 OR Piotroski ≥ 6 OR D/E < 1) to weed value-traps out of the cheap tail. Value-heavy weights, ranked by composite.',
    weights: wp({ pe: 26, pb: 22, ev_ebitda: 14, p_fcf: 12, ps: 10, roe: 10, de: 8 }),
    filters: [
      { field: 'pe', op: '>', a: 0 }, { field: 'pe', op: '<', a: 6 },
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1.5 },
    ],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'best_rp', label: 'Best Return-Potential', group: 'Featured', featured: true, flagship: true,
    blurb: 'Default. Ranks by after-tax, after-MTF-interest 1Y return (1Y − 12% interest − 12.5% LTCG on the gain), leaning MTF-eligible + beta < 1.2. The leveraged buy-and-hold shortlist.',
    weights: wp({ pe: 12, pb: 10, ev_ebitda: 8, roe: 12, roce: 10, r_1y: 10, r_6m: 6, upside_pct: 8, beta: 6, de: 6 }),
    flags: ['mtf_eligible'],
    filters: [{ field: 'beta', op: '<', a: 1.2 }],
    sort: { id: 'aftertax_1y', desc: true },
  },
  {
    id: 'qv_turn', label: 'Quality-Value + turnaround', group: 'Featured', featured: true,
    blurb: 'Quality (ROE > 15 & low D/E) that is cheap and turning. Turnaround condition is selectable — default: 6M momentum up (r_6m > 0 and below 52W high).',
    weights: wp({ pe: 14, pb: 12, roe: 18, roce: 12, de: 10, r_6m: 8, eps_growth: 6, rev_growth: 4 }),
    filters: [{ field: 'roe', op: '>', a: 15 }, { field: 'de', op: '<', a: 1 }],
    sort: { id: 'composite', desc: true },
    defaultVariant: 'mom6',
    variants: [
      { id: 'mom6', label: '6M momentum up', filters: [{ field: 'r_6m', op: '>', a: 0 }, { field: 'off_52wh', op: '>', a: 0 }] },
      { id: 'earn', label: 'Earnings turn', filters: [{ field: 'eps_growth', op: '>', a: 0 }, { field: 'rev_growth', op: '>', a: 0 }] },
      { id: 'both', label: 'Both', filters: [{ field: 'r_6m', op: '>', a: 0 }, { field: 'eps_growth', op: '>', a: 0 }] },
    ],
  },

  // ---- CORE --------------------------------------------------------------
  {
    id: 'value', label: 'Value', group: 'Core',
    blurb: 'Pure cheapness — value-heavy weights, no filter, ranked by composite.',
    weights: wp({ pe: 24, pb: 20, ps: 12, ev_ebitda: 16, p_fcf: 12, peg: 6 }),
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'quality_value', label: 'Quality-Value', group: 'Core',
    blurb: 'Cheap AND strong: ROE > 15%, D/E < 1. Cheap without the value-trap risk.',
    weights: wp({ pe: 16, pb: 14, roe: 18, roce: 14, de: 10, net_margin: 6 }),
    filters: [{ field: 'roe', op: '>', a: 15 }, { field: 'de', op: '<', a: 1 }],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'mtf', label: 'MTF Buy-Hold 1yr', group: 'Core', flagship: true,
    blurb: 'MTF/F&O-eligible, beta < 1.2, ranked by after-tax after-interest 1Y return.',
    weights: wp({ roe: 12, roce: 10, r_1y: 10, upside_pct: 8, beta: 8, pe: 10, de: 6 }),
    flags: ['mtf_eligible'],
    filters: [{ field: 'beta', op: '<', a: 1.2 }],
    sort: { id: 'aftertax_1y', desc: true },
  },
  {
    id: 'deep_net_net', label: 'Deep-Value net-net', group: 'Core',
    blurb: 'Asset-cheap: PB < 1, D/E < 0.5 — near/under book with a clean balance sheet.',
    weights: wp({ pb: 26, pe: 14, de: 14, p_fcf: 10 }),
    filters: [
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1 },
      { field: 'de', op: '<', a: 0.5 },
    ],
    sort: { id: 'composite', desc: true },
  },

  // ---- NAMED -------------------------------------------------------------
  {
    id: 'graham', label: 'Graham', group: 'Named',
    blurb: 'Graham defensive: PE < 15, PB < 1.5, D/E < 1.',
    weights: wp({ pe: 22, pb: 20, de: 12, roe: 8 }),
    filters: [
      { field: 'pe', op: '>', a: 0 }, { field: 'pe', op: '<', a: 15 },
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1.5 },
      { field: 'de', op: '<', a: 1 },
    ],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'magic', label: 'Magic Formula', group: 'Named',
    blurb: 'Greenblatt: cheap (EV/EBITDA) + high return on capital (ROCE).',
    weights: wp({ ev_ebitda: 24, roce: 24, roe: 10, pe: 8 }),
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'piotroski', label: 'Piotroski (F≥6)', group: 'Named',
    blurb: 'Fundamentally strong: Piotroski F-score ≥ 6. Enriched shortlist.',
    weights: wp({ f_score: 20, roe: 12, roce: 10, pe: 12, pb: 10 }),
    filters: [{ field: 'f_score', op: '>=', a: 6 }],
    sort: { id: 'composite', desc: true },
  },

  // ---- STRATEGY ----------------------------------------------------------
  {
    id: 'garp', label: 'GARP', group: 'Strategy',
    blurb: 'Growth at a reasonable price: PEG < 1, ROE > 15%, positive EPS growth.',
    weights: wp({ peg: 18, eps_growth: 14, roe: 14, pe: 10, roce: 8 }),
    filters: [
      { field: 'peg', op: '>', a: 0 }, { field: 'peg', op: '<', a: 1 },
      { field: 'roe', op: '>', a: 15 }, { field: 'eps_growth', op: '>', a: 0 },
    ],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'turnaround', label: 'Turnaround', group: 'Strategy',
    blurb: '6M momentum turning up (r_6m > 0) with positive revenue growth, still cheap.',
    weights: wp({ r_6m: 16, rev_growth: 12, eps_growth: 8, pe: 12, pb: 10 }),
    filters: [{ field: 'r_6m', op: '>', a: 0 }, { field: 'rev_growth', op: '>', a: 0 }],
    sort: { id: 'r_6m', desc: true },
  },
  {
    id: 'contrarian', label: 'Contrarian', group: 'Strategy',
    blurb: 'Beaten-down but solid: 1Y return < 0, D/E < 1, cheap.',
    weights: wp({ pe: 18, pb: 16, de: 12, r_1y: 6 }),
    filters: [{ field: 'r_1y', op: '<', a: 0 }, { field: 'de', op: '<', a: 1 }],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'accum', label: 'FII/DII Accumulation', group: 'Strategy',
    blurb: 'Smart-money-held + cheap: FII+DII ≥ 25%.',
    weights: wp({ fii_dii: 16, fii: 8, dii: 8, pe: 12, pb: 10 }),
    filters: [{ field: 'fii_dii', op: '>=', a: 25 }],
    sort: { id: 'composite', desc: true },
  },
  {
    id: 'fcf_yield', label: 'High FCF-Yield', group: 'Strategy',
    blurb: 'Top free-cash-flow yield: lowest P/FCF (most cash per rupee of price).',
    weights: wp({ p_fcf: 28, ev_ebitda: 12, pe: 10, roce: 8 }),
    filters: [{ field: 'p_fcf', op: '>', a: 0 }],
    sort: { id: 'composite', desc: true },
  },
];

export const PROFILES = PRESETS; // legacy alias

/** Which curated scans a row passes (by id) — drives AI narration. */
export function scanMembership(row: StockRow): string[] {
  const ok = (f: PresetFilter): boolean => {
    const v = metricVal(row, f.field);
    if (v === null) return false;
    if (f.op === '>=') return v >= f.a;
    if (f.op === '<=') return v <= f.a;
    if (f.op === '>') return v > f.a;
    if (f.op === '<') return v < f.a;
    return v >= f.a && v <= (f.b ?? f.a);
  };
  const out: string[] = [];
  for (const p of PRESETS) {
    if (!p.filters && !p.flags) continue;
    const flagsOk = (p.flags || []).every((fl) => Boolean(row[fl]));
    const filtersOk = (p.filters || []).every(ok);
    if (flagsOk && filtersOk) out.push(p.id);
  }
  return out;
}

// ---- column definitions (drive the grid + advanced filter builder) --------
export type Fmt = 'z' | 'x' | 'n1' | 'n2' | 'int' | 'pct1' | 'bool' | 'text' | 'rank' | 'pct';
export interface Col { key: string; label: string; fmt: Fmt; group?: string; help?: string; filterable?: boolean }
export const COLS: Col[] = [
  { key: 'symbol', label: 'Stock', fmt: 'text' },
  { key: 'sector', label: 'Sector', fmt: 'text' },
  { key: 'mcap', label: 'Mcap ₹cr', fmt: 'int', group: 'Valuation', filterable: true },
  { key: 'pe', label: 'PE', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / earnings' },
  { key: 'pb', label: 'PB', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / book' },
  { key: 'ps', label: 'PS', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'ev_ebitda', label: 'EV/EBITDA', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'p_fcf', label: 'P/FCF', fmt: 'x', group: 'Valuation', filterable: true, help: 'Lower = higher FCF yield' },
  { key: 'peg', label: 'PEG', fmt: 'n2', group: 'Valuation', filterable: true },
  { key: 'div_yield', label: 'Div %', fmt: 'n2', group: 'Valuation', filterable: true, help: 'Slab-taxed — light-weighted' },
  { key: 'roe', label: 'ROE %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'roce', label: 'ROCE %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'roa', label: 'ROA %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'net_margin', label: 'Net mgn %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'f_score', label: 'Piotroski', fmt: 'int', group: 'Quality', filterable: true, help: '9-pt health (enriched shortlist)' },
  { key: 'de', label: 'D/E', fmt: 'n2', group: 'Health', filterable: true, help: 'Debt / equity' },
  { key: 'int_cover', label: 'Int cover', fmt: 'n1', group: 'Health', filterable: true },
  { key: 'pledge', label: 'Pledge %', fmt: 'n1', group: 'Health', filterable: true },
  { key: 'eps_growth', label: 'EPS g %', fmt: 'n1', group: 'Growth', filterable: true },
  { key: 'rev_growth', label: 'Rev g %', fmt: 'n1', group: 'Growth', filterable: true },
  { key: 'r_1m', label: '1M %', fmt: 'n1', group: 'Momentum', filterable: true },
  { key: 'r_6m', label: '6M %', fmt: 'n1', group: 'Momentum', filterable: true },
  { key: 'r_1y', label: '1Y %', fmt: 'n1', group: 'Momentum', filterable: true },
  { key: 'off_52wh', label: 'off 52wH %', fmt: 'n1', group: 'Momentum', filterable: true, help: 'Distance below 52-week high' },
  { key: 'off_52wl', label: 'off 52wL %', fmt: 'n1', group: 'Momentum', filterable: true, help: 'Distance above 52-week low' },
  { key: 'beta', label: 'Beta', fmt: 'n2', group: 'Momentum', filterable: true },
  { key: 'promoter', label: 'Promoter %', fmt: 'n1', group: 'Ownership', filterable: true },
  { key: 'fii', label: 'FII %', fmt: 'n1', group: 'Ownership', filterable: true },
  { key: 'dii', label: 'DII %', fmt: 'n1', group: 'Ownership', filterable: true },
  { key: 'fii_dii', label: 'FII+DII %', fmt: 'n1', group: 'Ownership', filterable: true, help: 'Combined institutional stake' },
  { key: 'consensus', label: 'Rating', fmt: 'text', group: 'Analyst' },
  { key: 'upside_pct', label: 'Upside %', fmt: 'n1', group: 'Analyst', filterable: true, help: 'Analyst target vs price' },
  { key: 'mtf_net_1y', label: 'MTF net 1Y %', fmt: 'n1', group: 'MTF', filterable: true, help: '1Y return − 12% interest − LTCG on the gain' },
];

export const FMT: Record<Fmt, (v: unknown) => string> = {
  z: (v) => (typeof v !== 'number' ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2)),
  x: (v) => (typeof v !== 'number' ? '—' : v.toFixed(1) + 'x'),
  n1: (v) => (typeof v !== 'number' ? '—' : v.toFixed(1)),
  n2: (v) => (typeof v !== 'number' ? '—' : v.toFixed(2)),
  int: (v) => (typeof v !== 'number' ? '—' : Math.round(v).toLocaleString('en-IN')),
  pct1: (v) => (typeof v !== 'number' ? '—' : (v * 100).toFixed(1) + '%'),
  pct: (v) => (typeof v !== 'number' ? '—' : v.toFixed(0)),
  bool: (v) => (v ? '✓' : '·'),
  text: (v) => (v ? String(v) : '—'),
  rank: (v) => (typeof v !== 'number' ? '—' : '#' + v),
};
