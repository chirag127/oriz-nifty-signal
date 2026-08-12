"""Keyless LLM sentiment synthesis over news headlines.

Provider chain (verified 2026-08-12):
  1. kilo.ai  POST https://api.kilo.ai/api/gateway/v1/chat/completions
              model=kilo-auto/free — no key, returns OpenAI-compat JSON.
  2. Template fallback — deterministic from headline count/keywords.

Returns {"sentiment": "bullish|neutral|bearish", "confidence": 0-100,
         "one_line": "..."} or None on total failure (pipeline still runs).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypedDict

import httpx

from ..sources.news import Headline

log = logging.getLogger("nifty_signal")

_KILO_URL = "https://api.kilo.ai/api/gateway/v1/chat/completions"
_KILO_MODEL = "kilo-auto/free"
_TIMEOUT = 30


class Sentiment(TypedDict):
    sentiment: str   # "bullish" | "neutral" | "bearish"
    confidence: int  # 0-100
    one_line: str


def _prompt(headlines: list[Headline]) -> str:
    numbered = "\n".join(
        f"{i+1}. {h['title']} — {h['snippet'][:120]}"
        for i, h in enumerate(headlines[:10])
    )
    return (
        "You are a concise Indian equity analyst. Given these recent headlines, "
        "return ONLY a JSON object (no markdown, no explanation) with keys: "
        "sentiment (bullish|neutral|bearish), confidence (integer 0-100), "
        "one_line (max 20 words neutral market-timing take).\n\n"
        f"Headlines:\n{numbered}"
    )


def _parse_sentiment(text: str) -> Sentiment | None:
    # strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{[^}]+\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group())
        sentiment = str(d.get("sentiment", "")).lower()
        if sentiment not in {"bullish", "neutral", "bearish"}:
            sentiment = "neutral"
        confidence = int(d.get("confidence", 50))
        one_line = str(d.get("one_line", "")).strip()
        return Sentiment(sentiment=sentiment, confidence=confidence, one_line=one_line)
    except Exception:  # noqa: BLE001
        return None


def _kilo(prompt: str) -> str | None:
    try:
        r = httpx.post(
            _KILO_URL,
            json={"model": _KILO_MODEL, "messages": [{"role": "user", "content": prompt}]},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.info("kilo sentiment failed: %s", e)
        return None


def _template_sentiment(headlines: list[Headline]) -> Sentiment:
    """Deterministic keyword-based fallback."""
    text = " ".join(h["title"] + " " + h["snippet"] for h in headlines).lower()
    bull = sum(1 for w in ["rally", "surge", "gain", "bull", "buy", "strong", "record", "high"] if w in text)
    bear = sum(1 for w in ["fall", "crash", "decline", "bear", "sell", "weak", "low", "concern", "risk"] if w in text)
    if bull > bear + 1:
        return Sentiment(sentiment="bullish", confidence=55, one_line="Headlines lean positive; watch valuations.")
    if bear > bull + 1:
        return Sentiment(sentiment="bearish", confidence=55, one_line="Headlines cautious; stick to SIP.")
    return Sentiment(sentiment="neutral", confidence=50, one_line="Mixed signals; SIP continues.")


def analyse_sentiment(headlines: list[Headline]) -> Sentiment | None:
    """Run LLM sentiment synthesis. None if no headlines; template fallback if LLM fails."""
    if not headlines:
        return None
    prompt = _prompt(headlines)
    raw = _kilo(prompt)
    if raw:
        parsed = _parse_sentiment(raw)
        if parsed:
            log.info("sentiment: %s (confidence %d) via kilo", parsed["sentiment"], parsed["confidence"])
            return parsed
    # template fallback
    result = _template_sentiment(headlines)
    log.info("sentiment: %s via template fallback", result["sentiment"])
    return result
