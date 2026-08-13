import type { Filter } from './FilterBuilder';
import { METRICS, METRIC_GROUPS, type Metric, type Weights, DEFAULT_WEIGHTS, cloneWeights } from '../lib/scoring';

// The ~28 fundamental rows. Each row = a DUAL-THUMB filter band (writes to the
// shared Filter state, reusing passes()) PLUS a WEIGHT dial (how much the metric
// drives the composite). Key-6 always visible; the rest under expandable
// category <details>. A band left at full min–max applies no filter (dropped).
interface Props {
  filters: Filter[]; setFilters: (f: Filter[]) => void;
  weights: Weights; setWeights: (w: Weights) => void;
  onClear: () => void;
}

// current [min, max] for a field, read from num filters (>= / <= / between)
function bounds(m: Metric, filters: Filter[]): [number, number] {
  let lo = m.lo, hi = m.hi;
  for (const f of filters) {
    if (f.kind !== 'num' || f.field !== m.key) continue;
    if (f.op === '>=' || f.op === '>') lo = Math.max(lo, f.a);
    else if (f.op === '<=' || f.op === '<') hi = Math.min(hi, f.a);
    else if (f.op === 'between') { lo = Math.max(lo, f.a); hi = Math.min(hi, f.b ?? m.hi); }
  }
  return [Math.max(m.lo, Math.min(lo, m.hi)), Math.min(m.hi, Math.max(hi, m.lo))];
}

export function FundamentalSliders({ filters, setFilters, weights, setWeights, onClear }: Props) {
  // rewrite the two band-filters for a field; drop when at the extreme (= off)
  const setRange = (m: Metric, lo: number, hi: number) => {
    const rest = filters.filter((f) => !(f.kind === 'num' && f.field === m.key));
    const add: Filter[] = [];
    if (lo > m.lo) add.push({ kind: 'num', field: m.key, op: '>=', a: lo });
    if (hi < m.hi) add.push({ kind: 'num', field: m.key, op: '<=', a: hi });
    setFilters([...rest, ...add]);
  };
  const setWeight = (key: string, v: number) => setWeights({ ...cloneWeights(weights), [key]: v });

  const row = (m: Metric) => {
    const [lo, hi] = bounds(m, filters);
    const banded = lo > m.lo || hi < m.hi;
    const w = weights[m.key] || 0;
    const pctLo = ((lo - m.lo) / (m.hi - m.lo)) * 100;
    const pctHi = ((hi - m.lo) / (m.hi - m.lo)) * 100;
    return (
      <div class={'srow' + (banded ? ' on' : '') + (w > 0 ? ' weighted' : '')} key={m.key}>
        <div class="slab" title={m.help}>
          <span class="sname">{m.label}<span class="sdir">{m.dir === -1 ? ' ↓good' : ' ↑good'}</span></span>
          <span class="sval">{banded ? `${m.fmt(lo)}–${m.fmt(hi)}` : 'any'}</span>
        </div>
        <div class="strack">
          <span class="sfill" style={{ left: pctLo + '%', right: (100 - pctHi) + '%' }}></span>
          <input type="range" min={m.lo} max={m.hi} step={m.step} value={lo}
            onInput={(e) => setRange(m, Math.min(+(e.target as HTMLInputElement).value, hi), hi)}
            aria-label={`${m.label} minimum`} />
          <input type="range" min={m.lo} max={m.hi} step={m.step} value={hi}
            onInput={(e) => setRange(m, lo, Math.max(+(e.target as HTMLInputElement).value, lo))}
            aria-label={`${m.label} maximum`} />
        </div>
        <div class="wdial" title="weight in the composite rank">
          <input type="range" min={0} max={30} step={1} value={w}
            onInput={(e) => setWeight(m.key, +(e.target as HTMLInputElement).value)}
            aria-label={`${m.label} weight`} />
          <span class="wval">{w}</span>
        </div>
      </div>
    );
  };

  const key6 = METRICS.filter((m) => m.key6);
  const byGroup = (g: string) => METRICS.filter((m) => m.group === g && !m.key6);

  return (
    <section class="panel sliders-panel">
      <div class="phead">
        <h2>Metrics — filter band + weight</h2>
        <button class="mini" onClick={onClear}>clear</button>
      </div>
      <div class="scol-head">
        <span>metric</span><span>filter band</span><span>weight</span>
      </div>
      <div class="sgrid">{key6.map(row)}</div>
      {METRIC_GROUPS.map((g) => {
        const ms = byGroup(g);
        if (!ms.length) return null;
        const anyW = ms.some((m) => (weights[m.key] || 0) > 0);
        return (
          <details class="scat" key={g} open={g === 'Valuation'}>
            <summary>{g}<span class="scat-n">{ms.length}{anyW ? ' · weighted' : ''}</span></summary>
            <div class="sgrid">{ms.map(row)}</div>
          </details>
        );
      })}
      <p class="note">Drag the <b>band</b> to filter (left at full = off, ignored). Drag the <b>weight</b> to set how much the metric drives the composite rank (0 = excluded). Default weights are value-heavy; presets re-tilt them.</p>
    </section>
  );
}

export { DEFAULT_WEIGHTS };
