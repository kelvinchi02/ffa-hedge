#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"

# Ensure local package imports resolve even when executing from results/.
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Override with environment variables if desired.
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

DURATION_DAYS="${DURATION_DAYS:-45}"
K_SAMPLES="${K_SAMPLES:-60}"
ROUTES=("C8" "C14" "P2A")

echo "Cleaning results directory: ${RESULTS_DIR}"
rm -rf "${RESULTS_DIR}"
mkdir -p "${RESULTS_DIR}"

for route in "${ROUTES[@]}"; do
  echo "Running simulation for route ${route}..."
  (
    cd "${RESULTS_DIR}"
    "${PYTHON_BIN}" -c "from ffa_engine.main import run_voyage_simulation; run_voyage_simulation(route='${route}', duration=${DURATION_DAYS}, k_samples=${K_SAMPLES})"
  )
done

echo "Consolidating per-route SQLite files into a single summary..."
export RESULTS_DIR_ABS="${RESULTS_DIR}"
export ROUTES_CSV="$(IFS=,; echo "${ROUTES[*]}")"
"${PYTHON_BIN}" - <<'PY'
import os
import sqlite3
from pathlib import Path

import pandas as pd

results_dir = Path(os.environ["RESULTS_DIR_ABS"]).resolve()
routes = [route for route in os.environ["ROUTES_CSV"].split(",") if route]

summary_db_path = results_dir / "summary.sqlite"
summary_csv_path = results_dir / "summary.csv"

if summary_db_path.exists():
    summary_db_path.unlink()

all_market_frames = []
all_hedge_frames = []
route_rows = []

for route in routes:
    db_path = results_dir / f"results_{route}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Expected simulation output not found: {db_path}")

    conn_in = sqlite3.connect(db_path)
    try:
        market_df = pd.read_sql_query("SELECT * FROM market_data", conn_in)
        hedge_df = pd.read_sql_query("SELECT * FROM hedging_results", conn_in)
    finally:
        conn_in.close()

    market_df.insert(0, "route", route)
    hedge_df.insert(0, "route", route)

    all_market_frames.append(market_df)
    all_hedge_frames.append(hedge_df)

    route_rows.append(
        {
            "route": route,
            "market_rows": int(len(market_df)),
            "hedging_rows": int(len(hedge_df)),
            "avg_basis": float(market_df["basis"].mean()) if len(market_df) else float("nan"),
            "avg_hedge_ratio": float(hedge_df["hedge_ratio"].mean()) if len(hedge_df) else float("nan"),
        }
    )

market_all_df = pd.concat(all_market_frames, ignore_index=True) if all_market_frames else pd.DataFrame()
hedge_all_df = pd.concat(all_hedge_frames, ignore_index=True) if all_hedge_frames else pd.DataFrame()
summary_df = pd.DataFrame(route_rows)

conn_out = sqlite3.connect(summary_db_path)
try:
    market_all_df.to_sql("market_data_all_routes", conn_out, if_exists="replace", index=False)
    hedge_all_df.to_sql("hedging_results_all_routes", conn_out, if_exists="replace", index=False)
    summary_df.to_sql("route_summary", conn_out, if_exists="replace", index=False)
finally:
    conn_out.close()

summary_df.to_csv(summary_csv_path, index=False)
print(f"Wrote consolidated SQLite summary: {summary_db_path}")
print(f"Wrote route summary CSV: {summary_csv_path}")
PY

echo "All simulations and consolidation complete."
