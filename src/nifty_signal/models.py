"""Data models for the Nifty market-timing signal.

An `Indicator` = one valuation/sentiment reading with its zone. A `Signal` =
the full snapshot: every indicator + the combined verdict + commentary.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Indicator:
    """One valuation/sentiment reading.

    `score` is a normalised 0..100 buy-attractiveness contribution (higher =
    more attractive to buy). `None` value/score = source unavailable (n/a),
    never fabricated.
    """

    key: str            # "nifty_pe" | "nifty500_pe" | "buffett" | "mmi"
    label: str          # human label
    value: float | None = None
    unit: str = ""      # "x" | "%" | ""
    zone: str = ""      # cheap/fair/expensive/frothy | undervalued/... | fear zone
    score: float | None = None   # 0..100 buy-attractiveness
    detail: str = ""    # e.g. "vs 22.08 median" / "as of Dec 2025 (annual)"
    source: str = ""
    as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Signal:
    verdict: str                       # STRONG BUY | ACCUMULATE | HOLD-SIP-ONLY | CAUTION
    verdict_score: float               # 0..100 composite buy-attractiveness
    rationale: str                     # one-line why
    ts: str = field(default_factory=_now_iso)
    indicators: list[Indicator] = field(default_factory=list)
    summary: str = ""                  # g4f / template commentary

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["indicators"] = [i.to_dict() for i in self.indicators]
        return d
