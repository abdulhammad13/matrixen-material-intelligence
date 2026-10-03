"""Deterministic group holdout helpers to keep related records out of both splits."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def grouped_holdout_indices(
    group_ids: Sequence[str],
    *,
    test_fraction: float = 0.2,
    seed: str = "nummf-v1",
) -> tuple[list[int], list[int]]:
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be strictly between zero and one.")
    groups = sorted(set(group_ids))
    if len(groups) < 2:
        raise ValueError("At least two independent groups are required for a holdout split.")
    test_groups = {
        group
        for group in groups
        if int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:16], 16) / 0xFFFFFFFFFFFFFFFF < test_fraction
    }
    if not test_groups:
        test_groups = {max(groups, key=lambda group: hashlib.sha256(f"{seed}:{group}".encode()).hexdigest())}
    if len(test_groups) == len(groups):
        test_groups.remove(min(test_groups))
    train = [index for index, group in enumerate(group_ids) if group not in test_groups]
    test = [index for index, group in enumerate(group_ids) if group in test_groups]
    return train, test
