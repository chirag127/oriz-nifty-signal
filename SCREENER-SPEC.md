# oriz-nifty-signal → MTF Buy-and-Hold Stock Screener — FINAL consolidated spec

Repo: C:\g\ws\repos\own\oriz-nifty-signal (Python scraper, git-as-DB, GitHub Actions cron, Telegram/ntfy notify, Astro CF-Pages site at nifty.oriz.in). Fleet rules apply (minimum code, community packages, verify sources before scraping, tests, main-only commits, conventional commits).

## What we're building
Turn the site into a real **client-side stock screener** over the Nifty 500, tuned for the user's strategy: **MTF (leveraged) buy-and-hold for ~1 year, then churn (annual rebalance).** Backend-free: the daily GHA cron produces one big JSON; the site filters/sorts/re-ranks it in-browser.

## Data pipeline (Python, runs in existing scrape.yml cron)
Produce `data/nifty500_metrics.json` — one row per Nifty 500 stock with AS MANY fields as keyless sources expose. Verify every field name against known stocks (RELIANCE, HDFCBANK) before trusting.
Sources (merge by NSE symbol; use multiple): NSE Nifty 500 CSV (constituents) [confirmed: nsearchives.nseindia.com/content/indices/ind_nifty500list.csv]; Tickertape screener POST api.tickertape.in/screener/query (ratios); NSE F&O security list (F&O-eligible = MTF-eligible-with-high-funding proxy — keyless); Screener.in / others for financials + YoY (Piotroski) if reachable.
Fields to gather (omit + note any the sources truly lack; never fabricate):
- Valuation: PE, PB, PS, EV/EBITDA, EV/Sales, P/FCF, PEG, div yield, mcap, EV
- Quality: ROE, ROCE, ROA, net/op/gross margin, Piotroski F-score (9-pt; compute from YoY; note skipped components if data missing)
- Growth: revenue growth YoY + 3/5yr CAGR, EPS/profit growth
- Health: Debt/Equity, interest coverage, current ratio, promoter pledge %
- Ownership: promoter %, FII %, DII % (+ QoQ change if available)
- Momentum/risk: 1D/1W/1M/1Y (+3Y/5Y if available) returns, 52W-high distance, beta, volatility
- MTF: is_mtf_eligible (via F&O-list proxy), funding %/leverage if a keyless broker list is reachable
- Meta: name, sector, industry
Also store PER-FACTOR Z-SCORES (E/P, B/P, S/P, EBITDA/EV, FCF-yield, div-yield, 1/PEG) so the browser can re-weight the composite without refetching.

## Scoring (in the JSON)
- VALUE composite = equal-weight mean of the PERCENTILE ranks (0-100, higher=cheaper) of the 5 classic cheapness yields across the investable universe: E/P + B/P + S/P + EBITDA/EV + FCF-yield. Missing-factor-tolerant (avg over present, need ≥2); negative/zero earnings+book excluded per-factor; the investable filter already drops PE≤0/PB≤0/mcap<500Cr so loss-makers never score cheap. Div-yield percentile stored (`dy`) but KEPT OUT of the core rank (tax drag). Each factor's percentile stored in the row `z` object so the site can re-weight. Rank descending = cheapest.
- PRESET-BACKING fields (computed so site presets are exact): `graham_ok`/`graham_score` (Graham defensive: PE<15 & PB<1.5 & PE·PB<22.5 & D/E<1), `magic_rank`+`magic_ey_rank`+`magic_roce_rank` (Greenblatt Magic Formula, lower magic_rank=better), `f_score` (Piotroski, exposed as-is).
- QUALITY sub-score from ROE/ROCE/Piotroski/D-E (z-based, separate) + a quality flag (ROE>15 & D/E<1.5 & Piotroski>=6). Growth/momentum/analyst sub-scores stay z-based; only VALUE is percentile.
- "MTF Buy-and-Hold (1yr)" blended score = value + quality + reasonable momentum/growth, restricted to MTF-eligible + acceptable beta (<~1.2). This is the flagship ranking.

## Site (Astro, client-side, backend-free, bespoke to site identity)
- Loads nifty500_metrics.json, runs an interactive SCREENER in-browser:
  - Filter builder: any-metric numeric conditions (<,<=,>,>=,between), sector + mcap-tier + MTF-eligible filters, combinable (AND).
  - Sortable columns for every metric; **sort by the COMBINED VALUE COMPOSITE SCORE** (the differentiator Screener.in lacks) — default sort.
  - CUSTOM-WEIGHT sliders: user sets each factor's weight; composite + ranking recompute live from the stored per-factor z-scores.
  - PRESET queries (one-tap, tweakable): "MTF Buy-and-Hold (1yr)" [flagship], "Deep Value", "Quality Value", "Low PE+PB", "High FCF yield", "Value non-PSU".
  - Live result count; user picks their stocks. URL-encode the active query (shareable, client-side).
  - "MTF net-return sanity" column: 1Y return minus assumed MTF rate (~12%) so user sees if it clears interest.
- ON-SITE methodology docs (the source of truth, not just README): a prominent "How this works / Methodology" section or /methodology page explaining every metric (plain language + why it matters), the exact composite formula (equal-weight z-score, missing-value handling, loss-maker exclusion), the Piotroski 9-pt breakdown, value-vs-quality, the MTF-1yr strategy rationale (interest drag, margin-call risk, value-trap risk, LTCG >12mo = 12.5% vs 20% STCG → churn after 1yr), data sources + last-updated, and a clear "not investment advice / PSU-cyclical caveat" disclaimer.

## Automatic (hands-off)
scrape.yml cron (daily) → fetch all → score → write data/*.json (git-as-DB, rebase-before-push) → Telegram/ntfy sends daily top MTF-buy-hold + top value list → CF Pages auto-deploys from committed JSON. Resilient/best-effort: partial fetch still updates, doesn't fail the whole cron.

## Quality gates
pytest green (incl. composite z-score + Piotroski math with synthetic data). Astro build succeeds, screener + docs render in dist/. Commit conventional, rebase, push, trigger a test run, confirm data + site produced.

## UNIVERSE (updated): ALL Indian listed stocks (~5000 NSE + BSE), not just Nifty 500
- Constituents: NSE equity list (nsearchives.nseindia.com/content/equities/EQUITY_L.csv) + BSE list; ~5000 symbols. Fundamentals coverage thins on small/micro caps — that's fine, show what's available, flag data-completeness per stock.
- ~5000 rows is still client-side-filterable if the JSON is lean (numeric fields, short keys). Consider shipping a compact JSON (or gzipped) + lazy-render the table. Keep it fast.
- Keep a Nifty-500 (and index-membership) FILTER so the user can narrow to large-caps when wanted.

## TAX BURDEN (first-class dimension — user wants LOWEST tax)
For the MTF 1-year buy-and-hold strategy, compute + surface AFTER-TAX expected return, and document the tax logic on-site:
- Hold >12 months → LTCG 12.5% (vs STCG 20% if <12mo). The annual churn is already LTCG-optimal — reinforce in docs.
- LTCG exemption ₹1.25L/yr — note harvesting gains under the threshold.
- Dividends taxed at slab → high-div-yield = higher tax drag for this user → keep div-yield OUT of the core ranking (display only), and flag high-div names as tax-inefficient for this strategy.
- MTF interest deductibility note (may offset gains under business-income treatment) — surface as an informational note, not tax advice.
- Add an "after-tax 1Y return" helper column: (expected/1Y return − MTF interest ~12% − LTCG 12.5% on the gain). Rank the MTF-buy-hold preset by AFTER-TAX, after-interest return, not gross.
- Tax-loss-harvesting note: before annual churn, offset gains with losers.
- On-site docs: a clear tax section (LTCG vs STCG, exemption, dividend drag, interest deductibility, churn-after-12mo rationale) + "not tax advice" disclaimer.

## JSON schema (data contract) — `data/nifty_all_metrics.json`

Produced by `metrics.all_metrics()` + `pipeline.write_metrics()`. Compact (no whitespace) + a `.gz` sidecar. ~5842 rows, ~5.9 MB raw / ~1.4 MB gzip. Full run (async sweep + top-N enrichment) ≈ 15-18 s. Site loads this once, filters/re-ranks in-browser.

**Top level:**
```
{
  ts: ISO8601 build time,
  count: int (rows),
  mtf_eligible_count: int (F&O-eligible),
  analyst_covered: int (rows with analyst coverage),
  assumptions: {mtf_interest_pct:12.0, ltcg_pct:12.5, beta_cap:1.2},
  value_factors: ["ep","bp","sp","ebitda_ev","fcf_yield"],             // core VALUE composite factors (percentile-ranked)
  z_factors:     [...value_factors, "dy"],                              // all ranked factors (dy=div-yield, display-only, kept out of core)
  rp_weights: {value:0.30, growth:0.22, quality:0.22, momentum:0.16, analyst:0.10},
  ai: {                                     // keyless-AI block (cron-time, best-effort; ABSENT if LLM unreachable)
    ts: ISO8601, disclaimer: "AI-generated, not advice.",
    daily: "2-3 sentence market-context commentary",
    stocks: [{symbol, scans:[slug,...], why_cheap, key_risk}, ... flagship top-30 return-potential picks]
  },
  scan_labels: {graham:"Graham Defensive", magic_q1:"Magic Formula (top quartile)", piotroski8:"Piotroski 8-9", piotroski7:"Piotroski 7", garp:"GARP", quality:"Quality", deep_value:"Deep Value"},
  stocks: [ <row>, ... ]
}
```

**Row (`stocks[]`)** — lean: null/empty fields DROPPED, numerics rounded (scores 4dp, else 2dp). Data completeness varies (fundamentals thin on micro-caps — a missing key means the source lacked it, never fabricated).

| key | type | meaning |
|---|---|---|
| `symbol` `name` `sector` | str | NSE ticker (join key), company, sector |
| `pe` `pb` `ps` `ev_ebitda` `ev_ebit` `ev_sales` `ev_fcf` `p_fcf` `peg` `div_yield` `ev` `mcap` | num | valuation (ratios; ev/mcap in Cr; div_yield %) |
| `roe` `roce` `roa` `net_margin` `ebitda_margin` `roi` | num | quality % |
| `rev_growth` `rev_cagr_5y` `eps_growth` `eps_cagr_5y` | num | growth % (YoY + 5yr CAGR) |
| `de` `ltde` `int_cover` `current_ratio` `quick_ratio` `pledge` | num | health (D/E, LT-D/E, interest cover, ratios, promoter-pledge %) |
| `promoter` `fii` `dii` `mf` `retail` | num | ownership % |
| `r_1d` `r_1w` `r_1m` `r_6m` `r_1y` `r_cagr_5y` `off_52wh` `off_52wl` `beta` `volatility` `max_dd_1y` | num | momentum/risk (returns %, distance-from-52W %, beta, vol %, 1Y max drawdown %) |
| `bv` `fv` `price` `volume` `eps` `net_income` `revenue` `ebitda` `debt` `equity` `fcf` | num | meta + statement bits (Cr where applicable) |
| `lot` | int | F&O lot size — PRESENT ⇒ F&O-eligible ⇒ MTF-eligible proxy |
| `f_score` | int 0-9 | Piotroski (enriched shortlist only; YoY from financials.py) |
| `f_components_computed` | int | how many of the 9 F-score parts were computable |
| `consensus` | str | analyst rating (Buy/Outperform/Hold/…; enriched shortlist) |
| `consensus_score` | num 1-5 | analyst-count-weighted consensus |
| `analyst_count` | int | # analysts covering |
| `target` `target_high` `target_low` | num | analyst price targets |
| `upside_pct` | num | (target−price)/price ×100 |
| `z` | obj | per-factor VALUE **percentiles** 0-100 `{ep,bp,sp,ebitda_ev,fcf_yield,dy}` (present-only; higher=cheaper; `dy`=div-yield display-only) — **browser re-weights the composite from these without refetching** |
| `value_score` | num 0-100 | equal-weight mean of the present core value-factor percentiles (higher = cheaper); ≥2 factors required else absent |
| `graham_ok` | bool | classic Graham defensive: PE<15 & PB<1.5 & PE·PB<22.5 & D/E<1 (all four present + met) |
| `graham_score` | int 0-4 | how many of the four Graham rungs pass (present-tolerant; missing D/E fails that rung) |
| `magic_rank` | int | Greenblatt Magic Formula combined rank (lower=better); sum of the two component ranks, re-ranked 1..N |
| `magic_ey_rank` `magic_roce_rank` | int | component ranks: earnings-yield (EBIT/EV) and ROCE (rank 1 = best); both required else absent |
| `growth_score` `quality_score` `momentum_score` `analyst_score` | num | sub-score z-means (still z-based) |
| `rp_score` | num | flagship RETURN-POTENTIAL composite (rp_weights-weighted, renormalised over present subs) |
| `mtf_score` | num | rp_score GATED to F&O-eligible + beta<1.2 + non-loss (else absent) |
| `mtf_net_1y` | num | after-tax after-interest 1Y return: `r_1y − 12% − LTCG 12.5% on the positive net` |
| `quality_flag` | bool | ROE>15 & D/E<1.5 & (f_score≥6 or unknown) |
| `mtf_eligible` | bool | `lot` present |
| `scans` | str[] | named screens this stock passes (slugs; label map in top-level `scan_labels`): `graham`, `magic_q1` (Magic Formula top quartile), `piotroski8`/`piotroski7`, `garp`, `quality`, `deep_value` (value_score≥80) — site chips + AI narration ("passes Graham + Magic Formula + Piotroski 8") |
| `n500` | bool | Nifty-500 member (large-cap narrowing filter) |
| `value_rank` `rp_rank` `mtf_rank` | int | 1-based ranks (descending score) |

**Tiering / enrichment:** the async screener sweep gives ALL fields above for the full universe. Piotroski (`f_score`) + analyst (`consensus`/`target`/`upside_pct`) are per-stock enrichment (extra requests) run only over the top value/return-potential candidates that are liquid (F&O-eligible OR Nifty500 OR mcap≥2000 Cr) — micro-cap tail is skipped (no coverage). `enrich_top` (default 60) controls the shortlist size per ranking. Per-symbol disk cache under `data/.cache/{fin,an}_<sid>.json` makes an interrupted run resume without refetching.


