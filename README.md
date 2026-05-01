# ffa-hedge

High-fidelity risk management engine for dry bulk shipowners, built around freight basis streaming and liquidity-aware FFA hedging workflows.

## 1. Project Purpose

This repository implements a practical hedging engine for dry bulk operations. The workflow is designed around route-specific spot exposure (for example, Capesize lanes) and liquid Freight Forward Agreement (FFA) composite proxies.

The goal is to protect shipowners from freight-market volatility across the charter lifecycle, including ballast (pre-charter) days, loading, and voyage transit.

## 2. Key Technical Features

- Data Streaming and Sampling (ORIE 5270): Implements Reservoir Sampling (Algorithm R) to maintain a memory-efficient and statistically representative sample of streaming market packets.
- Liquidity-Aware Contract Selection: The data pipeline is built around liquid forward contracts and is designed to support maturity filtering (for example M1/M2/Q1) while avoiding near-expiry illiquid legs.
- Triggered Rebalancing Support: Sampling and streaming modules are structured for threshold-based hedge updates instead of forced daily turnover, helping reduce slippage impact.
- Dual-Book Persistence: SQLite persistence logs market data and optimization outputs side by side, enabling financial MTM and physical PnL reconciliation workflows.
- Min-Var Optimization Ready: Reservoir snapshots are exposed as DataFrames for optimization pipelines (including CVXPY-based hedge-ratio estimation $\beta$) and optimization results can be persisted through the database layer.

## 3. Dataset Used

The project uses a hybrid data approach:

- Spot indices: historical route/index settlement time series for Capesize and Panamax segments.
- FFA curves: historical contract data in long format, pivoted to contract columns for modeling.
- Sample fallback: `data_sample/` provides anonymized CSVs so the full pipeline remains reproducible when proprietary full data in `data/` is unavailable.

The loader always tries `data/` first and automatically falls back to sample files in `data_sample/`.

## 4. Repository Structure

```text
ffa_engine/
	data_loader.py   # data resolution, caching, preprocessing, FFA pivoting
	streaming.py     # stream controller + ReservoirSampler (Algorithm R)
	main.py          # voyage simulation entry point and orchestration
	optimization.py  # CVXPY minimum-variance hedge ratio optimizer
	strategies.py    # voyage + hedge strategy policy components
	database.py      # SQLite logging for market and hedge outputs

tests/
	test_data_loader.py
	test_streaming.py
	test_main.py
	test_optimization.py
	test_strategies.py
	test_database.py
```

## 5. Installation and Execution

```bash
# Clone
git clone https://github.com/your-username/ffa-hedge.git
cd ffa-hedge

# Install dependencies
pip install -r requirements.txt

# Optional editable install for package-style development
pip install -e .
```

Run the streaming + reservoir demo:

```bash
python -m ffa_engine.streaming
```

This demo executes the finite preview in `run_demo_stream()` and prints processed packet count plus sampled summary statistics.

Run all route simulations and consolidation in one step:

```bash
bash run_all_sims.sh
```

What it does:

- Creates a clean `results/` directory.
- Runs voyage simulations for routes C8, C14, and P2A.
- Produces per-route SQLite files (`results_C8.db`, `results_C14.db`, `results_P2A.db`) inside `results/`.
- Consolidates outputs into:
	- `results/summary.sqlite` (tables: `market_data_all_routes`, `hedging_results_all_routes`, `route_summary`)
	- `results/summary.csv` (route-level summary)

Optional environment overrides:

```bash
PYTHON_BIN=python3 DURATION_DAYS=45 K_SAMPLES=60 bash run_all_sims.sh
```

## 6. Unit Tests

The current test suite includes:

- `tests/test_data_loader.py`: path resolution, preprocessing, cache behavior, and pivot validation.
- `tests/test_streaming.py`: reservoir behavior, stream integrity, vessel aliases, and finite/infinite processing paths.
- `tests/test_main.py`: route alias resolution, stream key selection, optimizer frame shaping, and rebalance flow.
- `tests/test_optimization.py`: min-variance solver fallback/bounds behavior and PnL calculations.
- `tests/test_strategies.py`: voyage lifecycle defaults, contract targeting, rebalance trigger logic, and beta calculation.
- `tests/test_database.py`: schema initialization, canonical vessel handling, packet logging, and connection lifecycle behavior.

Run tests:

```bash
pytest -q
```

Run with coverage:

```bash
pytest -q --cov=ffa_engine.streaming --cov=ffa_engine.database --cov=ffa_engine.strategies --cov=ffa_engine.optimization --cov=ffa_engine.main --cov-branch --cov-report=term-missing --cov-fail-under=100
```

## 7. CI/CD

This repository includes a GitHub Actions pipeline at `.github/workflows/ci-cd.yml`.

- CI runs on pull requests to `main` and pushes to `main`.
- CI executes `pytest` on Python 3.10, 3.11, and 3.12.
- CD runs on tags starting with `v` (for example `v1.0.0`) and publishes a zipped release asset.

Trigger a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```
