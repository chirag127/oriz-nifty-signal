"""AI analysis: JSON extraction, per-stock validation, graceful degrade, and the
`ai` block shape. All offline (LLM monkeypatched)."""

from nifty_signal.llm import analysis


def _metrics():
    return {"stocks": [
        {"symbol": "A", "sector": "Energy", "pe": 6.0, "pb": 0.8, "roe": 22.0,
         "de": 0.3, "rev_growth": 15.0, "r_1y": 30.0, "value_score": 85.0, "rp_rank": 1,
         "scans": ["graham", "magic_q1", "piotroski8"]},
        {"symbol": "B", "sector": "Auto", "pe": 8.0, "value_score": 60.0, "rp_rank": 2,
         "scans": ["quality"]},
        {"symbol": "C", "value_score": None},  # no rp_rank => not a top pick
    ], "scan_labels": {"graham": "Graham Defensive", "magic_q1": "Magic Formula (top quartile)",
                       "piotroski8": "Piotroski 8-9", "quality": "Quality"}}


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
    # scan-membership emitted per pick (site + AI share it)
    assert ai["stocks"][0]["scans"] == ["graham", "magic_q1", "piotroski8"]


def test_scan_membership_survives_llm_failure(monkeypatch):
    # LLM returns unparseable => why_cheap/key_risk empty but scans still emitted
    monkeypatch.setattr(analysis, "complete",
                        lambda p: "not json" if "JSON array" in p else "Read.")
    ai = analysis.analyse(_metrics(), "ACCUMULATE", 60.0)
    a = next(s for s in ai["stocks"] if s["symbol"] == "A")
    assert a["scans"] == ["graham", "magic_q1", "piotroski8"]
    assert a["why_cheap"] == "" and a["key_risk"] == ""


def test_stock_facts_cites_scans():
    s = _metrics()["stocks"][0]
    labels = _metrics()["scan_labels"]
    line = analysis._stock_facts(s, labels)
    assert "Graham Defensive" in line and "Piotroski 8-9" in line


def test_stock_summaries_ignores_hallucinated_symbols(monkeypatch):
    # LLM hallucinates a symbol not in shortlist => its text ignored; real picks kept
    monkeypatch.setattr(analysis, "complete",
                        lambda p: '[{"symbol":"ZZZ","why_cheap":"x","key_risk":"y"}]')
    top = _metrics()["stocks"][:2]
    out = analysis._stock_summaries(top, _metrics()["scan_labels"])
    assert [s["symbol"] for s in out] == ["A", "B"]
    assert all(s["why_cheap"] == "" for s in out)   # hallucinated text not attached


def test_analyse_daily_only_when_stocks_fail(monkeypatch):
    # daily returns text, per-stock unparseable => block built; picks carry scans, no LLM text
    def fake(prompt: str) -> str:
        return "not json" if "JSON array" in prompt else "Neutral read today."
    monkeypatch.setattr(analysis, "complete", fake)
    ai = analysis.analyse(_metrics(), "ACCUMULATE", 60.0)
    assert ai["daily"] == "Neutral read today."
    assert [s["symbol"] for s in ai["stocks"]] == ["A", "B"]
