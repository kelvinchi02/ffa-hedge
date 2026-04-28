from pathlib import Path

import pandas as pd
import pytest

from ffa_engine.database import FFADatabase


@pytest.fixture
def db(tmp_path: Path) -> FFADatabase:
    instance = FFADatabase(str(tmp_path / "ffa_test.db"))
    yield instance
    instance.close()


def test_tables_are_created(db: FFADatabase) -> None:
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", db._get_connection()
    )
    assert {"market_data", "hedging_results"}.issubset(set(tables["name"]))


def test_normalize_vessel_type_aliases_and_invalid() -> None:
    assert FFADatabase._normalize_vessel_type(" cape ") == "cape"
    assert FFADatabase._normalize_vessel_type("capesize") == "cape"
    assert FFADatabase._normalize_vessel_type("panamax") == "pmx"

    with pytest.raises(ValueError, match="Unsupported vessel_type"):
        FFADatabase._normalize_vessel_type("supramax")


def test_to_iso_date_handles_common_inputs() -> None:
    assert FFADatabase._to_iso_date(pd.Timestamp("2024-01-01")) == "2024-01-01T00:00:00"
    assert FFADatabase._to_iso_date(20240101) == "20240101"

    with pytest.raises(ValueError, match="date must not be None"):
        FFADatabase._to_iso_date(None)


def test_log_market_data_persists_basis_and_canonical_vessel(db: FFADatabase) -> None:
    db.log_market_data(date=pd.Timestamp("2024-01-01"), vessel="capesize", spot=100.5, ffa=95.0)

    rows = db.get_market_data_df()
    assert len(rows) == 1
    assert rows.loc[0, "vessel_type"] == "cape"
    assert rows.loc[0, "spot_price"] == pytest.approx(100.5)
    assert rows.loc[0, "ffa_price"] == pytest.approx(95.0)
    assert rows.loc[0, "basis"] == pytest.approx(5.5)


def test_log_market_data_invalid_vessel_raises(db: FFADatabase) -> None:
    with pytest.raises(ValueError, match="Unsupported vessel_type"):
        db.log_market_data(date="2024-01-01", vessel="supramax", spot=1.0, ffa=1.0)


def test_log_optimization_persists_row(db: FFADatabase) -> None:
    db.log_optimization(date="2024-01-02", vessel="pan", ratio=0.35, risk=1.2, model="cvx")

    rows = db.get_results_df()
    assert len(rows) == 1
    assert rows.loc[0, "vessel_type"] == "pmx"
    assert rows.loc[0, "hedge_ratio"] == pytest.approx(0.35)
    assert rows.loc[0, "risk_metric"] == pytest.approx(1.2)
    assert rows.loc[0, "model_type"] == "cvx"


def test_log_stream_packet_uses_default_cape_keys(db: FFADatabase) -> None:
    packet = {
        "Date": pd.Timestamp("2024-01-03"),
        "C5": 120.0,
        "M_Jan_2026": 110.0,
    }

    db.log_stream_packet(packet=packet, vessel="cape")

    rows = db.get_market_data_df()
    assert len(rows) == 1
    assert rows.loc[0, "spot_price"] == pytest.approx(120.0)
    assert rows.loc[0, "ffa_price"] == pytest.approx(110.0)


def test_log_stream_packet_uses_default_pmx_keys(db: FFADatabase) -> None:
    packet = {
        "Date": "2024-01-04",
        "p4tc": 210.0,
        "M_Feb_2026": 205.0,
    }

    db.log_stream_packet(packet=packet, vessel="pmx")

    rows = db.get_market_data_df()
    assert len(rows) == 1
    assert rows.loc[0, "vessel_type"] == "pmx"
    assert rows.loc[0, "basis"] == pytest.approx(5.0)


def test_log_stream_packet_supports_custom_keys(db: FFADatabase) -> None:
    packet = {
        "Date": "2024-01-05",
        "spot_custom": 33.0,
        "contract_custom": 31.0,
    }

    db.log_stream_packet(packet=packet, vessel="cape", spot_key="spot_custom", ffa_key="contract_custom")

    rows = db.get_market_data_df()
    assert len(rows) == 1
    assert rows.loc[0, "spot_price"] == pytest.approx(33.0)
    assert rows.loc[0, "ffa_price"] == pytest.approx(31.0)


def test_log_stream_packet_requires_date(db: FFADatabase) -> None:
    with pytest.raises(KeyError, match="Missing 'Date' in stream packet"):
        db.log_stream_packet(packet={"C5": 100.0, "M_Jan_2026": 90.0}, vessel="cape")


def test_log_stream_packet_requires_spot_column(db: FFADatabase) -> None:
    packet = {"Date": "2024-01-06", "M_Jan_2026": 90.0}

    with pytest.raises(KeyError, match="Missing spot column 'C5'"):
        db.log_stream_packet(packet=packet, vessel="cape")


def test_log_stream_packet_requires_ffa_column_when_not_present(db: FFADatabase) -> None:
    packet = {"Date": "2024-01-06", "C5": 100.0}

    with pytest.raises(KeyError, match="Missing FFA contract column"):
        db.log_stream_packet(packet=packet, vessel="cape")


def test_log_stream_packet_requires_explicit_ffa_key_to_exist(db: FFADatabase) -> None:
    packet = {"Date": "2024-01-06", "C5": 100.0, "M_Jan_2026": 90.0}

    with pytest.raises(KeyError, match="Missing FFA contract column"):
        db.log_stream_packet(packet=packet, vessel="cape", ffa_key="M_Mar_2027")


def test_close_is_idempotent_and_blocks_future_queries(db: FFADatabase) -> None:
    db.close()
    db.close()

    with pytest.raises(RuntimeError, match="Database connection is closed"):
        db.get_results_df()


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "ctx.db"

    with FFADatabase(str(db_path)) as managed:
        managed.log_market_data(date="2024-01-01", vessel="cape", spot=1.0, ffa=0.5)

    with pytest.raises(RuntimeError, match="Database connection is closed"):
        managed.get_market_data_df()
