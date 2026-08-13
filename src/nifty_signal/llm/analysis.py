"""Keyless AI analysis for the screener JSON (cron-time, best-effort).

Two artefacts, both committed into nifty_all_metrics.json under `ai`:
  - `daily`   : one-paragraph market-context commentary for the read.
  - `stocks`  : per-top-pick {symbol, why_cheap, key_risk} for the site to render.

Uses the shared keyless chain (llm.client.complete: g4f -> kilo). Degrades
gracefully: LLM absent / disabled / unparseable => returns None (no `ai` block,
pipeline unaffected). Everything is labelled AI-generated, not advice on-site."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from .client import complete

log = logging.getLogger("nifty_signal")

DISCLAIMER = "AI-generated, not advice."
_MAX_STOCKS = 10  # per-stock summaries only for the top picks (token + latency budget)


def _fnum(v: object) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else "n/a"


def _stock_facts(s: dict) -> str:
    """Compact fact line for one stock — only the drivers of cheap/risk."""
    return (
        f"{s.get('symbol')} ({s.get('sector') or 'n/a'}): "
        f"PE {_fnum(s.get('pe'))}, PB {_fnum(s.get('pb'))}, "
        f"ROE {_fnum(s.get('roe'))}%, D/E {_fnum(s.get('de'))}, "
        f"rev_growth {_fnum(s.get('rev_growth'))}%, 1Y {_fnum(s.get('r_1y'))}%, "
        f"value_score {_fnum(s.get('value_score'))}, f_score {_fnum(s.get('f_score'))}"
    )


def _extract_json(text: str) -> object | None:
    """Parse a JSON object/array out of an LLM reply (fences / prose tolerant)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    for pat in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pat, text, re.S)
        if m:
            try:
                return json.loads(m.group())
            except Exception:  # noqa: BLE001
                continue
    return None


def _daily_commentary(verdict: str, score: float, top_syms: list[str]) -> str | None:
    prompt = (
        "You are an equity-desk strategist writing a daily note for a long-term "
        "Indian-equity investor running a leveraged (MTF) buy-and-hold, annual-churn "
        "strategy. In 2-3 plain sentences (max 60 words), give today's market context "
        "and how to think about the cheap-stock shortlist. Neutral, no hype, no "
        "disclaimer (added separately).\n\n"
        f"Market verdict: {verdict} (buy-attractiveness {score:.0f}/100).\n"
        f"Top return-potential picks: {', '.join(top_syms) or 'n/a'}."
    )
    out = complete(prompt)
    return out.strip() if out else None


def _stock_summaries(stocks: list[dict]) -> list[dict]:
    """Per-stock {symbol, why_cheap, key_risk}. Empty list if LLM unavailable."""
    if not stocks:
        return []
    facts = "\n".join(_stock_facts(s) for s in stocks)
    prompt = (
        "For each Indian stock below, in ONE short sentence each, explain why it "
        "screens cheap/attractive and its single key risk. Return ONLY a JSON array "
        "of objects with keys: symbol, why_cheap, key_risk. No markdown, no prose.\n\n"
        f"{facts}"
    )
    out = complete(prompt)
    if not out:
        return []
    parsed = _extract_json(out)
    if not isinstance(parsed, list):
        return []
    valid = {s.get("symbol") for s in stocks}
    result: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol", "")).strip()
        if sym not in valid:
            continue
        result.append({
            "symbol": sym,
            "why_cheap": str(item.get("why_cheap", "")).strip(),
            "key_risk": str(item.get("key_risk", "")).strip(),
        })
    return result


def analyse(metrics: dict, verdict: str, score: float) -> dict | None:
    """Build the `ai` block for the metrics JSON. None => no LLM / nothing to add
    (pipeline drops the block). Best-effort: partial (daily-only or stocks-only) ok."""
    stocks = metrics.get("stocks", [])
    top = sorted((s for s in stocks if s.get("rp_rank")),
                 key=lambda s: s["rp_rank"])[:_MAX_STOCKS]
    daily = _daily_commentary(verdict, score, [s["symbol"] for s in top])
    per_stock = _stock_summaries(top)
    if not daily and not per_stock:
        return None
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "daily": daily or "",
        "stocks": per_stock,
    }
