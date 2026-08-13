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
  { key: 'value', label: 'Value', field: 'value_score', hint: 'Cheapness — equal-weight z of E/P, B/P, S/P, EBITDA/EV, FCF-yield, 1/PEG.' },
  { key: 'growth', label: 'Growth', field: 'growth_score', hint: 'Revenue + EPS growth (YoY & 5yr CAGR).' },
  { key: 'quality', label: 'Quality', field: 'quality_score', hint: 'ROE / ROCE / margins / low debt.' },
  { key: 'momentum', label: 'Momentum', field: 'momentum_score', hint: '1M–1Y price trend, distance from 52W high.' },
  { key: 'analyst', label: 'Analyst', field: 'analyst_score', hint: 'Consensus rating + target upside (covered names only).' },
];

// ---- weighting PROFILES ----------------------------------------------------
export interface Profile { id: string; label: string; blurb: string; weights: Record<SubKey, number> }
export const PROFILES: Profile[] = [
  {
    id: 'return', label: 'Return Potential', flagship: true,
    blurb: 'Growth + momentum + analyst upside carry the weight — hunts the highest forward-return names, not just the cheapest.',
    weights: { value: 20, growth: 28, quality: 18, momentum: 22, analyst: 12 },
  } as Profile & { flagship: boolean },
  {
    id: 'balanced', label: 'Balanced',
    blurb: 'Equal say to every factor — the neutral, all-round ranking.',
    weights: { value: 20, growth: 20, quality: 20, momentum: 20, analyst: 20 },
  },
  {
    id: 'deep', label: 'Deep Value',
    blurb: 'E/P + B/P heavy — cheapness dominates, quality only as a value-trap guard.',
    weights: { value: 55, growth: 8, quality: 25, momentum: 7, analyst: 5 },
  },
  {
    id: 'quality', label: 'Quality Value',
    blurb: 'Cheap AND strong — value and quality share the load, growth as tiebreak.',
    weights: { value: 38, growth: 12, quality: 38, momentum: 7, analyst: 5 },
  },
];

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

/** Live composite from sub-scores, renormalised over the subs the stock HAS. */
export function composite(row: StockRow, w: Record<SubKey, number>): number | null {
  let sum = 0, wsum = 0;
  for (const s of SUBS) {
    const weight = w[s.key];
    if (!weight) continue;
    const v = clampZ(nn(row[s.field]));
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
    const v = clampZ(nn(row[s.field]));
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
  { key: 'mcap', label: 'Mcap ₹cr', fmt: 'int', group: 'Valuation', filterable: true },
  { key: 'pe', label: 'PE', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / earnings' },
  { key: 'pb', label: 'PB', fmt: 'x', group: 'Valuation', filterable: true, help: 'Price / book' },
  { key: 'ps', label: 'PS', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'ev_ebitda', label: 'EV/EBITDA', fmt: 'x', group: 'Valuation', filterable: true },
  { key: 'p_fcf', label: 'P/FCF', fmt: 'x', group: 'Valuation', filterable: true },
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
  { key: 'r_1y', label: '1Y %', fmt: 'n1', group: 'Momentum', filterable: true },
  { key: 'off_52wh', label: 'off 52wH %', fmt: 'n1', group: 'Momentum', filterable: true, help: 'Distance below 52-week high' },
  { key: 'beta', label: 'Beta', fmt: 'n2', group: 'Momentum', filterable: true },
  { key: 'promoter', label: 'Promoter %', fmt: 'n1', group: 'Ownership', filterable: true },
  { key: 'fii', label: 'FII %', fmt: 'n1', group: 'Ownership', filterable: true },
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
