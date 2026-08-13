"""Full-universe stock screener metrics — ~5850 NSE+BSE listed names.

One paginated keyless sweep of Tickertape `screener/query` (universe=AllStocks)
returns every field the site needs, then we compute per-factor cross-sectional
z-scores, the VALUE composite, a QUALITY sub-score + flag, and the flagship
"MTF Buy-and-Hold (1yr)" score ranked by AFTER-TAX after-interest 1Y return.

DATA SOURCE (VERIFIED 2026-08-13, httpx; UA + Referer tickertape.in):
- api.tickertape.in/screener/query POST, universe=AllStocks — ~5850 rows,
  stock.info.{ticker(==NSE symbol),name,sector} + stock.advancedRatios.<label>.
  Response nests results under data.data.results. stock.slug tail (after the
  final "-") is the Tickertape internal `sid` (e.g. .../...-RELI => "RELI") —
  REQUIRED for the financials.py enrichment fetch (which 404-empties on the NSE
  ticker). Every field below returned free (no premium 403) + verified on RELIANCE /
  HDFCBANK / TCS. `ftls` (F&O lot size) present == F&O-eligible == MTF-eligible
  proxy. Fields not exposed keyless (Piotroski YoY, promoter-pledge QoQ) are
  enriched separately (financials.py) or omitted + noted — never fabricated.
- nsearchives.nseindia.com ind_nifty500list.csv (Nifty-500 membership flag).

TICKERTAPE LABEL -> our short key (units verified: %, ratio, or Cr):
  apef PE · pbr PB · ps PS · evebitd EV/EBITDA · evebit EV/EBIT · evByRev EV/Sales
  evCafFcf EV/FCF · lcpCafFcf P/FCF · divDps DivYield% · ev EV(Cr) · mrktCapf mcap(Cr)
  roe ROE% · roce ROCE% · rtnAsts ROA% · pftMrg NetMargin% · aopm EBITDAMargin% · aroi ROI%
  rvng RevGrowth% · 5YrevChg Rev5YCAGR% · epsg EPSGrowth% · epsGwth EPS5YCAGR%
  dbtEqt D/E · ldbtEqt LTD/E · aint IntCover · qcur CurrentRatio · aqui QuickRatio
  strown Promoter% · forInstHldng FII% · domInstHldng DII% · instown MF% · retailHolding Retail% · promShrPled Pledge%
  pr1d 1D% · pr1w 1W% · 4wpct 1M% · 26wpct 6M% · 52wpct 1Y% · 5yCagrPct 5Yprice CAGR%
  52whd %from52WHigh · 52wld %from52WLow · beta Beta · 12mVol Volatility% · maxDrawdown 1YmaxLoss%
  ftls F&O lot(present=>MTF-eligible) · bookValue BV · faceValue FV · lastPrice price · acVol volume
  incEps EPS · incNinc NetIncome(Cr) · incTrev Revenue(Cr) · incEbi EBITDA(Cr) · balTdeb Debt · balTeq Equity · cafFcf FCF

VALUE composite = equal-weight mean of per-factor z-scores of the cheapness
yields (E/P=1/PE, B/P=1/PB, S/P=1/PS, EBITDA/EV=1/EV_EBITDA, FCF-yield=1/P_FCF,
1/PEG). Positive-only (loss-makers / negative-book never score cheap); missing
a factor => averaged over the rest. Div-yield stored + z-scored for re-weighting
but KEPT OUT of the core rank (tax-inefficient for this strategy).

MTF Buy-and-Hold (1yr) = ranked by AFTER-TAX after-interest expected 1Y return:
  net = gross_return% - MTF_INTEREST% - LTCG(12.5% on the positive gain net of
  interest). Restricted to F&O-eligible (MTF) + beta < BETA_CAP. See util-level
  constants below + on-site methodology.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from pathlib import Path

from ..util import (
    afetch_json_post,
    fetch_text,
    gather_bounded,
    run_async,
)

log = logging.getLogger("nifty_signal")

SCREENER_URL = "https://api.tickertape.in/screener/query"
NSE_500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
_REFERER = "https://www.tickertape.in/"

# async fetch tuning
_SWEEP_PAGE = 500          # rows per screener page
_SWEEP_END = 8000          # scan offsets up to here (universe ~5850)
_CONCURRENCY = 24          # in-flight keyless requests (16-32 band)
_CACHE = Path("data/.cache")   # per-symbol enrichment cache for resume

# tax / leverage assumptions for the MTF-1yr after-tax rank (see methodology)
MTF_INTEREST_PCT = 12.0   # annual MTF funding cost
LTCG_PCT = 12.5           # >12mo hold => LTCG 12.5%
BETA_CAP = 1.2            # MTF-buy-hold restricted to beta < this
Z_CLAMP = 3.0             # winsorize per-factor z-scores to +/-3 (robust composite)
VALUE_MIN_FACTORS = 2     # need >=2 value factors present to earn a value_score

# Tickertape label -> our short JSON key. Screener `project` accepts these labels;
# response `advancedRatios` echoes them back under the same key.
_FIELD_MAP: dict[str, str] = {
    # valuation
    "apef": "pe", "pbr": "pb", "ps": "ps", "evebitd": "ev_ebitda", "evebit": "ev_ebit",
    "evByRev": "ev_sales", "evCafFcf": "ev_fcf", "lcpCafFcf": "p_fcf", "divDps": "div_yield",
    "ev": "ev", "mrktCapf": "mcap",
    # quality
    "roe": "roe", "roce": "roce", "rtnAsts": "roa", "pftMrg": "net_margin",
    "aopm": "ebitda_margin", "aroi": "roi",
    # growth
    "rvng": "rev_growth", "5YrevChg": "rev_cagr_5y", "epsg": "eps_growth", "epsGwth": "eps_cagr_5y",
    # health
    "dbtEqt": "de", "ldbtEqt": "ltde", "aint": "int_cover", "qcur": "current_ratio", "aqui": "quick_ratio",
    # ownership
    "strown": "promoter", "forInstHldng": "fii", "domInstHldng": "dii",
    "instown": "mf", "retailHolding": "retail", "promShrPled": "pledge",
    # momentum / risk
    "pr1d": "r_1d", "pr1w": "r_1w", "4wpct": "r_1m", "26wpct": "r_6m", "52wpct": "r_1y",
    "5yCagrPct": "r_cagr_5y", "52whd": "off_52wh", "52wld": "off_52wl",
    "beta": "beta", "12mVol": "volatility", "maxDrawdown": "max_dd_1y",
    # meta / mtf / statement bits
    "ftls": "lot", "bookValue": "bv", "faceValue": "fv", "lastPrice": "price", "acVol": "volume",
    "incEps": "eps", "incNinc": "net_income", "incTrev": "revenue", "incEbi": "ebitda",
    "balTdeb": "debt", "balTeq": "equity", "cafFcf": "fcf",
}
_LABELS = list(_FIELD_MAP)

# VALUE composite factors: our key -> how to turn it into a cheapness yield.
# "inv" => 1/x (positive-only). "raw" => used as-is (already a yield, >=0).
_VALUE_FACTORS = {
    "ep": ("pe", "inv"),          # E/P
    "bp": ("pb", "inv"),          # B/P
    "sp": ("ps", "inv"),          # S/P
    "ebitda_ev": ("ev_ebitda", "inv"),
    "fcf_yield": ("p_fcf", "inv"),
    "inv_peg": ("peg", "inv"),    # peg added during enrich; 1/PEG
}
# div-yield z-scored for re-weighting but NOT in the default composite (tax drag)
_EXTRA_Z = {"dy": ("div_yield", "raw")}

# GROWTH catalyst factors (higher = better): our key -> raw metric, all "raw"
# (already growth %s). Averaged into a growth sub-score z.
_GROWTH_FACTORS = {"g_rev": "rev_growth", "g_eps": "eps_growth",
                   "g_rev5y": "rev_cagr_5y", "g_eps5y": "eps_cagr_5y"}
# MOMENTUM factors (higher = better, except off_52wh which is negative distance):
_MOMENTUM_FACTORS = {"m_3m": "r_1m", "m_6m": "r_6m", "m_1y": "r_1y", "m_52wh": "off_52wh"}

# RETURN-POTENTIAL composite weights (documented on-site). Value-led (cheap = room
# to re-rate), growth catalyst + quality (real, not a trap) equal, momentum
# (market agreeing) + analyst upside (direct return signal, but laggy/optimistic
# => modest) rounding it out. Sum = 1.0; renormalised over available sub-scores.
_RP_WEIGHTS = {"value": 0.30, "growth": 0.22, "quality": 0.22,
               "momentum": 0.16, "analyst": 0.10}


def _parse_page(data: dict | None) -> list[dict]:
    """Turn one screener page response into lean rows (symbol/name/sector + mapped
    fields). Bad/empty page => []."""
    inner = data.get("data", {}) if isinstance(data, dict) else {}
    results = inner.get("results", []) if isinstance(inner, dict) else []
    out: list[dict] = []
    for x in results:
        st = x.get("stock", {})
        info = st.get("info", {})
        ticker = info.get("ticker")
        if not ticker:
            continue
        ar = st.get("advancedRatios", {})
        slug = st.get("slug") or ""
        row = {"symbol": ticker, "name": info.get("name"), "sector": info.get("sector") or ar.get("sector"),
               "sid": slug.rsplit("-", 1)[-1] if "-" in slug else None}
        for label, key in _FIELD_MAP.items():
            row[key] = ar.get(label)
        out.append(row)
    return out


def _sweep() -> list[dict]:
    """Full AllStocks universe (~5850) via ASYNC sharded pagination — each offset
    page is one bounded-concurrency POST, so the whole universe fetches in a few
    round-trips instead of ~16 sequential calls. Per-page best-effort: a failed
    page yields None and is skipped (partial sweep still scores)."""
    offsets = list(range(0, _SWEEP_END, _SWEEP_PAGE))

    def page_fn(offset: int):
        body = {
            "match": {}, "sortBy": "mrktCapf", "sortOrder": -1,
            "project": _LABELS, "offset": offset, "count": _SWEEP_PAGE,
            "sids": [], "universe": "AllStocks",
        }
        return lambda client: afetch_json_post(client, SCREENER_URL, body, referer=_REFERER)

    pages = run_async(gather_bounded([page_fn(o) for o in offsets], concurrency=_CONCURRENCY))

    rows: list[dict] = []
    seen: set[str] = set()
    for data in pages:
        for row in _parse_page(data):
            if row["symbol"] in seen:
                continue
            seen.add(row["symbol"])
            rows.append(row)
    if not rows:
        raise ValueError("screener: empty universe")
    log.info("metrics sweep: %d stocks (async, concurrency=%d)", len(rows), _CONCURRENCY)
    return rows


def _nifty500_symbols() -> set[str]:
    try:
        text = fetch_text(NSE_500_CSV)
        syms = {(r.get("Symbol") or "").strip() for r in csv.DictReader(io.StringIO(text))}
        syms.discard("")
        return syms if len(syms) >= 400 else set()
    except Exception as e:  # noqa: BLE001
        log.warning("nifty500 csv failed: %s", e)
        return set()


def _zscores(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z, winsorized to +/-Z_CLAMP so a single fat-tail outlier
    (thin-coverage micro-cap) can't dominate the composite (standard robust
    multi-factor practice)."""
    n = len(values)
    if n == 0:
        return {}
    mean = sum(values.values()) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values.values()) / n)
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: max(-Z_CLAMP, min(Z_CLAMP, (v - mean) / sd)) for k, v in values.items()}


def _yield_of(row: dict, key: str, mode: str) -> float | None:
    v = row.get(key)
    if not isinstance(v, (int, float)):
        return None
    if mode == "inv":
        return 1.0 / v if v > 0 else None
    return float(v) if v >= 0 else None


def _peg(row: dict) -> float | None:
    """PEG = PE / EPS-growth% (positive-only)."""
    pe, g = row.get("pe"), row.get("eps_growth")
    if isinstance(pe, (int, float)) and pe > 0 and isinstance(g, (int, float)) and g > 0:
        return pe / g
    return None


def mtf_after_tax_return(gross_1y_pct: float | None) -> float | None:
    """After-interest, after-LTCG net 1Y return for a leveraged buy-and-hold.
    net = gross - MTF_INTEREST; if net>0, tax LTCG 12.5% on it. Loss stays as-is
    (no tax benefit modelled here). None when no 1Y return available."""
    if not isinstance(gross_1y_pct, (int, float)):
        return None
    net = gross_1y_pct - MTF_INTEREST_PCT
    if net > 0:
        net -= net * (LTCG_PCT / 100.0)
    return net


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if isinstance(v, (int, float)) else None


def _quality_stats(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """mean/sd for roe, roce, de (de inverted: lower=better)."""
    stats: dict[str, tuple[float, float]] = {}
    for key, invert in (("roe", False), ("roce", False), ("de", True)):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if invert:
            vals = [-v for v in vals]
        if not vals:
            continue
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) or 1.0
        stats[key] = (m, sd)
    return stats


def _sub_z(rows: list[dict], factors: dict[str, str]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Per-factor z (raw metrics, higher=better) + a per-stock mean sub-score."""
    fz: dict[str, dict[str, float]] = {}
    for fkey, metric in factors.items():
        vals = {r["symbol"]: r[metric] for r in rows if isinstance(r.get(metric), (int, float))}
        fz[fkey] = _zscores(vals)
    sub: dict[str, float] = {}
    for r in rows:
        s = r["symbol"]
        parts = [fz[f][s] for f in factors if s in fz[f]]
        if parts:
            sub[s] = sum(parts) / len(parts)
    return fz, sub


def compute(rows: list[dict]) -> list[dict]:
    """Attach PEG, per-factor z-scores, VALUE composite, growth/quality/momentum/
    analyst sub-scores, the flagship RETURN-POTENTIAL composite, quality flag, and
    the MTF-buy-hold after-tax fields to every row. Pure function over the swept
    rows (unit-tested with synthetic data)."""
    for row in rows:
        row["peg"] = _r(_peg(row))

    # value cheapness-yield z-scores (+ div-yield extra, kept out of core rank)
    factor_yields: dict[str, dict[str, float]] = {f: {} for f in {**_VALUE_FACTORS, **_EXTRA_Z}}
    for row in rows:
        s = row["symbol"]
        for f, (key, mode) in {**_VALUE_FACTORS, **_EXTRA_Z}.items():
            y = _yield_of(row, key, mode)
            if y is not None:
                factor_yields[f][s] = y
    zs = {f: _zscores(vals) for f, vals in factor_yields.items()}
    qstats = _quality_stats(rows)

    # growth + momentum sub-scores (raw-metric z-means) + quality/analyst sub-scores
    _gfz, growth_sub = _sub_z(rows, _GROWTH_FACTORS)
    _mfz, mom_sub = _sub_z(rows, _MOMENTUM_FACTORS)
    quality_sub = {r["symbol"]: q for r in rows if (q := _quality_score(r, qstats)) is not None}
    upside_vals = {r["symbol"]: r["upside_pct"] for r in rows if isinstance(r.get("upside_pct"), (int, float))}
    analyst_z = _zscores(upside_vals)

    for row in rows:
        s = row["symbol"]
        z: dict[str, float] = {}
        for f in {**_VALUE_FACTORS, **_EXTRA_Z}:
            if s in zs[f]:
                z[f] = round(zs[f][s], 3)
        row["z"] = z

        core = [z[f] for f in _VALUE_FACTORS if f in z]
        row["value_score"] = round(sum(core) / len(core), 4) if len(core) >= VALUE_MIN_FACTORS else None
        row["growth_score"] = _r(growth_sub.get(s), 4)
        row["quality_score"] = _r(quality_sub.get(s), 4)
        row["momentum_score"] = _r(mom_sub.get(s), 4)
        row["analyst_score"] = _r(analyst_z.get(s), 4)

        roe, de, f = row.get("roe"), row.get("de"), row.get("f_score")
        row["quality_flag"] = bool(
            isinstance(roe, (int, float)) and roe > 15
            and isinstance(de, (int, float)) and de < 1.5
            and (f is None or f >= 6)
        )
        row["mtf_eligible"] = row.get("lot") is not None
        row["mtf_net_1y"] = _r(mtf_after_tax_return(row.get("r_1y")))
        row["rp_score"] = _return_potential(row)

    _finalize_mtf_score(rows)
    return rows


def _return_potential(row: dict) -> float | None:
    """Flagship RETURN-POTENTIAL composite: weighted mean of value/growth/quality/
    momentum/analyst sub-scores (weights renormalised over the ones present).
    Loss-makers + no value signal => None (can't be a value re-rate candidate)."""
    if row.get("value_score") is None:
        return None
    subs = {"value": row.get("value_score"), "growth": row.get("growth_score"),
            "quality": row.get("quality_score"), "momentum": row.get("momentum_score"),
            "analyst": row.get("analyst_score")}
    num = den = 0.0
    for k, v in subs.items():
        if isinstance(v, (int, float)):
            num += _RP_WEIGHTS[k] * v
            den += _RP_WEIGHTS[k]
    return round(num / den, 4) if den else None


def _quality_score(row: dict, stats: dict[str, tuple[float, float]]) -> float | None:
    parts: list[float] = []
    for key, invert in (("roe", False), ("roce", False), ("de", True)):
        v = row.get(key)
        if isinstance(v, (int, float)) and key in stats:
            m, sd = stats[key]
            x = -v if invert else v
            parts.append((x - m) / sd)
    fs = row.get("f_score")
    if isinstance(fs, (int, float)):
        parts.append((fs - 4.5) / 2.0)  # centre 9-pt Piotroski on ~mid, ~2 sd
    return round(sum(parts) / len(parts), 4) if parts else None


def _finalize_mtf_score(rows: list[dict]) -> None:
    """Flagship MTF Buy-and-Hold (1yr) score = the RETURN-POTENTIAL composite,
    gated to MTF-eligible (F&O proxy) + beta < cap + non-loss quality. Non-
    eligible / value-trap => None. The site ranks this preset by rp_score with
    mtf_net_1y (after-tax after-interest 1Y return) shown alongside."""
    for row in rows:
        if not row.get("mtf_eligible"):
            row["mtf_score"] = None
            continue
        beta = row.get("beta")
        if isinstance(beta, (int, float)) and beta >= BETA_CAP:
            row["mtf_score"] = None
            continue
        # flagship MTF preset score = the return-potential composite (None => trap/no-signal)
        row["mtf_score"] = row.get("rp_score")


MIN_MCAP_CR = 500.0   # drop nano/micro-caps below Rs 500 Cr (illiquid, unreliable data)

def _investable_filter(rows: list[dict]) -> list[dict]:
    """Drop non-investable rows before scoring: tiny/illiquid micro-caps
    (mcap < MIN_MCAP_CR) and negative/zero PE or PB (loss-making / negative
    book — not value candidates). Keeps a row with a MISSING (None) mcap/pe/pb
    only if it isn't explicitly negative — missing != negative."""
    out: list[dict] = []
    for r in rows:
        mc = r.get("mcap")
        if isinstance(mc, (int, float)) and mc < MIN_MCAP_CR:
            continue
        pe = r.get("pe")
        if isinstance(pe, (int, float)) and pe <= 0:
            continue
        pb = r.get("pb")
        if isinstance(pb, (int, float)) and pb <= 0:
            continue
        out.append(r)
    log.info("investable filter: %d -> %d (mcap>=%.0fCr, PE>0, PB>0)", len(rows), len(out), MIN_MCAP_CR)
    return out


def all_metrics(enrich_top: int = 60) -> dict:
    """Full pipeline: sweep -> Piotroski-enrich the value leaders -> compute
    scores -> annotate membership flags. Returns the JSON payload dict.
    `enrich_top` per-stock enrichment fetches (financials: Piotroski/EV-EBITDA/PEG;
    analyst: MoneyControl consensus + target + upside) over the top candidates."""
    rows = _sweep()
    rows = _investable_filter(rows)
    n500 = _nifty500_symbols()
    by_sym = {r["symbol"]: r for r in rows}

    # rough value pre-rank -> financials shortlist (cheapest by 1/PE proxy)
    def cheap_key(r: dict) -> float:
        pe = r.get("pe")
        return (1.0 / pe) if isinstance(pe, (int, float)) and pe > 0 else -1e9
    fin_shortlist = [r["symbol"] for r in sorted(rows, key=cheap_key, reverse=True)[:enrich_top]]

    fin = _enrich(fin_shortlist, rows)
    for sym, f in fin.items():
        r = by_sym.get(sym)
        if not r:
            continue
        r["f_score"] = f.get("f_score")
        r["f_components_computed"] = f.get("f_components_computed")
        for k_src, k_dst in (("debt_to_equity", "de"), ("ev_ebitda", "ev_ebitda"),
                             ("p_fcf", "p_fcf"), ("fcf_yield", "fcf_yield"), ("peg", "peg"),
                             ("earnings_growth_pct", "eps_growth")):
            if r.get(k_dst) is None and f.get(k_src) is not None:
                r[k_dst] = f[k_src]

    # pass 1: provisional scores (no analyst yet) to pick the analyst shortlist.
    # TIERING: analyst coverage (MoneyControl) exists only for liquid large/mid
    # caps — spend the analyst budget on F&O-eligible / Nifty500 / large-mcap
    # names among the value+rp leaders; micro-cap tail is skipped (no coverage,
    # wasted requests). enrich_top from each of the value + rp rankings.
    compute(rows)

    def _covered(r: dict) -> bool:
        return bool(r.get("lot") is not None or r["symbol"] in n500
                    or (isinstance(r.get("mcap"), (int, float)) and r["mcap"] >= 2000))

    top_rp = [r["symbol"] for r in sorted((x for x in rows if x.get("rp_score") is not None and _covered(x)),
                                          key=lambda x: x["rp_score"], reverse=True)[:enrich_top]]
    top_val = [r["symbol"] for r in sorted((x for x in rows if x.get("value_score") is not None and _covered(x)),
                                           key=lambda x: x["value_score"], reverse=True)[:enrich_top]]
    an_shortlist = list(dict.fromkeys(top_rp + top_val))

    prices = {s: by_sym[s].get("price") for s in an_shortlist if s in by_sym}
    an = _enrich_analyst(an_shortlist, prices)
    for sym, a in an.items():
        r = by_sym.get(sym)
        if r:
            r.update({k: v for k, v in a.items() if v is not None})

    # pass 2: recompute so analyst upside folds into the return-potential composite
    compute(rows)

    for r in rows:
        r["n500"] = r["symbol"] in n500

    ranked_value = sorted((r for r in rows if r.get("value_score") is not None),
                          key=lambda r: r["value_score"], reverse=True)
    for i, r in enumerate(ranked_value, 1):
        r["value_rank"] = i
    ranked_rp = sorted((r for r in rows if r.get("rp_score") is not None),
                       key=lambda r: r["rp_score"], reverse=True)
    for i, r in enumerate(ranked_rp, 1):
        r["rp_rank"] = i
    ranked_mtf = sorted((r for r in rows if r.get("mtf_score") is not None),
                        key=lambda r: r["mtf_score"], reverse=True)
    for i, r in enumerate(ranked_mtf, 1):
        r["mtf_rank"] = i

    return {
        "stocks": [_lean(r) for r in rows],
        "count": len(rows),
        "mtf_eligible_count": sum(1 for r in rows if r.get("mtf_eligible")),
        "analyst_covered": sum(1 for r in rows if r.get("analyst_count")),
        "assumptions": {"mtf_interest_pct": MTF_INTEREST_PCT, "ltcg_pct": LTCG_PCT, "beta_cap": BETA_CAP},
        "value_factors": list(_VALUE_FACTORS),
        "z_factors": list({**_VALUE_FACTORS, **_EXTRA_Z}),
        "rp_weights": _RP_WEIGHTS,
    }


# keys kept as-is (bool/int/str/dict); every other numeric key rounded to 2dp.
_KEEP = {"symbol", "name", "sector", "z", "quality_flag", "mtf_eligible", "consensus",
         "n500", "value_rank", "mtf_rank", "rp_rank", "f_score", "f_components_computed",
         "analyst_count"}
_NUM4 = {"value_score", "quality_score", "growth_score", "momentum_score",
         "analyst_score", "rp_score", "mtf_score"}


def _lean(row: dict) -> dict:
    """Lean row for the shipped JSON: drop null/empty, round floats. Short keys
    already used throughout. `z` (per-factor z-scores) kept so the browser can
    re-weight the composite without refetching."""
    out: dict = {}
    for k, v in row.items():
        if k == "sid":
            continue
        if v is None or (k == "z" and not v):
            continue
        if k in _KEEP:
            out[k] = v
        elif isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = round(v, 4 if k in _NUM4 else 2)
        else:
            out[k] = v
    return out


def _enrich(sids: list[str], rows: list[dict]) -> dict[str, dict]:
    """Piotroski + refined ratios for the shortlist via financials.py (reused).
    Per-symbol disk cache (data/.cache/fin_<sid>.json) makes a re-run resume
    without re-fetching a stock already enriched this cycle."""
    try:
        from .financials import stock_financials
    except Exception as e:  # noqa: BLE001
        log.warning("financials import failed: %s", e)
        return {}
    by_sym = {r["symbol"]: r for r in rows}

    def compute_one(sym: str) -> dict | None:
        r = by_sym.get(sym, {})
        tsid = r.get("sid")
        if not tsid:
            return None
        return stock_financials(tsid, pe=r.get("pe"), mcap=r.get("mcap"), ev=r.get("ev"))

    return _cached_enrich("fin", sids, compute_one)


def _enrich_analyst(symbols: list[str], prices: dict[str, float | None]) -> dict[str, dict]:
    """Analyst rating + target + upside for the shortlist via analyst.py (reused).
    Per-symbol disk cache (data/.cache/an_<sid>.json) for resume."""
    try:
        from .analyst import analyst
    except Exception as e:  # noqa: BLE001
        log.warning("analyst import failed: %s", e)
        return {}

    def compute_one(sym: str) -> dict | None:
        return analyst(sym, price=prices.get(sym))

    return _cached_enrich("an", symbols, compute_one)


def _cached_enrich(prefix: str, sids: list[str], compute_one) -> dict[str, dict]:
    """Run `compute_one(sid)` over `sids` with a per-symbol JSON cache in
    data/.cache — a hit skips the network so an interrupted run resumes. Misses
    fetched concurrently (16 workers). Resilient: one bad sid never aborts."""
    from ..util import map_concurrent

    out: dict[str, dict] = {}
    misses: list[str] = []
    for sid in sids:
        c = _cache_read(prefix, sid)
        if c is not None:
            out[sid] = c
        else:
            misses.append(sid)

    fetched = map_concurrent(compute_one, misses, workers=16)
    for sid, val in fetched.items():
        _cache_write(prefix, sid, val)
        out[sid] = val
    return out


def _cache_read(prefix: str, sid: str) -> dict | None:
    f = _CACHE / f"{prefix}_{sid}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt cache => re-fetch
        return None


def _cache_write(prefix: str, sid: str, val: dict) -> None:
    try:
        _CACHE.mkdir(parents=True, exist_ok=True)
        (_CACHE / f"{prefix}_{sid}.json").write_text(
            json.dumps(val, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001 — cache is best-effort
        log.debug("cache write failed %s_%s: %s", prefix, sid, e)
