"""Deterministic financial calculations.

These are the ONLY place derived metrics (growth rates, margins) are computed. The
validator recomputes a claim's asserted derived value using these functions and
compares against the claim's stated `values` -- it never trusts a derived number that
didn't come from here (see validate.check_calculations).
"""
from __future__ import annotations


def yoy_growth(current: float, prior: float) -> float:
    """Year-over-year growth rate as a fraction (e.g. 0.12 for +12%)."""
    if prior == 0:
        raise ValueError("Cannot compute YoY growth with a zero prior-period value")
    return (current - prior) / prior


def margin(numerator: float, denominator: float) -> float:
    """A margin ratio (e.g. gross margin = gross_profit / revenue) as a fraction."""
    if denominator == 0:
        raise ValueError("Cannot compute margin with a zero denominator")
    return numerator / denominator


def eps_growth(current_eps: float, prior_eps: float) -> float:
    return yoy_growth(current_eps, prior_eps)


CALCULATION_REGISTRY = {
    "yoy_growth": yoy_growth,
    "margin": margin,
    "eps_growth": eps_growth,
}


def recompute(calc_name: str, inputs: dict[str, float]) -> float:
    """Look up and run a named calculation by keyword-argument inputs.

    `calc_name` and the keys of `inputs` must match one of CALCULATION_REGISTRY's
    function signatures, e.g. calc_name="yoy_growth", inputs={"current": 110, "prior": 100}.
    """
    fn = CALCULATION_REGISTRY.get(calc_name)
    if fn is None:
        raise ValueError(f"Unknown calculation: {calc_name}")
    return fn(**inputs)
