"""Pipeline (verdict build + snapshot) + notify + LLM fallback tests (no network)."""

import json
from pathlib import Path

import pytest

from nifty_signal.llm.sentiment import Sentiment, _parse_sentiment, _template_sentiment
from nifty_signal.llm.summary import _template, commentary
from nifty_signal.models import Indicator, Signal
from nifty_signal.notify.channels import (
    format_message,
    format_ntfy,
    send_ntfy,
    send_telegram,
)
from nifty_signal.pipeline import build_signal, write_snapshot
from nifty_signal.util import composite_score, score_news_sentiment, verdict_label

FIX = Path(__file__).parent / "fixtures"


def _inds():
    return [
        Indicator("nifty_pe", "Nifty 50 PE", 20.91, "x", "fair", 61.0),
        Indicator("nifty500_pe", "Nifty 500 PE (breadth)", 23.26, "x", "fair", 60.0),
        Indicator("buffett", "Buffett indicator", 137.4, "%", "overvalued", 24.0),
        Indicator("mmi", "Market Mood (MMI)", 74.4, "", "Extreme Greed", 25.6),
        Indicator("midcap_pe", "Nifty Midcap 100 PE", 30.92, "x", "expensive", None),
        Indicator("smallcap_pe", "Nifty Smallcap 100 PE", 31.89, "x", "frothy", None),
    ]


def _signal():
    inds = _inds()
    score = composite_score({i.key: i.score for i in inds if i.score is not None})
    sig = Signal(verdict_label(score), score, "rationale", ts="2026-08-05T10:00:00+00:00", indicators=inds)
    return sig


def _mmi_snapshot():
    return json.loads((FIX / "mmi_latest.json").read_text(encoding="utf-8"))


# ---- composite / verdict ----------------------------------------------------

def test_build_signal_monkeypatched(monkeypatch):
    monkeypatch.setattr("nifty_signal.pipeline.collect", lambda: (_inds(), []))
    monkeypatch.setattr("nifty_signal.pipeline.fetch_headlines", lambda: [])
    monkeypatch.setattr("nifty_signal.pipeline.analyse_sentiment", lambda h: None)
    sig, errors = build_signal()
    assert sig.verdict in {"STRONG BUY", "ACCUMULATE", "HOLD-SIP-ONLY", "CAUTION"}
    assert 0 <= sig.verdict_score <= 100
    assert errors == []


def test_segment_indicators_excluded_from_composite():
    # midcap_pe / smallcap_pe have score=None → never enter composite
    scores = {i.key: i.score for i in _inds() if i.score is not None}
    assert "midcap_pe" not in scores
    assert "smallcap_pe" not in scores
    score = composite_score(scores)
    assert 0 <= score <= 100


def test_write_snapshot_creates_latest_and_history(tmp_path: Path):
    write_snapshot(_signal(), ["buffett: n/a"], tmp_path)
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["verdict"]
    assert len(latest["indicators"]) == 6
    assert latest["errors"] == ["buffett: n/a"]
    hist = json.loads((tmp_path / "history" / "2026-08-05.json").read_text(encoding="utf-8"))
    assert len(hist) == 1
    assert "score" in hist[0]


def test_history_appends(tmp_path: Path):
    write_snapshot(_signal(), [], tmp_path)
    write_snapshot(_signal(), [], tmp_path)
    hist = json.loads((tmp_path / "history" / "2026-08-05.json").read_text(encoding="utf-8"))
    assert len(hist) == 2


# ---- combined message formatter ---------------------------------------------

def test_format_message_html_with_mmi():
    sig = _signal()
    sig.summary = "test take"
    mmi = _mmi_snapshot()
    m = format_message(sig, mmi_snapshot=mmi)
    assert sig.verdict in m
    assert "nifty-signal.oriz.in" in m
    assert "mmi.oriz.in" in m
    assert "MMI" in m
    assert "72.1" in m or "72.09" in m or "72" in m


def test_format_message_html_without_mmi():
    sig = _signal()
    m = format_message(sig, mmi_snapshot=None)
    assert sig.verdict in m
    assert "nifty-signal.oriz.in" in m
    assert "mmi.oriz.in" not in m


def test_format_message_contains_segment_breakdown():
    sig = _signal()
    m = format_message(sig, mmi_snapshot=None)
    # segment line should contain Mid or Small
    assert "Mid" in m or "Midcap" in m or "Large" in m


def test_format_ntfy_with_mmi():
    sig = _signal()
    m = format_ntfy(sig, mmi_snapshot=_mmi_snapshot())
    assert "<" not in m
    assert "nifty-signal.oriz.in" in m
    assert "MMI" in m
    assert "mmi.oriz.in" in m


def test_format_ntfy_without_mmi():
    m = format_ntfy(_signal(), mmi_snapshot=None)
    assert "<" not in m
    assert "nifty-signal.oriz.in" in m


_LOWPE = [{"symbol": "HINDPETRO", "pe": 4.61}, {"symbol": "IOC", "pe": 4.7}, {"symbol": "PFC", "pe": 4.85}]


def test_format_message_includes_lowest_pe():
    m = format_message(_signal(), mmi_snapshot=None, lowest_pe=_LOWPE)
    assert "Cheapest Nifty 500 by PE" in m
    assert "HINDPETRO" in m and "4.61x" in m


def test_format_ntfy_includes_lowest_pe():
    m = format_ntfy(_signal(), mmi_snapshot=None, lowest_pe=_LOWPE)
    assert "<" not in m
    assert "Cheapest Nifty 500 by PE" in m
    assert "HINDPETRO 4.61x" in m


def test_lowest_pe_omitted_when_empty():
    m = format_message(_signal(), mmi_snapshot=None, lowest_pe=[])
    assert "Cheapest Nifty 500" not in m


def test_write_snapshot_writes_lowest_pe_file(tmp_path: Path):
    write_snapshot(_signal(), [], tmp_path, lowest_pe=_LOWPE)
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["lowest_pe"] == _LOWPE
    lp = json.loads((tmp_path / "lowest_pe_nifty500.json").read_text(encoding="utf-8"))
    assert lp["stocks"] == _LOWPE
    assert lp["ts"]


def test_notifiers_noop_without_env(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC"):
        monkeypatch.delenv(k, raising=False)
    assert send_telegram("hi") is False
    assert send_ntfy("hi") is False


# ---- sentiment --------------------------------------------------------------

def test_parse_sentiment_valid():
    raw = '{"sentiment": "bearish", "confidence": 70, "one_line": "Caution warranted."}'
    s = _parse_sentiment(raw)
    assert s is not None
    assert s["sentiment"] == "bearish"
    assert s["confidence"] == 70
    assert s["one_line"] == "Caution warranted."


def test_parse_sentiment_with_markdown_fence():
    raw = '```json\n{"sentiment": "bullish", "confidence": 60, "one_line": "OK"}\n```'
    s = _parse_sentiment(raw)
    assert s is not None
    assert s["sentiment"] == "bullish"


def test_parse_sentiment_invalid_returns_none():
    assert _parse_sentiment("not json at all") is None


def test_parse_sentiment_unknown_sentiment_normalises():
    raw = '{"sentiment": "unknown_xyz", "confidence": 50, "one_line": "test"}'
    s = _parse_sentiment(raw)
    assert s is not None
    assert s["sentiment"] == "neutral"


def test_template_sentiment_bullish():
    headlines = [
        {"title": "Nifty rally surge record high", "snippet": "buy strong bull", "url": "", "source": ""},
    ]
    s = _template_sentiment(headlines)
    assert s["sentiment"] == "bullish"


def test_template_sentiment_bearish():
    headlines = [
        {"title": "Nifty crash decline risk concern fall weak", "snippet": "bear sell low", "url": "", "source": ""},
    ]
    s = _template_sentiment(headlines)
    assert s["sentiment"] == "bearish"


def test_score_news_sentiment_bounds():
    from nifty_signal.util import score_news_sentiment
    assert 0 <= score_news_sentiment("bullish", 100) <= 100
    assert 0 <= score_news_sentiment("bearish", 100) <= 100
    assert score_news_sentiment("neutral", 100) == 50.0
    # bearish contrarian -> higher buy score than bullish
    assert score_news_sentiment("bearish", 80) > score_news_sentiment("bullish", 80)


# ---- LLM summary fallback ---------------------------------------------------

def test_template_commentary():
    out = _template(_signal())
    assert "score" in out.lower()
    assert "Nifty 50 PE" in out


def test_commentary_falls_back_without_llm(monkeypatch):
    monkeypatch.setenv("NIFTY_DISABLE_LLM", "1")
    out = commentary(_signal())
    assert isinstance(out, str) and len(out) > 10


def test_format_message_renders_top_picks():
    picks_mtf = [{"symbol": "RELIANCE"}, {"symbol": "TCS"}]
    picks_val = [{"symbol": "IOC"}]
    html = format_message(_signal(), top_mtf=picks_mtf, top_value=picks_val)
    assert "Top MTF buy-and-hold" in html and "RELIANCE" in html and "IOC" in html
    txt = format_ntfy(_signal(), top_mtf=picks_mtf, top_value=picks_val)
    assert "Top value" in txt and "TCS" in txt


def test_notify_all_accepts_top_picks_kwargs(monkeypatch):
    # regression: pipeline passes top_mtf/top_value on STRONG BUY — must not TypeError
    from nifty_signal.notify import channels
    monkeypatch.setattr(channels, "send_telegram", lambda msg: True)
    monkeypatch.setattr(channels, "send_ntfy", lambda msg: True)
    out = channels.notify_all(_signal(), lowest_pe=[{"symbol": "IOC", "pe": 4.7}],
                              top_mtf=[{"symbol": "RELIANCE"}], top_value=[{"symbol": "TCS"}])
    assert out == {"telegram": True, "ntfy": True}


# ---- integration: live network (skip if offline) ----------------------------

@pytest.mark.integration
def test_news_fetch_live():
    """Fetch real headlines via ddgs — skip if offline."""
    pytest.importorskip("ddgs")
    from nifty_signal.sources.news import fetch_headlines
    headlines = fetch_headlines()
    # may be empty if network blocked; just check shape
    for h in headlines:
        assert "title" in h and "snippet" in h and "url" in h


@pytest.mark.integration
def test_kilo_sentiment_live():
    """Call kilo.ai LLM — skip if offline."""
    import httpx
    from nifty_signal.llm.sentiment import analyse_sentiment
    from nifty_signal.sources.news import Headline
    headlines = [
        Headline(title="Nifty 50 at 24000 levels, valuation fair says analyst",
                 snippet="Experts say Indian equities are fairly valued at current PE of 21x.",
                 url="https://example.com/1", source="test"),
        Headline(title="FII selling continues, markets cautious",
                 snippet="Foreign investors pulled out 1500 crore in the last session.",
                 url="https://example.com/2", source="test"),
    ]
    try:
        result = analyse_sentiment(headlines)
    except httpx.ConnectError:
        pytest.skip("network unavailable")
    assert result is not None
    assert result["sentiment"] in {"bullish", "neutral", "bearish"}
    assert 0 <= result["confidence"] <= 100
    assert result["one_line"]
    # Print actual output for the task report
    print(f"\nkilo LLM sentiment: {result}")
