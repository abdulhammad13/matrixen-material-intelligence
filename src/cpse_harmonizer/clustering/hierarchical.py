"""Layer 6 clustering: hierarchical grouping of near-duplicate material records."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, Sequence


class HierarchicalClusterer:
    """Simple deterministic clustering by text similarity for material families."""

    def __init__(self, threshold: float = 0.75) -> None:
        self.threshold = threshold

    def fit_predict(self, texts: Sequence[str]) -> list[int]:
        labels: list[int] = []
        clusters: list[list[str]] = []
        for text in texts:
            assigned = False
            for cluster_index, cluster in enumerate(clusters):
                representative = cluster[0]
                similarity = SequenceMatcher(None, representative.lower(), str(text).lower()).ratio()
                if similarity >= self.threshold:
                    cluster.append(str(text))
                    labels.append(cluster_index)
                    assigned = True
                    break
            if not assigned:
                clusters.append([str(text)])
                labels.append(len(clusters) - 1)
        return labels


def cluster_materials(texts: Iterable[str], threshold: float = 0.75) -> list[int]:
    """Cluster texts by similarity, returning a label for each item."""
    items = list(texts)
    return HierarchicalClusterer(threshold=threshold).fit_predict(items)
