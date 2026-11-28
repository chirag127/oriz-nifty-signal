"""metrics: screener page parse, cross-sectional scoring, and enrich-merge on
synthetic data (no network). Covers z-scores, percentile VALUE composite, Graham
+ Magic-Formula preset fields, quality flag, MTF after-tax return,
return-potential, and the sid/slug extraction + financials/analyst merge into the
swept rows."""

from nifty_signal.sources import metrics


# ---- page parse (screener response shape) -----------------------------------

def _page(*stocks: dict) -> dict:
    """Real screener shape: {success, data:{results:[{stock:{info,advancedRatios,slug}}]}}."""
    return {"success": True, "data": {"results": [{"stock": s} for s in stocks]}}


def test_parse_page_maps_fields_and_sid():
    page = _page(
        {"info": {"ticker": "RELIANCE", "name": "Reliance", "sector": "Energy"},
         "slug": "/stocks/reliance-industries-RELI",
         "advancedRatios": {"apef": 22.0, "pbr": 1.6, "roe": 8.0, "ftls": 500, "52wpct": -4.3}},
    )
    rows = metrics._parse_page(page)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "RELIANCE"
    assert r["sid"] == "RELI"           # last slug segment
    assert r["pe"] == 22.0 and r["pb"] == 1.6 and r["roe"] == 8.0
    assert r["lot"] == 500              # ftls present => F&O/MTF proxy
    assert r["r_1y"] == -4.3


def test_parse_page_skips_tickerless_and_bad():
    assert metrics._parse_page({"data": {"results": [{"stock": {"info": {}}}]}}) == []
    assert metrics._parse_page(None) == []
    assert metrics._parse_page({"success": False}) == []


# ---- z-scores ----------------------------------------------------------------

def test_zscores_mean0_sd1():
    z = metrics._zscores({"a": 1.0, "b": 2.0, "c": 3.0})
    assert abs(sum(z.values())) < 1e-9          # mean 0
    assert z["a"] < z["b"] < z["c"]             # order preserved
    assert z["b"] == 0.0                         # middle == mean


def test_zscores_zero_variance():
    z = metrics._zscores({"a": 5.0, "b": 5.0})
    assert z == {"a": 0.0, "b": 0.0}


# ---- value composite + factor yields ----------------------------------------

def _rows():
    # cheap: low PE/PB/PS/EV_EBITDA => high yields; rich: opposite; loss: negatives
    return [
        {"symbol": "CHEAP", "pe": 5.0, "pb": 0.5, "ps": 0.4, "ev_ebitda": 3.0,
         "ev_ebit": 4.0, "roce": 30.0,
         "roe": 25.0, "de": 0.2, "beta": 0.9, "r_1y": 40.0,
         "rev_growth": 20.0, "eps_growth": 25.0, "lot": 500, "mcap": 50000, "div_yield": 1.0},
        {"symbol": "RICH", "pe": 60.0, "pb": 12.0, "ps": 10.0, "ev_ebitda": 40.0,
         "ev_ebit": 50.0, "roce": 9.0,
         "roe": 10.0, "de": 2.0, "beta": 1.4, "r_1y": -5.0,
         "rev_growth": 3.0, "eps_growth": 1.0, "lot": 200, "mcap": 90000, "div_yield": 0.2},
        {"symbol": "LOSS", "pe": -8.0, "pb": -1.0, "ps": 2.0, "ev_ebitda": -5.0,
         "ev_ebit": -6.0, "roce": -15.0,
         "roe": -20.0, "de": 3.0, "beta": 1.1, "r_1y": -30.0,
         "rev_growth": -10.0, "eps_growth": None, "lot": None, "mcap": 300, "div_yield": 0.0},
    ]


def test_yield_of_positive_only():
    assert metrics._yield_of({"pe": 5.0}, "pe", "inv") == 0.2
    assert metrics._yield_of({"pe": -5.0}, "pe", "inv") is None   # loss-maker not cheap
    assert metrics._yield_of({"div_yield": 2.0}, "div_yield", "raw") == 2.0
    assert metrics._yield_of({"pe": None}, "pe", "inv") is None


def test_compute_value_ranks_cheap_above_rich():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    assert by["CHEAP"]["value_score"] > by["RICH"]["value_score"]
    # loss-maker: negative pe/pb/ev excluded; only ps yield => <2 factors => no score
    assert by["LOSS"]["value_score"] is None
    # per-factor z stored for browser re-weighting
    assert "ep" in by["CHEAP"]["z"]
    assert "ep" not in by["LOSS"]["z"]           # negative earnings => no E/P


def test_value_score_needs_min_factors():
    # one row with a single valid value factor => value_score None (no domination)
    rows = [
        {"symbol": "ONE", "pe": 5.0, "pb": None, "ps": None, "ev_ebitda": None},
        {"symbol": "TWO", "pe": 6.0, "pb": 1.0, "ps": None, "ev_ebitda": None},
        {"symbol": "THREE", "pe": 7.0, "pb": 2.0, "ps": None, "ev_ebitda": None},
    ]
    by = {r["symbol"]: r for r in metrics.compute(rows)}
    assert by["ONE"]["value_score"] is None       # 1 factor < VALUE_MIN_FACTORS
    assert by["TWO"]["value_score"] is not None    # 2 factors ok


def test_zscore_winsorized():
    # one extreme outlier clamped to +/-Z_CLAMP so it can't dominate
    z = metrics._zscores({f"n{i}": 1.0 for i in range(20)} | {"OUT": 1000.0})
    assert z["OUT"] == metrics.Z_CLAMP            # clamped, not ~4.4


def test_quality_flag():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    assert by["CHEAP"]["quality_flag"] is True   # ROE 25>15, D/E 0.2<1.5, no f_score
    assert by["RICH"]["quality_flag"] is False   # ROE 10 not >15


def test_mtf_eligible_from_lot():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    assert by["CHEAP"]["mtf_eligible"] is True
    assert by["LOSS"]["mtf_eligible"] is False   # no lot => not F&O/MTF


def test_mtf_score_gated_by_beta():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    assert by["CHEAP"]["mtf_score"] is not None   # beta 0.9 < cap
    assert by["RICH"]["mtf_score"] is None        # beta 1.4 >= 1.2 cap


# ---- MTF after-tax return ----------------------------------------------------

def test_mtf_after_tax_positive():
    # 40% gross - 12% interest = 28% net; LTCG 12.5% on 28 => 24.5
    assert metrics.mtf_after_tax_return(40.0) == 24.5


def test_mtf_after_tax_below_interest_no_tax():
    # 8% gross - 12% = -4%, loss => no LTCG applied
    assert metrics.mtf_after_tax_return(8.0) == -4.0


def test_mtf_after_tax_none():
    assert metrics.mtf_after_tax_return(None) is None


# ---- return-potential composite ---------------------------------------------

def test_return_potential_needs_value_signal():
    r = {"value_score": None, "growth_score": 1.0}
    assert metrics._return_potential(r) is None
    r2 = {"value_score": 1.0, "growth_score": 0.5, "quality_score": None,
          "momentum_score": None, "analyst_score": None}
    # only value+growth present => renormalised over their weights
    assert metrics._return_potential(r2) is not None


# ---- percentile normalization (VALUE factor scale) --------------------------

def test_percentile_0_100_scale():
    p = metrics._percentile({"lo": 1.0, "mid": 2.0, "hi": 3.0})
    assert p["lo"] == 0.0 and p["hi"] == 100.0 and p["mid"] == 50.0


def test_percentile_ties_average_rank():
    p = metrics._percentile({"a": 1.0, "b": 1.0, "c": 3.0})
    assert p["a"] == p["b"]                       # ties share avg rank
    assert p["c"] == 100.0


def test_value_score_is_percentile_mean():
    # 3 rows, PE+PB present for all => each factor percentile in {0,50,100};
    # value_score = mean of the two factor percentiles (0-100 scale, not z)
    rows = metrics.compute([
        {"symbol": "A", "pe": 5.0, "pb": 0.5},    # cheapest both => 100,100
        {"symbol": "B", "pe": 10.0, "pb": 1.0},   # mid => 50,50
        {"symbol": "C", "pe": 20.0, "pb": 2.0},   # richest => 0,0
    ])
    by = {r["symbol"]: r for r in rows}
    assert by["A"]["value_score"] == 100.0
    assert by["B"]["value_score"] == 50.0
    assert by["C"]["value_score"] == 0.0
    assert 0.0 <= by["B"]["z"]["ep"] <= 100.0     # z object holds percentiles now


# ---- Graham defensive preset -------------------------------------------------

def test_graham_ok_and_score():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    # CHEAP: PE 5<15, PB 0.5<1.5, PE*PB 2.5<22.5, D/E 0.2<1 => all 4 pass
    assert by["CHEAP"]["graham_ok"] is True
    assert by["CHEAP"]["graham_score"] == 4
    # RICH: PE 60, PB 12, PE*PB 720, D/E 2 => 0 rungs
    assert by["RICH"]["graham_ok"] is False
    assert by["RICH"]["graham_score"] == 0


def test_graham_partial_and_missing():
    r = metrics.compute([
        {"symbol": "P", "pe": 10.0, "pb": 3.0, "de": 0.5},   # PE ok, PB fails, PE*PB=30 fails, D/E ok => 2
        {"symbol": "Q", "pe": 10.0, "pb": 1.0, "de": None},  # PE ok, PB ok, PE*PB=10 ok, D/E unknown fails => 3
    ])
    by = {x["symbol"]: x for x in r}
    assert by["P"]["graham_score"] == 2 and by["P"]["graham_ok"] is False
    assert by["Q"]["graham_score"] == 3 and by["Q"]["graham_ok"] is False   # missing D/E => not ok


# ---- Magic Formula (Greenblatt) ----------------------------------------------

def test_magic_formula_combined_rank():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    # CHEAP: EBIT/EV 1/4=0.25 highest, ROCE 30 highest => both component rank 1
    assert by["CHEAP"]["magic_ey_rank"] == 1
    assert by["CHEAP"]["magic_roce_rank"] == 1
    # combined = sum of components; CHEAP smallest => magic_rank 1 (best)
    assert by["CHEAP"]["magic_rank"] == 1
    assert by["RICH"]["magic_rank"] > by["CHEAP"]["magic_rank"]
    # LOSS: EBIT/EV negative => excluded from magic ranking
    assert "magic_rank" not in by["LOSS"]


def test_magic_formula_needs_both_metrics():
    # only rows with BOTH positive ev_ebit AND roce ranked
    out = metrics._magic_formula([
        {"symbol": "A", "ev_ebit": 5.0, "roce": 20.0},
        {"symbol": "B", "ev_ebit": 10.0, "roce": None},   # no roce => skipped
        {"symbol": "C", "ev_ebit": -3.0, "roce": 15.0},   # negative ev_ebit => skipped
    ])
    assert set(out) == {"A"}
    assert out["A"] == (1, 1, 1)


# ---- scan membership ---------------------------------------------------------

def test_scans_annotate_named_screens():
    rows = metrics.compute(_rows())
    by = {r["symbol"]: r for r in rows}
    # CHEAP passes Graham (all 4) + Magic top-quartile + Quality + Deep-value
    assert "graham" in by["CHEAP"]["scans"]
    assert "magic_q1" in by["CHEAP"]["scans"]
    assert "quality" in by["CHEAP"]["scans"]
    # RICH: fails Graham, not quality
    assert "graham" not in by["RICH"]["scans"]


def test_scans_deep_value_and_piotroski():
    r = {"value_score": 90.0, "f_score": 8, "magic_rank": 100}
    out = metrics._scans(r, magic_q1=1)   # magic top-quartile cut at rank 1 => 100 excluded
    assert "deep_value" in out            # value_score 90 >= 80
    assert "piotroski8" in out
    assert "magic_q1" not in out          # rank 100 > cut


def test_scan_labels_cover_all_slugs():
    # every slug _scans can emit has a human label
    r = {"graham_ok": True, "magic_rank": 1, "f_score": 8, "quality_flag": True,
         "value_score": 95.0, "peg": 0.5, "eps_growth": 30.0}
    for slug in metrics._scans(r, magic_q1=1):
        assert slug in metrics._SCAN_LABELS


# ---- enrich merge ------------------------------------------------------------

def test_enrich_uses_sid_not_symbol(monkeypatch):
    rows = [{"symbol": "RELIANCE", "sid": "RELI", "pe": 22.0, "mcap": 1000.0, "ev": 1100.0}]
    seen = {}

    def fake_sf(sid, *, pe, mcap, ev):
        seen["sid"] = sid
        return {"f_score": 7, "f_components_computed": 9, "peg": 1.2}

    monkeypatch.setattr("nifty_signal.sources.financials.stock_financials", fake_sf)
    monkeypatch.setattr(metrics, "_cache_read", lambda p, s: None)
    monkeypatch.setattr(metrics, "_cache_write", lambda p, s, v: None)
    out = metrics._enrich(["RELIANCE"], rows)
    assert seen["sid"] == "RELI"                 # Tickertape sid, not NSE symbol
    assert out["RELIANCE"]["f_score"] == 7


def test_enrich_skips_missing_sid(monkeypatch):
    rows = [{"symbol": "NOSID", "sid": None, "pe": 5.0}]
    monkeypatch.setattr(metrics, "_cache_read", lambda p, s: None)
    monkeypatch.setattr(metrics, "_cache_write", lambda p, s, v: None)
    assert metrics._enrich(["NOSID"], rows) == {}


def test_lean_drops_sid_and_nulls():
    row = {"symbol": "X", "sid": "XSID", "pe": 12.345, "de": None, "z": {}, "quality_flag": True}
    lean = metrics._lean(row)
    assert "sid" not in lean                     # internal, never shipped
    assert "de" not in lean                      # null dropped
    assert "z" not in lean                       # empty z dropped
    assert lean["pe"] == 12.34 or lean["pe"] == 12.35   # rounded 2dp
    assert lean["quality_flag"] is True


# ---- cached enrich resume ----------------------------------------------------

def test_cached_enrich_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "_CACHE", tmp_path)
    calls = []

    def compute_one(sid):
        calls.append(sid)
        return {"v": sid}

    # first pass: miss -> fetch + write
    out1 = metrics._cached_enrich("t", ["A", "B"], compute_one)
    assert out1 == {"A": {"v": "A"}, "B": {"v": "B"}}
    assert set(calls) == {"A", "B"}
    # second pass: hit -> no new fetch (resume)
    calls.clear()
    out2 = metrics._cached_enrich("t", ["A", "B"], compute_one)
    assert out2 == out1
    assert calls == []
