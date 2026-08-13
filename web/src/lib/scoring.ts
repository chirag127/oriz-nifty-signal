// Shared screener config + scoring. The island re-weights the RETURN-POTENTIAL
// composite live from per-stock sub-scores (value/growth/quality/momentum/
// analyst) and the VALUE composite from per-factor z-scores.
import type { StockRow } from './screener';

export const MTF_RATE = 12; // %/yr assumed MTF interest
export const LTCG = 0.125; // 12.5% on the gain

// ---- return-potential SUB-SCORES (the profile re-weights these) -----------
export interface Sub { key: SubKey; label: string; field: keyof StockRow; hint: string }
export type SubKey = 'value' | 'growth' | 'quality' | 'momentum' | 'analyst';
export const SUBS: Sub[] = [
  { key: 'value', label: 'Value', field: 'value_score', hint: 'Cheapness — 0-100 percentile of E/P, B/P, S/P, EBITDA/EV, FCF-yield (higher=cheaper).' },
  { key: 'growth', label: 'Growth', field: 'growth_score', hint: 'Revenue + EPS growth (YoY & 5yr CAGR).' },
  { key: 'quality', label: 'Quality', field: 'quality_score', hint: 'ROE / ROCE / margins / low debt.' },
  { key: 'momentum', label: 'Momentum', field: 'momentum_score', hint: '1M–1Y price trend, distance from 52W high.' },
  { key: 'analyst', label: 'Analyst', field: 'analyst_score', hint: 'Consensus rating + target upside (covered names only).' },
];

// ---- PRESETS ---------------------------------------------------------------
// Two kinds, one curated set of 12 + a default. WEIGHT presets re-tilt the
// return-potential composite (sub-score slider state). SCAN presets apply a
// filter set + a sort — they screen the universe by the classic rules, using
// the percentile value + Graham/Magic/Piotroski backing fields.
export type PresetGroup = 'Core' | 'Named' | 'Strategy';
export interface PresetFilter { field: string; op: '>=' | '<=' | '>' | '<' | 'between'; a: number; b?: number }
export interface PresetSort { id: string; desc: boolean }
export interface Preset {
  id: string; label: string; group: PresetGroup; blurb: string;
  flagship?: boolean;
  weights?: Record<SubKey, number>;   // present ⇒ also sets slider state
  filters?: PresetFilter[];           // present ⇒ scan (sets filter builder)
  flags?: ('mtf_eligible' | 'n500' | 'quality_flag')[]; // quick-flag toggles
  sort?: PresetSort;                  // required for scans
}

// slider defaults reused across weight presets
const W = (value: number, growth: number, quality: number, momentum: number, analyst: number): Record<SubKey, number> =>
  ({ value, growth, quality, momentum, analyst });

export const DEFAULT_PRESET = 'my_deep_value';

export const PRESETS: Preset[] = [
  // ---- USER DEFAULT ----
  {
    id: 'my_deep_value', label: 'My Deep Value', group: 'Core',
    blurb: 'PE < 6 and PB < 1.5 with a quality guard (ROE>12 OR Piotroski≥6 OR D/E<1) to weed out value-traps in the cheap tail. Sorted cheapest-first. Loads by default.',
    weights: W(60, 8, 24, 5, 3),
    filters: [
      { field: 'pe', op: '>', a: 0 }, { field: 'pe', op: '<', a: 6 },
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1.5 },
    ],
    sort: { id: 'value_score', desc: true },
  },

  // ---- CORE ----
  {
    id: 'value', label: 'Value', group: 'Core',
    blurb: 'Pure cheapness — ranks the whole universe by the 5-factor percentile value score, no other filter.',
    weights: W(70, 6, 18, 4, 2),
    sort: { id: 'value_score', desc: true },
  },
  {
    id: 'quality_value', label: 'Quality-Value', group: 'Core',
    blurb: 'Cheap AND strong: value ≥70th pct, ROE > 15%, D/E < 1. Cheap without the value-trap risk.',
    weights: W(40, 8, 40, 7, 5),
    filters: [
      { field: 'value_score', op: '>=', a: 70 },
      { field: 'roe', op: '>', a: 15 }, { field: 'de', op: '<', a: 1 },
    ],
    sort: { id: 'value_score', desc: true },
  },
  {
    id: 'mtf', label: 'MTF Buy-Hold 1yr', group: 'Core', flagship: true,
    blurb: 'Flagship. MTF/F&O-eligible names with beta < 1.2, ranked by after-tax, after-interest 1Y return (1Y − 12% MTF interest − 12.5% LTCG on the gain). The leveraged buy-and-hold shortlist.',
    weights: W(30, 20, 26, 14, 10),
    flags: ['mtf_eligible'],
    filters: [{ field: 'beta', op: '<', a: 1.2 }],
    sort: { id: 'aftertax_1y', desc: true },
  },
  {
    id: 'deep_net_net', label: 'Deep-Value net-net', group: 'Core',
    blurb: 'Asset-cheap: PB < 1 with D/E < 0.5 — trading near/under book with a clean balance sheet.',
    weights: W(65, 5, 25, 3, 2),
    filters: [
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1 },
      { field: 'de', op: '<', a: 0.5 },
    ],
    sort: { id: 'pb', desc: false },
  },

  // ---- NAMED ----
  {
    id: 'graham', label: 'Graham', group: 'Named',
    blurb: 'Graham defensive: PE < 15, PB < 1.5, PE×PB < 22.5, D/E < 1. All four rungs must pass (graham_ok).',
    filters: [
      { field: 'pe', op: '>', a: 0 }, { field: 'pe', op: '<', a: 15 },
      { field: 'pb', op: '>', a: 0 }, { field: 'pb', op: '<', a: 1.5 },
      { field: 'de', op: '<', a: 1 },
    ],
    sort: { id: 'value_score', desc: true },
  },
  {
    id: 'magic', label: 'Magic Formula', group: 'Named',
    blurb: 'Greenblatt: combined rank of earnings-yield (EBIT/EV) + ROCE. Sorted by magic_rank ascending (1 = best).',
    sort: { id: 'magic_rank', desc: false },
  },
  {
    id: 'piotroski', label: 'Piotroski (F≥7)', group: 'Named',
    blurb: 'Fundamentally strong: Piotroski F-score ≥ 7 of 9. Computed on the enriched shortlist, sorted cheapest-first.',
    filters: [{ field: 'f_score', op: '>=', a: 7 }],
    sort: { id: 'value_score', desc: true },
  },

  // ---- STRATEGY ----
  {
    id: 'garp', label: 'GARP', group: 'Strategy',
    blurb: 'Growth at a reasonable price: PEG < 1, ROE > 15%, positive EPS growth. Sorted by PEG ascending.',
    filters: [
      { field: 'peg', op: '>', a: 0 }, { field: 'peg', op: '<', a: 1 },
      { field: 'roe', op: '>', a: 15 }, { field: 'eps_growth', op: '>', a: 0 },
    ],
    sort: { id: 'peg', desc: false },
  },
  {
    id: 'turnaround', label: 'Turnaround', group: 'Strategy',
    blurb: 'Re-rate catch: cheap (value ≥60th pct) with 6M momentum turning up (r_6m > 0) and positive revenue growth. Sorted by 6M return.',
    filters: [
      { field: 'value_score', op: '>=', a: 60 },
      { field: 'r_6m', op: '>', a: 0 }, { field: 'rev_growth', op: '>', a: 0 },
    ],
    sort: { id: 'r_6m', desc: true },
  },
  {
    id: 'contrarian', label: 'Contrarian', group: 'Strategy',
    blurb: 'Beaten-down but solid: 1Y return < 0, D/E < 1, positive FCF, cheap (value ≥60th pct). Sorted cheapest-first.',
    filters: [
      { field: 'r_1y', op: '<', a: 0 }, { field: 'de', op: '<', a: 1 },
      { field: 'fcf', op: '>', a: 0 }, { field: 'value_score', op: '>=', a: 60 },
    ],
    sort: { id: 'value_score', desc: true },
  },
  {
    id: 'accum', label: 'FII/DII Accumulation', group: 'Strategy',
    blurb: 'Smart-money-held + cheap: FII+DII combined ≥ 25%, value ≥60th pct. Sorted by combined institutional stake.',
    filters: [
      { field: 'fii_dii', op: '>=', a: 25 },
      { field: 'value_score', op: '>=', a: 60 },
    ],
    sort: { id: 'fii_dii', desc: true },
  },
  {
    id: 'fcf_yield', label: 'High FCF-Yield', group: 'Strategy',
    blurb: 'Top free-cash-flow yield: lowest P/FCF (most cash per rupee of price). Sorted by P/FCF ascending.',
    filters: [{ field: 'p_fcf', op: '>', a: 0 }],
    sort: { id: 'p_fcf', desc: false },
  },
];

// legacy alias — some callers still reference PROFILES
export const PROFILES = PRESETS;

/** Which curated scans a row passes (by id) — drives chips + AI narration. */
export function scanMembership(row: StockRow): string[] {
  const num = (k: string): number | null => {
    if (k === 'fii_dii') { const v = (nn(row.fii) ?? 0) + (nn(row.dii) ?? 0); return (row.fii == null && row.dii == null) ? null : v; }
    return nn(row[k]);
  };
  const ok = (f: PresetFilter): boolean => {
    const v = num(f.field);
    if (v === null) return false;
    if (f.op === '>=') return v >= f.a;
    if (f.op === '<=') return v <= f.a;
    if (f.op === '>') return v > f.a;
    if (f.op === '<') return v < f.a;
    return v >= f.a && v <= (f.b ?? f.a);
  };
  const out: string[] = [];
  for (const p of PRESETS) {
    if (!p.filters && !p.flags) continue; // pure-sort presets (Value, Magic) aren't membership scans
    const flagsOk = (p.flags || []).every((fl) => Boolean(row[fl]));
    const filtersOk = (p.filters || []).every(ok);
    if (flagsOk && filtersOk) out.push(p.id);
  }
  return out;
}

/** Normalise a weight map so present-and-nonzero entries sum to 100 (%). */
export function normalise(w: Record<SubKey, number>): Record<SubKey, number> {
  const total = SUBS.reduce((a, s) => a + Math.max(0, w[s.key] || 0), 0) || 1;
  const out = {} as Record<SubKey, number>;
  for (const s of SUBS) out[s.key] = (Math.max(0, w[s.key] || 0) / total) * 100;
  return out;
}

const nn = (v: unknown): number | null => (typeof v === 'number' && isFinite(v) ? v : null);
// Sub-scores are cross-sectional z-means: a valid one never exceeds ~±5. The
// pipeline occasionally emits an un-normalised value (e.g. quality_score 73) on
// a data-junk micro-cap; clamp so one bad row can't hijack the ranking.
const Z_CLAMP = 5;
const clampZ = (v: number | null): number | null => (v === null ? null : Math.max(-Z_CLAMP, Math.min(Z_CLAMP, v)));

// value_score is a 0-100 PERCENTILE (higher=cheaper); the other subs are
// cross-sectional z-means (~±3). Map the percentile onto the z scale so the
// weighted blend is apples-to-apples: 50th→0, ~90th→+2, ~10th→-2.
const subZ = (key: SubKey, row: StockRow): number | null => {
  if (key === 'value') { const v = nn(row.value_score); return v === null ? null : clampZ((v - 50) / 20); }
  return clampZ(nn(row[SUBS.find((s) => s.key === key)!.field]));
};

/** Live composite from sub-scores, renormalised over the subs the stock HAS. */
export function composite(row: StockRow, w: Record<SubKey, number>): number | null {
  let sum = 0, wsum = 0;
  for (const s of SUBS) {
    const weight = w[s.key];
    if (!weight) continue;
    const v = subZ(s.key, row);
    if (v === null) continue;
    sum += weight * v;
    wsum += weight;
  }
  return wsum === 0 ? clampZ(nn(row.rp_score)) : sum / wsum;
}

/** Which sub-scores drive this row's composite, biggest contribution first. */
export function drivers(row: StockRow, w: Record<SubKey, number>): { key: SubKey; label: string; contrib: number }[] {
  const norm = normalise(w);
  const out: { key: SubKey; label: string; contrib: number }[] = [];
  for (const s of SUBS) {
    const v = subZ(s.key, row);
    if (v === null || !norm[s.key]) continue;
    out.push({ key: s.key, label: s.label, contrib: (norm[s.key] / 100) * v });
  }
  return out.sort((a, b) => Math.abs(b.contrib) - Math.abs(a.contrib));
}

export function aftertax1y(row: StockRow): number | null {
  const r = nn(row.r_1y);
  if (r === null) return null;
  const afterInt = r - MTF_RATE;
  const tax = afterInt > 0 ? afterInt * LTCG : 0;
  return afterInt - tax;
}

// ---- column definitions (drive the grid + filter builder) -----------------
export type Fmt = 'z' | 'x' | 'n1' | 'n2' | 'int' | 'pct1' | 'bool' | 'text' | 'rank';
export interface Col { key: string; label: string; fmt: Fmt; group?: string; help?: string; filterable?: boolean }
export const COLS: Col[] = [
  { key: 'symbol', label: 'Stock', fmt: 'text' },
  { key: 'sector', label: 'Sector', fmt: 'text' },
  { key: 'value_score', label: 'Value pct', fmt: 'n1', group: 'Scores', filterable: true, help: '0-100 percentile cheapness (higher=cheaper)' },
  { key: 'magic_rank', label: 'Magic #', fmt: 'rank', group: 'Scores', filterable: true, help: 'Greenblatt combined rank (lower=better)' },
  { key: 'mcap', label: 'Mcap ₹cr', fmt: 'int', group: 'Valuation', filterable: true },
  { key: 'pe', label: 'PE', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / earnings' },
  { key: 'pb', label: 'PB', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / book' },
  { key: 'ps', label: 'PS', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'ev_ebitda', label: 'EV/EBITDA', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'p_fcf', label: 'P/FCF', fmt: 'x', group: 'Valuation', filterable: true, help: 'Lower = higher FCF yield' },
  { key: 'peg', label: 'PEG', fmt: 'n2', group: 'Valuation', filterable: true },
  { key: 'div_yield', label: 'Div %', fmt: 'n2', group: 'Valuation', filterable: true, help: 'Display-only — slab-taxed, out of the core rank' },
  { key: 'roe', label: 'ROE %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'roce', label: 'ROCE %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'net_margin', label: 'Net mgn %', fmt: 'n1', group: 'Quality', filterable: true },
  { key: 'de', label: 'D/E', fmt: 'n2', group: 'Health', filterable: true, help: 'Debt / equity' },
  { key: 'int_cover', label: 'Int cover', fmt: 'n1', group: 'Health', filterable: true },
  { key: 'pledge', label: 'Pledge %', fmt: 'n1', group: 'Health', filterable: true },
  { key: 'f_score', label: 'Piotroski', fmt: 'int', group: 'Quality', filterable: true, help: '9-pt health (enriched shortlist)' },
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
  bool: (v) => (v ? '✓' : '·'),
  text: (v) => (v ? String(v) : '—'),
  rank: (v) => (typeof v !== 'number' ? '—' : '#' + v),
};
