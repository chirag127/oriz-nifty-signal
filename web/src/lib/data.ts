import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = (rel: string) => [
  path.resolve(process.cwd(), `../data/${rel}`),
  path.resolve(here, `../../../data/${rel}`),
];

export interface Indicator {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  zone: string;
  score: number | null;
  detail: string;
  source: string;
  as_of: string;
}
export interface Signal {
  verdict: string;
  verdict_score: number;
  rationale: string;
  ts: string;
  indicators: Indicator[];
  summary: string;
  errors: string[];
}
export interface HistPoint {
  ts: string;
  score: number;
  verdict: string;
}

const EMPTY: Signal = {
  verdict: 'HOLD-SIP-ONLY',
  verdict_score: 0,
  rationale: 'Awaiting first run.',
  ts: '',
  indicators: [],
  summary: '',
  errors: [],
};

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

export function loadSignal(): Signal {
  const raw = readFirst(dataDir('latest.json'));
  if (!raw) return EMPTY;
  try {
    return { ...EMPTY, ...JSON.parse(raw) };
  } catch {
    return EMPTY;
  }
}

/** Merge every history/<date>.json into one time-ordered score series. */
export function loadHistory(): HistPoint[] {
  const dirs = [
    path.resolve(process.cwd(), '../data/history'),
    path.resolve(here, '../../../data/history'),
  ];
  for (const dir of dirs) {
    try {
      const files = fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort();
      const pts: HistPoint[] = [];
      for (const f of files) {
        try {
          const arr = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf-8'));
          if (Array.isArray(arr)) pts.push(...arr);
        } catch {
          /* skip */
        }
      }
      pts.sort((a, b) => a.ts.localeCompare(b.ts));
      return pts;
    } catch {
      /* next dir */
    }
  }
  return [];
}
