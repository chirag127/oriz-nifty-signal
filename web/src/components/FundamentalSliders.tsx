import type { Filter } from './FilterBuilder';

// Fundamental threshold sliders — the friendly, primary way to filter. Each is a
// dual-thumb min/max range that reads FROM and writes TO the shared Filter state
// (reusing FilterBuilder's Filter type + passes()). Switching a preset moves the
// thumbs; dragging a thumb updates the numeric filter live.
interface Metric { field: string; label: string; min: number; max: number; step: number; fmt: (n: number) => string }
const METRICS: Metric[] = [
  { field: 'pe', label: 'PE', min: 0, max: 60, step: 1, fmt: (n) => n.toFixed(0) + 'x' },
  { field: 'pb', label: 'PB', min: 0, max: 15, step: 0.1, fmt: (n) => n.toFixed(1) + 'x' },
  { field: 'roe', label: 'ROE %', min: 0, max: 50, step: 1, fmt: (n) => n.toFixed(0) },
  { field: 'de', label: 'D/E', min: 0, max: 5, step: 0.1, fmt: (n) => n.toFixed(1) },
  { field: 'mcap', label: 'Mcap ₹cr', min: 0, max: 200000, step: 1000, fmt: (n) => n >= 100000 ? (n / 100000).toFixed(1) + 'L' : (n / 1000).toFixed(0) + 'k' },
  { field: 'div_yield', label: 'Div %', min: 0, max: 12, step: 0.25, fmt: (n) => n.toFixed(1) },
];

// current [min, max] for a field, read from num filters (>= / <= / between)
function bounds(m: Metric, filters: Filter[]): [number, number] {
  let lo = m.min, hi = m.max;
  for (const f of filters) {
    if (f.kind !== 'num' || f.field !== m.field) continue;
    if (f.op === '>=' || f.op === '>') lo = Math.max(lo, f.a);
    else if (f.op === '<=' || f.op === '<') hi = Math.min(hi, f.a);
    else if (f.op === 'between') { lo = Math.max(lo, f.a); hi = Math.min(hi, f.b ?? m.max); }
  }
  return [Math.max(m.min, Math.min(lo, m.max)), Math.min(m.max, Math.max(hi, m.min))];
}

export function FundamentalSliders({ filters, setFilters }: { filters: Filter[]; setFilters: (f: Filter[]) => void }) {
  // rewrite the two bound-filters for a field; drop them when at the extreme
  const setRange = (m: Metric, lo: number, hi: number) => {
    const rest = filters.filter((f) => !(f.kind === 'num' && f.field === m.field));
    const add: Filter[] = [];
    if (lo > m.min) add.push({ kind: 'num', field: m.field, op: '>=', a: lo });
    if (hi < m.max) add.push({ kind: 'num', field: m.field, op: '<=', a: hi });
    setFilters([...rest, ...add]);
  };

  return (
    <section class="panel sliders-panel">
      <div class="phead">
        <h2>Fundamental filters</h2>
        <button class="mini" onClick={() => setFilters(filters.filter((f) => !(f.kind === 'num' && METRICS.some((m) => m.field === f.field))))}>clear</button>
      </div>
      <div class="sgrid">
        {METRICS.map((m) => {
          const [lo, hi] = bounds(m, filters);
          const active = lo > m.min || hi < m.max;
          const pctLo = ((lo - m.min) / (m.max - m.min)) * 100;
          const pctHi = ((hi - m.min) / (m.max - m.min)) * 100;
          return (
            <div class={'srow' + (active ? ' on' : '')} key={m.field}>
              <div class="slab"><span>{m.label}</span><span class="sval">{m.fmt(lo)}–{m.fmt(hi)}</span></div>
              <div class="strack">
                <span class="sfill" style={{ left: pctLo + '%', right: (100 - pctHi) + '%' }}></span>
                <input type="range" min={m.min} max={m.max} step={m.step} value={lo}
                  onInput={(e) => setRange(m, Math.min(+(e.target as HTMLInputElement).value, hi), hi)}
                  aria-label={`${m.label} minimum`} />
                <input type="range" min={m.min} max={m.max} step={m.step} value={hi}
                  onInput={(e) => setRange(m, lo, Math.max(+(e.target as HTMLInputElement).value, lo))}
                  aria-label={`${m.label} maximum`} />
              </div>
            </div>
          );
        })}
      </div>
      <p class="note">Drag to set min/max thresholds — each becomes a filter. Presets move these; the advanced builder below adds any other metric.</p>
    </section>
  );
}
