"""Notifiers: Telegram (HTML) + ntfy. Both best-effort, both read config from env,
both no-op when unconfigured. Uses the single oriz bot (TELEGRAM_BOT_TOKEN +
TELEGRAM_CHAT_ID from env — NEVER hardcoded).
"""

from __future__ import annotations

import logging
import os

import httpx

from ..models import Signal

log = logging.getLogger("nifty_signal")

SITE = "https://nifty-signal.oriz.in"

_VERDICT_EMOJI = {
    "STRONG BUY": "🟢",
    "ACCUMULATE": "🟩",
    "HOLD-SIP-ONLY": "🟡",
    "CAUTION": "🔴",
}


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ind_line(sig: Signal) -> str:
    bits = [
        f"{i.label} {i.value:g}{i.unit} ({i.zone})"
        for i in sig.indicators
        if i.value is not None
    ]
    return " · ".join(bits)


def format_message(sig: Signal) -> str:
    """Telegram HTML message for one signal."""
    emoji = _VERDICT_EMOJI.get(sig.verdict, "⚪")
    head = (
        f'{emoji} <a href="{SITE}"><b>{_esc(sig.verdict)} — '
        f'score {sig.verdict_score:.0f}/100</b></a>'
    )
    lines = [head, _esc(sig.rationale)]
    ind = _ind_line(sig)
    if ind:
        lines.append(_esc(ind))
    if sig.summary and sig.summary != sig.rationale:
        lines.append(_esc(sig.summary))
    lines.append(f"→ {SITE}")
    return "\n".join(lines)


def format_ntfy(sig: Signal) -> str:
    lines = [f"{sig.verdict} — score {sig.verdict_score:.0f}/100", sig.rationale]
    ind = _ind_line(sig)
    if ind:
        lines.append(ind)
    lines.append(SITE)
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.info("telegram: TELEGRAM_BOT_TOKEN/CHAT_ID unset — skipping")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        log.info("telegram: sent")
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("telegram send failed: %s", e)
        return False


def send_ntfy(text: str) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        log.info("ntfy: NTFY_TOPIC unset — skipping")
        return False
    base = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
    headers = {"Title": "Nifty Signal", "Tags": "chart_with_upwards_trend"}
    user = os.environ.get("NTFY_USER", "").strip()
    pw = os.environ.get("NTFY_PASSWORD", "").strip()
    auth = (user, pw) if user and pw else None
    try:
        r = httpx.post(
            f"{base}/{topic}",
            content=text.encode("utf-8"),
            headers=headers,
            auth=auth,
            timeout=20,
        )
        r.raise_for_status()
        log.info("ntfy: sent to %s/%s", base, topic)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy send failed: %s", e)
        return False


def notify_all(sig: Signal) -> dict[str, bool]:
    return {
        "telegram": send_telegram(format_message(sig)),
        "ntfy": send_ntfy(format_ntfy(sig)),
    }
