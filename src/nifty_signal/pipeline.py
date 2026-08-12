"""Pipeline: collect indicators -> classify zones + score -> combine into verdict
-> keyless-LLM news sentiment (best-effort) + commentary -> write data/latest.json +
data/history/<date>.json -> notify with combined Nifty+MMI message.

Daily cadence (equity valuation moves slowly): the workflow runs once at 1pm IST
and always sends, so the daily read lands in Telegram regardless of change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .llm.sentiment import Sentiment, analyse_sentiment
from .llm.summary import commentary
from .models import Indicator, Signal
from .sources import collect
from .sources.news import fetch_headlines
from .util import composite_score, score_news_sentiment, verdict_label

log = logging.getLogger("nifty_signal")

_MMI_URL = "https://raw.githubusercontent.com/chirag127/oriz-mmi/main/data/latest.json"

_RATIONALE = {
    "STRONG BUY": "Valuations cheap + sentiment supportive — good time to add lumpsum; SIP always.",
    "ACCUMULATE": "Fairly-to-cheaply valued — stagger lumpsum in; SIP always.",
    "HOLD-SIP-ONLY": "Fully valued — SIP only, hold lumpsum for a better entry.",
    "CAUTION": "Rich valuations / greedy sentiment — SIP only, wait for a pullback.",
}


def _fetch_mmi_snapshot() -> dict[str, Any] | None:
    """Fetch oriz-mmi published data (best-effort, 15s timeout)."""
    try:
        r = httpx.get(_MMI_URL, timeout=15, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("mmi snapshot fetch failed: %s", e)
        return None


def _news_sentiment_indicator(sent: Sentiment) -> Indicator:
    from .util import score_news_sentiment
    sc = score_news_sentiment(sent["sentiment"], sent["confidence"])
    return Indicator(
        key="news_sentiment",
        label="News sentiment",
        value=float(sent["confidence"]),
        unit="",
        zone=sent["sentiment"],
        score=round(sc, 1),
        detail=sent.get("one_line", ""),
        source="kilo/ddgs",
    )


def build_signal() -> tuple[Signal, list[str]]:
    indicators, errors = collect()

    # news + LLM sentiment (best-effort)
    headlines = fetch_headlines()
    sent = analyse_sentiment(headlines)
    if sent:
        indicators.append(_news_sentiment_indicator(sent))

    scores = {i.key: i.score for i in indicators if i.score is not None}
    score = composite_score(scores)
    verdict = verdict_label(score)
    sig = Signal(
        verdict=verdict,
        verdict_score=score,
        rationale=_RATIONALE.get(verdict, "SIP always; time lumpsum by valuation."),
        indicators=indicators,
    )
    return sig, errors


def write_snapshot(sig: Signal, errors: list[str], data_dir: Path) -> None:
    """latest.json = current signal. history/<date>.json = append-only daily log
    (drives the sparkline)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {**sig.to_dict(), "errors": errors}
    (data_dir / "latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    hist_dir = data_dir / "history"
    hist_dir.mkdir(exist_ok=True)
    day = sig.ts[:10] or "snapshot"
    hist_file = hist_dir / f"{day}.json"
    points: list[dict] = []
    if hist_file.exists():
        try:
            points = json.loads(hist_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            points = []
    points.append(
        {"ts": sig.ts, "score": sig.verdict_score, "verdict": sig.verdict}
    )
    hist_file.write_text(json.dumps(points, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote latest.json + history/%s.json (%d points)", day, len(points))


def run(
    data_dir: Path,
    with_llm: bool = True,
    with_notify: bool = True,
) -> Signal:
    sig, errors = build_signal()
    log.info("verdict %s (score %.1f), %d indicators, %d errors",
             sig.verdict, sig.verdict_score, len(sig.indicators), len(errors))

    if with_llm:
        sig.summary = commentary(sig)

    write_snapshot(sig, errors, data_dir)

    if with_notify:
        from .notify.channels import notify_all
        mmi_snapshot = _fetch_mmi_snapshot()
        notify_all(sig, mmi_snapshot=mmi_snapshot)

    return sig
