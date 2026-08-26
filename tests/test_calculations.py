import pytest

from earnings.calculations import eps_growth, margin, recompute, yoy_growth


def test_yoy_growth_basic():
    assert yoy_growth(110, 100) == pytest.approx(0.10)


def test_yoy_growth_negative():
    assert yoy_growth(90, 100) == pytest.approx(-0.10)


def test_yoy_growth_zero_prior_raises():
    with pytest.raises(ValueError):
        yoy_growth(10, 0)


def test_margin_basic():
    assert margin(45, 100) == pytest.approx(0.45)


def test_margin_zero_denominator_raises():
    with pytest.raises(ValueError):
        margin(10, 0)


def test_eps_growth_matches_yoy_growth():
    assert eps_growth(1.1, 1.0) == pytest.approx(yoy_growth(1.1, 1.0))


def test_recompute_dispatches_by_name():
    assert recompute("yoy_growth", {"current": 110, "prior": 100}) == pytest.approx(0.10)


def test_recompute_unknown_calculation_raises():
    with pytest.raises(ValueError):
        recompute("not_a_real_calc", {})
