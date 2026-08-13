import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// nifty_all_metrics.json is produced by the Python pipeline (another owner). It
// may not exist at build time — degrade gracefully. Field names follow the
// pipeline contract (value_score.py + financials.py); every field is optional
// and the client tolerates missing values.
const metricsCandidates = [
  path.resolve(process.cwd(), '../data/nifty_all_metrics.json'),
  path.resolve(here, '../../../data/nifty_all_metrics.json'),
  // legacy/interim name from the spec
  path.resolve(process.cwd(), '../data/nifty500_metrics.json'),
  path.resolve(here, '../../../data/nifty500_metrics.json'),
];

/** One stock row. All metrics optional (coverage thins on small/micro caps). */
export interface StockRow {
  symbol: string;
  name?: string;
  sector?: string;
  industry?: string;
  mcap?: number | null;
  mcap_tier?: string | null; // large | mid | small | micro
  // valuation
  pe?: number | null;
  pb?: number | null;
  ps?: number | null;
  ev_ebit?: number | null;
  ev_ebitda?: number | null;
  p_fcf?: number | null;
  peg?: number | null;
  div_yield?: number | null;
  fcf_yield?: number | null;
  // quality
  roe?: number | null;
  roce?: number | null;
  roa?: number | null;
  debt_to_equity?: number | null;
  f_score?: number | null; // Piotroski 0..9
  f_components_computed?: number | null;
  earnings_growth_pct?: number | null;
  quality?: boolean;
  // momentum / risk
  ret_1y?: number | null;
  ret_1m?: number | null;
  ret_1w?: number | null;
  ret_3y?: number | null;
  beta?: number | null;
  // flags / membership
  is_mtf_eligible?: boolean;
  is_psu?: boolean;
  indices?: string[]; // e.g. ["NIFTY50","NIFTY500"]
  // scores from pipeline (recomputed client-side when weights change)
  value_score?: number | null;
  vq_score?: number | null;
  quality_score?: number | null;
  mtf_score?: number | null;
  rank?: number | null;
  vq_rank?: number | null;
  // per-factor cross-sectional z-scores (drive live re-weighting)
  z?: Record<string, number | null>;
  // arbitrary extra numeric fields tolerated
  [k: string]: unknown;
}

export interface MetricsPayload {
  ts?: string;
  count?: number;
  factors?: string[]; // value-factor keys present in z
  stocks: StockRow[];
}

function readFirst(candidates: string[]): string | null {
  for (const p of candidates) {
    try {
      return fs.readFileSync(p, 'utf-8');
    } catch {
      /* next */
    }
  }
  return null;
}

/**
 * Build a demo universe so the screener + docs render before the pipeline has
 * produced real data. Deterministic (seeded) — never shown once real data lands.
 */
function demoUniverse(): MetricsPayload {
  const SECTORS = [
    'Energy', 'Financials', 'IT', 'Consumer', 'Auto', 'Pharma', 'Metals',
    'Utilities', 'Materials', 'Realty', 'Telecom', 'Industrials',
  ];
  const NAMES = [
    'RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'ICICIBANK', 'ITC', 'SBIN', 'LT',
    'BHARTIARTL', 'HINDUNILVR', 'MARUTI', 'SUNPHARMA', 'TATASTEEL', 'NTPC',
    'ONGC', 'COALINDIA', 'POWERGRID', 'IOC', 'BPCL', 'HINDPETRO', 'PFC',
    'RECLTD', 'VEDL', 'BANKBARODA', 'CANBK', 'PNB', 'UNIONBANK', 'GAIL',
    'DLF', 'GRASIM', 'JSWSTEEL', 'HINDALCO', 'WIPRO', 'TECHM', 'AXISBANK',
    'KOTAKBANK', 'BAJFINANCE', 'NESTLEIND', 'ASIANPAINT', 'TITAN',
  ];
  let seed = 42;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  const FACT = ['ep', 'bp', 'sp', 'ebit_ev', 'fcf_yield', 'inv_peg', 'div_yield'];
  const stocks: StockRow[] = [];
  const N = 600;
  for (let i = 0; i < N; i++) {
    const base = i < NAMES.length ? NAMES[i] : `STOCK${String(i).padStart(4, '0')}`;
    const sector = SECTORS[i % SECTORS.length];
    const isPsu = ['IOC', 'BPCL', 'HINDPETRO', 'PFC', 'RECLTD', 'COALINDIA', 'NTPC', 'ONGC', 'POWERGRID', 'GAIL', 'SBIN', 'BANKBARODA', 'CANBK', 'PNB', 'UNIONBANK'].includes(base);
    const mcap = Math.round((rnd() ** 3) * 1900000 + 300);
    const tier = mcap > 200000 ? 'large' : mcap > 50000 ? 'mid' : mcap > 5000 ? 'small' : 'micro';
    const pe = +(3 + rnd() * 55).toFixed(2);
    const pb = +(0.4 + rnd() * 12).toFixed(2);
    const ps = +(0.3 + rnd() * 14).toFixed(2);
    const evEbit = +(3 + rnd() * 40).toFixed(2);
    const div = +(rnd() * 6).toFixed(2);
    const roe = +(-8 + rnd() * 40).toFixed(1);
    const roce = +(-4 + rnd() * 42).toFixed(1);
    const de = +(rnd() * 3).toFixed(2);
    const fcfY = +(-0.03 + rnd() * 0.14).toFixed(4);
    const peg = pe > 0 ? +(0.3 + rnd() * 4).toFixed(2) : null;
    const ret1y = +(-35 + rnd() * 90).toFixed(1);
    const beta = +(0.4 + rnd() * 1.6).toFixed(2);
    const fscore = Math.min(9, Math.max(0, Math.round(rnd() * 9)));
    // z-scores: cheaper = higher. Fake from the inverse ratios, roughly centred.
    const z: Record<string, number> = {
      ep: +((1 / pe - 0.05) * 18).toFixed(3),
      bp: +((1 / pb - 0.25) * 2.2).toFixed(3),
      sp: +((1 / ps - 0.25) * 2.4).toFixed(3),
      ebit_ev: +((1 / evEbit - 0.08) * 14).toFixed(3),
      fcf_yield: +((fcfY - 0.05) * 22).toFixed(3),
      inv_peg: peg ? +((1 / peg - 0.5) * 1.4).toFixed(3) : 0,
      div_yield: +((div - 1.5) * 0.55).toFixed(3),
    };
    const value = +((z.ep + z.bp + z.sp + z.ebit_ev + z.fcf_yield + z.inv_peg) / 6).toFixed(4);
    const quality = roe > 15 && roce > 15 && fscore >= 6 && de < 1.5;
    stocks.push({
      symbol: base,
      name: base,
      sector,
      mcap,
      mcap_tier: tier,
      pe,
      pb,
      ps,
      ev_ebit: evEbit,
      div_yield: div,
      fcf_yield: fcfY,
      peg,
      roe,
      roce,
      debt_to_equity: de,
      f_score: fscore,
      f_components_computed: 9,
      earnings_growth_pct: +(-20 + rnd() * 60).toFixed(1),
      quality,
      ret_1y: ret1y,
      beta,
      is_mtf_eligible: rnd() > 0.4,
      is_psu: isPsu,
      indices: [
        ...(i < 50 ? ['NIFTY50'] : []),
        ...(i < 100 ? ['NIFTY100'] : []),
        ...(i < 500 ? ['NIFTY500'] : []),
      ],
      value_score: value,
      z,
    });
  }
  return { ts: '', count: N, factors: FACT, stocks, __demo: true } as MetricsPayload & { __demo: boolean };
}

let cache: MetricsPayload | null = null;

/** Load metrics at build time; fall back to a demo universe if absent. */
export function loadMetrics(): MetricsPayload {
  if (cache) return cache;
  const raw = readFirst(metricsCandidates);
  if (!raw) {
    cache = demoUniverse();
    return cache;
  }
  try {
    const parsed = JSON.parse(raw);
    const stocks: StockRow[] = Array.isArray(parsed)
      ? parsed
      : Array.isArray(parsed.stocks)
        ? parsed.stocks
        : Array.isArray(parsed.data)
          ? parsed.data
          : [];
    if (!stocks.length) {
      cache = demoUniverse();
      return cache;
    }
    cache = {
      ts: parsed.ts ?? '',
      count: parsed.count ?? stocks.length,
      factors: parsed.factors,
      stocks,
    };
    return cache;
  } catch {
    cache = demoUniverse();
    return cache;
  }
}

export function isDemo(): boolean {
  return Boolean((loadMetrics() as MetricsPayload & { __demo?: boolean }).__demo);
}
