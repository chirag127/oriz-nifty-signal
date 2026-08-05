"""Nifty valuation — Nifty 50 PE (primary) + Nifty 500 PE vs median (breadth).

Source: indexpe.in — server-rendered, keyless. VERIFIED 2026-08-05 (httpx). Both
the current PE and its 5-yr median appear in the page <meta description> and
title, e.g. "Nifty 50 PE ratio is 20.91 as of August 2026, about 5% below its
5-year median of 22.08." Fallback for the Nifty 50 headline PE: nifty-pe-ratio.com
(value in <title>).
"""

from __future__ import annotations

import re

from ..models import Indicator
from ..util import (
    fetch_text,
    score_nifty_pe,
    score_vs_median,
    zone_nifty_pe,
    zone_vs_median,
)
from .base import Source

_DESC_RE = re.compile(r'name="description"\s+content="([^"]+)"', re.I)
_PE_RE = re.compile(r"PE ratio is\s+([0-9]+\.[0-9]+)", re.I)
_MEDIAN_RE = re.compile(r"median of\s+([0-9]+\.[0-9]+)", re.I)
_ASOF_RE = re.compile(r"as of\s+([A-Za-z]+ [0-9]{4})", re.I)


def _parse_indexpe(html: str) -> tuple[float, float | None, str]:
    """Return (pe, median|None, as_of) from an indexpe.in page."""
    m = _DESC_RE.search(html)
    blob = m.group(1) if m else html
    pe_m = _PE_RE.search(blob)
    if not pe_m:
        raise ValueError("indexpe: no PE found")
    pe = float(pe_m.group(1))
    med_m = _MEDIAN_RE.search(blob)
    asof_m = _ASOF_RE.search(blob)
    median = float(med_m.group(1)) if med_m else None
    return pe, median, (asof_m.group(1) if asof_m else "")


class Nifty50PE(Source):
    key = "nifty_pe"
    url = "https://indexpe.in/nifty-50"

    def fetch(self) -> Indicator:
        pe, median, as_of = _parse_indexpe(fetch_text(self.url))
        detail = f"vs {median:g} 5-yr median" if median else "cheap <18 / fair 18-22 / expensive 22-24 / frothy >24"
        return Indicator(
            key="nifty_pe",
            label="Nifty 50 PE",
            value=round(pe, 2),
            unit="x",
            zone=zone_nifty_pe(pe),
            score=round(score_nifty_pe(pe), 1),
            detail=detail,
            source="IndexPE",
            as_of=as_of,
        )


class Nifty500PE(Source):
    key = "nifty500_pe"
    url = "https://indexpe.in/nifty-500"

    def fetch(self) -> Indicator:
        pe, median, as_of = _parse_indexpe(fetch_text(self.url))
        if median is None:
            raise ValueError("nifty500: no median for breadth judgement")
        return Indicator(
            key="nifty500_pe",
            label="Nifty 500 PE (breadth)",
            value=round(pe, 2),
            unit="x",
            zone=zone_vs_median(pe, median),
            score=round(score_vs_median(pe, median), 1),
            detail=f"vs {median:g} 5-yr median",
            source="IndexPE",
            as_of=as_of,
        )
