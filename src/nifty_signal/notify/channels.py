"""Notifiers: Telegram (HTML) + ntfy. Both best-effort, both read config from env,
both no-op when unconfigured. Uses the single oriz bot (TELEGRAM_BOT_TOKEN +
TELEGRAM_CHAT_ID from env — NEVER hardcoded).

notify_all(sig, mmi_snapshot=...) sends ONE combined message per channel.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..models import Signal

log = logging.getLogger("nifty_signal")

SITE = "https://nifty-signal.oriz.in"
MMI_SITE = "https://mmi.oriz.in"

_VERDICT_EMOJI = {
    "STRONG BUY": "🟢",
    "ACCUMULATE": "🟩",
    "HOLD-SIP-ONLY": "🟡",
    "CAUTION": "🔴",
}

_ZONE_EMOJI = {
    "Extreme Fear": "😱",
    "Fear": "😟",
    "Greed": "😊",
    "Extreme Greed": "🤑",
}


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ind_line(sig: Signal) -> str:
    # only scored, non-segment indicators for the compact summary line
    CORE = {"nifty_pe", "nifty500_pe", "buffett", "mmi"}
    bits = [
        f"{i.label} {i.value:g}{i.unit} ({i.zone})"
        for i in sig.indicators
        if i.value is not None and i.key in CORE
    ]
    return " · ".join(bits)


def _segment_line(sig: Signal, html: bool = False) -> str:
    """Build large/mid/small PE segment comparison line."""
    SEG = {
        "nifty_pe": "Large",
        "nifty500_pe": "Broad",
        "midcap_pe": "Mid",
        "smallcap_pe": "Small",
    }
    bits = []
    for ind in sig.indicators:
        label = SEG.get(ind.key)
        if label and ind.value is not None:
            bits.append(f"{label}: {ind.value:g}x ({ind.zone})")
    return "  ".join(bits)


def _segment_advice(sig: Signal) -> str:
    """One-line segment-specific lumpsum guidance."""
    zones: dict[str, str] = {}
    for ind in sig.indicators:
        if ind.key in {"nifty_pe", "midcap_pe", "smallcap_pe"} and ind.zone:
            zones[ind.key] = ind.zone

    cheap = [k for k, z in zones.items() if z in {"cheap", "undervalued"}]
    pricey = [k for k, z in zones.items() if z in {"expensive", "frothy", "overvalued"}]
    label_map = {"nifty_pe": "large-cap", "midcap_pe": "mid-cap", "smallcap_pe": "small-cap"}

    parts = []
    if cheap:
        parts.append("lumpsum ok: " + ", ".join(label_map[k] for k in cheap if k in label_map))
    if pricey:
        parts.append("avoid lumpsum: " + ", ".join(label_map[k] for k in pricey if k in label_map))
    return "; ".join(parts) if parts else ""


def _news_sentiment_line(sig: Signal, html: bool = False) -> str:
    sent = next((i for i in sig.indicators if i.key == "news_sentiment"), None)
    if not sent or not sent.detail:
        return ""
    emoji = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(sent.zone, "")
    label = f"{emoji} News: {sent.zone} ({sent.value:.0f}% confidence) — {sent.detail}"
    return _esc(label) if html else label


def _mmi_section(mmi: dict[str, Any], html: bool = False) -> str:
    """Format the MMI section from oriz-mmi latest.json."""
    try:
        value = float(mmi["value"])
        zone = str(mmi.get("zone", ""))
        summary = str(mmi.get("summary", ""))
        emoji = _ZONE_EMOJI.get(zone, "")
        nifty = mmi.get("nifty")
        nifty_str = f"  Nifty {nifty:,.0f}" if nifty else ""
        fii = mmi.get("fii")
        fii_str = f"  FII {fii:+,.0f}" if fii is not None else ""
    except (KeyError, TypeError, ValueError):
        return ""

    if html:
        link = f'<a href="{MMI_SITE}">mmi.oriz.in</a>'
        head = f"{emoji} MMI {value:.1f} — <b>{_esc(zone)}</b>"
        parts = [head]
        if summary:
            parts.append(_esc(summary))
        extras = (nifty_str + fii_str).strip()
        if extras:
            parts.append(_esc(extras.strip()))
        parts.append(f"→ {link}")
        return "\n".join(parts)
    else:
        head = f"{emoji} MMI {value:.1f} — {zone}"
        parts = [head]
        if summary:
            parts.append(summary)
        extras = (nifty_str + fii_str).strip()
        if extras:
            parts.append(extras.strip())
        parts.append(f"→ {MMI_SITE}")
        return "\n".join(parts)


def _lowest_pe_section(lowest_pe: list[dict], html: bool = False, top: int = 10) -> str:
    """Cheapest Nifty 500 by trailing PE — top N as symbol PEx."""
    if not lowest_pe:
        return ""
    rows = lowest_pe[:top]
    bits = [f"{_esc(r['symbol']) if html else r['symbol']} {r['pe']:g}x" for r in rows]
    head = "💰 <b>Cheapest Nifty 500 by PE</b>" if html else "Cheapest Nifty 500 by PE:"
    return head + "\n" + " · ".join(bits)


def format_message(sig: Signal, mmi_snapshot: dict[str, Any] | None = None, lowest_pe: list[dict] | None = None) -> str:
    """Telegram HTML combined message: Nifty verdict + segment breakdown + MMI."""
    emoji = _VERDICT_EMOJI.get(sig.verdict, "⚪")
    head = (
        f'{emoji} <a href="{SITE}"><b>{_esc(sig.verdict)} — '
        f'score {sig.verdict_score:.0f}/100</b></a>'
    )
    lines = [head, _esc(sig.rationale)]

    ind = _ind_line(sig)
    if ind:
        lines.append(_esc(ind))

    seg = _segment_line(sig, html=True)
    if seg:
        lines.append(f"<b>Segments</b> {_esc(seg)}")

    seg_adv = _segment_advice(sig)
    if seg_adv:
        lines.append(_esc(seg_adv))

    news_line = _news_sentiment_line(sig, html=True)
    if news_line:
        lines.append(news_line)

    if sig.summary and sig.summary != sig.rationale:
        lines.append(_esc(sig.summary))

    lines.append(f"→ {SITE}")

    lp = _lowest_pe_section(lowest_pe or [], html=True)
    if lp:
        lines.append("")
        lines.extend(lp.split("\n"))

    # MMI section (separator + block)
    if mmi_snapshot:
        mmi_block = _mmi_section(mmi_snapshot, html=True)
        if mmi_block:
            lines.append("")
            lines.extend(mmi_block.split("\n"))

    return "\n".join(lines)


def format_ntfy(sig: Signal, mmi_snapshot: dict[str, Any] | None = None, lowest_pe: list[dict] | None = None) -> str:
    lines = [f"{sig.verdict} — score {sig.verdict_score:.0f}/100", sig.rationale]

    ind = _ind_line(sig)
    if ind:
        lines.append(ind)

    seg = _segment_line(sig)
    if seg:
        lines.append(f"Segments: {seg}")

    seg_adv = _segment_advice(sig)
    if seg_adv:
        lines.append(seg_adv)

    news_line = _news_sentiment_line(sig)
    if news_line:
        lines.append(news_line)

    lines.append(SITE)

    lp = _lowest_pe_section(lowest_pe or [], html=False)
    if lp:
        lines.append("")
        lines.append(lp)

    if mmi_snapshot:
        mmi_block = _mmi_section(mmi_snapshot, html=False)
        if mmi_block:
            lines.append("")
            lines.append(mmi_block)

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


def notify_all(sig: Signal, mmi_snapshot: dict[str, Any] | None = None, lowest_pe: list[dict] | None = None) -> dict[str, bool]:
    return {
        "telegram": send_telegram(format_message(sig, mmi_snapshot=mmi_snapshot, lowest_pe=lowest_pe)),
        "ntfy": send_ntfy(format_ntfy(sig, mmi_snapshot=mmi_snapshot, lowest_pe=lowest_pe)),
    }
