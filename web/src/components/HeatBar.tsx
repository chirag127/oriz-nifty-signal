import type { SubKey } from '../lib/scoring';

const FACTOR_COLOR: Record<string, string> = {
  value: 'var(--f-value)', growth: 'var(--f-growth)', quality: 'var(--f-quality)',
  momentum: 'var(--f-momentum)', analyst: 'var(--f-analyst)',
};

// The signature nifty.oriz.in mark: a diverging return-heat gauge. Rank badge
// on the left, a bar filling from a centre baseline (teal left = negative rp,
// amber-gold right = positive rp), the value, and a stacked driver micro-strip
// showing which factors built the score.
export function HeatBar({
  rank, value, max, drivers,
}: {
  rank: number; value: number | null; max: number;
  drivers: { key: SubKey; label: string; contrib: number }[];
}) {
  const v = value ?? 0;
  const frac = Math.max(-1, Math.min(1, v / (max || 1)));
  const pct = Math.abs(frac) * 50; // half-width max
  const pos = frac >= 0;
  const col = colorFor(v);
  const top = rank <= 3;

  // driver strip: proportional to |contrib|
  const totalC = drivers.reduce((a, d) => a + Math.abs(d.contrib), 0) || 1;

  return (
    <div class="heat">
      <span class={'rank' + (top ? ' top' : '') + (rank <= 10 ? ' t10' : '')}>{rank}</span>
      <div class="heat-body">
        <div class="gauge" title={`return-potential composite ${v >= 0 ? '+' : ''}${v.toFixed(2)}`}>
          <span class="axis" aria-hidden="true"></span>
          <span
            class="fill"
            style={{
              left: pos ? '50%' : `${50 - pct}%`,
              width: `${pct}%`,
              background: col,
            }}
          ></span>
        </div>
        <div class="drv" aria-hidden="true">
          {drivers.map((d) => (
            <span
              key={d.key}
              class="drv-seg"
              title={`${d.label}: ${d.contrib >= 0 ? '+' : ''}${d.contrib.toFixed(2)}`}
              style={{ width: `${(Math.abs(d.contrib) / totalC) * 100}%`, background: FACTOR_COLOR[d.key], opacity: d.contrib >= 0 ? 0.9 : 0.35 }}
            ></span>
          ))}
        </div>
      </div>
      <span class="zval" style={{ color: col }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}</span>
    </div>
  );
}

export function colorFor(v: number): string {
  if (v >= 0.6) return 'var(--heat-hi)';
  if (v >= 0.15) return 'var(--heat-hi-2)';
  if (v > -0.15) return 'var(--heat-mid)';
  return 'var(--heat-lo)';
}
