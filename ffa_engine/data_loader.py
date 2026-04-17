import os
from typing import Dict

import pandas as pd

class FFADataLoader:
    """Load and cache FFA datasets with full-data-first fallback behavior."""

    def __init__(self) -> None:
        """Initialize data paths and in-memory DataFrame cache."""
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.full_path = os.path.join(self.base_dir, 'data')
        self.sample_path = os.path.join(self.base_dir, 'data_sample')
        self._cache: Dict[str, pd.DataFrame] = {}

        # Backwards-compatible attributes for callers that inspect loader state.
        self.use_full = os.path.isdir(self.full_path)
        self.active_path = self.full_path if self.use_full else self.sample_path

    def _sample_file_name(self, file_name: str) -> str:
        """Convert foo.csv to foo_sample.csv."""
        stem, ext = os.path.splitext(file_name)
        return f"{stem}_sample{ext}"

    def _resolve_data_file(self, file_name: str) -> str:
        """Load from /data first; fallback to sample file in sample directory."""
        full_candidate = os.path.join(self.full_path, file_name)
        if os.path.isfile(full_candidate):
            return full_candidate

        sample_name = self._sample_file_name(file_name)
        sample_candidate = os.path.join(self.sample_path, sample_name)
        if os.path.isfile(sample_candidate):
            return sample_candidate

        raise FileNotFoundError(
            f"Missing data file '{file_name}' in '{self.full_path}' and sample fallback '{sample_name}' "
            f"in '{self.sample_path}'."
        )

    def _read_csv_cached(self, file_name: str) -> pd.DataFrame:
        """Read a CSV once and reuse it on subsequent calls."""
        resolved_path = self._resolve_data_file(file_name)
        if resolved_path not in self._cache:
            self._cache[resolved_path] = pd.read_csv(resolved_path, parse_dates=['Date'])
        return self._cache[resolved_path]

    def _preprocess_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sort index series by date and forward-fill missing values."""
        # C5TC_180/182 are common targets; forward fill or drop based on logic
        return df.sort_values('Date').ffill()

    @property
    def cape_spot(self) -> pd.DataFrame:
        """Return CAPE spot index data."""
        df = self._read_csv_cached('cape_index_fixed.csv')
        return self._preprocess_index(df)

    @property
    def cape_ffa(self) -> pd.DataFrame:
        """Return CAPE FFA prices in long format."""
        return self._read_csv_cached('FFA_Cape_Fixed.csv')

    @property
    def pmx_spot(self) -> pd.DataFrame:
        """Return PMX spot index data."""
        df = self._read_csv_cached('pmx_index_fixed.csv')
        return self._preprocess_index(df)

    @property
    def pmx_ffa(self) -> pd.DataFrame:
        """Return PMX FFA prices in long format."""
        return self._read_csv_cached('FFA_Pan_Fixed.csv')

    def get_pivoted_ffa(self, vessel_type: str) -> pd.DataFrame:
        """Return wide FFA prices with Date index and Contract columns.

        Args:
            vessel_type: Supported values are "cape", "capesize", "pmx", "pan", and "panamax".

        Returns:
            Pivoted DataFrame with Date as index and Contract as columns.

        Raises:
            ValueError: If vessel_type is unsupported.
        """
        normalized = vessel_type.strip().lower()
        if normalized in {'cape', 'capesize'}:
            df = self.cape_ffa
        elif normalized in {'pmx', 'pan', 'panamax'}:
            df = self.pmx_ffa
        else:
            raise ValueError(
                "Unsupported vessel_type. Use one of: cape, capesize, pmx, pan, panamax."
            )

        pivoted = df.pivot_table(
            index='Date',
            columns='Contract',
            values='Price',
            aggfunc='last'
        )
        return pivoted.sort_index().sort_index(axis=1)