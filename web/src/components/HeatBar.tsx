import type { MetricGroup } from '../lib/scoring';

export const GROUP_COLOR: Record<MetricGroup, string> = {
  Valuation: 'var(--f-value)', Growth: 'var(--f-growth)', Quality: 'var(--f-quality)',
  Momentum: 'var(--f-momentum)', Health: 'var(--f-quality)',
  Ownership: 'var(--f-analyst)', Analyst: 'var(--f-analyst)',
};

// The signature nifty.oriz.in mark: a return-heat gauge. Rank badge on the left,
// a bar filling 0→100 (the weighted-percentile composite), the value, and a
// stacked driver micro-strip showing which metrics built the score.
export function HeatBar({
  rank, value, drivers,
}: {
  rank: number; value: number | null;
  drivers: { key: string; label: string; group: MetricGroup; contrib: number }[];
}) {
  const v = value ?? 0;
  const pct = Math.max(0, Math.min(100, v));
  const col = colorFor(v);
  const top = rank <= 3;
  const totalC = drivers.reduce((a, d) => a + Math.abs(d.contrib), 0) || 1;

  return (
    <div class="heat">
      <span class={'rank' + (top ? ' top' : '') + (rank <= 10 ? ' t10' : '')}>{rank}</span>
      <div class="heat-body">
        <div class="gauge" title={`return-potential composite ${value == null ? '—' : v.toFixed(0)}/100`}>
          <span class="fill" style={{ left: '0%', width: `${pct}%`, background: col }}></span>
        </div>
        <div class="drv" aria-hidden="true">
          {drivers.map((d) => (
            <span
              key={d.key}
              class="drv-seg"
              title={`${d.label}: ${d.contrib.toFixed(1)}`}
              style={{ width: `${(Math.abs(d.contrib) / totalC) * 100}%`, background: GROUP_COLOR[d.group] }}
            ></span>
          ))}
        </div>
      </div>
      <span class="zval" style={{ color: col }}>{value == null ? '—' : v.toFixed(0)}</span>
    </div>
  );
}

export function colorFor(v: number): string {
  if (v >= 75) return 'var(--heat-hi)';
  if (v >= 55) return 'var(--heat-hi-2)';
  if (v >= 40) return 'var(--heat-mid)';
  return 'var(--heat-lo)';
}
