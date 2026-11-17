"""Which adapters does "Fetch now" run?

For now this is a function, not a config file: the only automatic source is the sample
market. A real portal adapter would be added to the list here (CSV files are imported
on demand because they need a file).
"""

from __future__ import annotations

from immo.core.sample_data import SAMPLE_SOURCE
from immo.sources.base import SourceAdapter
from immo.sources.sample import SampleAdapter
from immo.storage.repository import Repository


def next_sample_round(repo: Repository) -> int:
    """Each logged sample run advances the simulated market by one round.

    `seed` logs 12 runs (rounds 0-11), so the first "Fetch now" gets round 12.
    """
    return repo.count_fetch_runs(SAMPLE_SOURCE)


def active_adapters(repo: Repository) -> list[SourceAdapter]:
    return [SampleAdapter(round_index=next_sample_round(repo))]
