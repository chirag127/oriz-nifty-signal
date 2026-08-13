"""Analyst ratings + price target — MoneyControl keyless mcapi (enrichment pass).

Tickertape's analyst forecast is Pro-locked (verified 2026-08-13: 403/locked on
screener fields + stock widget). MoneyControl's mcapi IS keyless + verified:
- symbol -> scId: moneycontrol.com/mccode/common/autosuggestion_solr.php
    (?query=<NSE symbol>&type=1&format=json) -> rows with sc_id + a display
    string "<ISIN>, <NSE symbol>, <BSE code>". Pick the row whose NSE symbol == query.
- analyst rating: api.moneycontrol.com/mcapi/v1/stock/estimates/analyst-rating
    ?scId=<scId>&ex=N&deviceType=W -> data.{ratings[{name,value}], finalRating, analystCount}
- price forecast: .../estimates/price-forecast?scId=...&ex=N -> data.{high,mean,low}

Verified on RELIANCE (RI: Buy, 31 analysts, target 1682) + HDFCBANK + TCS.

SCALE: mapping + 2 forecast calls per stock is ~3 requests/stock. The full ~5850
universe would be ~17k requests/run (rate-limit + quota risk), so this is an
ENRICHMENT pass over a SHORTLIST (top value/return-potential candidates, ~60),
same pattern as financials.py. No-coverage stocks return None (not penalised);
`analyst_count` lets the UI/AI say "cheap but no coverage" vs "28% upside".
"""

from __future__ import annotations

import logging
import re

from ..util import fetch_json

log = logging.getLogger("nifty_signal")

_SUGGEST = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
_MCAPI = "https://api.moneycontrol.com/mcapi/v1/stock/estimates"
# consensus label -> numeric (5=most bullish). Weighted mean => consensus score.
_RATING_WT = {"Buy": 5, "Outperform": 4, "Hold": 3, "Underperform": 2, "Sell": 1}


def _sc_id(symbol: str) -> str | None:
    """Resolve NSE `symbol` -> MoneyControl scId (exact NSE-symbol match)."""
    url = f"{_SUGGEST}?classic=true&query={symbol}&type=1&format=json"
    rows = fetch_json(url)
    if not isinstance(rows, list):
        return None
    for x in rows:
        disp = x.get("pdt_dis_nm", "")
        m = re.search(r"<span>([^,]+),\s*([^,]+),", disp)
        if m and m.group(2).strip() == symbol and x.get("sc_id"):
            return x["sc_id"]
    return None


def _consensus_score(ratings: list[dict]) -> float | None:
    """Analyst-count-weighted mean of the 5-bucket distribution -> 1..5."""
    num = den = 0.0
    for r in ratings:
        w = _RATING_WT.get(r.get("name"))
        try:
            c = float(r.get("value"))
        except (TypeError, ValueError):
            continue
        if w is not None:
            num += w * c
            den += c
    return round(num / den, 2) if den else None


def analyst(symbol: str, price: float | None = None) -> dict | None:
    """Analyst rating + target for one NSE `symbol`. None on no-coverage/failure.
    Returns {consensus, consensus_score, analyst_count, target, target_high,
    target_low, upside_pct} — upside only when `price` given."""
    try:
        sc = _sc_id(symbol)
    except Exception as e:  # noqa: BLE001 — resilient enrichment
        log.warning("mc sc_id failed sym=%s: %s", symbol, e)
        return None
    if not sc:
        return None

    out: dict = {}
    try:
        ar = fetch_json(f"{_MCAPI}/analyst-rating?scId={sc}&ex=N&deviceType=W").get("data", {})
        cnt = ar.get("analystCount")
        out["consensus"] = ar.get("finalRating")
        out["consensus_score"] = _consensus_score(ar.get("ratings", []))
        out["analyst_count"] = int(cnt) if str(cnt).isdigit() else None
    except Exception as e:  # noqa: BLE001
        log.warning("mc analyst-rating failed sym=%s: %s", symbol, e)

    try:
        pf = fetch_json(f"{_MCAPI}/price-forecast?scId={sc}&ex=N&deviceType=W").get("data", {})

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        tgt, hi, lo = num(pf.get("mean")), num(pf.get("high")), num(pf.get("low"))
        out["target"] = tgt
        out["target_high"] = hi
        out["target_low"] = lo
        if tgt is not None and isinstance(price, (int, float)) and price > 0:
            out["upside_pct"] = round((tgt - price) / price * 100.0, 2)
    except Exception as e:  # noqa: BLE001
        log.warning("mc price-forecast failed sym=%s: %s", symbol, e)

    return out or None


def enrich_many(symbols: list[str], prices: dict[str, float]) -> dict[str, dict]:
    """{symbol: analyst(...)} over `symbols`, fetched concurrently (12 workers —
    MoneyControl, gentler). Skips no-coverage/failed. Resilient partial results."""
    from ..util import map_concurrent
    return map_concurrent(lambda s: analyst(s, price=prices.get(s)), symbols, workers=12)
