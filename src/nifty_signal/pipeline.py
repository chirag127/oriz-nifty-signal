"""Pipeline: collect indicators -> classify zones + score -> combine into verdict
-> keyless-LLM news sentiment (best-effort) + commentary -> write data/latest.json +
data/history/<date>.json -> notify with combined Nifty+MMI message.

Daily cadence (equity valuation moves slowly): the workflow runs once at 1pm IST
and always sends, so the daily read lands in Telegram regardless of change.
"""

from __future__ import annotations

import gzip
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


def _fetch_metrics() -> dict:
    """Full-universe screener metrics payload (best-effort, {} on failure)."""
    try:
        from .sources.metrics import all_metrics
        return all_metrics()
    except Exception as e:  # noqa: BLE001
        log.warning("metrics build failed: %s", e)
        return {}


def _top_lists(metrics: dict) -> tuple[list[dict], list[dict]]:
    """(top MTF-buy-hold, top value) short lists for the notification."""
    stocks = metrics.get("stocks", [])
    mtf = sorted((s for s in stocks if s.get("mtf_rank")), key=lambda s: s["mtf_rank"])[:10]
    val = sorted((s for s in stocks if s.get("value_rank")), key=lambda s: s["value_rank"])[:10]
    return mtf, val


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


def write_snapshot(sig: Signal, errors: list[str], data_dir: Path, lowest_pe: list[dict] | None = None) -> None:
    """latest.json = current signal (+ lowest_pe list). history/<date>.json =
    append-only daily log (drives the sparkline). lowest_pe_nifty500.json =
    standalone cheapest-by-PE list (git-as-DB)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lowest_pe = lowest_pe or []
    payload = {**sig.to_dict(), "lowest_pe": lowest_pe, "errors": errors}
    (data_dir / "latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if lowest_pe:
        (data_dir / "lowest_pe_nifty500.json").write_text(
            json.dumps({"ts": sig.ts, "stocks": lowest_pe}, indent=2, ensure_ascii=False),
            encoding="utf-8",
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


def write_metrics(metrics: dict, ts: str, data_dir: Path) -> None:
    """nifty_all_metrics.json = full-universe screener rows (git-as-DB, site
    contract). Compact (no indent) + gzip sidecar for the browser."""
    if not metrics.get("stocks"):
        log.warning("metrics empty — not writing nifty_all_metrics.json")
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ts": ts, **metrics}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (data_dir / "nifty_all_metrics.json").write_text(blob, encoding="utf-8")
    with gzip.open(data_dir / "nifty_all_metrics.json.gz", "wt", encoding="utf-8") as f:
        f.write(blob)
    log.info("wrote nifty_all_metrics.json (%d stocks, %d KB raw)",
             metrics.get("count", 0), len(blob) // 1024)


def _lowest_pe_from_metrics(metrics: dict, top: int = 20) -> list[dict]:
    """Cheapest Nifty-500 by trailing PE, from the metrics sweep (git-as-DB back-compat)."""
    stocks = [s for s in metrics.get("stocks", [])
              if s.get("n500") and isinstance(s.get("pe"), (int, float)) and s["pe"] > 0]
    stocks.sort(key=lambda s: s["pe"])
    return [{"symbol": s["symbol"], "pe": round(s["pe"], 2)} for s in stocks[:top]]


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

    metrics = _fetch_metrics()
    if metrics and with_llm:
        # keyless AI: daily commentary + per-top-pick why-cheap/key-risk, committed
        # into the metrics JSON for the site to render. Best-effort; degrades to no block.
        from .llm.analysis import analyse
        ai = analyse(metrics, sig.verdict, sig.verdict_score)
        if ai:
            metrics["ai"] = ai
    if metrics:
        write_metrics(metrics, sig.ts, data_dir)
    lowest_pe = _lowest_pe_from_metrics(metrics)
    write_snapshot(sig, errors, data_dir, lowest_pe=lowest_pe)

    if with_notify:
        from .notify.channels import notify_all
        mmi_snapshot = _fetch_mmi_snapshot()
        # Stock recommendations (top return-potential / value) ride along ONLY on
        # a STRONG BUY market signal; other verdicts send the market read alone.
        strong = sig.verdict == "STRONG BUY"
        top_mtf, top_value = _top_lists(metrics) if strong else ([], [])
        notify_all(sig, mmi_snapshot=mmi_snapshot,
                   lowest_pe=lowest_pe if strong else [],
                   top_mtf=top_mtf, top_value=top_value)

    return sig
