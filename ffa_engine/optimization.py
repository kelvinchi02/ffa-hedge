import cvxpy as cp
import pandas as pd


class FFAOptimizer:
    """Compute hedge ratios and settlement PnL for FFA workflows."""

    def __init__(self, risk_aversion: float = 1.0) -> None:
        self.gamma = risk_aversion

    def solve_min_var_beta(self, reservoir_df: pd.DataFrame) -> float:
        """Solve min-variance hedge ratio using spot/FFA return residuals."""
        # 1. Prepare Returns (Required for stationary time series in optimization)
        # Assuming reservoir_df has columns: 'spot_price' and 'ffa_price'
        # Disable forward-fill so return calculation remains explicit and warning-free.
        returns = reservoir_df[["spot_price", "ffa_price"]].pct_change(fill_method=None).dropna()

        if len(returns) < 5:
            return 1.0  # Fallback to 1:1 if sample is too small

        spot_ret = returns["spot_price"].values
        index_ret = returns["ffa_price"].values

        # 2. Define CVXPY Variables
        # h is the hedge ratio we are solving for
        h = cp.Variable(1)

        # 3. Define Objective Function
        # Residual Risk = Spot_Returns - h * Index_Returns
        residual = spot_ret - h * index_ret
        objective = cp.Minimize(cp.sum_squares(residual))

        # 4. Define Constraints
        # - h >= 0: No naked shorting (we only hedge physical exposure)
        # - h <= 2.0: Cap over-hedging to prevent speculative behavior
        constraints = [h >= 0, h <= 2.0]

        # 5. Solve
        prob = cp.Problem(objective, constraints)
        prob.solve(solver=cp.ECOS)  # ECOS is reliable for quadratic problems

        if prob.status != cp.OPTIMAL:
            return 1.0  # Fallback

        return float(h.value[0])

    def calculate_pnl(
        self,
        initial_price: float,
        current_price: float,
        quantity: float,
        side: str = "short",
    ) -> float:
        """Calculate daily mark-to-market PnL for a long or short position."""
        multiplier = -1 if side == "short" else 1
        return (current_price - initial_price) * quantity * multiplier