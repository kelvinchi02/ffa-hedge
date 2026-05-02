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

### 3.1 Data Source and Licensing

- Market data originates from Baltic Exchange assessments and forward curves.
- Data is pulled via Bloomberg and then preprocessed into model-ready CSV files used by this project.
- Due to licensing restrictions, raw vendor exports and the full historical dataset are not distributed in this repository.
- Only a reproducible snippet is committed under `data_sample/` so the full code and test pipeline can run without licensed raw files.

The loader always tries `data/` first (for licensed local full files) and automatically falls back to `data_sample/`.

### 3.2 Repository-Distributed Files (`data_sample/`)

The tracked sample files are:

| File | Rows | Date range | Columns |
|---|---:|---|---|
| `data_sample/cape_index_fixed_sample.csv` | 540 | 2024-01-01 to 2026-01-23 | `Date`, `C2`, `C3`, `C5`, `C7`, `C8`, `C9`, `C10`, `C14`, `C16`, `C17`, `C5TC_180`, `C5TC_182` |
| `data_sample/pmx_index_fixed_sample.csv` | 540 | 2024-01-01 to 2026-01-23 | `Date`, `p4tc`, `P1A`, `P2A`, `P3A`, `P6`, `P5`, `BPI825TC`, `P4`, `P8` |
| `data_sample/FFA_Cape_Fixed_sample.csv` | 6480 | 2024-01-01 to 2026-01-23 | `Date`, `Forward`, `Contract`, `Route`, `Price` |
| `data_sample/FFA_Pan_Fixed_sample.csv` | 6480 | 2024-01-01 to 2026-01-23 | `Date`, `Forward`, `Contract`, `Route`, `Price` |

Observed categorical values in the sample FFA files:

- `Route`: `BCI5TC` (cape), `BPI5TC` (pmx).
- `Forward`: `M0`-`M3`, `Q0`-`Q3`, `Y0`-`Y3`.

### 3.3 Full Licensed Snapshot (Local, Not Committed)

Expected local filenames in `data/`:

- `cape_index_fixed.csv`
- `pmx_index_fixed.csv`
- `FFA_Cape_Fixed.csv`
- `FFA_Pan_Fixed.csv`

In the current local development snapshot, the observed windows are:

- Spot indices: approximately 2001/2002 to 2026-01-23.
- FFA curves: 2021-12-20 to 2026-01-23.

Your licensed pull may have different endpoints based on refresh date and entitlement.

### 3.4 Preprocessing and Modeling Interface

Preprocessing behavior in `ffa_engine/data_loader.py`:

- Parse `Date` as datetime at load time.
- Cache CSV reads in memory to avoid repeated disk I/O.
- Spot/index files are sorted by `Date` and forward-filled (`ffill`) for missing historical route values.
- FFA long-format tables are pivoted to wide matrices with `Date` index and `Contract` columns (`Price` as values).

### 3.5 Data Quality and Reproducibility Notes

- Early periods contain structural missing values in some route columns (historical route availability differs by start date); this is expected.
- Date fields in shipped sample files are fully parseable and non-null.
- To reproduce exact published results, use your licensed full files in `data/`; sample files are intended for open reproducibility of code paths and tests, not for commercial-grade backtest fidelity.

### 3.6 How to Read the Dataset Files

Index files (`cape_index_fixed*.csv`, `pmx_index_fixed*.csv`):

- Each row is a trading date (`Date`).
- Each non-date column is a route/index series (for example `C8`, `C10`, `P1A`, `p4tc`).
- Conceptually, this is already a wide time-series matrix: one date index with multiple route columns.

FFA files (`FFA_Cape_Fixed*.csv`, `FFA_Pan_Fixed*.csv`):

- Each row is one quote observation for a given date.
- `Forward` is the relative tenor bucket observed on that date (for example `M0`, `M1`, `Q1`, `Y1`).
- `Contract` is the actual expiry contract label (for example `M_Jan_2026`, `Q_2_2025`, `Y_2027`).
- `Price` is the quoted FFA price for that row's `Route` and `Contract` on that date.
- Conceptually, this is long format and is pivoted to wide format before optimization (`Date` x `Contract`).

Minimal pandas examples:

```python
import pandas as pd

# Index file: wide by default (Date + many route columns)
idx = pd.read_csv("data_sample/cape_index_fixed_sample.csv", parse_dates=["Date"])
idx = idx.sort_values("Date").set_index("Date")

# FFA file: long format (one row per Date/Contract quote)
ffa_long = pd.read_csv("data_sample/FFA_Cape_Fixed_sample.csv", parse_dates=["Date"])

# Pivot to model-ready wide matrix: Date x Contract
ffa_wide = (
	ffa_long.pivot_table(index="Date", columns="Contract", values="Price", aggfunc="last")
	.sort_index()
	.sort_index(axis=1)
)
```

## 4. Repository Structure

```text
ffa_engine/
	__init__.py      # explicit package marker for imports and tooling
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

Reproducible setup (recommended):

```bash
# Clone
git clone https://github.com/kelvinchi02/ffa-hedge.git
cd ffa-hedge

# Install uv (https://docs.astral.sh/uv/getting-started/installation/)
# Then create/update the locked project environment
uv sync --frozen --extra dev
```

The command above uses `uv.lock` to install exact dependency versions. This is the most reproducible option across machines.

Minimum Python version: 3.10+ (3.11 recommended for parity with current development setup).

Fallback setup with pip:

```bash
# Clone
git clone https://github.com/kelvinchi02/ffa-hedge.git
cd ffa-hedge

# Install dependencies
pip install -r requirements.txt

# Optional editable install for package-style development
pip install -e .
```

Run the streaming + reservoir demo:

```bash
uv run python -m ffa_engine.streaming
```

This demo executes the finite preview in `run_demo_stream()` and prints processed packet count plus sampled summary statistics.

Import and execute package components directly:

```python
from ffa_engine.data_loader import FFADataLoader
from ffa_engine.streaming import StreamController

loader = FFADataLoader()
controller = StreamController(loader)
first_packet = next(controller.stream_vessel_data(vessel_type="cape", infinite=False))
print(first_packet["Date"], first_packet["C5"])
```

Run all route simulations and consolidation in one step:

```bash
bash run_all_sims.sh
```

If you used `uv sync`, `run_all_sims.sh` automatically prefers local project interpreters at `.venv` (and then `.uvtmp`) before falling back to system `python3`/`python`.

What it does:

- Creates a clean `results/` directory.
- Runs voyage simulations for routes C8, C10, C14, P1A, and P3A.
- Produces per-route SQLite files (for example `results_C8.db`, `results_C10.db`, `results_C14.db`, `results_P1A.db`, `results_P3A.db`) inside `results/`.
- Consolidates outputs into:
	- `results/summary.sqlite` (tables: `market_data_all_routes`, `hedging_results_all_routes`, `route_summary`)
	- `results/summary.csv` (route-level summary)

Optional environment overrides:

```bash
PYTHON_BIN=python3 DURATION_DAYS=45 K_SAMPLES=60 bash run_all_sims.sh
```

Temporary environment with uv (throwaway alternative):

```powershell
# Install uv (one-time)
winget install --id astral-sh.uv -e --source winget --accept-package-agreements --accept-source-agreements

# If the current shell cannot find uv yet, restart the shell first.
# Then create a throwaway environment using your preferred Python interpreter.
uv venv --python C:/Users/kelvi/anaconda3/envs/pandtong/python.exe .uvtmp
uv pip install --python .\.uvtmp\Scripts\python.exe -r requirements.txt

# Run all sims from bash using the temporary interpreter
bash -lc "PYTHON_BIN='/mnt/c/Users/kelvi/ffa-hedge/.uvtmp/Scripts/python.exe' ./run_all_sims.sh"

# Remove the temporary environment when done
Remove-Item -Recurse -Force .uvtmp
```

Notes:

- `run_all_sims.sh` now auto-adjusts `PYTHONPATH` format when `PYTHON_BIN` points to a Windows `.exe` from Git Bash.
- You can substitute any other interpreter path in the `uv venv --python ...` command.
- To regenerate lockfile after dependency changes: `uv lock`.

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
uv run pytest -q
```

Run with coverage:

```bash
uv run pytest -q --cov=ffa_engine --cov-branch --cov-report=term-missing --cov-fail-under=100
```

## 7. CI/CD

This repository includes a GitHub Actions pipeline at `.github/workflows/ci-cd.yml`.

- CI runs on pull requests to `main` and pushes to `main`.
- CI executes `pytest` on Python 3.10, 3.11, and 3.12.
- CI enforces full-package branch coverage (`--cov=ffa_engine`) with a 100% minimum threshold.
- CD runs on tags starting with `v` (for example `v1.0.0`) and publishes a zipped release asset.

Trigger a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```
