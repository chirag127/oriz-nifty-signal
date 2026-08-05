"""Shared helpers: HTTP fetch, logging, zone classification + buy-attractiveness
scoring for each indicator, and the composite verdict.

Framework (researched 2026-08-05):
- Nifty 50 PE: cheap <18 / fair 18-22 / expensive 22-24 / frothy >24.
  Lower PE => higher expected forward return => higher buy score.
- Nifty 500 PE: judged vs its own median (breadth). Below median = attractive.
- Buffett indicator (mkt-cap/GDP, India): <75 undervalued / 75-115 fair /
  >115 overvalued.
- MMI (contrarian): Extreme Fear = buy, Extreme Greed = caution.

Composite verdict from the weighted mean buy-attractiveness score:
  >=70 STRONG BUY · 55-70 ACCUMULATE · 40-55 HOLD-SIP-ONLY · <40 CAUTION.
"""

from __future__ import annotations

import logging
import sys

import httpx

log = logging.getLogger("nifty_signal")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ---- zone classifiers (label per band) ----------------------------------

def zone_nifty_pe(pe: float) -> str:
    if pe < 18:
        return "cheap"
    if pe < 22:
        return "fair"
    if pe < 24:
        return "expensive"
    return "frothy"


def zone_vs_median(pe: float, median: float) -> str:
    """Nifty 500 breadth: how the current PE sits vs its own median."""
    if median <= 0:
        return "fair"
    ratio = pe / median
    if ratio < 0.90:
        return "cheap"
    if ratio <= 1.05:
        return "fair"
    if ratio <= 1.15:
        return "expensive"
    return "frothy"


def zone_buffett(pct: float) -> str:
    if pct < 75:
        return "undervalued"
    if pct <= 115:
        return "fair"
    return "overvalued"


def zone_mmi(v: float) -> str:
    # Tickertape 4-zone: <30 Extreme Fear · 30-50 Fear · 50-70 Greed · >70 Extreme Greed
    if v < 30:
        return "Extreme Fear"
    if v < 50:
        return "Fear"
    if v < 70:
        return "Greed"
    return "Extreme Greed"


# ---- buy-attractiveness scores (0..100, higher = better time to buy) -----

def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _lerp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linear map x in [x0,x1] -> [y0,y1] (x0 may be > x1 for inverse)."""
    if x1 == x0:
        return y0
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def score_nifty_pe(pe: float) -> float:
    """PE 15 -> ~95 (cheap), 24 -> ~15 (frothy). Piecewise, inverse."""
    if pe <= 15:
        return 95.0
    if pe <= 18:
        return _clamp(_lerp(pe, 15, 18, 95, 78))
    if pe <= 22:
        return _clamp(_lerp(pe, 18, 22, 78, 50))
    if pe <= 24:
        return _clamp(_lerp(pe, 22, 24, 50, 30))
    if pe <= 28:
        return _clamp(_lerp(pe, 24, 28, 30, 8))
    return 5.0


def score_vs_median(pe: float, median: float) -> float:
    """ratio 0.85 -> ~90, 1.0 -> 55, 1.15 -> ~25. Inverse of over/under median."""
    if median <= 0:
        return 50.0
    ratio = pe / median
    return _clamp(_lerp(ratio, 0.80, 1.20, 92, 18))


def score_buffett(pct: float) -> float:
    """75% -> ~85, 100% -> ~62, 115% -> ~48, 140% -> ~22. Inverse."""
    return _clamp(_lerp(pct, 60, 150, 95, 12))


def score_mmi(v: float) -> float:
    """Contrarian: MMI 0 (extreme fear) -> 100 buy, MMI 100 (extreme greed) -> 0."""
    return _clamp(100.0 - v)


# ---- composite verdict ---------------------------------------------------

# weights sum to 1 among AVAILABLE indicators (renormalised if any n/a).
WEIGHTS = {
    "nifty_pe": 0.40,   # primary
    "buffett": 0.25,
    "mmi": 0.20,
    "nifty500_pe": 0.15,
}


def verdict_label(score: float) -> str:
    if score >= 70:
        return "STRONG BUY"
    if score >= 55:
        return "ACCUMULATE"
    if score >= 40:
        return "HOLD-SIP-ONLY"
    return "CAUTION"


def composite_score(scores: dict[str, float]) -> float:
    """Weighted mean over the indicators that produced a score; renormalise
    weights over the available set. Returns 0..100."""
    num = 0.0
    den = 0.0
    for key, sc in scores.items():
        w = WEIGHTS.get(key, 0.0)
        num += w * sc
        den += w
    if den == 0:
        return 0.0
    return round(num / den, 1)


def fetch_json(url: str, timeout: float = 25.0, referer: str = "") -> dict:
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


def fetch_text(url: str, timeout: float = 25.0) -> str:
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text
