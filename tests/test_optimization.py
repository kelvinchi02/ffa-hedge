import pandas as pd
import pytest

import ffa_engine.optimization as optimization_module
from ffa_engine.optimization import FFAOptimizer


def _build_price_df(spot_returns: list[float], ffa_returns: list[float]) -> pd.DataFrame:
    spot_prices = [100.0]
    ffa_prices = [100.0]

    for spot_ret in spot_returns:
        spot_prices.append(spot_prices[-1] * (1.0 + spot_ret))
    for ffa_ret in ffa_returns:
        ffa_prices.append(ffa_prices[-1] * (1.0 + ffa_ret))

    return pd.DataFrame({"spot_price": spot_prices, "ffa_price": ffa_prices})


def test_solve_min_var_beta_returns_fallback_for_small_sample() -> None:
    optimizer = FFAOptimizer()
    reservoir_df = pd.DataFrame(
        {
            "spot_price": [100.0, 101.0, 102.0, 103.0, 104.0],
            "ffa_price": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    )

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(1.0)


def test_solve_min_var_beta_finds_interior_solution() -> None:
    optimizer = FFAOptimizer()
    reservoir_df = _build_price_df(spot_returns=[0.05] * 5, ffa_returns=[0.10] * 5)

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(0.5, abs=1e-3)


def test_solve_min_var_beta_returns_one_for_perfect_correlation() -> None:
    optimizer = FFAOptimizer()
    returns = [0.01, -0.02, 0.03, 0.015, -0.01, 0.02]
    reservoir_df = _build_price_df(spot_returns=returns, ffa_returns=returns)

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(1.0, abs=1e-3)


def test_solve_min_var_beta_applies_upper_bound() -> None:
    optimizer = FFAOptimizer()
    reservoir_df = _build_price_df(spot_returns=[0.05] * 5, ffa_returns=[0.01] * 5)

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(2.0, abs=1e-3)


def test_solve_min_var_beta_applies_lower_bound() -> None:
    optimizer = FFAOptimizer()
    reservoir_df = _build_price_df(spot_returns=[0.05] * 5, ffa_returns=[-0.05] * 5)

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(0.0, abs=1e-3)


def test_solve_min_var_beta_returns_fallback_when_problem_not_optimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonOptimalProblem:
        def __init__(self, objective: object, constraints: object) -> None:
            self.status = "not_optimal"

        def solve(self, solver: object | None = None) -> None:
            self.status = "not_optimal"

    monkeypatch.setattr(optimization_module.cp, "Problem", NonOptimalProblem)

    optimizer = FFAOptimizer()
    reservoir_df = _build_price_df(spot_returns=[0.02] * 5, ffa_returns=[0.02] * 5)

    beta = optimizer.solve_min_var_beta(reservoir_df)
    assert beta == pytest.approx(1.0)


def test_calculate_pnl_for_short_and_long_positions() -> None:
    optimizer = FFAOptimizer()

    short_pnl = optimizer.calculate_pnl(initial_price=100.0, current_price=90.0, quantity=10.0, side="short")
    long_pnl = optimizer.calculate_pnl(initial_price=100.0, current_price=90.0, quantity=10.0, side="long")

    assert short_pnl == pytest.approx(100.0)
    assert long_pnl == pytest.approx(-100.0)
