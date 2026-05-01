import pandas as pd
from ffa_engine.data_loader import FFADataLoader
from ffa_engine.streaming import StreamController, ReservoirSampler
from ffa_engine.strategies import ShippingVoyage, HedgeStrategy
from ffa_engine.optimization import FFAOptimizer
from ffa_engine.database import FFADatabase


def _resolve_vessel_type(route: str) -> str:
    """Map route labels and vessel aliases to canonical vessel types."""
    normalized = route.strip().lower()

    if normalized in {"cape", "capesize"} or normalized.startswith("c"):
        return "cape"
    if normalized in {"pmx", "pan", "panamax"} or normalized.startswith("p"):
        return "pmx"

    raise ValueError(
        "Unsupported route/vessel_type. Use cape/capesize, pmx/pan/panamax, or route codes like C8/P4."
    )


def _select_market_keys(packet: dict, vessel_type: str) -> tuple[str, str]:
    """Pick spot and FFA keys from a stream packet using current schema conventions."""
    spot_key = "C5" if vessel_type == "cape" else "p4tc"
    if spot_key not in packet:
        raise KeyError(f"Missing spot column '{spot_key}' in stream packet.")

    # Keep compatibility with both old-style M1 and current pivoted M_* columns.
    ffa_key = "M1" if "M1" in packet else next((key for key in packet if key.startswith("M_")), None)
    if ffa_key is None:
        raise KeyError("Missing FFA contract column in stream packet.")

    return spot_key, ffa_key


def _build_optimizer_frame(sample_df: pd.DataFrame, spot_key: str, ffa_key: str) -> pd.DataFrame:
    """Shape stream sample data into the optimizer's expected column names."""
    missing = [column for column in (spot_key, ffa_key) if column not in sample_df.columns]
    if missing:
        raise KeyError(f"Missing required optimization columns: {missing}")

    return sample_df[[spot_key, ffa_key]].rename(
        columns={spot_key: "spot_price", ffa_key: "ffa_price"}
    )


def run_voyage_simulation(route="C8", duration=45, k_samples=60):
    # 1. Initialize Infrastructure
    loader = FFADataLoader()
    db = FFADatabase(f"results_{route}.db")
    controller = StreamController(loader)
    sampler = ReservoirSampler(k=k_samples)
    optimizer = FFAOptimizer()
    vessel_type = _resolve_vessel_type(route)
    
    # 2. Define the Physical Voyage
    # We'll use the first available date from the stream as our 'Signing Date'
    stream = controller.stream_vessel_data(vessel_type=vessel_type)
    voyage = None
    strategy = HedgeStrategy(rebalance_threshold=0.15)
    
    active_beta = 0.0
    spot_key = None
    ffa_key = None

    print(f"--- Launching Simulation for Route {route} ---")

    try:
        for i, data_packet in enumerate(stream):
            # Update Reservoir (ORIE 5270 Algorithm R)
            sampler.update(data_packet)
            current_date = pd.to_datetime(data_packet["Date"])

            if spot_key is None or ffa_key is None:
                spot_key, ffa_key = _select_market_keys(data_packet, vessel_type)

            # Initialize Voyage on the first packet
            if voyage is None:
                voyage = ShippingVoyage(route, current_date, duration)
                # Calculate initial hedge using the first available reservoir state
                active_beta = optimizer.solve_min_var_beta(
                    _build_optimizer_frame(sampler.get_sample_df(), spot_key, ffa_key)
                )

                db.log_optimization(data_packet["Date"], vessel_type, active_beta, 0.0, "Initial")
                print(f"Fixed Charter on {current_date.date()}. Initial Beta: {active_beta:.2f}")

            # Check if voyage is still active
            if current_date > voyage.end_date:
                print(f"Voyage completed on {current_date.date()}.")
                break

            # Daily Tracker & Rebalancing Logic
            if i % 5 == 0:  # Check for rebalance every 5 business days to save on slippage
                current_beta = optimizer.solve_min_var_beta(
                    _build_optimizer_frame(sampler.get_sample_df(), spot_key, ffa_key)
                )

                if strategy.should_rebalance(current_beta, active_beta):
                    # Apply Slippage for the trade
                    active_beta = current_beta
                    db.log_optimization(data_packet["Date"], vessel_type, active_beta, 0.0, "Rebalance")
                    print(f"[{current_date.date()}] Rebalancing Hedge. New Beta: {active_beta:.2f}")

            # Log daily MTM and Physical Basis to SQLite
            db.log_market_data(
                date=data_packet["Date"],
                vessel=vessel_type,
                spot=data_packet[spot_key],
                ffa=data_packet[ffa_key],
            )

        # 3. Cleanup
        results = db.get_results_df()
        print(f"Simulation Finished. Total Days Logged: {len(results)}")
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    run_voyage_simulation()