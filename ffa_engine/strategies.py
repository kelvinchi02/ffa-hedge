from datetime import timedelta

import pandas as pd


class ShippingVoyage:
    """Simulates a shipping voyage lifecycle and tracks hedge state."""

    def __init__(
        self,
        route: str,
        start_date: object,
        duration_days: int,
        slippage: float = 0.03,
    ) -> None:
        self.route = route
        self.start_date = pd.to_datetime(start_date)
        self.end_date = self.start_date + timedelta(days=duration_days)
        self.slippage = slippage

        # State tracking
        self.current_contract = None
        self.initial_hedge_price = None
        self.physical_revenue_accumulated = 0.0
        self.paper_pnl = 0.0
        self.is_hedged = False

    def get_target_contract(self, current_date: pd.Timestamp) -> str:
        """Select the hedge contract with a simple month-end liquidity filter."""
        # Logic to check business days left in the month
        # If near end-of-month, move to front-month label M1; otherwise use M0.
        days_in_month = current_date.days_in_month
        if (days_in_month - current_date.day) < 5:
            return "M1"
        return "M0"


class HedgeStrategy:
    """Defines the triggered rebalancing behavior for hedge management."""

    def __init__(self, rebalance_threshold: float = 0.15) -> None:
        self.threshold = rebalance_threshold  # 15% change in Beta triggers trade

    def should_rebalance(self, current_beta: float, active_beta: float) -> bool:
        """Rebalance when the relative beta drift exceeds the configured threshold."""
        if active_beta == 0:
            return True
        return abs(current_beta - active_beta) / active_beta > self.threshold

    def calculate_beta(self, reservoir_df: pd.DataFrame) -> float:
        """Compute min-variance beta as Cov(route_spot, index_composite) / Var(index_composite)."""
        # In a real run, reservoir_df is the output of ReservoirSampler.get_sample_df()
        matrix = reservoir_df.cov()
        # Assuming columns are 'spot' and 'ffa'
        beta = matrix.iloc[0, 1] / matrix.iloc[1, 1]
        return beta