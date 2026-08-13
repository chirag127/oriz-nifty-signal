"""financials: Piotroski F-score + derived-ratio math on synthetic statements.

Monkeypatch `_statements` to feed synthetic (income, balance, cashflow) FY lists;
no network. Two FY periods each: index -2 = prev, -1 = curr.
"""

import pytest

from nifty_signal.sources import financials


def _fy(n: int) -> str:
    return f"FY {n}"


def _set(monkeypatch, inc, bal, caf):
    monkeypatch.setattr(financials, "_statements", lambda sid: (inc, bal, caf))


# --- synthetic builders: [prev, curr] ------------------------------------

def _perfect():
    """All 9 improve curr>prev; gross-margin path (incRaw present)."""
    inc = [
        {"displayPeriod": _fy(2024), "incNinc": 100, "incEbi": 150, "incTrev": 1000, "incDep": 50, "incRaw": 600},
        {"displayPeriod": _fy(2025), "incNinc": 200, "incEbi": 320, "incTrev": 1300, "incDep": 60, "incRaw": 700},
    ]
    bal = [
        {"displayPeriod": _fy(2024), "balTota": 2000, "balTltd": 400, "balTdeb": 500, "balTca": 800, "balTcl": 400, "balTeq": 1000, "balTcso": 100},
        {"displayPeriod": _fy(2025), "balTota": 2100, "balTltd": 300, "balTdeb": 350, "balTca": 1200, "balTcl": 300, "balTeq": 1400, "balTcso": 100},
    ]
    caf = [
        {"displayPeriod": _fy(2024), "cafCfoa": 120, "cafFcf": 90, "cafCexp": -30},
        {"displayPeriod": _fy(2025), "cafCfoa": 260, "cafFcf": 200, "cafCexp": -40},
    ]
    return inc, bal, caf


def _weak():
    """Losses, negative trends, dilution -> ~0-2."""
    inc = [
        {"displayPeriod": _fy(2024), "incNinc": -50, "incEbi": -20, "incTrev": 900, "incDep": 40, "incRaw": 500},
        {"displayPeriod": _fy(2025), "incNinc": -120, "incEbi": -80, "incTrev": 700, "incDep": 45, "incRaw": 500},
    ]
    bal = [
        {"displayPeriod": _fy(2024), "balTota": 2000, "balTltd": 300, "balTdeb": 400, "balTca": 900, "balTcl": 300, "balTeq": 800, "balTcso": 100},
        {"displayPeriod": _fy(2025), "balTota": 2200, "balTltd": 500, "balTdeb": 700, "balTca": 700, "balTcl": 400, "balTeq": 600, "balTcso": 130},
    ]
    caf = [
        {"displayPeriod": _fy(2024), "cafCfoa": 30, "cafFcf": 10, "cafCexp": -20},
        {"displayPeriod": _fy(2025), "cafCfoa": -40, "cafFcf": -80, "cafCexp": -40},
    ]
    return inc, bal, caf


# --- Piotroski --------------------------------------------------------------

def test_perfect_nine(monkeypatch):
    _set(monkeypatch, *_perfect())
    r = financials.stock_financials("PERF")
    assert r["f_components_computed"] == 9
    assert r["f_score"] == 9
    assert all(r["f_components"].values())
    assert "gross_margin_increase" in r["f_components"]


def test_weak_low_score(monkeypatch):
    _set(monkeypatch, *_weak())
    r = financials.stock_financials("WEAK")
    assert r["f_components_computed"] == 9
    assert r["f_score"] <= 2


def test_operating_margin_fallback(monkeypatch):
    """No incRaw -> operating-margin component used."""
    inc, bal, caf = _perfect()
    for p in inc:
        p.pop("incRaw")
    _set(monkeypatch, inc, bal, caf)
    r = financials.stock_financials("OPM")
    assert "opmargin_increase" in r["f_components"]
    assert "gross_margin_increase" not in r["f_components"]


def test_missing_field_skips_component(monkeypatch):
    """Drop balTcso from both periods -> no_new_shares uncomputable."""
    inc, bal, caf = _perfect()
    for p in bal:
        p.pop("balTcso")
    _set(monkeypatch, inc, bal, caf)
    r = financials.stock_financials("MISS")
    assert r["f_components_computed"] == 8
    assert "no_new_shares" not in r["f_components"]
    assert r["f_score"] == 8


# --- derived ratios ---------------------------------------------------------

def test_derived_ratios_numeric(monkeypatch):
    _set(monkeypatch, *_perfect())
    # curr: balTdeb=350 balTeq=1400 -> D/E 0.25; EBITDA=320+60=380, ev=3800 -> 10.0;
    # fcf=200 mcap=4000 -> p_fcf 20.0, fcf_yield 0.05;
    # ni 100->200 growth=100%, pe=30 -> peg 0.30
    r = financials.stock_financials("PERF", pe=30.0, mcap=4000.0, ev=3800.0)
    assert r["debt_to_equity"] == 0.25
    assert r["ev_ebitda"] == 10.0
    assert r["p_fcf"] == 20.0
    assert r["fcf_yield"] == 0.05
    assert r["earnings_growth_pct"] == 100.0
    assert r["peg"] == 0.3


def test_ratios_none_on_bad_inputs(monkeypatch):
    inc, bal, caf = _perfect()
    bal[-1]["balTeq"] = 0          # D/E None
    caf[-1]["cafFcf"] = -10        # p_fcf, fcf_yield None
    _set(monkeypatch, inc, bal, caf)
    r = financials.stock_financials("BAD", pe=30.0, mcap=4000.0, ev=3800.0)
    assert r["debt_to_equity"] is None
    assert r["p_fcf"] is None
    assert r["fcf_yield"] is None


def test_peg_none_on_earnings_decline(monkeypatch):
    inc, bal, caf = _perfect()
    inc[-1]["incNinc"] = 50        # 100 -> 50, negative growth
    _set(monkeypatch, inc, bal, caf)
    r = financials.stock_financials("DECL", pe=30.0)
    assert r["peg"] is None
    assert r["earnings_growth_pct"] == -50.0


def test_peg_none_on_prior_loss(monkeypatch):
    inc, bal, caf = _perfect()
    inc[-2]["incNinc"] = -10       # can't PEG a turnaround
    _set(monkeypatch, inc, bal, caf)
    r = financials.stock_financials("TURN", pe=30.0)
    assert r["peg"] is None
    assert r["earnings_growth_pct"] is None


# --- public surface ---------------------------------------------------------

def test_returns_none_on_fetch_failure(monkeypatch):
    def boom(sid):
        raise RuntimeError("network")
    monkeypatch.setattr(financials, "_statements", boom)
    assert financials.stock_financials("X") is None


def test_returns_none_on_single_period(monkeypatch):
    inc, bal, caf = _perfect()
    _set(monkeypatch, inc[-1:], bal, caf)
    assert financials.stock_financials("Y") is None


def test_enrich_many_skips_failures(monkeypatch):
    good = _perfect()

    def statements(sid):
        if sid == "OK":
            return good
        raise RuntimeError("fail")
    monkeypatch.setattr(financials, "_statements", statements)
    out = financials.enrich_many(["OK", "FAIL"], {"OK": {"pe": 30.0, "mcap": 4000.0, "ev": 3800.0}})
    assert set(out) == {"OK"}
    assert out["OK"]["f_score"] == 9
