"""News headlines for Indian equity sentiment — keyless, best-effort.

Uses ddgs (DuckDuckGo Search, pip install ddgs) — no API key, no rate-limit on
reasonable usage. VERIFIED 2026-08-12: `from ddgs import DDGS` works; returns
list of {title, body, href, ...}.

Fallback: if ddgs raises, returns [] (pipeline continues without news).
"""

from __future__ import annotations

import logging
from typing import TypedDict

log = logging.getLogger("nifty_signal")

_QUERIES = [
    "Nifty 50 PE valuation outlook today",
    "Indian stock market sentiment Nifty bullish bearish",
]
_MAX_PER_QUERY = 5


class Headline(TypedDict):
    title: str
    snippet: str
    url: str
    source: str


def fetch_headlines() -> list[Headline]:
    """Return up to 10 recent headlines via DuckDuckGo. Empty list on any error."""
    try:
        from ddgs import DDGS  # lazy — may be absent in test env
    except Exception as e:  # noqa: BLE001
        log.info("ddgs unavailable: %s", e)
        return []

    seen: set[str] = set()
    results: list[Headline] = []
    try:
        ddg = DDGS()
        for q in _QUERIES:
            for item in ddg.text(q, max_results=_MAX_PER_QUERY):
                url = item.get("href") or item.get("url", "")
                if url in seen:
                    continue
                seen.add(url)
                results.append(
                    Headline(
                        title=item.get("title", ""),
                        snippet=item.get("body", ""),
                        url=url,
                        source=item.get("source", ""),
                    )
                )
    except Exception as e:  # noqa: BLE001
        log.warning("news fetch failed: %s", e)
    log.info("news: fetched %d headlines", len(results))
    return results
