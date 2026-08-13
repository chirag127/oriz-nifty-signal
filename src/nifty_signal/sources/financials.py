"""Per-stock annual financials + Piotroski F-score, D/E, EV/EBITDA, P/FCF, PEG.

Enrichment pass over a SHORTLIST (~40-60 sids). Per-stock keyless fetch,
fully resilient: one bad stock never raises — it is skipped + logged.

DATA SOURCES (keyless GET, VERIFIED 2026-08-13; UA + Referer tickertape.in):
- income:   api.tickertape.in/stocks/financials/income/{sid}/annual/normal
- balance:  api.tickertape.in/stocks/financials/balancesheet/{sid}/annual/normal
- cashflow: api.tickertape.in/stocks/financials/cashflow/{sid}/annual/normal
Each => {"success":true,"data":[{displayPeriod:"FY 2025",endDate,...fields},...]}.
Income has a trailing "TTM" period; balance/cashflow are FY-only. We keep only
periods whose displayPeriod startswith "FY"; curr = last FY, prev = 2nd-last FY.
Monetary values share one unit (INR crore-ish) — ratios are unit-agnostic.

FIELD MAP:
  income:   incNinc net-income · incEbi EBIT · incPbt pre-tax · incTrev total-rev
            incDep depreciation · incEps EPS · incRaw raw-material (for gross margin)
  balance:  balTota total-assets · balTltd long-term-debt · balTdeb total-debt
            balTca total-current-assets · balTcl total-current-liab · balTeq equity
            balTcso total-common-shares-out · balTinv inventory
  cashflow: cafCfoa CFO · cafFcf FCF · cafCexp capex

PIOTROSKI F-SCORE (9 pts, 1 each, curr vs prev FY). ROA = incNinc/balTota using
CURRENT-year total assets (standard uses avg assets — single-year is fine here).
  Profitability (4): 1 ROA>0 (incNinc>0) · 2 CFO>0 (cafCfoa>0) ·
    3 ROA_curr>ROA_prev · 4 accruals CFO>net-income (cafCfoa>incNinc)
  Leverage/liquidity (3): 5 LT-debt ratio down (balTltd/balTota curr<prev) ·
    6 current ratio up (balTca/balTcl curr>prev) · 7 no new shares (balTcso curr<=prev)
  Efficiency (2): 8 margin up YoY — GROSS margin (incTrev-incRaw)/incTrev when
    incRaw present, ELSE OPERATING margin incEbi/incTrev (component records which) ·
    9 asset turnover up (incTrev/balTota curr>prev)
A component with a missing field is SKIPPED (not faked); f_score = sum of TRUE
among computed; f_components_computed = how many of 9 were computable.

DERIVED RATIOS (market data passed by caller — screener sweep already has them):
  debt_to_equity = balTdeb/balTeq                 (None if equity<=0)
  ev_ebitda      = ev/(incEbi+incDep)             (None if EBITDA<=0)
  p_fcf          = mcap/cafFcf                     (None if fcf<=0)
  fcf_yield      = cafFcf/mcap  (=1/p_fcf)         (None if mcap<=0 or fcf<=0)
  peg            = pe/earnings_growth_pct          (None if growth<=0/pe<=0/prev-ni<=0)
    earnings_growth_pct = (incNinc_curr-incNinc_prev)/abs(incNinc_prev)*100
"""

from __future__ import annotations

import logging

from ..util import fetch_json

log = logging.getLogger("nifty_signal")

_BASE = "https://api.tickertape.in/stocks/financials"
_REFERER = "https://www.tickertape.in/"


def _fetch(kind: str, sid: str) -> list[dict]:
    url = f"{_BASE}/{kind}/{sid}/annual/normal"
    data = fetch_json(url, referer=_REFERER).get("data", [])
    return [p for p in data if isinstance(p, dict) and str(p.get("displayPeriod", "")).startswith("FY")]


def _statements(sid: str) -> tuple[list[dict], list[dict], list[dict]]:
    """(income, balance, cashflow) FY-only period lists. Monkeypatch this in tests."""
    return _fetch("income", sid), _fetch("balancesheet", sid), _fetch("cashflow", sid)


def _g(period: dict, key: str) -> float | None:
    v = period.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _piotroski(inc: list[dict], bal: list[dict], caf: list[dict]) -> tuple[int, dict, int]:
    ic, ip = inc[-1], inc[-2]
    bc, bp = bal[-1], bal[-2]
    cc = caf[-1]

    comps: dict[str, bool] = {}

    def add(name: str, *needed: float | None, test):
        if any(x is None for x in needed):
            return  # missing field -> skip, don't fake
        comps[name] = bool(test())

    ni_c, ni_p = _g(ic, "incNinc"), _g(ip, "incNinc")
    ta_c, ta_p = _g(bc, "balTota"), _g(bp, "balTota")
    cfo = _g(cc, "cafCfoa")

    add("roa_positive", ni_c, test=lambda: ni_c > 0)
    add("cfo_positive", cfo, test=lambda: cfo > 0)
    add("roa_increase", ni_c, ta_c, ni_p, ta_p, test=lambda: (ni_c / ta_c) > (ni_p / ta_p) if ta_c and ta_p else False)
    add("accruals", cfo, ni_c, test=lambda: cfo > ni_c)

    ltd_c, ltd_p = _g(bc, "balTltd"), _g(bp, "balTltd")
    add("ltdebt_decrease", ltd_c, ta_c, ltd_p, ta_p, test=lambda: (ltd_c / ta_c) < (ltd_p / ta_p) if ta_c and ta_p else False)

    ca_c, cl_c = _g(bc, "balTca"), _g(bc, "balTcl")
    ca_p, cl_p = _g(bp, "balTca"), _g(bp, "balTcl")
    add("currentratio_increase", ca_c, cl_c, ca_p, cl_p, test=lambda: (ca_c / cl_c) > (ca_p / cl_p) if cl_c and cl_p else False)

    sh_c, sh_p = _g(bc, "balTcso"), _g(bp, "balTcso")
    add("no_new_shares", sh_c, sh_p, test=lambda: sh_c <= sh_p)

    # margin: gross if raw-material present, else operating (record which)
    rev_c, rev_p = _g(ic, "incTrev"), _g(ip, "incTrev")
    raw_c, raw_p = _g(ic, "incRaw"), _g(ip, "incRaw")
    if raw_c is not None and raw_p is not None:
        add("gross_margin_increase", rev_c, rev_p, raw_c, raw_p,
            test=lambda: ((rev_c - raw_c) / rev_c) > ((rev_p - raw_p) / rev_p) if rev_c and rev_p else False)
    else:
        ebit_c, ebit_p = _g(ic, "incEbi"), _g(ip, "incEbi")
        add("opmargin_increase", ebit_c, rev_c, ebit_p, rev_p,
            test=lambda: (ebit_c / rev_c) > (ebit_p / rev_p) if rev_c and rev_p else False)

    add("assetturnover_increase", rev_c, ta_c, rev_p, ta_p, test=lambda: (rev_c / ta_c) > (rev_p / ta_p) if ta_c and ta_p else False)

    return sum(1 for v in comps.values() if v), comps, len(comps)


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None


def stock_financials(
    sid: str, *, pe: float | None = None, mcap: float | None = None, ev: float | None = None
) -> dict | None:
    """Fetch annual statements for `sid` + compute F-score and derived ratios.
    Returns None on fetch failure. Needs >=2 FY periods per statement."""
    try:
        inc, bal, caf = _statements(sid)
    except Exception as e:  # noqa: BLE001 — resilient enrichment: one bad stock never fatal
        log.warning("financials fetch failed sid=%s: %s", sid, e)
        return None
    if len(inc) < 2 or len(bal) < 2 or len(caf) < 2:
        log.warning("financials sid=%s: <2 FY periods (inc=%d bal=%d caf=%d)", sid, len(inc), len(bal), len(caf))
        return None

    f_score, f_components, f_computed = _piotroski(inc, bal, caf)

    ic, bc, cc = inc[-1], bal[-1], caf[-1]
    ni_c, ni_p = _g(ic, "incNinc"), _g(inc[-2], "incNinc")
    ebit, dep = _g(ic, "incEbi"), _g(ic, "incDep")
    tdeb, teq = _g(bc, "balTdeb"), _g(bc, "balTeq")
    fcf = _g(cc, "cafFcf")

    debt_to_equity = tdeb / teq if (tdeb is not None and teq and teq > 0) else None

    ebitda = (ebit + dep) if (ebit is not None and dep is not None) else None
    ev_ebitda = ev / ebitda if (ev is not None and ebitda and ebitda > 0) else None

    p_fcf = mcap / fcf if (mcap is not None and fcf and fcf > 0) else None
    fcf_yield = fcf / mcap if (fcf is not None and fcf > 0 and mcap and mcap > 0) else None

    earnings_growth_pct = None
    if ni_c is not None and ni_p is not None and ni_p > 0:
        earnings_growth_pct = (ni_c - ni_p) / abs(ni_p) * 100.0
    peg = None
    if (pe is not None and pe > 0 and earnings_growth_pct is not None and earnings_growth_pct > 0):
        peg = pe / earnings_growth_pct

    return {
        "f_score": f_score,
        "f_components": f_components,
        "f_components_computed": f_computed,
        "debt_to_equity": _r(debt_to_equity),
        "ev_ebitda": _r(ev_ebitda),
        "p_fcf": _r(p_fcf),
        "fcf_yield": _r(fcf_yield, 4),
        "peg": _r(peg),
        "earnings_growth_pct": _r(earnings_growth_pct),
    }


def enrich_many(sids: list[str], meta: dict[str, dict]) -> dict[str, dict]:
    """{sid: stock_financials(...)} over `sids`, fetched concurrently (16 workers).
    meta[sid]={pe,mcap,ev} (any None). Skips sids that fail. Keyless."""
    from ..util import map_concurrent

    def one(sid: str) -> dict | None:
        m = meta.get(sid, {})
        return stock_financials(sid, pe=m.get("pe"), mcap=m.get("mcap"), ev=m.get("ev"))

    return map_concurrent(one, sids, workers=16)
