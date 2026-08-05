"""Buffett indicator (India) — market cap / GDP %.

Source: ceicdata.com — server-rendered <meta description>, keyless. VERIFIED
2026-08-05 (httpx): "India Market Capitalization accounted for 137.4 % of its
Nominal GDP in Dec 2025 ...". CEIC reports this ANNUALLY, so the figure lags
(latest = prior year-end); `detail` flags that honestly. gurufocus (the usual
daily source) 403s from CI, so CEIC is the reliable free fallback.

Bands: <75 undervalued / 75-115 fair / >115 overvalued.
"""

from __future__ import annotations

import re

from ..models import Indicator
from ..util import fetch_text, score_buffett, zone_buffett
from .base import Source

_DESC_RE = re.compile(r'name="description"\s+content="([^"]+)"', re.I)
_PCT_RE = re.compile(r"accounted for\s+([0-9]+\.[0-9]+)\s*%", re.I)
_ASOF_RE = re.compile(r"\bin\s+([A-Za-z]+ [0-9]{4})", re.I)


class BuffettIndicator(Source):
    key = "buffett"
    url = "https://www.ceicdata.com/en/indicator/india/market-capitalization--nominal-gdp"

    def fetch(self) -> Indicator:
        html = fetch_text(self.url)
        m = _DESC_RE.search(html)
        blob = m.group(1) if m else html
        pct_m = _PCT_RE.search(blob)
        if not pct_m:
            raise ValueError("buffett: no market-cap/GDP % found")
        pct = float(pct_m.group(1))
        asof_m = _ASOF_RE.search(blob)
        as_of = asof_m.group(1) if asof_m else ""
        return Indicator(
            key="buffett",
            label="Buffett indicator",
            value=round(pct, 1),
            unit="%",
            zone=zone_buffett(pct),
            score=round(score_buffett(pct), 1),
            detail=f"mkt-cap/GDP, {as_of} (annual, lagging)" if as_of else "mkt-cap/GDP (annual)",
            source="CEIC",
            as_of=as_of,
        )
