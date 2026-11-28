"""Shared keyless-LLM completion — the fleet chain, best-effort.

Chain (first hit wins, verified 2026-08-12):
  1. g4f (GPT4Free) local client — multi-provider failover, no key.
  2. kilo.ai gateway POST — model=kilo-auto/free, OpenAI-compat, no key.
  3. None — caller degrades to a deterministic template.

`NIFTY_DISABLE_LLM=1` forces None (tests / offline cron). Never raises."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("nifty_signal")

_KILO_URL = "https://api.kilo.ai/api/gateway/v1/chat/completions"
_KILO_MODEL = "kilo-auto/free"
_TIMEOUT = 45


def _g4f(prompt: str) -> str | None:
    try:
        from g4f.client import Client  # lazy — g4f may be absent
    except Exception as e:  # noqa: BLE001
        log.info("g4f unavailable: %s", e)
        return None
    try:
        client = Client()
        # "auto" routes to the best working keyless provider/model; fall through.
        for model in ("auto", "gpt-4o", "gpt-4o-mini"):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=_TIMEOUT,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text and len(text) >= 15 and len(text.split()) >= 3:
                    return text
                log.info("g4f model %s returned too-short output %r — trying next", model, text)
            except Exception as e:  # noqa: BLE001 - try next model
                log.info("g4f model %s failed: %s", model, e)
                continue
        return None
    except Exception as e:  # noqa: BLE001
        log.info("g4f completion failed: %s", e)
        return None


def _kilo(prompt: str) -> str | None:
    try:
        r = httpx.post(
            _KILO_URL,
            json={"model": _KILO_MODEL, "messages": [{"role": "user", "content": prompt}]},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.info("kilo completion failed: %s", e)
        return None


def complete(prompt: str) -> str | None:
    """Keyless completion via the fleet chain. None on total failure / disabled."""
    if os.environ.get("NIFTY_DISABLE_LLM") == "1":
        return None
    return _g4f(prompt) or _kilo(prompt)
