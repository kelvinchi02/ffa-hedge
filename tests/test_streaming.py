import itertools

import pandas as pd
import pytest

from ffa_engine.data_loader import FFADataLoader
from ffa_engine.streaming import ReservoirSampler, StreamController, run_demo_stream


@pytest.fixture
def controller() -> StreamController:
    return StreamController(FFADataLoader())


def test_reservoir_sampler_respects_capacity() -> None:
    sampler = ReservoirSampler(k=5, seed=7)

    for value in range(50):
        sampler.update({"x": value})

    assert sampler.n == 50
    assert len(sampler.get_sample()) == 5


def test_reservoir_sampler_extend_and_clear() -> None:
    sampler = ReservoirSampler(k=3, seed=3)
    sampler.extend([{"x": 1}, {"x": 2}, {"x": 3}, {"x": 4}])

    assert sampler.n == 4
    assert len(sampler.get_sample()) == 3

    sample_df = sampler.get_sample_df()
    assert isinstance(sample_df, pd.DataFrame)
    assert "x" in sample_df.columns

    external_copy = sampler.get_sample()
    external_copy.append({"x": 999})
    assert len(external_copy) == len(sampler.get_sample()) + 1

    sampler.clear()
    assert sampler.n == 0
    assert sampler.get_sample() == []


def test_reservoir_sampler_replacement_and_skip_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = ReservoirSampler(k=2, seed=4)
    sampler.extend([{"x": 10}, {"x": 20}])

    monkeypatch.setattr(sampler._rng, "randrange", lambda _: 0)
    sampler.update({"x": 30})
    assert any(item["x"] == 30 for item in sampler.get_sample())

    before = sampler.get_sample()
    monkeypatch.setattr(sampler._rng, "randrange", lambda _: sampler.n)
    sampler.update({"x": 40})
    assert sampler.get_sample() == before


def test_reservoir_sampler_rejects_invalid_k() -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        ReservoirSampler(k=0)


def test_normalize_vessel_type_aliases() -> None:
    assert StreamController._normalize_vessel_type("cape") == "cape"
    assert StreamController._normalize_vessel_type(" capesize ") == "cape"
    assert StreamController._normalize_vessel_type("panamax") == "pmx"


def test_stream_vessel_data_finite_cycle_has_expected_fields(controller: StreamController) -> None:
    packet = next(controller.stream_vessel_data(vessel_type="cape", infinite=False))

    assert "Date" in packet

    # Spot columns come from the index dataset and contract columns from pivoted FFA prices.
    assert "C5" in packet
    assert any(key.startswith("M_") for key in packet.keys())


def test_stream_vessel_data_aliases_match(controller: StreamController) -> None:
    cape_packet = next(controller.stream_vessel_data(vessel_type="cape", infinite=False))
    capesize_packet = next(controller.stream_vessel_data(vessel_type="capesize", infinite=False))

    assert cape_packet["Date"] == capesize_packet["Date"]


def test_get_spot_frame_supports_both_vessel_groups(controller: StreamController) -> None:
    cape_spot = controller._get_spot_frame("cape")
    pmx_spot = controller._get_spot_frame("pmx")

    assert "Date" in cape_spot.columns
    assert "Date" in pmx_spot.columns


def test_get_merged_frame_is_cached(controller: StreamController) -> None:
    first = controller._get_merged_frame("cape")
    second = controller._get_merged_frame("cape")

    assert first is second


def test_build_merged_frame_raises_on_no_overlap() -> None:
    class NoOverlapLoader:
        @property
        def cape_spot(self) -> pd.DataFrame:
            return pd.DataFrame({"Date": pd.to_datetime(["2020-01-01"]), "C5": [1.0]})

        @property
        def pmx_spot(self) -> pd.DataFrame:
            return pd.DataFrame({"Date": pd.to_datetime(["2020-01-01"]), "p4tc": [1.0]})

        def get_pivoted_ffa(self, vessel_type: str) -> pd.DataFrame:
            pivot = pd.DataFrame(
                {"M_Jan_2021": [100.0]},
                index=pd.to_datetime(["2021-01-01"]),
            )
            pivot.index.name = "Date"
            return pivot

    controller = StreamController(NoOverlapLoader())
    with pytest.raises(ValueError, match="No overlapping dates found"):
        controller._build_merged_frame("cape")


def test_stream_vessel_data_include_cycle_rolls_over(controller: StreamController) -> None:
    merged_len = len(controller._get_merged_frame("cape"))
    packets = list(
        itertools.islice(
            controller.stream_vessel_data(vessel_type="cape", infinite=True, include_cycle=True),
            merged_len + 1,
        )
    )

    assert packets[0]["_cycle"] == 0
    assert packets[-1]["_cycle"] == 1
    assert packets[0]["Date"] == packets[-1]["Date"]


def test_stream_vessel_data_finite_mode_exhausts_one_cycle(controller: StreamController) -> None:
    packets = list(controller.stream_vessel_data(vessel_type="pmx", infinite=False))
    assert len(packets) == len(controller._get_merged_frame("pmx"))


def test_stream_vessel_data_invalid_vessel_type_raises(controller: StreamController) -> None:
    with pytest.raises(ValueError, match="Unsupported vessel_type"):
        next(controller.stream_vessel_data(vessel_type="supramax", infinite=False))


def test_process_stream_max_packets_limits_infinite_mode(controller: StreamController) -> None:
    sampler = ReservoirSampler(k=10, seed=11)
    processed = controller.process_stream(
        sampler=sampler,
        vessel_type="pmx",
        max_packets=37,
        infinite=True,
    )

    assert processed == 37
    assert sampler.n == 37
    assert len(sampler.get_sample()) == 10


def test_process_stream_finite_mode_processes_full_cycle(controller: StreamController) -> None:
    sampler = ReservoirSampler(k=20, seed=13)
    processed = controller.process_stream(
        sampler=sampler,
        vessel_type="cape",
        max_packets=None,
        infinite=False,
    )

    assert processed == len(controller._get_merged_frame("cape"))
    assert sampler.n == processed


def test_run_demo_stream_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    run_demo_stream(k=5, vessel_type="cape", max_packets=10, seed=21)
    output = capsys.readouterr().out

    assert "Starting CAPE stream" in output
    assert "Processed 10 packets" in output
