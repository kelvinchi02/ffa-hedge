import pandas as pd
import pytest

from ffa_engine.strategies import HedgeStrategy, ShippingVoyage


def test_shipping_voyage_initialization_populates_state() -> None:
    voyage = ShippingVoyage(route="C5", start_date="2024-01-10", duration_days=20, slippage=0.05)

    assert voyage.route == "C5"
    assert voyage.start_date == pd.Timestamp("2024-01-10")
    assert voyage.end_date == pd.Timestamp("2024-01-30")
    assert voyage.slippage == pytest.approx(0.05)
    assert voyage.current_contract is None
    assert voyage.initial_hedge_price is None
    assert voyage.physical_revenue_accumulated == pytest.approx(0.0)
    assert voyage.paper_pnl == pytest.approx(0.0)
    assert voyage.is_hedged is False


def test_get_target_contract_returns_m0_when_not_near_expiry() -> None:
    voyage = ShippingVoyage(route="C5", start_date="2024-01-01", duration_days=10)
    current_date = pd.Timestamp("2024-01-20")

    assert voyage.get_target_contract(current_date) == "M0"


def test_get_target_contract_returns_m1_near_expiry() -> None:
    voyage = ShippingVoyage(route="C5", start_date="2024-01-01", duration_days=10)
    current_date = pd.Timestamp("2024-01-30")

    assert voyage.get_target_contract(current_date) == "M1"


def test_should_rebalance_returns_true_when_active_beta_zero() -> None:
    strategy = HedgeStrategy(rebalance_threshold=0.15)

    assert strategy.should_rebalance(current_beta=0.2, active_beta=0.0)


def test_should_rebalance_returns_true_when_threshold_breached() -> None:
    strategy = HedgeStrategy(rebalance_threshold=0.15)

    assert strategy.should_rebalance(current_beta=1.3, active_beta=1.0)


def test_should_rebalance_returns_false_when_threshold_not_breached() -> None:
    strategy = HedgeStrategy(rebalance_threshold=0.15)

    assert not strategy.should_rebalance(current_beta=1.1, active_beta=1.0)


def test_calculate_beta_returns_cov_over_var() -> None:
    strategy = HedgeStrategy()
    sample_df = pd.DataFrame(
        {
            "spot": [100.0, 102.0, 104.0, 106.0],
            "ffa": [50.0, 51.0, 52.0, 53.0],
        }
    )

    beta = strategy.calculate_beta(sample_df)
    assert beta == pytest.approx(2.0)


def test_calculate_beta_uses_first_two_cov_columns_when_extra_fields_exist() -> None:
    strategy = HedgeStrategy()
    sample_df = pd.DataFrame(
        {
            "spot": [10.0, 11.0, 12.0, 13.0],
            "ffa": [5.0, 5.5, 6.0, 6.5],
            "noise": [1.0, 0.0, 1.0, 0.0],
        }
    )

    beta = strategy.calculate_beta(sample_df)
    assert beta == pytest.approx(2.0)
