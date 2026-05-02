import pandas as pd
import pytest

import ffa_engine.main as main_module


class _FakeDataLoader:
    pass


class _FakeStreamController:
    instances = []

    def __init__(self, loader: object) -> None:
        self.loader = loader
        self.vessel_calls: list[str] = []
        _FakeStreamController.instances.append(self)

    def stream_vessel_data(self, vessel_type: str = "cape"):
        self.vessel_calls.append(vessel_type)

        if vessel_type == "cape":
            yield {
                "Date": pd.Timestamp("2024-01-01"),
                "C5": 120.0,
                "M_Jan_2026": 110.0,
            }
            yield {
                "Date": pd.Timestamp("2024-01-03"),
                "C5": 121.0,
                "M_Jan_2026": 111.0,
            }
            return

        yield {
            "Date": pd.Timestamp("2024-02-01"),
            "p4tc": 220.0,
            "M_Feb_2026": 215.0,
        }


class _FakeDB:
    instances = []

    def __init__(self, db_name: str) -> None:
        self.db_name = db_name
        self.market_rows: list[dict] = []
        self.opt_rows: list[dict] = []
        self.closed = False
        _FakeDB.instances.append(self)

    def log_market_data(self, date: object, vessel: str, spot: float, ffa: float) -> None:
        self.market_rows.append(
            {
                "date": date,
                "vessel": vessel,
                "spot": float(spot),
                "ffa": float(ffa),
            }
        )

    def log_optimization(
        self,
        date: object,
        vessel: str,
        ratio: float,
        risk: float,
        model: str,
    ) -> None:
        self.opt_rows.append(
            {
                "date": date,
                "vessel": vessel,
                "ratio": float(ratio),
                "risk": float(risk),
                "model": model,
            }
        )

    def get_results_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.opt_rows)

    def close(self) -> None:
        self.closed = True


class _FakeOptimizer:
    instances = []

    def __init__(self) -> None:
        self.frames: list[pd.DataFrame] = []
        _FakeOptimizer.instances.append(self)

    def solve_min_var_beta(self, reservoir_df: pd.DataFrame) -> float:
        self.frames.append(reservoir_df.copy())
        return 0.8


@pytest.fixture(autouse=True)
def _clear_fakes() -> None:
    _FakeStreamController.instances.clear()
    _FakeDB.instances.clear()
    _FakeOptimizer.instances.clear()


def _patch_main_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "FFADataLoader", _FakeDataLoader)
    monkeypatch.setattr(main_module, "StreamController", _FakeStreamController)
    monkeypatch.setattr(main_module, "FFADatabase", _FakeDB)
    monkeypatch.setattr(main_module, "FFAOptimizer", _FakeOptimizer)


def test_run_voyage_simulation_cape_route_uses_canonical_vessel_and_packet_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_main_dependencies(monkeypatch)

    main_module.run_voyage_simulation(route="C8", duration=1, k_samples=5)

    controller = _FakeStreamController.instances[0]
    db = _FakeDB.instances[0]
    optimizer = _FakeOptimizer.instances[0]

    assert controller.vessel_calls == ["cape"]
    assert db.market_rows[0]["vessel"] == "cape"
    assert db.market_rows[0]["spot"] == pytest.approx(120.0)
    assert db.market_rows[0]["ffa"] == pytest.approx(110.0)
    assert db.opt_rows[0]["vessel"] == "cape"
    assert db.closed is True

    assert len(optimizer.frames) >= 1
    first_frame = optimizer.frames[0]
    assert list(first_frame.columns) == ["spot_price", "ffa_price"]


def test_run_voyage_simulation_pmx_route_uses_pmx_stream_and_spot_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_main_dependencies(monkeypatch)

    main_module.run_voyage_simulation(route="P4", duration=2, k_samples=5)

    controller = _FakeStreamController.instances[0]
    db = _FakeDB.instances[0]

    assert controller.vessel_calls == ["pmx"]
    assert db.market_rows[0]["vessel"] == "pmx"
    assert db.market_rows[0]["spot"] == pytest.approx(220.0)
    assert db.market_rows[0]["ffa"] == pytest.approx(215.0)


def test_resolve_vessel_type_rejects_unknown_route() -> None:
    with pytest.raises(ValueError, match="Unsupported route/vessel_type"):
        main_module._resolve_vessel_type("S1")


def test_select_market_keys_supports_legacy_m1_field() -> None:
    spot_key, ffa_key = main_module._select_market_keys(
        packet={"Date": "2024-01-01", "C5": 100.0, "M1": 99.0},
        vessel_type="cape",
    )

    assert spot_key == "C5"
    assert ffa_key == "M1"


def test_select_market_keys_prefers_earliest_non_expired_monthly_contract() -> None:
    spot_key, ffa_key = main_module._select_market_keys(
        packet={
            "Date": pd.Timestamp("2022-01-10"),
            "p4tc": 220.0,
            "M_Dec_2021": float("nan"),
            "M_Jan_2022": 215.0,
            "M_Feb_2022": 220.0,
        },
        vessel_type="pmx",
    )

    assert spot_key == "p4tc"
    assert ffa_key == "M_Feb_2022"


def test_select_market_keys_raises_for_missing_spot_column() -> None:
    with pytest.raises(KeyError, match="Missing spot column"):
        main_module._select_market_keys(
            packet={"Date": "2024-01-01", "M_Jan_2026": 99.0},
            vessel_type="cape",
        )


def test_select_market_keys_raises_for_missing_ffa_column() -> None:
    with pytest.raises(KeyError, match="Missing FFA contract column"):
        main_module._select_market_keys(
            packet={"Date": "2024-01-01", "C5": 100.0},
            vessel_type="cape",
        )


def test_build_optimizer_frame_raises_for_missing_columns() -> None:
    with pytest.raises(KeyError, match="Missing required optimization columns"):
        main_module._build_optimizer_frame(
            sample_df=pd.DataFrame({"C5": [100.0]}),
            spot_key="C5",
            ffa_key="M_Jan_2026",
        )


def test_run_voyage_simulation_logs_rebalance_when_beta_drift_breaches_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SequenceOptimizer(_FakeOptimizer):
        def __init__(self) -> None:
            super().__init__()
            self._values = iter([0.8, 1.2, 1.2])

        def solve_min_var_beta(self, reservoir_df: pd.DataFrame) -> float:
            self.frames.append(reservoir_df.copy())
            return next(self._values)

    monkeypatch.setattr(main_module, "FFADataLoader", _FakeDataLoader)
    monkeypatch.setattr(main_module, "StreamController", _FakeStreamController)
    monkeypatch.setattr(main_module, "FFADatabase", _FakeDB)
    monkeypatch.setattr(main_module, "FFAOptimizer", _SequenceOptimizer)

    # Keep voyage active through at least two packets to cover i % 5 false branch.
    main_module.run_voyage_simulation(route="C8", duration=10, k_samples=5)

    db = _FakeDB.instances[0]
    models = [row["model"] for row in db.opt_rows]

    assert "Initial" in models
    assert "Rebalance" in models


def test_run_voyage_simulation_rolls_to_non_null_monthly_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RollingPMXController:
        instances = []

        def __init__(self, loader: object) -> None:
            self.loader = loader
            self.vessel_calls: list[str] = []
            _RollingPMXController.instances.append(self)

        def stream_vessel_data(self, vessel_type: str = "pmx"):
            self.vessel_calls.append(vessel_type)
            yield {
                "Date": pd.Timestamp("2022-01-03"),
                "p4tc": 100.0,
                "M_Jan_2022": 101.0,
                "M_Feb_2022": 102.0,
            }
            yield {
                "Date": pd.Timestamp("2022-02-03"),
                "p4tc": 103.0,
                "M_Jan_2022": float("nan"),
                "M_Feb_2022": 104.0,
            }

    monkeypatch.setattr(main_module, "FFADataLoader", _FakeDataLoader)
    monkeypatch.setattr(main_module, "StreamController", _RollingPMXController)
    monkeypatch.setattr(main_module, "FFADatabase", _FakeDB)
    monkeypatch.setattr(main_module, "FFAOptimizer", _FakeOptimizer)

    main_module.run_voyage_simulation(route="P2A", duration=40, k_samples=5)

    db = _FakeDB.instances[0]
    assert len(db.market_rows) == 2
    assert db.market_rows[0]["vessel"] == "pmx"
    assert db.market_rows[0]["ffa"] == pytest.approx(102.0)
    assert db.market_rows[1]["ffa"] == pytest.approx(104.0)
