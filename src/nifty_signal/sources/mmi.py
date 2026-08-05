"""MMI sentiment — Tickertape keyless JSON api.tickertape.in/mmi/now.

VERIFIED 2026-08-05 (httpx): {"data": {"indicator": 74.42, "nifty": 24624.65,
"date": "...", ...}}. Same source oriz-mmi uses. Contrarian input: high MMI
(greed) => low buy score, low MMI (fear) => high buy score.
"""

from __future__ import annotations

from ..models import Indicator
from ..util import fetch_json, score_mmi, zone_mmi
from .base import Source

URL = "https://api.tickertape.in/mmi/now"


def parse_mmi(data: dict) -> Indicator:
    ind = data.get("indicator")
    if ind is None:
        raise ValueError("mmi: no 'indicator' in payload")
    v = round(float(ind), 2)
    return Indicator(
        key="mmi",
        label="Market Mood (MMI)",
        value=v,
        unit="",
        zone=zone_mmi(v),
        score=round(score_mmi(v), 1),
        detail="contrarian: fear = buy, greed = caution",
        source="Tickertape MMI",
        as_of=str(data.get("date", "")),
    )


class MmiSource(Source):
    key = "mmi"
    url = URL

    def fetch(self) -> Indicator:
        payload = fetch_json(self.url, referer="https://www.tickertape.in/market-mood-index")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("mmi: unexpected payload (no 'data')")
        return parse_mmi(data)
