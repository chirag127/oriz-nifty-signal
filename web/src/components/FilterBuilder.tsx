import { useState } from 'preact/hooks';
import type { StockRow } from '../lib/screener';
import { COLS } from '../lib/scoring';

export type Filter =
  | { kind: 'num'; field: string; op: string; a: number; b?: number }
  | { kind: 'flag'; field: 'mtf_eligible' | 'n500' | 'quality_flag'; on: boolean }
  | { kind: 'text'; field: 'sector'; vals: string[] }
  | { kind: 'derived'; field: 'composite' | 'aftertax_1y'; op: string; a: number; b?: number };

const NUM_COLS = COLS.filter((c) => c.filterable);
const OPS = [['>=', '≥'], ['<=', '≤'], ['>', '>'], ['<', '<'], ['between', 'between']];

export function passes(row: StockRow, filters: Filter[], composite: number | null, aftertax: number | null): boolean {
  for (const f of filters) {
    if (f.kind === 'num' || f.kind === 'derived') {
      const v = f.kind === 'derived'
        ? (f.field === 'composite' ? composite : aftertax)
        : (f.field === 'fii_dii'
            ? ((row.fii == null && row.dii == null) ? undefined : (row.fii ?? 0) + (row.dii ?? 0))
            : (row[f.field] as number | undefined));
      if (typeof v !== 'number') return false;
      if (f.op === '>=' && !(v >= f.a)) return false;
      if (f.op === '<=' && !(v <= f.a)) return false;
      if (f.op === '>' && !(v > f.a)) return false;
      if (f.op === '<' && !(v < f.a)) return false;
      if (f.op === 'between' && !(v >= f.a && v <= (f.b ?? f.a))) return false;
    } else if (f.kind === 'flag') {
      if (Boolean(row[f.field]) !== f.on) return false;
    } else if (f.kind === 'text') {
      if (f.vals.length && !f.vals.includes(String(row.sector ?? ''))) return false;
    }
  }
  return true;
}

export function FilterBuilder({ filters, setFilters }: { filters: Filter[]; setFilters: (f: Filter[]) => void }) {
  const [field, setField] = useState('pe');
  const [op, setOp] = useState('<=');
  const [a, setA] = useState('');
  const [b, setB] = useState('');

  const add = () => {
    const na = parseFloat(a);
    if (!isFinite(na)) return;
    const derivedKeys = ['composite', 'aftertax_1y'];
    const f: Filter = derivedKeys.includes(field)
      ? { kind: 'derived', field: field as 'composite' | 'aftertax_1y', op, a: na, b: op === 'between' ? parseFloat(b) : undefined }
      : { kind: 'num', field, op, a: na, b: op === 'between' ? parseFloat(b) : undefined };
    setFilters([...filters, f]);
    setA(''); setB('');
  };
  const remove = (i: number) => setFilters(filters.filter((_, j) => j !== i));
  const toggleFlag = (field: 'mtf_eligible' | 'n500' | 'quality_flag', on: boolean) => {
    const key = JSON.stringify({ kind: 'flag', field, on });
    const idx = filters.findIndex((x) => JSON.stringify(x) === key);
    if (idx >= 0) setFilters(filters.filter((_, j) => j !== idx));
    else setFilters([...filters.filter((x) => !(x.kind === 'flag' && x.field === field)), { kind: 'flag', field, on }]);
  };
  const flagOn = (field: string, on: boolean) => filters.some((x) => x.kind === 'flag' && x.field === field && x.on === on);

  const label = (field: string) => {
    if (field === 'composite') return 'Composite';
    if (field === 'aftertax_1y') return 'After-tax 1Y';
    return COLS.find((c) => c.key === field)?.label ?? field;
  };

  return (
    <section class="panel filter-panel">
      <h2>Filter builder</h2>
      <div class="fb-row">
        <select value={field} onChange={(e) => setField((e.target as HTMLSelectElement).value)} aria-label="metric">
          <optgroup label="Scores">
            <option value="composite">Composite (live)</option>
            <option value="aftertax_1y">After-tax 1Y</option>
          </optgroup>
          {Object.entries(groupCols()).map(([g, cs]) => (
            <optgroup label={g} key={g}>
              {cs.map((c) => <option value={c.key} key={c.key}>{c.label}</option>)}
            </optgroup>
          ))}
        </select>
        <select value={op} onChange={(e) => setOp((e.target as HTMLSelectElement).value)} aria-label="operator">
          {OPS.map(([v, l]) => <option value={v} key={v}>{l}</option>)}
        </select>
        <input type="number" step="any" value={a} placeholder="value" onInput={(e) => setA((e.target as HTMLInputElement).value)} aria-label="value" />
        {op === 'between' && <input type="number" step="any" value={b} placeholder="to" onInput={(e) => setB((e.target as HTMLInputElement).value)} aria-label="upper" />}
        <button class="btn add" onClick={add}>add</button>
      </div>

      <div class="quick">
        <button class={'q' + (flagOn('mtf_eligible', true) ? ' on' : '')} onClick={() => toggleFlag('mtf_eligible', true)}>MTF-eligible</button>
        <button class={'q' + (flagOn('quality_flag', true) ? ' on' : '')} onClick={() => toggleFlag('quality_flag', true)}>Quality</button>
        <button class={'q' + (flagOn('n500', true) ? ' on' : '')} onClick={() => toggleFlag('n500', true)}>Nifty 500</button>
      </div>

      <div class="chips">
        {filters.map((f, i) => (
          <span class="chip" key={i}>
            {f.kind === 'flag' ? `${label(f.field)} ${f.on ? '✓' : '✗'}`
              : f.kind === 'text' ? `sector: ${f.vals.join(', ')}`
              : `${label(f.field)} ${op2sym(f.op)} ${f.a}${f.op === 'between' ? '–' + (f.b ?? '') : ''}`}
            <button class="chip-x" aria-label="remove" onClick={() => remove(i)}>×</button>
          </span>
        ))}
        {!filters.length && <span class="chip-empty">no filters — whole universe</span>}
      </div>
    </section>
  );
}

function op2sym(op: string) { return op === '>=' ? '≥' : op === '<=' ? '≤' : op; }
function groupCols() {
  const g: Record<string, typeof NUM_COLS> = {};
  for (const c of NUM_COLS) (g[c.group || 'Other'] ||= []).push(c);
  return g;
}
