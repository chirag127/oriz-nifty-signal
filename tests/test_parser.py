"""Parser tests against real-shape fixtures (no network)."""

import json
from pathlib import Path

from nifty_signal.sources.buffett import BuffettIndicator
from nifty_signal.sources.mmi import parse_mmi
from nifty_signal.sources.nifty_pe import (
    Nifty500PE,
    Nifty50PE,
    NiftyMidcap100PE,
    NiftySmallcap100PE,
    _parse_indexpe,
)

FIX = Path(__file__).parent / "fixtures"


def test_parse_indexpe_nifty50():
    html = (FIX / "indexpe_nifty50.html").read_text(encoding="utf-8")
    pe, median, as_of = _parse_indexpe(html)
    assert pe == 20.91
    assert median == 22.08
    assert "2026" in as_of


def test_nifty50_indicator_from_fixture(monkeypatch):
    html = (FIX / "indexpe_nifty50.html").read_text(encoding="utf-8")
    monkeypatch.setattr("nifty_signal.sources.nifty_pe.fetch_text", lambda url: html)
    ind = Nifty50PE().fetch()
    assert ind.key == "nifty_pe"
    assert ind.value == 20.91
    assert ind.zone == "fair"           # 18-22
    assert 0 <= ind.score <= 100


def test_nifty500_indicator_from_fixture(monkeypatch):
    html = (FIX / "indexpe_nifty500.html").read_text(encoding="utf-8")
    monkeypatch.setattr("nifty_signal.sources.nifty_pe.fetch_text", lambda url: html)
    ind = Nifty500PE().fetch()
    assert ind.value == 23.26
    assert ind.zone in {"cheap", "fair", "expensive", "frothy"}
    assert "23.86" in ind.detail


def test_midcap100_indicator_from_fixture(monkeypatch):
    html = (FIX / "indexpe_midcap100.html").read_text(encoding="utf-8")
    monkeypatch.setattr("nifty_signal.sources.nifty_pe.fetch_text", lambda url: html)
    ind = NiftyMidcap100PE().fetch()
    assert ind.key == "midcap_pe"
    assert ind.value == 30.92
    assert ind.score is None           # informational only
    assert "29.52" in ind.detail
    assert ind.zone in {"cheap", "fair", "expensive", "frothy"}


def test_smallcap100_indicator_from_fixture(monkeypatch):
    html = (FIX / "indexpe_smallcap100.html").read_text(encoding="utf-8")
    monkeypatch.setattr("nifty_signal.sources.nifty_pe.fetch_text", lambda url: html)
    ind = NiftySmallcap100PE().fetch()
    assert ind.key == "smallcap_pe"
    assert ind.value == 31.89
    assert ind.score is None           # informational only
    assert "28.99" in ind.detail


def test_buffett_indicator_from_fixture(monkeypatch):
    html = (FIX / "ceic_buffett.html").read_text(encoding="utf-8")
    monkeypatch.setattr("nifty_signal.sources.buffett.fetch_text", lambda url: html)
    ind = BuffettIndicator().fetch()
    assert ind.key == "buffett"
    assert ind.value == 137.4
    assert ind.zone == "overvalued"
    assert ind.unit == "%"
    assert "Dec 2025" in ind.detail


def test_parse_mmi_fixture():
    data = json.loads((FIX / "mmi_now.json").read_text(encoding="utf-8"))["data"]
    ind = parse_mmi(data)
    assert ind.key == "mmi"
    assert 0 <= ind.value <= 100
    assert ind.zone == "Extreme Greed"   # 74.4 > 70
    assert ind.score is not None


def test_parse_mmi_missing_indicator():
    import pytest

    with pytest.raises(ValueError):
        parse_mmi({"date": "x"})


def test_lowest_pe_ranks_ascending_positive(monkeypatch):
    from nifty_signal.sources import lowest_pe as lp
    monkeypatch.setattr(lp, "_nifty500_symbols", lambda: {"AAA", "BBB", "CCC", "DDD", "EEE"})
    monkeypatch.setattr(lp, "_pe_by_ticker", lambda: {
        "AAA": 30.0, "BBB": 4.0, "CCC": None, "DDD": -5.0, "EEE": 12.5, "ZZZ": 1.0,
    })
    out = lp.lowest_pe_nifty500(top=10)
    assert [r["symbol"] for r in out] == ["BBB", "EEE", "AAA"]  # None/neg dropped, ZZZ not in 500
    assert out[0]["pe"] == 4.0
    assert all(r["pe"] > 0 for r in out)


def test_lowest_pe_respects_top(monkeypatch):
    from nifty_signal.sources import lowest_pe as lp
    monkeypatch.setattr(lp, "_nifty500_symbols", lambda: {f"S{i}" for i in range(30)})
    monkeypatch.setattr(lp, "_pe_by_ticker", lambda: {f"S{i}": float(i + 1) for i in range(30)})
    assert len(lp.lowest_pe_nifty500(top=5)) == 5
