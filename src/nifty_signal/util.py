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

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Awaitable, Callable, TypeVar

import httpx

log = logging.getLogger("nifty_signal")

_T = TypeVar("_T")
_R = TypeVar("_R")


def map_concurrent(
    fn: Callable[[_T], _R], items: list[_T], *, workers: int = 16
) -> dict[_T, _R]:
    """Run `fn` over `items` in a thread pool (I/O-bound keyless GETs). Returns
    {item: result} for items whose result is not None; one failure never aborts
    the batch (logged + skipped). Resilient partial results."""
    out: dict[_T, _R] = {}
    if not items:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for fut in as_completed(futs):
            it = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001 — resilient: skip bad item
                log.warning("concurrent task failed item=%s: %s", it, e)
                continue
            if res is not None:
                out[it] = res
    return out

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


def score_news_sentiment(sentiment: str, confidence: int) -> float:
    """Map LLM sentiment to buy-attractiveness score.
    bullish -> below 50 (contrarian: market optimism = less attractive entry)
    bearish -> above 50 (contrarian: fear = better entry)
    neutral -> 50.
    Weight in composite is small (0.05) so this nudges ±a few points only.
    """
    base = {"bullish": 35.0, "bearish": 65.0}.get(sentiment.lower(), 50.0)
    # scale by confidence: low confidence pulls toward 50
    return _clamp(50.0 + (base - 50.0) * (confidence / 100.0))


# ---- composite verdict ---------------------------------------------------

# weights sum to 1 among AVAILABLE indicators (renormalised if any n/a).
# news_sentiment is a small nudge (±3-5 pts effect); midcap/smallcap_pe have
# score=None so they never enter composite_score regardless.
WEIGHTS = {
    "nifty_pe": 0.38,       # primary large-cap valuation
    "buffett": 0.24,        # total-market / GDP
    "mmi": 0.19,            # sentiment contrarian
    "nifty500_pe": 0.14,    # broad-market breadth
    "news_sentiment": 0.05, # keyless-LLM news nudge (small weight)
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


def fetch_json_post(url: str, body: dict, timeout: float = 40.0, referer: str = "") -> dict:
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
    }
    if referer:
        headers["Referer"] = referer
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        return r.json()


def fetch_text(url: str, timeout: float = 25.0) -> str:
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


# ---- async keyless fetch (bounded concurrency) --------------------------

def _headers(referer: str = "", json_body: bool = False) -> dict[str, str]:
    h = {
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    if referer:
        h["Referer"] = referer
    return h


async def gather_bounded(
    coro_fns: list[Callable[[httpx.AsyncClient], Awaitable[_R]]],
    *,
    concurrency: int = 24,
    timeout: float = 40.0,
) -> list[_R | None]:
    """Run coroutine-factories over one shared AsyncClient, capped at
    `concurrency` in-flight. Order preserved; a failing task yields None
    (logged) so a partial sweep still scores. I/O-bound keyless calls."""
    if not coro_fns:
        return []
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, limits=limits) as client:
        async def guarded(fn: Callable[[httpx.AsyncClient], Awaitable[_R]]) -> _R | None:
            async with sem:
                try:
                    return await fn(client)
                except Exception as e:  # noqa: BLE001 — resilient: skip bad task
                    log.warning("async task failed: %s", e)
                    return None
        return await asyncio.gather(*(guarded(fn) for fn in coro_fns))


async def afetch_json_post(client: httpx.AsyncClient, url: str, body: dict, referer: str = "") -> dict:
    r = await client.post(url, json=body, headers=_headers(referer, json_body=True))
    r.raise_for_status()
    return r.json()


async def afetch_json(client: httpx.AsyncClient, url: str, referer: str = "") -> dict:
    r = await client.get(url, headers=_headers(referer))
    r.raise_for_status()
    return r.json()


def run_async(coro: Awaitable[_R]) -> _R:
    """Run an async coroutine from sync code (fresh loop per call)."""
    return asyncio.run(coro)
