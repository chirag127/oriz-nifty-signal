"""Composite value score for Nifty 500 — NSE Nifty500 Value 50 style multi-factor.

PRIMARY RANK = a multi-factor VALUE composite: the equal-weight cross-sectional
z-score of every cheapness factor the best keyless source exposes, higher =
cheaper. Per stock the composite averages over the factors it HAS (missing a
factor => averaged over the rest).

  E/P     = 1/PE      earnings-to-price
  B/P     = 1/PB      book-to-price
  S/P     = 1/PS      sales-to-price
  EBIT/EV = 1/evebit  operating-earnings-to-enterprise-value (cap-structure-neutral)
  DivYld  = divYield  dividend yield

A factor only counts when its ratio is valid + positive (PE/PB/PS/evebit > 0,
divYield >= 0) — loss-makers / negative-book names never score "cheap".

FACTORS OMITTED (no keyless source exposes them cleanly — verified 2026-08-13
against RELIANCE/HDFCBANK; every field-name variant returned empty on Tickertape
screener, and Screener.in's keyless page lacks them too): EV/EBITDA proper,
FCF yield / P-FCF, PEG. EV/EBIT (`evebit`) stands in for the EV-cheapness factor.

QUALITY (separate — NOT in the value rank): ROE, ROCE shown as columns + a
`quality` flag (ROE > 15% & ROCE > 15%). Debt/Equity omitted (not keyless).
`vq_score` = value_score + quality tilt, exposed as a SECONDARY combined rank so
the user can spot genuine value vs value-traps; PRIMARY rank stays pure value.

DATA SOURCE (chosen 2026-08-13): Tickertape keyless `screener/query` POST — best
keyless bulk source. One paginated sweep (~12 calls) returns pe/pb/ps/roe/roce/
evebit/divYield for the whole ~5.8k universe, verified accurate on RELIANCE +
HDFCBANK. Screener.in rejected: keyless page exposes only P/E, ROCE, ROE,
DivYield (no PS/PB/EV) and needs 500 per-stock fetches (heavy, rate-limited).

Two keyless JSON sources (VERIFIED 2026-08-13, httpx):
- Nifty 500 constituents CSV: nsearchives.nseindia.com — column Symbol.
- Per-stock ratios: api.tickertape.in/screener/query POST — stock.info.ticker
  (== NSE Symbol) + stock.advancedRatios.{pe,pb,ps,roe,roce,evebit,divYield}.
"""

from __future__ import annotations

import csv
import io
import logging
import math

from ..util import fetch_text, fetch_json_post

log = logging.getLogger("nifty_signal")

NSE_500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
SCREENER_URL = "https://api.tickertape.in/screener/query"
_REFERER = "https://www.tickertape.in/"

# value factors in the composite rank. "inv" => yield = 1/ratio (positive-only);
# "raw" => used as-is (already a yield). Each equal-weight in the z-score mean.
_VALUE_FACTORS = {"pe": "inv", "pb": "inv", "ps": "inv", "evebit": "inv", "divYield": "raw"}
_QUALITY = ("roe", "roce")  # display + flag, NOT ranked
_ALL_FIELDS = list(_VALUE_FACTORS) + list(_QUALITY)


def _nifty500_symbols() -> set[str]:
    text = fetch_text(NSE_500_CSV)
    rows = csv.DictReader(io.StringIO(text))
    syms = {(r.get("Symbol") or "").strip() for r in rows}
    syms.discard("")
    if len(syms) < 400:
        raise ValueError(f"nifty500 csv: only {len(syms)} symbols")
    return syms


def _ratios_by_ticker() -> dict[str, dict[str, float | None]]:
    """Ticker -> ratio dict across the full Tickertape universe. Best-effort per
    page: a failed page is skipped, not fatal, so a partial fetch still scores."""
    out: dict[str, dict[str, float | None]] = {}
    for offset in range(0, 6000, 500):
        body = {
            "match": {}, "sortBy": "mrktCapf", "sortOrder": -1,
            "project": _ALL_FIELDS, "offset": offset, "count": 500,
            "sids": [], "universe": "AllStocks",
        }
        try:
            data = fetch_json_post(SCREENER_URL, body, referer=_REFERER).get("data", {})
        except Exception as e:  # noqa: BLE001 — resilient: skip bad page
            log.warning("screener page offset=%d failed: %s", offset, e)
            continue
        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            break
        for x in results:
            stock = x.get("stock", {})
            ticker = stock.get("info", {}).get("ticker")
            if ticker:
                ar = stock.get("advancedRatios", {})
                out[ticker] = {f: ar.get(f) for f in _ALL_FIELDS}
    if not out:
        raise ValueError("screener: empty universe")
    return out


def _zscores(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z-score over the provided values."""
    n = len(values)
    if n == 0:
        return {}
    mean = sum(values.values()) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values.values()) / n)
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: (v - mean) / sd for k, v in values.items()}


def _yield_for(field: str, mode: str, v: float | None) -> float | None:
    """Per-factor cheapness yield: 1/ratio for inv factors (positive-only), the
    raw value for raw factors (>=0)."""
    if v is None:
        return None
    if mode == "inv":
        return 1.0 / v if v > 0 else None
    return v if v >= 0 else None  # divYield


def _r(v: float | None, keep_neg: bool = False) -> float | None:
    if v is None:
        return None
    if not keep_neg and v <= 0:
        return None
    return round(v, 2)


def value_score_nifty500(top: int = 0) -> list[dict]:
    """Rank Nifty 500 by the multi-factor value composite (equal-weight z-score
    of E/P, B/P, S/P, EBIT/EV, DivYield). Descending — highest = cheapest overall.
    `top` <= 0 returns the full ranked list. Rows carry quality columns (roe,
    roce) + a `quality` flag (ROE>15% & ROCE>15%) + a secondary `vq_rank`
    (value+quality). PRIMARY `rank` is pure value."""
    syms = _nifty500_symbols()
    ratios = _ratios_by_ticker()
    universe = {t: ratios[t] for t in syms if t in ratios}

    # per-factor yields, then per-factor cross-sectional z-scores
    factor_yields: dict[str, dict[str, float]] = {f: {} for f in _VALUE_FACTORS}
    for t, r in universe.items():
        for f, mode in _VALUE_FACTORS.items():
            y = _yield_for(f, mode, r.get(f))
            if y is not None:
                factor_yields[f][t] = y
    zs = {f: _zscores(factor_yields[f]) for f in _VALUE_FACTORS}

    ranked: list[dict] = []
    for t, r in universe.items():
        fz = [zs[f][t] for f in _VALUE_FACTORS if t in zs[f]]
        if not fz:
            continue
        roe, roce = r.get("roe"), r.get("roce")
        quality = (roe is not None and roe > 15.0) and (roce is not None and roce > 15.0)
        vscore = sum(fz) / len(fz)
        ranked.append({
            "symbol": t,
            "pe": _r(r.get("pe")),
            "pb": _r(r.get("pb")),
            "ps": _r(r.get("ps")),
            "ev_ebit": _r(r.get("evebit"), keep_neg=True),
            "div_yield": _r(r.get("divYield"), keep_neg=True),
            "roe": _r(roe, keep_neg=True),
            "roce": _r(roce, keep_neg=True),
            "quality": quality,
            "value_score": round(vscore, 4),
            # combined: nudge value by a small quality bonus (+0.5 z if quality)
            "vq_score": round(vscore + (0.5 if quality else 0.0), 4),
        })

    ranked.sort(key=lambda x: x["value_score"], reverse=True)
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    for i, row in enumerate(sorted(ranked, key=lambda x: x["vq_score"], reverse=True), 1):
        row["vq_rank"] = i
    log.info("value_score: %d/%d nifty500 scored (>=1 valid value factor)", len(ranked), len(syms))
    return ranked[:top] if top and top > 0 else ranked
