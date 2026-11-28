"""g4f (GPT4Free) commentary — keyless, best-effort. Deterministic template
fallback so a missing/failed LLM never blocks the pipeline or notification.
"""

from __future__ import annotations

import logging

from ..models import Signal
from .client import complete

log = logging.getLogger("nifty_signal")

_VERDICT_ADVICE = {
    "STRONG BUY": "valuations attractive — deploy lumpsum + keep the SIP.",
    "ACCUMULATE": "reasonable entry — stagger lumpsum in, keep the SIP.",
    "HOLD-SIP-ONLY": "fully valued — SIP only, hold lumpsum for a better price.",
    "CAUTION": "rich valuations — SIP only, trim/hedge, wait for a pullback.",
}


def _template(sig: Signal) -> str:
    bits = [f"{i.label} {i.value:g}{i.unit} ({i.zone})" for i in sig.indicators if i.value is not None]
    lead = f"{sig.verdict} (score {sig.verdict_score:.0f}/100)"
    advice = _VERDICT_ADVICE.get(sig.verdict, "SIP always; time lumpsum by valuation.")
    body = "; ".join(bits)
    return f"{lead}. {advice} {body}."


def commentary(sig: Signal) -> str:
    """One-line market-timing take. LLM if available, else template."""
    lines = "; ".join(
        f"{i.label}={i.value:g}{i.unit} [{i.zone}]" for i in sig.indicators if i.value is not None
    )
    prompt = (
        "You are an equity-desk strategist. In ONE concise sentence (max 28 words), "
        "give a neutral market-timing read for a long-term Indian-equity investor: "
        "is now a good time to add lumpsum, or SIP-only? No hype, no disclaimer.\n\n"
        f"Verdict: {sig.verdict} (buy-attractiveness {sig.verdict_score:.0f}/100)\n"
        f"Indicators: {lines}"
    )
    return complete(prompt) or _template(sig)
