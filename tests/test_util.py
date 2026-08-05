"""Zone classification + scoring + verdict boundary tests."""

from nifty_signal.util import (
    composite_score,
    score_buffett,
    score_mmi,
    score_nifty_pe,
    verdict_label,
    zone_buffett,
    zone_mmi,
    zone_nifty_pe,
    zone_vs_median,
)


def test_zone_nifty_pe_bands():
    assert zone_nifty_pe(15) == "cheap"
    assert zone_nifty_pe(17.99) == "cheap"
    assert zone_nifty_pe(18) == "fair"
    assert zone_nifty_pe(21.99) == "fair"
    assert zone_nifty_pe(22) == "expensive"
    assert zone_nifty_pe(23.99) == "expensive"
    assert zone_nifty_pe(24) == "frothy"
    assert zone_nifty_pe(30) == "frothy"


def test_zone_vs_median():
    assert zone_vs_median(20, 25) == "cheap"       # ratio 0.80
    assert zone_vs_median(25, 25) == "fair"        # ratio 1.0
    assert zone_vs_median(28, 25) == "expensive"   # ratio 1.12
    assert zone_vs_median(30, 25) == "frothy"      # ratio 1.2


def test_zone_buffett_bands():
    assert zone_buffett(70) == "undervalued"
    assert zone_buffett(75) == "fair"
    assert zone_buffett(115) == "fair"
    assert zone_buffett(115.1) == "overvalued"
    assert zone_buffett(137) == "overvalued"


def test_zone_mmi_bands():
    assert zone_mmi(0) == "Extreme Fear"
    assert zone_mmi(29.9) == "Extreme Fear"
    assert zone_mmi(30) == "Fear"
    assert zone_mmi(50) == "Greed"
    assert zone_mmi(70) == "Extreme Greed"


def test_scores_monotonic_and_bounded():
    # cheaper PE => higher buy score
    assert score_nifty_pe(15) > score_nifty_pe(20) > score_nifty_pe(24) > score_nifty_pe(28)
    assert 0 <= score_nifty_pe(30) <= 100
    # lower buffett => higher score
    assert score_buffett(75) > score_buffett(115) > score_buffett(140)
    # contrarian MMI
    assert score_mmi(10) > score_mmi(50) > score_mmi(90)
    assert score_mmi(0) == 100 and score_mmi(100) == 0


def test_verdict_label_boundaries():
    assert verdict_label(70) == "STRONG BUY"
    assert verdict_label(69.9) == "ACCUMULATE"
    assert verdict_label(55) == "ACCUMULATE"
    assert verdict_label(54.9) == "HOLD-SIP-ONLY"
    assert verdict_label(40) == "HOLD-SIP-ONLY"
    assert verdict_label(39.9) == "CAUTION"


def test_composite_renormalises_over_available():
    # only two indicators present -> weights renormalise, no crash
    s = composite_score({"nifty_pe": 80, "mmi": 40})
    assert 40 <= s <= 80
    # empty -> 0
    assert composite_score({}) == 0.0
    # single indicator -> its own score
    assert composite_score({"mmi": 62}) == 62.0
