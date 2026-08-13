import { useMemo, useState, useCallback, useRef, useEffect } from 'preact/hooks';
import {
  useReactTable, getCoreRowModel, flexRender,
  type ColumnDef, type SortingState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import type { StockRow, Payload } from '../lib/screener';
import {
  SUBS, PRESETS, DEFAULT_PRESET, COLS, FMT,
  normalise, composite, drivers, aftertax1y, scanMembership,
  type SubKey, type Col, type Preset, type PresetGroup,
} from '../lib/scoring';
import { HeatBar } from './HeatBar';
import { WeightPanel } from './WeightPanel';
import { FilterBuilder, type Filter, passes } from './FilterBuilder';
import { FundamentalSliders } from './FundamentalSliders';
import { Compare } from './Compare';

const FACTOR_COLOR: Record<SubKey, string> = {
  value: 'var(--f-value)', growth: 'var(--f-growth)', quality: 'var(--f-quality)',
  momentum: 'var(--f-momentum)', analyst: 'var(--f-analyst)',
};

type Weights = Record<SubKey, number>;
const eqWeights = (): Weights => ({ value: 20, growth: 20, quality: 20, momentum: 20, analyst: 20 });
const TOP_N = 100; // scans surface the top ~100; user narrows to their 5

const PRESET_GROUPS: PresetGroup[] = ['Core', 'Named', 'Strategy'];
const byId = (id: string): Preset | undefined => PRESETS.find((p) => p.id === id);
// convert a preset's declarative filters+flags into FilterBuilder state
function presetFilters(p: Preset): Filter[] {
  const out: Filter[] = [];
  for (const fl of p.flags || []) out.push({ kind: 'flag', field: fl, on: true });
  for (const f of p.filters || []) out.push({ kind: 'num', field: f.field, op: f.op, a: f.a, b: f.b });
  return out;
}

export default function Screener({ demo, hasAi }: { demo: boolean; hasAi: boolean }) {
  const [data, setData] = useState<Payload | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    fetch('/screener-data.json')
      .then((r) => r.json())
      .then((d: Payload) => setData(d))
      .catch(() => setErr(true));
  }, []);

  if (err) return <div class="loading err">Couldn’t load screener data — try again after the next daily run.</div>;
  if (!data) return <div class="loading"><span class="pulse" aria-hidden="true"></span>Loading the universe…</div>;
  return <Board data={data} />;
}

function Board({ data }: { data: Payload }) {
  const rows = useMemo(() => (data.stocks || [])
    .filter((r) => r && r.symbol)
    .map((r) => (r.fii == null && r.dii == null) ? r : { ...r, fii_dii: (r.fii ?? 0) + (r.dii ?? 0) }), [data]);

  const defPreset = byId(DEFAULT_PRESET)!;
  const [preset, setPreset] = useState(DEFAULT_PRESET);
  const [weights, setWeights] = useState<Weights>(() => ({ ...(defPreset.weights || eqWeights()) }));
  const [filters, setFilters] = useState<Filter[]>(() => presetFilters(defPreset));
  const [sorting, setSorting] = useState<SortingState>(() => [{ id: defPreset.sort!.id, desc: defPreset.sort!.desc }]);
  const [watch, setWatch] = useState<Set<string>>(new Set());
  const [showSector, setShowSector] = useState(false);
  const [topOnly, setTopOnly] = useState(true);

  // apply a preset: set weights (if any), filters+flags, and sort together
  const applyPreset = useCallback((id: string) => {
    const p = byId(id);
    if (!p) return;
    setPreset(id);
    if (p.weights) setWeights({ ...p.weights });
    setFilters(presetFilters(p));
    if (p.sort) setSorting([{ id: p.sort.id, desc: p.sort.desc }]);
  }, []);

  // ---- URL state (shareable) ----
  useEffect(() => {
    const u = new URLSearchParams(location.search);
    if (u.get('p') && byId(u.get('p')!)) { applyPreset(u.get('p')!); }
    if (u.get('w')) {
      const parts = u.get('w')!.split(',').map(Number);
      const w = eqWeights();
      SUBS.forEach((s, i) => { if (isFinite(parts[i])) w[s.key] = parts[i]; });
      setWeights(w);
      setPreset('custom');
    }
    if (u.get('s')) {
      const [id, dir] = u.get('s')!.split(':');
      if (id) setSorting([{ id, desc: dir !== 'asc' }]);
    }
    if (u.get('f')) {
      try { setFilters(JSON.parse(decodeURIComponent(u.get('f')!))); } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    const u = new URLSearchParams();
    if (preset && preset !== 'custom') u.set('p', preset);
    u.set('w', SUBS.map((s) => weights[s.key]).join(','));
    if (sorting[0]) u.set('s', sorting[0].id + ':' + (sorting[0].desc ? 'desc' : 'asc'));
    if (filters.length) u.set('f', encodeURIComponent(JSON.stringify(filters)));
    history.replaceState(null, '', '?' + u.toString());
  }, [preset, weights, sorting, filters]);

  const derived = useCallback((r: StockRow) => composite(r, weights), [weights]);

  // ---- filtered + augmented rows ----
  const view = useMemo(() => {
    const aug = rows.map((r) => ({
      row: r,
      composite: derived(r),
      aftertax_1y: aftertax1y(r),
    }));
    const filtered = aug.filter((a) => passes(a.row, filters, a.composite, a.aftertax_1y));
    const s = sorting[0];
    if (s) {
      const dir = s.desc ? -1 : 1;
      filtered.sort((a, b) => {
        const va = cellVal(a, s.id), vb = cellVal(b, s.id);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return dir * va.localeCompare(vb as string);
        return dir * ((va as number) - (vb as number));
      });
    }
    return filtered;
  }, [rows, derived, filters, sorting]);

  const shown = useMemo(() => (topOnly ? view.slice(0, TOP_N) : view), [view, topOnly]);

  const onWeights = (w: Weights) => { setWeights(w); setPreset('custom'); };

  const toggleWatch = (sym: string) => setWatch((prev) => {
    const n = new Set(prev);
    n.has(sym) ? n.delete(sym) : n.add(sym);
    return n;
  });

  const reset = () => applyPreset(DEFAULT_PRESET);
  const share = async () => {
    try { await navigator.clipboard.writeText(location.href); } catch { /* address bar has it */ }
  };

  const activePreset = byId(preset);
  const nz = normalise(weights);

  return (
    <div class="scr">
      {data.__demo && (
        <div class="demo-banner" role="status">
          <span class="pulse" aria-hidden="true"></span>
          <b>Demo data.</b> The daily pipeline hasn’t published <code>nifty_all_metrics.json</code> yet —
          numbers are illustrative. Every control below is fully live; real figures land on the next run.
        </div>
      )}

      {data.ai && <AiCard ai={data.ai} rows={rows} weights={weights} />}

      {/* PRESET picker — grouped scans (filters + sort) */}
      <section class="profiles">
        <div class="phead">
          <h2>Presets — scans</h2>
          <span class="pct-hint">each sets filters + sort; surfaces the top {TOP_N} — narrow to your 5</span>
        </div>
        {PRESET_GROUPS.map((g) => (
          <div class="preset-group" key={g}>
            <span class="pg-label">{g}</span>
            <div class="profile-row">
              {PRESETS.filter((p) => p.group === g).map((p) => (
                <button
                  key={p.id}
                  class={'profile-chip' + (preset === p.id ? ' active' : '') + (p.flagship ? ' flagship' : '')}
                  onClick={() => applyPreset(p.id)}
                  aria-pressed={preset === p.id}
                >
                  {p.flagship && <span class="star" aria-hidden="true">★</span>}
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        ))}
        {preset === 'custom' && <div class="profile-row"><span class="profile-chip active custom">Custom mix</span></div>}
        <p class="profile-blurb">{preset === 'custom' ? 'Your own score weighting — the factor sliders drive the composite ranking live.' : activePreset?.blurb}</p>
      </section>

      <div class="grid">
        <aside class="controls">
          <FundamentalSliders filters={filters} setFilters={setFilters} />
          <details class="adv-filter">
            <summary>Advanced filter builder</summary>
            <FilterBuilder filters={filters} setFilters={setFilters} />
          </details>
          <WeightPanel
            weights={weights} normalised={nz} colors={FACTOR_COLOR}
            onChange={onWeights} onEqual={() => onWeights(eqWeights())}
          />
          <div class="panel actions">
            <button class="btn ghost" onClick={reset}>reset</button>
            <button class="btn" onClick={share}>share screen ↗</button>
          </div>
        </aside>

        <section class="results">
          <div class="results-bar">
            <div class="count">
              <b>{shown.length.toLocaleString('en-IN')}</b>
              {topOnly && view.length > TOP_N ? <> of top {TOP_N}</> : <> of {view.length.toLocaleString('en-IN')}</>}
              {' '}({rows.length.toLocaleString('en-IN')} total)
            </div>
            <div class="rb-actions">
              <button class={'mini' + (topOnly ? ' on' : '')} onClick={() => setTopOnly((t) => !t)}>top {TOP_N}</button>
              <button class={'mini' + (showSector ? ' on' : '')} onClick={() => setShowSector((s) => !s)}>sector view</button>
              <button class="mini" onClick={() => exportCsv(shown, weights)}>export CSV</button>
            </div>
          </div>
          <Grid
            view={shown} weights={weights} sorting={sorting} setSorting={setSorting}
            watch={watch} toggleWatch={toggleWatch}
          />
        </section>
      </div>

      {showSector && <SectorView rows={rows} derived={derived} />}

      <Compare rows={rows} watch={watch} weights={weights} clear={() => setWatch(new Set())} toggleWatch={toggleWatch} />
    </div>
  );
}

// value used for sorting a given column id
function cellVal(a: { row: StockRow; composite: number | null; aftertax_1y: number | null }, id: string) {
  if (id === 'composite') return a.composite;
  if (id === 'aftertax_1y') return a.aftertax_1y;
  if (id === 'symbol') return a.row.symbol;
  if (id === 'sector') return a.row.sector ?? '';
  if (id === 'consensus') return a.row.consensus ?? null;
  if (id === 'fii_dii') {
    const r = a.row;
    return (r.fii == null && r.dii == null) ? null : (r.fii ?? 0) + (r.dii ?? 0);
  }
  const v = a.row[id];
  return typeof v === 'number' ? v : null;
}

// ------------------------------------------------------------------ GRID ---
interface Aug { row: StockRow; composite: number | null; aftertax_1y: number | null }

function Grid({
  view, weights, sorting, setSorting, watch, toggleWatch,
}: {
  view: Aug[]; weights: Record<SubKey, number>; sorting: SortingState;
  setSorting: (s: SortingState) => void; watch: Set<string>; toggleWatch: (s: string) => void;
}) {
  const parentRef = useRef<HTMLDivElement>(null);

  // heat domain: 95th-percentile of |composite| over the view, so a single
  // garbage outlier (bad data) doesn't flatten every other bar to nothing.
  const heatMax = useMemo(() => {
    const abs = view.map((a) => (a.composite != null ? Math.abs(a.composite) : 0)).filter((x) => x > 0).sort((a, b) => a - b);
    if (!abs.length) return 1;
    const p95 = abs[Math.floor(abs.length * 0.95)] ?? abs[abs.length - 1];
    return Math.max(0.5, p95);
  }, [view]);

  const columns = useMemo<ColumnDef<Aug>[]>(() => {
    const cols: ColumnDef<Aug>[] = [
      {
        id: 'composite', header: 'Return-potential rank', size: 260,
        accessorFn: (a) => a.composite,
        cell: ({ row, table }) => {
          const a = row.original;
          const rank = table.getSortedRowModel().rows.findIndex((r) => r.id === row.id) + 1;
          return <HeatBar rank={rank} value={a.composite} max={heatMax} drivers={drivers(a.row, weights)} />;
        },
      },
      {
        id: 'symbol', header: 'Stock', size: 150,
        accessorFn: (a) => a.row.symbol,
        cell: ({ row }) => {
          const r = row.original.row;
          const sym = r.symbol;
          const on = watch.has(sym);
          return (
            <div class="sym-cell">
              <button class={'star-btn' + (on ? ' on' : '')} aria-label="watchlist" onClick={(e) => { e.stopPropagation(); toggleWatch(sym); }}>{on ? '★' : '☆'}</button>
              <div class="sym-txt">
                <div class="sym">{sym}{r.mtf_eligible && <span class="tag-mtf" title="F&O / MTF-eligible">MTF</span>}{r.n500 && <span class="tag-n500" title="Nifty 500 member">500</span>}</div>
                <div class="sym-name">{r.name || ''}</div>
              </div>
            </div>
          );
        },
      },
      ...COLS.filter((c) => c.key !== 'symbol').map(colDef),
    ];
    return cols;
  }, [heatMax, weights, watch]);

  const table = useReactTable({
    data: view, columns, state: { sorting },
    onSortingChange: (u) => setSorting(typeof u === 'function' ? u(sorting) : u),
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true, // we pre-sort `view`
  });

  const sortedRows = table.getRowModel().rows;
  const rowVirt = useVirtualizer({
    count: sortedRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 46,
    overscan: 12,
  });
  const items = rowVirt.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBot = items.length ? rowVirt.getTotalSize() - items[items.length - 1].end : 0;

  return (
    <div class="table-scroll" ref={parentRef}>
      <table class="stable">
        <thead>
          <tr>
            {table.getHeaderGroups()[0].headers.map((h) => {
              const col = h.column.columnDef;
              const canSort = h.column.getCanSort();
              const dir = h.column.getIsSorted();
              const isText = (col as { meta?: { text?: boolean } }).meta?.text;
              return (
                <th key={h.id} class={(isText ? 'th-text ' : '') + (h.column.id === 'composite' ? 'th-hero' : '')} style={{ width: h.getSize() }}>
                  <button class={'sort-btn' + (dir ? ' active' : '')} onClick={h.column.getToggleSortingHandler()} disabled={!canSort}>
                    {flexRender(col.header, h.getContext())}
                    {dir === 'desc' ? ' ↓' : dir === 'asc' ? ' ↑' : ''}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {padTop > 0 && <tr style={{ height: padTop }}><td colSpan={columns.length}></td></tr>}
          {items.map((vi) => {
            const row = sortedRows[vi.index];
            return (
              <tr key={row.id} data-index={vi.index} ref={(n) => n && rowVirt.measureElement(n)}>
                {row.getVisibleCells().map((cell) => {
                  const meta = (cell.column.columnDef as { meta?: { text?: boolean; cls?: string } }).meta;
                  return (
                    <td key={cell.id} class={(meta?.text ? 'td-text ' : '') + (cell.column.id === 'composite' ? 'td-hero ' : '') + (meta?.cls || '')}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {padBot > 0 && <tr style={{ height: padBot }}><td colSpan={columns.length}></td></tr>}
        </tbody>
      </table>
      {!sortedRows.length && <div class="empty">No stocks match — loosen a filter.</div>}
    </div>
  );
}

function colDef(c: Col): ColumnDef<Aug> {
  const text = c.fmt === 'text';
  return {
    id: c.key,
    header: c.label,
    size: text ? 130 : 96,
    enableSorting: true,
    meta: { text, cls: colorCls(c.key) },
    accessorFn: (a) => (a.row[c.key] as number | string | undefined) ?? null,
    cell: ({ getValue }) => {
      const v = getValue();
      if (c.key === 'consensus') {
        const s = v ? String(v) : '—';
        return <span class={'rating r-' + s.toLowerCase().replace(/[^a-z]/g, '')}>{s}</span>;
      }
      const out = FMT[c.fmt](v ?? undefined);
      if (colorCls(c.key) === 'signed' && typeof v === 'number') {
        return <span title={c.help} style={{ color: v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--dim)' }}>{out}</span>;
      }
      return <span title={c.help}>{out}</span>;
    },
  };
}
function colorCls(key: string): string {
  if (['mtf_net_1y', 'r_1y', 'r_1m', 'eps_growth', 'rev_growth', 'upside_pct'].includes(key)) return 'signed';
  return '';
}

// ---------------------------------------------------------------- SECTOR ---
function SectorView({ rows, derived }: { rows: StockRow[]; derived: (r: StockRow) => number | null }) {
  const secs = useMemo(() => {
    const by: Record<string, StockRow[]> = {};
    for (const r of rows) (by[r.sector || '—'] ||= []).push(r);
    const med = (arr: (number | null)[]) => {
      const v = arr.filter((x): x is number => x != null).sort((a, b) => a - b);
      return v.length ? v[Math.floor(v.length / 2)] : null;
    };
    return Object.entries(by)
      .filter(([, a]) => a.length >= 4)
      .map(([s, a]) => {
        const cq = a.filter((r) => r.quality_flag).sort((x, y) => (derived(y) ?? -9) - (derived(x) ?? -9))[0];
        return {
          sector: s, n: a.length,
          comp: med(a.map(derived)),
          pe: med(a.map((r) => r.pe ?? null)),
          roe: med(a.map((r) => r.roe ?? null)),
          r1y: med(a.map((r) => r.r_1y ?? null)),
          top: cq?.symbol,
        };
      })
      .sort((a, b) => (b.comp ?? -9) - (a.comp ?? -9));
  }, [rows, derived]);

  return (
    <section class="panel sector-panel">
      <h2>Sector view — median metrics + strongest name</h2>
      <div class="table-scroll static">
        <table class="stable sector-table">
          <thead><tr><th class="th-text">Sector</th><th>n</th><th>Med composite</th><th>Med PE</th><th>Med ROE %</th><th>Med 1Y %</th><th class="th-text">Top quality name</th></tr></thead>
          <tbody>
            {secs.map((s) => (
              <tr key={s.sector}>
                <td class="td-text sec-name">{s.sector}</td>
                <td>{s.n}</td>
                <td><span class="zval" style={{ color: heatColor(s.comp ?? 0) }}>{FMT.z(s.comp ?? undefined)}</span></td>
                <td>{FMT.x(s.pe ?? undefined)}</td>
                <td>{FMT.n1(s.roe ?? undefined)}</td>
                <td class="signed">{FMT.n1(s.r1y ?? undefined)}</td>
                <td class="td-text sym">{s.top || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p class="note">Median across sector members (n≥4). “Top quality name” = highest-composite stock passing the quality flag.</p>
    </section>
  );
}

// ------------------------------------------------------------------ AI ------
function AiCard({ ai, rows, weights }: { ai: NonNullable<Payload['ai']>; rows: StockRow[]; weights: Record<SubKey, number> }) {
  const bySym = useMemo(() => {
    const m: Record<string, StockRow> = {};
    for (const r of rows) m[r.symbol] = r;
    return m;
  }, [rows]);
  const scanLabel = (id: string) => byId(id)?.label ?? id;
  return (
    <section class="panel ai-card">
      <div class="ai-head">
        <h2>AI read</h2>
        <span class="ai-tag">{ai.disclaimer || 'AI-generated · not investment advice'}</span>
      </div>
      {ai.daily && <p class="ai-daily">{ai.daily}</p>}
      {ai.stocks?.length ? (
        <ul class="ai-picks">
          {ai.stocks.slice(0, 10).map((p) => {
            const r = bySym[p.symbol];
            const scans = r ? scanMembership(r) : [];
            return (
              <li key={p.symbol}>
                <b>{p.symbol}</b> {p.why_cheap && <span>{p.why_cheap}</span>}
                {p.key_risk && <span class="ai-risk"> Risk: {p.key_risk}</span>}
                {scans.length > 0 && (
                  <span class="ai-scans"> Passes: {scans.map(scanLabel).join(', ')}</span>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

// heat color helper shared with HeatBar
export function heatColor(v: number): string {
  if (v == null) return 'var(--dimmer)';
  if (v >= 0.6) return 'var(--heat-hi)';
  if (v >= 0.15) return 'var(--heat-hi-2)';
  if (v > -0.15) return 'var(--heat-mid)';
  return 'var(--heat-lo)';
}

// ------------------------------------------------------------------ CSV -----
function exportCsv(view: Aug[], weights: Record<SubKey, number>) {
  const keys = ['symbol', 'sector', 'composite', ...COLS.filter((c) => c.key !== 'symbol' && c.key !== 'sector').map((c) => c.key), 'aftertax_1y'];
  const head = keys.join(',');
  const lines = [head];
  for (const a of view) {
    const cells = keys.map((k) => {
      let v: unknown;
      if (k === 'composite') v = a.composite;
      else if (k === 'aftertax_1y') v = a.aftertax_1y;
      else v = a.row[k];
      if (v == null) return '';
      return typeof v === 'string' ? `"${v.replace(/"/g, '""')}"` : v;
    });
    lines.push(cells.join(','));
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = 'nifty-screen.csv'; link.click();
  URL.revokeObjectURL(url);
}
