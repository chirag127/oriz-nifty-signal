import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// nifty_all_metrics.json is produced by the Python pipeline. May not exist at
// build time -> degrade to a demo universe with the SAME shape. Field names
// follow the data contract in SCREENER-SPEC.md.
const candidates = [
  path.resolve(process.cwd(), '../data/nifty_all_metrics.json'),
  path.resolve(here, '../../../data/nifty_all_metrics.json'),
];

export interface StockRow {
  symbol: string;
  name?: string;
  sector?: string;
  // valuation
  pe?: number; pb?: number; ps?: number;
  ev_ebitda?: number; ev_ebit?: number; ev_sales?: number; ev_fcf?: number;
  p_fcf?: number; peg?: number; div_yield?: number; ev?: number; mcap?: number;
  // quality
  roe?: number; roce?: number; roa?: number; net_margin?: number; ebitda_margin?: number;
  // growth
  rev_growth?: number; rev_cagr_5y?: number; eps_growth?: number; eps_cagr_5y?: number;
  // health
  de?: number; ltde?: number; int_cover?: number; current_ratio?: number; pledge?: number;
  // ownership
  promoter?: number; fii?: number; dii?: number; mf?: number; retail?: number;
  // momentum / risk
  r_1d?: number; r_1w?: number; r_1m?: number; r_6m?: number; r_1y?: number; r_cagr_5y?: number;
  off_52wh?: number; off_52wl?: number; beta?: number; volatility?: number; max_dd_1y?: number;
  // meta
  price?: number; volume?: number; eps?: number; lot?: number;
  // enrichment
  f_score?: number; consensus?: string; consensus_score?: number; analyst_count?: number;
  target?: number; upside_pct?: number;
  // z + scores
  z?: Record<string, number>;
  value_score?: number; growth_score?: number; quality_score?: number;
  momentum_score?: number; analyst_score?: number;
  rp_score?: number; mtf_score?: number; mtf_net_1y?: number;
  quality_flag?: boolean; mtf_eligible?: boolean; n500?: boolean;
  value_rank?: number; rp_rank?: number; mtf_rank?: number;
  [k: string]: unknown;
}

export interface Payload {
  ts?: string;
  count?: number;
  mtf_eligible_count?: number;
  analyst_covered?: number;
  assumptions?: { mtf_interest_pct?: number; ltcg_pct?: number; beta_cap?: number };
  value_factors?: string[];
  z_factors?: string[];
  rp_weights?: Record<string, number>;
  ai?: { ts?: string; disclaimer?: string; daily?: string; stocks?: { symbol: string; why_cheap?: string; key_risk?: string }[] };
  stocks: StockRow[];
  __demo?: boolean;
}

function readFirst(paths: string[]): string | null {
  for (const p of paths) {
    try { return fs.readFileSync(p, 'utf-8'); } catch { /* next */ }
  }
  return null;
}

// Deterministic demo universe mirroring the real contract, so the screener +
// docs render fully before the pipeline publishes. Never shown once real data
// lands (__demo drops out).
function demoUniverse(): Payload {
  const SECTORS = ['Financials', 'Information Technology', 'Consumer Discretionary', 'Materials', 'Energy', 'Health Care', 'Industrials', 'Consumer Staples', 'Utilities', 'Real Estate', 'Communication Services'];
  const NAMES = ['RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'ICICIBANK', 'ITC', 'SBIN', 'LT', 'BHARTIARTL', 'HINDUNILVR', 'MARUTI', 'SUNPHARMA', 'TATASTEEL', 'NTPC', 'ONGC', 'COALINDIA', 'POWERGRID', 'JSWSTEEL', 'HINDALCO', 'WIPRO', 'TECHM', 'AXISBANK', 'KOTAKBANK', 'BAJFINANCE', 'NESTLEIND', 'ASIANPAINT', 'TITAN', 'ULTRACEMCO', 'GRASIM', 'DLF'];
  let seed = 42;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const rn = (m: number) => (rnd() - 0.5) * m; // roughly centred noise
  const stocks: StockRow[] = [];
  const N = 520;
  for (let i = 0; i < N; i++) {
    const symbol = i < NAMES.length ? NAMES[i] : `DEMO${String(i).padStart(3, '0')}`;
    const sector = SECTORS[i % SECTORS.length];
    const mcap = Math.round((rnd() ** 3) * 1800000 + 250);
    const pe = +(4 + rnd() * 52).toFixed(2);
    const pb = +(0.4 + rnd() * 11).toFixed(2);
    const ps = +(0.3 + rnd() * 13).toFixed(2);
    const ev_ebitda = +(3 + rnd() * 30).toFixed(2);
    const p_fcf = +(6 + rnd() * 45).toFixed(2);
    const div_yield = +(rnd() * 5).toFixed(2);
    const roe = +(-6 + rnd() * 40).toFixed(1);
    const roce = +(-3 + rnd() * 42).toFixed(1);
    const de = +(rnd() * 2.6).toFixed(2);
    const eps_growth = +(-25 + rnd() * 90).toFixed(1);
    const rev_growth = +(-10 + rnd() * 45).toFixed(1);
    const r_1y = +(-38 + rnd() * 95).toFixed(1);
    const r_1m = +(-14 + rnd() * 28).toFixed(1);
    const beta = +(0.4 + rnd() * 1.5).toFixed(2);
    const peg = pe > 0 && eps_growth > 0 ? +(pe / eps_growth).toFixed(2) : undefined;
    const z = {
      ep: +(rn(3)).toFixed(3), bp: +(rn(3)).toFixed(3), sp: +(rn(3)).toFixed(3),
      ebitda_ev: +(rn(3)).toFixed(3), fcf_yield: +(rn(3)).toFixed(3),
      inv_peg: +(rn(3)).toFixed(3), dy: +((div_yield - 1.4) * 0.5).toFixed(3),
    };
    const value_score = +((z.ep + z.bp + z.sp + z.ebitda_ev + z.fcf_yield + z.inv_peg) / 6).toFixed(4);
    const growth_score = +((eps_growth - 12) / 30).toFixed(4);
    const quality_score = +((roe - 12) / 18 + (roce - 12) / 18).toFixed(4);
    const momentum_score = +((r_1y - 12) / 40).toFixed(4);
    const mtf_eligible = i < 90 && rnd() > 0.3;
    const analyst = i < 40 && rnd() > 0.3;
    const analyst_score = analyst ? +(rn(2)).toFixed(3) : undefined;
    // rp = rp_weights blend over present subs
    const parts: [number, number][] = [[value_score, 0.3], [growth_score, 0.22], [quality_score, 0.22], [momentum_score, 0.16]];
    if (analyst_score !== undefined) parts.push([analyst_score, 0.1]);
    const wsum = parts.reduce((a, [, w]) => a + w, 0);
    const rp_score = +(parts.reduce((a, [v, w]) => a + v * w, 0) / wsum).toFixed(4);
    const mtf_net_1y = +(r_1y - 12 - (r_1y - 12 > 0 ? (r_1y - 12) * 0.125 : 0)).toFixed(2);
    const quality_flag = roe > 15 && de < 1.5;
    const beta_ok = beta < 1.2;
    stocks.push({
      symbol, name: symbol, sector, mcap, pe, pb, ps, ev_ebitda, p_fcf, div_yield, peg,
      roe, roce, de, eps_growth, rev_growth, r_1y, r_1m, beta,
      lot: mtf_eligible ? 500 : undefined,
      f_score: analyst ? Math.round(rnd() * 9) : undefined,
      consensus: analyst ? ['Buy', 'Outperform', 'Hold'][Math.floor(rnd() * 3)] : undefined,
      consensus_score: analyst ? +(2 + rnd() * 3).toFixed(2) : undefined,
      analyst_count: analyst ? Math.round(3 + rnd() * 35) : undefined,
      target: analyst ? +(120 + rnd() * 2400).toFixed(0) : undefined,
      upside_pct: analyst ? +(-10 + rnd() * 45).toFixed(1) : undefined,
      z, value_score, growth_score, quality_score, momentum_score, analyst_score,
      rp_score, mtf_score: mtf_eligible && beta_ok && rp_score > -2 ? rp_score : undefined,
      mtf_net_1y, quality_flag, mtf_eligible, n500: i < 260,
    });
  }
  // ranks
  const rank = (key: 'value_score' | 'rp_score' | 'mtf_score', into: 'value_rank' | 'rp_rank' | 'mtf_rank') => {
    const sorted = stocks.filter((s) => typeof s[key] === 'number').sort((a, b) => (b[key] as number) - (a[key] as number));
    sorted.forEach((s, i) => { s[into] = i + 1; });
  };
  rank('value_score', 'value_rank'); rank('rp_score', 'rp_rank'); rank('mtf_score', 'mtf_rank');
  return {
    ts: '', count: N, mtf_eligible_count: stocks.filter((s) => s.mtf_eligible).length,
    analyst_covered: stocks.filter((s) => s.consensus).length,
    assumptions: { mtf_interest_pct: 12, ltcg_pct: 12.5, beta_cap: 1.2 },
    value_factors: ['ep', 'bp', 'sp', 'ebitda_ev', 'fcf_yield', 'inv_peg'],
    z_factors: ['ep', 'bp', 'sp', 'ebitda_ev', 'fcf_yield', 'inv_peg', 'dy'],
    rp_weights: { value: 0.3, growth: 0.22, quality: 0.22, momentum: 0.16, analyst: 0.1 },
    stocks, __demo: true,
  };
}

let cache: Payload | null = null;

export function loadMetrics(): Payload {
  if (cache) return cache;
  const raw = readFirst(candidates);
  if (!raw) { cache = demoUniverse(); return cache; }
  try {
    const p = JSON.parse(raw);
    const stocks: StockRow[] = Array.isArray(p.stocks) ? p.stocks : [];
    if (!stocks.length) { cache = demoUniverse(); return cache; }
    cache = { ...p, stocks };
    return cache;
  } catch { cache = demoUniverse(); return cache; }
}

export function isDemo(): boolean {
  return Boolean(loadMetrics().__demo);
}
