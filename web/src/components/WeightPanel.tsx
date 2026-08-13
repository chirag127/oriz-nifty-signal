import { SUBS, type SubKey } from '../lib/scoring';

type Weights = Record<SubKey, number>;

// Weight sliders that show each factor's NORMALISED share (% of influence, sums
// to 100) alongside the raw slider — so relative influence is always visible.
export function WeightPanel({
  weights, normalised, colors, onChange, onEqual,
}: {
  weights: Weights; normalised: Weights; colors: Record<SubKey, string>;
  onChange: (w: Weights) => void; onEqual: () => void;
}) {
  const set = (k: SubKey, v: number) => onChange({ ...weights, [k]: v });

  return (
    <section class="panel weights-panel">
      <div class="phead">
        <h2>Factor weights</h2>
        <button class="mini" onClick={onEqual}>equal</button>
      </div>

      {/* stacked influence bar — the normalized proportion, at a glance */}
      <div class="influence" role="img" aria-label="factor influence proportions">
        {SUBS.map((s) => normalised[s.key] > 0.5 && (
          <span
            key={s.key}
            class="inf-seg"
            style={{ width: `${normalised[s.key]}%`, background: colors[s.key] }}
            title={`${s.label}: ${normalised[s.key].toFixed(0)}%`}
          >
            {normalised[s.key] >= 10 ? `${Math.round(normalised[s.key])}%` : ''}
          </span>
        ))}
      </div>

      <div class="wgrid">
        {SUBS.map((s) => (
          <label class="wrow" key={s.key} title={s.hint}>
            <span class="wlab"><span class="wswatch" style={{ background: colors[s.key] }}></span>{s.label}</span>
            <input
              type="range" min="0" max="100" step="1"
              value={weights[s.key]}
              style={{ accentColor: colors[s.key] }}
              onInput={(e) => set(s.key, +(e.target as HTMLInputElement).value)}
              aria-label={`${s.label} weight`}
            />
            <span class="wpct">{normalised[s.key].toFixed(0)}%</span>
          </label>
        ))}
      </div>
      <p class="note">The composite recomputes live from each stock’s stored sub-scores — no refetch. Renormalised over the factors a stock actually has.</p>
    </section>
  );
}
