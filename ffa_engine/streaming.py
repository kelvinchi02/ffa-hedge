import random
from typing import Any, Dict, Generator, Iterable, List, Optional

import pandas as pd

from ffa_engine.data_loader import FFADataLoader


class ReservoirSampler:
    """Reservoir Sampling (Algorithm R) for streaming optimization inputs."""

    def __init__(self, k: int, seed: Optional[int] = None) -> None:
        if k <= 0:
            raise ValueError("k must be a positive integer.")

        self.k = k
        self.n = 0
        self.reservoir: List[Dict[str, Any]] = []
        self._rng = random.Random(seed)

    def update(self, item: Dict[str, Any]) -> None:
        """Process one packet while maintaining uniform sample probability."""
        self.n += 1
        packet = dict(item)

        if len(self.reservoir) < self.k:
            self.reservoir.append(packet)
            return

        replacement_index = self._rng.randrange(self.n)
        if replacement_index < self.k:
            self.reservoir[replacement_index] = packet

    def extend(self, items: Iterable[Dict[str, Any]]) -> None:
        """Consume an iterable of stream packets in a single pass."""
        for item in items:
            self.update(item)

    def clear(self) -> None:
        """Reset sampler state without changing reservoir size k."""
        self.n = 0
        self.reservoir.clear()

    def get_sample(self) -> List[Dict[str, Any]]:
        """Return a copy of current sample packets."""
        return list(self.reservoir)

    def get_sample_df(self) -> pd.DataFrame:
        """Expose sample as DataFrame for CVXPY feature construction."""
        return pd.DataFrame(self.reservoir)


class StreamController:
    """Build and stream merged spot/FFA packets for a single-pass engine."""

    _VESSEL_MAP = {
        "cape": "cape",
        "capesize": "cape",
        "pmx": "pmx",
        "pan": "pmx",
        "panamax": "pmx",
    }

    def __init__(self, loader: FFADataLoader):
        self.loader = loader
        self._merged_cache: Dict[str, pd.DataFrame] = {}

    @classmethod
    def _normalize_vessel_type(cls, vessel_type: str) -> str:
        normalized = vessel_type.strip().lower()
        canonical = cls._VESSEL_MAP.get(normalized)
        if canonical is None:
            raise ValueError(
                "Unsupported vessel_type. Use one of: cape, capesize, pmx, pan, panamax."
            )
        return canonical

    def _get_spot_frame(self, vessel_type: str) -> pd.DataFrame:
        return self.loader.cape_spot if vessel_type == "cape" else self.loader.pmx_spot

    def _build_merged_frame(self, vessel_type: str) -> pd.DataFrame:
        spot_df = self._get_spot_frame(vessel_type)
        ffa_df = self.loader.get_pivoted_ffa(vessel_type)

        # get_pivoted_ffa returns a Date index; align spot data to Date index for reliable joins.
        spot_indexed = spot_df.sort_values("Date").set_index("Date")
        merged = spot_indexed.join(ffa_df, how="inner")
        merged = merged.sort_index()

        if merged.empty:
            raise ValueError(
                f"No overlapping dates found between spot and FFA data for vessel_type='{vessel_type}'."
            )

        return merged

    def _get_merged_frame(self, vessel_type: str) -> pd.DataFrame:
        if vessel_type not in self._merged_cache:
            self._merged_cache[vessel_type] = self._build_merged_frame(vessel_type)
        return self._merged_cache[vessel_type]

    def stream_vessel_data(
        self,
        vessel_type: str = "cape",
        infinite: bool = True,
        include_cycle: bool = False,
    ) -> Generator[Dict[str, Any], None, None]:
        """Yield merged packets row-by-row and optionally cycle forever."""
        canonical = self._normalize_vessel_type(vessel_type)
        merged = self._get_merged_frame(canonical)
        columns = list(merged.columns)
        cycle_index = 0

        while True:
            for row in merged.itertuples(index=True, name=None):
                packet: Dict[str, Any] = {"Date": row[0]}
                packet.update(dict(zip(columns, row[1:])))
                if include_cycle:
                    packet["_cycle"] = cycle_index
                yield packet

            if not infinite:
                return

            cycle_index += 1

    def process_stream(
        self,
        sampler: ReservoirSampler,
        vessel_type: str = "cape",
        max_packets: Optional[int] = None,
        infinite: bool = True,
    ) -> int:
        """Consume the stream in a single pass and update a sampler incrementally."""
        packet_count = 0
        stream = self.stream_vessel_data(vessel_type=vessel_type, infinite=infinite)

        for packet in stream:
            sampler.update(packet)
            packet_count += 1

            if max_packets is not None and packet_count >= max_packets:
                break

        return packet_count


def run_demo_stream(
    k: int = 30,
    vessel_type: str = "cape",
    max_packets: int = 500,
    seed: Optional[int] = 42,
) -> None:
    """Run a finite preview of the infinite-stream engine."""
    loader = FFADataLoader()
    controller = StreamController(loader)
    sampler = ReservoirSampler(k=k, seed=seed)

    print(
        f"Starting {vessel_type.upper()} stream with reservoir size={k} and max_packets={max_packets}."
    )
    processed = controller.process_stream(
        sampler=sampler,
        vessel_type=vessel_type,
        max_packets=max_packets,
        infinite=True,
    )

    sample_df = sampler.get_sample_df()
    numeric_cols = sample_df.select_dtypes(include="number").columns
    mean_value = float(sample_df[numeric_cols].mean().mean()) if len(numeric_cols) else float("nan")

    print(
        f"Processed {processed} packets. Reservoir size={len(sample_df)}. "
        f"Mean across numeric sample fields={mean_value:.2f}"
    )


if __name__ == "__main__":  # pragma: no cover
    run_demo_stream()