from pathlib import Path

import pandas as pd
import pytest

from ffa_engine.data_loader import FFADataLoader


@pytest.fixture
def loader() -> FFADataLoader:
    """Return a loader instance for integration-style file loading tests."""
    return FFADataLoader()


@pytest.mark.parametrize("data_attr", ["cape_spot", "pmx_spot", "cape_ffa", "pmx_ffa"])
def test_data_properties_load(loader: FFADataLoader, data_attr: str) -> None:
    """Technical sanity check: every exposed dataset must be usable as a time series input."""
    df = getattr(loader, data_attr)

    assert isinstance(df, pd.DataFrame)
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])
    assert not df.empty


@pytest.mark.parametrize("data_attr", ["cape_spot", "pmx_spot"])
def test_spot_data_is_sorted_by_date(loader: FFADataLoader, data_attr: str) -> None:
    """Financial rationale: spot-index signals must be chronological for streaming and backtests."""
    df = getattr(loader, data_attr)
    assert df["Date"].is_monotonic_increasing


def test_resolve_prefers_full_file_when_present(loader: FFADataLoader) -> None:
    """Technical rationale: production-grade full data should be preferred over sampled surrogates."""
    resolved = loader._resolve_data_file("cape_index_fixed.csv")
    assert Path(resolved).name == "cape_index_fixed.csv"
    assert Path(resolved).parent.name == "data"


def test_resolve_falls_back_to_sample_name(
    loader: FFADataLoader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Technical rationale: robust fallback keeps model pipelines runnable when full data is unavailable."""
    missing_full_path = str(Path(loader.full_path) / "__missing__")
    monkeypatch.setattr(loader, "full_path", missing_full_path)

    resolved = loader._resolve_data_file("cape_index_fixed.csv")
    assert Path(resolved).name == "cape_index_fixed_sample.csv"
    assert Path(resolved).parent.name == "data_sample"


def test_cached_property_returns_same_object(loader: FFADataLoader) -> None:
    """Technical rationale: caching avoids repeated disk I/O during iterative optimization runs."""
    first = loader.cape_ffa
    second = loader.cape_ffa
    assert first is second


def test_get_pivoted_ffa_returns_wide_matrix(loader: FFADataLoader) -> None:
    """Financial rationale: CVXPY hedge optimization needs a unique-contract wide price matrix."""
    pivoted = loader.get_pivoted_ffa("cape")

    assert isinstance(pivoted, pd.DataFrame)
    assert not pivoted.empty
    assert pivoted.index.name == "Date"
    assert pd.api.types.is_datetime64_any_dtype(pivoted.index)
    assert len(pivoted.columns) > 0
    assert not pivoted.columns.duplicated().any()


def test_get_pivoted_ffa_invalid_vessel_type_raises(loader: FFADataLoader) -> None:
    """Technical rationale: strict input validation prevents silent portfolio-construction errors."""
    with pytest.raises(ValueError, match="Unsupported vessel_type"):
        loader.get_pivoted_ffa("supramax")


@pytest.mark.parametrize(
    "spot_attr, ffa_attr",
    [("cape_spot", "cape_ffa"), ("pmx_spot", "pmx_ffa")],
)
def test_spot_and_ffa_date_ranges_overlap(
    loader: FFADataLoader, spot_attr: str, ffa_attr: str
) -> None:
    """Financial rationale: basis and hedge calculations require overlapping spot/FFA time windows."""
    spot_df = getattr(loader, spot_attr)
    ffa_df = getattr(loader, ffa_attr)

    spot_min, spot_max = spot_df["Date"].min(), spot_df["Date"].max()
    ffa_min, ffa_max = ffa_df["Date"].min(), ffa_df["Date"].max()

    overlap_start = max(spot_min, ffa_min)
    overlap_end = min(spot_max, ffa_max)
    assert overlap_start <= overlap_end