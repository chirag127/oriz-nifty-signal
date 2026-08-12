"""Collect all indicators. Each source is best-effort: a source that fails
yields NO indicator (never a fabricated number). The verdict renormalises over
whatever succeeded, and the pipeline records which were n/a.
"""

from __future__ import annotations

import logging

from ..models import Indicator
from .base import Source
from .buffett import BuffettIndicator
from .mmi import MmiSource
from .nifty_pe import Nifty500PE, Nifty50PE, NiftyMidcap100PE, NiftySmallcap100PE

log = logging.getLogger("nifty_signal")


def build_sources() -> list[Source]:
    return [
        Nifty50PE(),
        Nifty500PE(),
        BuffettIndicator(),
        MmiSource(),
        NiftyMidcap100PE(),    # informational — score=None, excluded from composite
        NiftySmallcap100PE(),  # informational — score=None, excluded from composite
    ]


def collect() -> tuple[list[Indicator], list[str]]:
    """Return (indicators, errors). Never raises for a single bad source."""
    indicators: list[Indicator] = []
    errors: list[str] = []
    for src in build_sources():
        try:
            log.info("indicator %s <- %s", src.key, src.url)
            ind = src.fetch()
            got = ind if isinstance(ind, list) else [ind]
            for i in got:
                log.info("  %s = %s%s (%s) score=%s", i.key, i.value, i.unit, i.zone, i.score)
                indicators.append(i)
        except Exception as e:  # noqa: BLE001 - per-source failover
            log.warning("indicator %s failed: %s", src.key, e)
            errors.append(f"{src.key}: {e}")
    if not indicators:
        raise RuntimeError("all indicators failed:\n  " + "\n  ".join(errors))
    return indicators, errors
