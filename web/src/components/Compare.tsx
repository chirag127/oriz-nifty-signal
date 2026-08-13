import { useMemo } from 'preact/hooks';
import type { StockRow } from '../lib/screener';
import { composite, type SubKey } from '../lib/scoring';

const CMP = [
  { key: 'composite', label: 'Composite', fmt: 'z', hi: 'high' },
  { key: 'pe', label: 'PE', fmt: 'x', hi: 'low' },
  { key: 'pb', label: 'PB', fmt: 'x', hi: 'low' },
  { key: 'ev_ebitda', label: 'EV/EBITDA', fmt: 'x', hi: 'low' },
  { key: 'peg', label: 'PEG', fmt: 'n2', hi: 'low' },
  { key: 'roe', label: 'ROE %', fmt: 'n1', hi: 'high' },
  { key: 'roce', label: 'ROCE %', fmt: 'n1', hi: 'high' },
  { key: 'de', label: 'D/E', fmt: 'n2', hi: 'low' },
  { key: 'eps_growth', label: 'EPS g %', fmt: 'n1', hi: 'high' },
  { key: 'r_1y', label: '1Y %', fmt: 'n1', hi: 'high' },
  { key: 'beta', label: 'Beta', fmt: 'n2', hi: 'low' },
  { key: 'div_yield', label: 'Div %', fmt: 'n2', hi: 'high' },
] as const;

const f = {
  z: (v: number | null) => (v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2)),
  x: (v: number | null) => (v == null ? '—' : v.toFixed(1) + 'x'),
  n1: (v: number | null) => (v == null ? '—' : v.toFixed(1)),
  n2: (v: number | null) => (v == null ? '—' : v.toFixed(2)),
} as Record<string, (v: number | null) => string>;

export function Compare({
  rows, watch, weights, clear, toggleWatch,
}: {
  rows: StockRow[]; watch: Set<string>; weights: Record<SubKey, number>;
  clear: () => void; toggleWatch: (s: string) => void;
}) {
  const picked = useMemo(
    () => [...watch].slice(0, 8).map((s) => rows.find((r) => r.symbol === s)).filter((x): x is StockRow => !!x),
    [watch, rows],
  );
  const val = (r: StockRow, k: string): number | null =>
    k === 'composite' ? composite(r, weights) : (typeof r[k] === 'number' ? (r[k] as number) : null);

  return (
    <section class="panel compare-panel">
      <div class="phead">
        <h2>Watchlist &amp; compare ({watch.size})</h2>
        {watch.size > 0 && <button class="mini" onClick={clear}>clear</button>}
      </div>
      {!picked.length ? (
        <div class="cmp-empty">
          <span class="cmp-empty-star">☆</span>
          <p>Star stocks in the table to compare up to 8 side-by-side — the “pick your basket” workflow.</p>
        </div>
      ) : (
        <div class="table-scroll static">
          <table class="stable cmp-table">
            <thead>
              <tr>
                <th class="th-text">Metric</th>
                {picked.map((p) => (
                  <th key={p.symbol}>
                    <div class="cmp-sym">{p.symbol}<button class="cmp-x" aria-label="remove" onClick={() => toggleWatch(p.symbol)}>×</button></div>
                    <div class="cmp-sec">{p.sector || ''}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CMP.map((m) => {
                const vals = picked.map((p) => val(p, m.key));
                const valid = vals.filter((v): v is number => v != null);
                const best = valid.length > 1 ? (m.hi === 'high' ? Math.max(...valid) : Math.min(...valid)) : null;
                return (
                  <tr key={m.key}>
                    <td class="td-text cmp-metric">{m.label}</td>
                    {vals.map((v, i) => (
                      <td key={i} class={best != null && v === best ? 'best' : ''}>{f[m.fmt](v)}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
