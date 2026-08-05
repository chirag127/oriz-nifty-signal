"""Source base. Each source returns one Indicator (or a list) or raises."""

from __future__ import annotations

from ..models import Indicator


class Source:
    key: str = "base"
    url: str = ""

    def fetch(self) -> Indicator | list[Indicator]:  # pragma: no cover - interface
        raise NotImplementedError
