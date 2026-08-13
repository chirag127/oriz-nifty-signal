"""Lowest-PE Nifty 500 — cheapest names by trailing P/E.

Two keyless JSON sources (VERIFIED 2026-08-13, httpx):
- Nifty 500 constituents CSV: nsearchives.nseindia.com — columns incl. Symbol.
- Per-stock trailing PE: api.tickertape.in/screener/query POST — each result has
  stock.info.ticker (== NSE Symbol) + stock.advancedRatios.pe.

Match Tickertape universe to the NSE 500 symbols by ticker, drop null/<=0 PE
(loss-making excluded), rank ascending, keep the cheapest `top`.
"""

from __future__ import annotations

import csv
import io
import logging

from ..util import fetch_text, fetch_json_post

log = logging.getLogger("nifty_signal")

NSE_500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
SCREENER_URL = "https://api.tickertape.in/screener/query"
_REFERER = "https://www.tickertape.in/"


def _nifty500_symbols() -> set[str]:
    text = fetch_text(NSE_500_CSV)
    rows = csv.DictReader(io.StringIO(text))
    syms = {(r.get("Symbol") or "").strip() for r in rows}
    syms.discard("")
    if len(syms) < 400:
        raise ValueError(f"nifty500 csv: only {len(syms)} symbols")
    return syms


def _pe_by_ticker() -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for offset in range(0, 6000, 500):
        body = {
            "match": {}, "sortBy": "mrktCapf", "sortOrder": -1,
            "project": ["pe"], "offset": offset, "count": 500,
            "sids": [], "universe": "AllStocks",
        }
        data = fetch_json_post(SCREENER_URL, body, referer=_REFERER).get("data", {})
        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            break
        for x in results:
            stock = x.get("stock", {})
            ticker = stock.get("info", {}).get("ticker")
            if ticker:
                out[ticker] = stock.get("advancedRatios", {}).get("pe")
    if not out:
        raise ValueError("screener: empty universe")
    return out


def lowest_pe_nifty500(top: int = 20) -> list[dict]:
    """Return the cheapest-by-PE Nifty 500 names, ascending positive PE."""
    syms = _nifty500_symbols()
    pe = _pe_by_ticker()
    ranked = sorted(
        (
            {"symbol": t, "pe": round(float(pe[t]), 2)}
            for t in syms
            if pe.get(t) is not None and pe[t] > 0
        ),
        key=lambda r: r["pe"],
    )
    log.info("lowest_pe: %d/%d nifty500 matched with positive PE", len(ranked), len(syms))
    return ranked[:top]
