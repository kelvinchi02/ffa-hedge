#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"

to_windows_path() {
    local path="$1"

    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "${path}"
        return
    fi

    # Fallback for bash environments without cygpath (e.g., WSL-style /mnt paths).
    if [[ "${path}" =~ ^/mnt/([a-zA-Z])/(.*)$ ]]; then
        local drive="${BASH_REMATCH[1]}"
        local rest="${BASH_REMATCH[2]}"
        drive="${drive^^}"
        rest="${rest//\//\\}"
        printf '%s:\\%s' "${drive}" "${rest}"
        return
    fi

    printf '%s' "${path}"
}

# Override with environment variables if desired.
if [[ -z "${PYTHON_BIN:-}" ]]; then
    if [[ -f "${SCRIPT_DIR}/.venv/Scripts/python.exe" ]]; then
        PYTHON_BIN="${SCRIPT_DIR}/.venv/Scripts/python.exe"
    elif [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
        PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
    elif [[ -f "${SCRIPT_DIR}/.uvtmp/Scripts/python.exe" ]]; then
        PYTHON_BIN="${SCRIPT_DIR}/.uvtmp/Scripts/python.exe"
    else
        PYTHON_BIN="python3"
        if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
            PYTHON_BIN="python"
        fi
    fi
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "ERROR: Could not resolve Python interpreter: ${PYTHON_BIN}" >&2
    echo "Set PYTHON_BIN explicitly, or create a local virtualenv at .venv/.uvtmp." >&2
    exit 1
fi

# Ensure local package imports resolve even when executing from results/.
# If using a Windows .exe Python from Git Bash, use Windows-style paths and separators.
SCRIPT_DIR_FOR_PYTHONPATH="${SCRIPT_DIR}"
RESULTS_DIR_FOR_PYTHON="${RESULTS_DIR}"
PYTHONPATH_SEP=":"
if [[ "${PYTHON_BIN,,}" == *.exe ]]; then
    SCRIPT_DIR_FOR_PYTHONPATH="$(to_windows_path "${SCRIPT_DIR}")"
    RESULTS_DIR_FOR_PYTHON="$(to_windows_path "${RESULTS_DIR}")"
    PYTHONPATH_SEP=";"
fi
export PYTHONPATH="${SCRIPT_DIR_FOR_PYTHONPATH}${PYTHONPATH:+${PYTHONPATH_SEP}${PYTHONPATH}}"

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
"${PYTHON_BIN}" - "${RESULTS_DIR_FOR_PYTHON}" "${ROUTES[@]}" <<'PY'
import sqlite3
from pathlib import Path
import sys

import pandas as pd

results_dir = Path(sys.argv[1]).resolve()
routes = [route for route in sys.argv[2:] if route]

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
