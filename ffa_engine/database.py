import sqlite3
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd


class FFADatabase:
    """SQLite persistence helpers for stream packets and optimization outputs."""

    _VESSEL_MAP = {
        "cape": "cape",
        "capesize": "cape",
        "pmx": "pmx",
        "pan": "pmx",
        "panamax": "pmx",
    }

    def __init__(self, db_name: str = "ffa_results.db") -> None:
        self.db_path = Path(db_name)
        self.conn: Optional[sqlite3.Connection] = sqlite3.connect(
            self.db_path, check_same_thread=False
        )
        self._create_tables()

    @classmethod
    def _normalize_vessel_type(cls, vessel_type: str) -> str:
        normalized = vessel_type.strip().lower()
        canonical = cls._VESSEL_MAP.get(normalized)
        if canonical is None:
            raise ValueError(
                "Unsupported vessel_type. Use one of: cape, capesize, pmx, pan, panamax."
            )
        return canonical

    @staticmethod
    def _to_iso_date(date_value: Any) -> str:
        if date_value is None:
            raise ValueError("date must not be None")

        if hasattr(date_value, "isoformat"):
            return str(date_value.isoformat())
        return str(date_value)

    def _get_connection(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database connection is closed.")
        return self.conn

    def _create_tables(self) -> None:
        """Initializes the relational schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_data (
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                date TEXT,
                vessel_type TEXT,
                spot_price REAL,
                ffa_price REAL,
                basis REAL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hedging_results (
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                date TEXT,
                vessel_type TEXT,
                hedge_ratio REAL,
                risk_metric REAL,
                model_type TEXT
            )
            """
        )
        conn.commit()

    def log_market_data(self, date: Any, vessel: str, spot: float, ffa: float) -> None:
        """Log one market packet with canonical vessel naming and basis."""
        conn = self._get_connection()
        cursor = conn.cursor()

        canonical = self._normalize_vessel_type(vessel)
        iso_date = self._to_iso_date(date)
        spot_value = float(spot)
        ffa_value = float(ffa)
        basis = spot_value - ffa_value

        cursor.execute(
            "INSERT INTO market_data (date, vessel_type, spot_price, ffa_price, basis) VALUES (?, ?, ?, ?, ?)",
            (iso_date, canonical, spot_value, ffa_value, basis),
        )
        conn.commit()

    def log_stream_packet(
        self,
        packet: Mapping[str, Any],
        vessel: str,
        spot_key: Optional[str] = None,
        ffa_key: Optional[str] = None,
    ) -> None:
        """Log a packet emitted by StreamController.stream_vessel_data."""
        canonical = self._normalize_vessel_type(vessel)

        if "Date" not in packet:
            raise KeyError("Missing 'Date' in stream packet.")

        selected_spot_key = spot_key or ("C5" if canonical == "cape" else "p4tc")
        if selected_spot_key not in packet:
            raise KeyError(f"Missing spot column '{selected_spot_key}' in stream packet.")

        selected_ffa_key = ffa_key
        if selected_ffa_key is None:
            selected_ffa_key = next((key for key in packet.keys() if key.startswith("M_")), None)
        if selected_ffa_key is None or selected_ffa_key not in packet:
            raise KeyError("Missing FFA contract column in stream packet.")

        self.log_market_data(
            date=packet["Date"],
            vessel=canonical,
            spot=float(packet[selected_spot_key]),
            ffa=float(packet[selected_ffa_key]),
        )

    def log_optimization(
        self,
        date: Any,
        vessel: str,
        ratio: float,
        risk: float,
        model: str,
    ) -> None:
        """Log one optimization output row."""
        conn = self._get_connection()
        cursor = conn.cursor()

        canonical = self._normalize_vessel_type(vessel)
        iso_date = self._to_iso_date(date)

        cursor.execute(
            "INSERT INTO hedging_results (date, vessel_type, hedge_ratio, risk_metric, model_type) VALUES (?, ?, ?, ?, ?)",
            (iso_date, canonical, float(ratio), float(risk), model),
        )
        conn.commit()

    def get_market_data_df(self) -> pd.DataFrame:
        """Return all logged market data rows as a DataFrame."""
        conn = self._get_connection()
        return pd.read_sql_query("SELECT * FROM market_data", conn)

    def get_results_df(self) -> pd.DataFrame:
        """Return all logged optimization rows as a DataFrame."""
        conn = self._get_connection()
        return pd.read_sql_query("SELECT * FROM hedging_results", conn)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "FFADatabase":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()