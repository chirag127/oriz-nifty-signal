"""Pipeline (verdict build + snapshot) + notify + LLM fallback tests (no network)."""

import json
from pathlib import Path

from nifty_signal.llm.summary import _template, commentary
from nifty_signal.models import Indicator, Signal
from nifty_signal.notify.channels import (
    format_message,
    format_ntfy,
    send_ntfy,
    send_telegram,
)
from nifty_signal.pipeline import build_signal, write_snapshot
from nifty_signal.util import composite_score, verdict_label


def _inds():
    return [
        Indicator("nifty_pe", "Nifty 50 PE", 20.91, "x", "fair", 61.0),
        Indicator("nifty500_pe", "Nifty 500 PE (breadth)", 23.26, "x", "fair", 60.0),
        Indicator("buffett", "Buffett indicator", 137.4, "%", "overvalued", 24.0),
        Indicator("mmi", "Market Mood (MMI)", 74.4, "", "Extreme Greed", 25.6),
    ]


def _signal():
    inds = _inds()
    score = composite_score({i.key: i.score for i in inds})
    sig = Signal(verdict_label(score), score, "rationale", ts="2026-08-05T10:00:00+00:00", indicators=inds)
    return sig


def test_build_signal_monkeypatched(monkeypatch):
    monkeypatch.setattr("nifty_signal.pipeline.collect", lambda: (_inds(), []))
    sig, errors = build_signal()
    assert sig.verdict in {"STRONG BUY", "ACCUMULATE", "HOLD-SIP-ONLY", "CAUTION"}
    assert 0 <= sig.verdict_score <= 100
    assert len(sig.indicators) == 4
    assert errors == []


def test_write_snapshot_creates_latest_and_history(tmp_path: Path):
    write_snapshot(_signal(), ["buffett: n/a"], tmp_path)
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["verdict"]
    assert len(latest["indicators"]) == 4
    assert latest["errors"] == ["buffett: n/a"]
    hist = json.loads((tmp_path / "history" / "2026-08-05.json").read_text(encoding="utf-8"))
    assert len(hist) == 1
    assert "score" in hist[0]


def test_history_appends(tmp_path: Path):
    write_snapshot(_signal(), [], tmp_path)
    write_snapshot(_signal(), [], tmp_path)
    hist = json.loads((tmp_path / "history" / "2026-08-05.json").read_text(encoding="utf-8"))
    assert len(hist) == 2


def test_format_message_html():
    sig = _signal()
    sig.summary = "test take"
    m = format_message(sig)
    assert sig.verdict in m
    assert "nifty-signal.oriz.in" in m
    assert "Nifty 50 PE" in m


def test_format_ntfy_plain():
    m = format_ntfy(_signal())
    assert "<" not in m
    assert "nifty-signal.oriz.in" in m


def test_notifiers_noop_without_env(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC"):
        monkeypatch.delenv(k, raising=False)
    assert send_telegram("hi") is False
    assert send_ntfy("hi") is False


def test_template_commentary():
    out = _template(_signal())
    assert "score" in out.lower()
    assert "Nifty 50 PE" in out


def test_commentary_falls_back_without_llm(monkeypatch):
    monkeypatch.setenv("NIFTY_DISABLE_LLM", "1")
    out = commentary(_signal())
    assert isinstance(out, str) and len(out) > 10
