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
_MAX_STOCKS = 30  # flagship top-30 shortlist (return-potential ranked)


def _fnum(v: object) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else "n/a"


def _scan_phrase(s: dict, labels: dict[str, str]) -> str:
    """Human list of the named screens this stock passes (for the AI to cite)."""
    scans = s.get("scans") or []
    named = [labels.get(x, x) for x in scans]
    return ", ".join(named) if named else "none"


def _stock_facts(s: dict, labels: dict[str, str]) -> str:
    """Compact fact line for one stock — drivers of cheap/risk + which scans it passes."""
    return (
        f"{s.get('symbol')} ({s.get('sector') or 'n/a'}): "
        f"PE {_fnum(s.get('pe'))}, PB {_fnum(s.get('pb'))}, "
        f"ROE {_fnum(s.get('roe'))}%, D/E {_fnum(s.get('de'))}, "
        f"rev_growth {_fnum(s.get('rev_growth'))}%, 1Y {_fnum(s.get('r_1y'))}%, "
        f"value_score {_fnum(s.get('value_score'))}, f_score {_fnum(s.get('f_score'))}, "
        f"magic_rank {_fnum(s.get('magic_rank'))}; passes: {_scan_phrase(s, labels)}"
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


def _stock_summaries(stocks: list[dict], labels: dict[str, str]) -> list[dict]:
    """Per-stock {symbol, scans, why_cheap, key_risk}. `scans` (which named screens
    it passes) is emitted from metrics regardless of LLM; why_cheap/key_risk filled
    by the LLM (empty if unavailable). Empty list only if no stocks."""
    if not stocks:
        return []
    base = {s.get("symbol"): list(s.get("scans") or []) for s in stocks}
    facts = "\n".join(_stock_facts(s, labels) for s in stocks)
    prompt = (
        "For each Indian stock below, in ONE short sentence each, explain why it "
        "screens cheap/attractive (cite the named screens it passes — e.g. 'passes "
        "Graham + Magic Formula + Piotroski 8') and its single key risk. Return ONLY "
        "a JSON array of objects with keys: symbol, why_cheap, key_risk. No markdown, "
        "no prose.\n\n"
        f"{facts}"
    )
    out = complete(prompt)
    parsed = _extract_json(out) if out else None
    llm_by_sym: dict[str, dict] = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                sym = str(item.get("symbol", "")).strip()
                if sym in base:
                    llm_by_sym[sym] = item
    result: list[dict] = []
    for s in stocks:
        sym = s.get("symbol")
        llm = llm_by_sym.get(sym, {})
        result.append({
            "symbol": sym,
            "scans": base[sym],
            "why_cheap": str(llm.get("why_cheap", "")).strip(),
            "key_risk": str(llm.get("key_risk", "")).strip(),
        })
    return result


def analyse(metrics: dict, verdict: str, score: float) -> dict | None:
    """Build the `ai` block for the metrics JSON. Focuses on the flagship top-30
    return-potential shortlist. `stocks[]` always carries per-pick scan-membership
    (which named screens it passes) so site + AI agree; why_cheap/key_risk are LLM
    text. None => no LLM daily AND no picks (pipeline drops the block)."""
    stocks = metrics.get("stocks", [])
    labels = metrics.get("scan_labels", {})
    top = sorted((s for s in stocks if s.get("rp_rank")),
                 key=lambda s: s["rp_rank"])[:_MAX_STOCKS]
    daily = _daily_commentary(verdict, score, [s["symbol"] for s in top])
    per_stock = _stock_summaries(top, labels)
    # scans live on the top-level stocks[] rows regardless; the `ai` block is LLM
    # commentary — emit only if the LLM produced daily text OR any why_cheap/key_risk.
    has_llm_text = bool(daily) or any(s["why_cheap"] or s["key_risk"] for s in per_stock)
    if not has_llm_text:
        return None
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "daily": daily or "",
        "stocks": per_stock,
    }
