"""AI analysis: JSON extraction, per-stock validation, graceful degrade, and the
`ai` block shape. All offline (LLM monkeypatched)."""

from nifty_signal.llm import analysis


def _metrics():
    return {"stocks": [
        {"symbol": "A", "sector": "Energy", "pe": 6.0, "pb": 0.8, "roe": 22.0,
         "de": 0.3, "rev_growth": 15.0, "r_1y": 30.0, "value_score": 1.2, "rp_rank": 1},
        {"symbol": "B", "sector": "Auto", "pe": 8.0, "value_score": 0.9, "rp_rank": 2},
        {"symbol": "C", "value_score": None},  # no rp_rank => not a top pick
    ]}


def test_extract_json_from_fenced_array():
    txt = '```json\n[{"symbol":"A","why_cheap":"x","key_risk":"y"}]\n```'
    out = analysis._extract_json(txt)
    assert out == [{"symbol": "A", "why_cheap": "x", "key_risk": "y"}]


def test_extract_json_none_on_garbage():
    assert analysis._extract_json("no json here") is None


def test_analyse_none_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(analysis, "complete", lambda p: None)
    assert analysis.analyse(_metrics(), "STRONG BUY", 72.0) is None


def test_analyse_builds_block(monkeypatch):
    def fake(prompt: str) -> str:
        if "JSON array" in prompt:
            return '[{"symbol":"A","why_cheap":"low PE high ROE","key_risk":"cyclical"},' \
                   '{"symbol":"B","why_cheap":"cheap auto","key_risk":"demand"}]'
        return "Market cheap; add on the shortlist."
    monkeypatch.setattr(analysis, "complete", fake)
    ai = analysis.analyse(_metrics(), "STRONG BUY", 72.0)
    assert ai["disclaimer"] == analysis.DISCLAIMER
    assert ai["daily"].startswith("Market cheap")
    assert [s["symbol"] for s in ai["stocks"]] == ["A", "B"]
    assert ai["stocks"][0]["key_risk"] == "cyclical"


def test_stock_summaries_drops_unknown_symbols(monkeypatch):
    # LLM hallucinates a symbol not in the shortlist => filtered out
    monkeypatch.setattr(analysis, "complete",
                        lambda p: '[{"symbol":"ZZZ","why_cheap":"x","key_risk":"y"}]')
    top = _metrics()["stocks"][:2]
    assert analysis._stock_summaries(top) == []


def test_analyse_daily_only_when_stocks_fail(monkeypatch):
    # daily returns text, per-stock returns unparseable => block still built (daily-only)
    def fake(prompt: str) -> str:
        return "not json" if "JSON array" in prompt else "Neutral read today."
    monkeypatch.setattr(analysis, "complete", fake)
    ai = analysis.analyse(_metrics(), "ACCUMULATE", 60.0)
    assert ai["daily"] == "Neutral read today."
    assert ai["stocks"] == []
