"""Metrics that consume explicit label sets and never synthesize test results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log2


def retrieval_metrics(
    retrieved: Mapping[str, Sequence[str]],
    relevant: Mapping[str, set[str]],
    cutoffs: Sequence[int] = (1, 5, 10),
) -> dict[str, float]:
    if not relevant:
        raise ValueError("Retrieval evaluation requires at least one labeled query.")
    if any(cutoff < 1 for cutoff in cutoffs):
        raise ValueError("Retrieval cutoffs must be positive.")
    recall_sums = {cutoff: 0.0 for cutoff in cutoffs}
    reciprocal_rank = 0.0
    ndcg_sum = 0.0
    for query_id, expected in relevant.items():
        if not expected:
            continue
        result = list(retrieved.get(query_id, ()))
        for cutoff in cutoffs:
            recall_sums[cutoff] += len(set(result[:cutoff]) & expected) / len(expected)
        first_rank = next((index for index, item in enumerate(result, 1) if item in expected), None)
        if first_rank:
            reciprocal_rank += 1 / first_rank
        dcg = sum(1 / log2(index + 2) for index, item in enumerate(result) if item in expected)
        ideal = sum(1 / log2(index + 2) for index in range(min(len(expected), len(result))))
        ndcg_sum += dcg / ideal if ideal else 0.0
    query_count = sum(bool(values) for values in relevant.values())
    if not query_count:
        raise ValueError("Retrieval evaluation has no queries with relevant candidates.")
    output = {f"recall_at_{k}": value / query_count for k, value in recall_sums.items()}
    output["mrr"] = reciprocal_rank / query_count
    output["ndcg"] = ndcg_sum / query_count
    return output


def pair_classification_metrics(
    labels: Sequence[int],
    scores: Sequence[float],
    *,
    threshold: float = 0.5,
    calibrated: bool = False,
    calibration_bins: int = 10,
) -> dict[str, float]:
    if len(labels) != len(scores) or not labels:
        raise ValueError("Evaluation requires non-empty, equal-length labels and scores.")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("Pair labels must be binary (0 or 1).")
    if any(not 0.0 <= score <= 1.0 for score in scores):
        raise ValueError("Scores must lie in [0, 1].")
    truth = [int(label) for label in labels]
    predicted = [int(score >= threshold) for score in scores]
    tp = sum(y == 1 and p == 1 for y, p in zip(truth, predicted, strict=True))
    fp = sum(y == 0 and p == 1 for y, p in zip(truth, predicted, strict=True))
    fn = sum(y == 1 and p == 0 for y, p in zip(truth, predicted, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    result = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "pr_auc": _average_precision(truth, scores),
    }
    if calibrated:
        result["brier_score"] = sum(
            (score - label) ** 2 for label, score in zip(truth, scores, strict=True)
        ) / len(truth)
        result["ece"] = expected_calibration_error(truth, scores, bins=calibration_bins)
    return result


def expected_calibration_error(
    labels: Sequence[int],
    probabilities: Sequence[float],
    *,
    bins: int = 10,
) -> float:
    if bins < 1 or len(labels) != len(probabilities) or not labels:
        raise ValueError("ECE requires aligned non-empty labels/probabilities and a positive bin count.")
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            (label, probability)
            for label, probability in zip(labels, probabilities, strict=True)
            if lower <= probability < upper or (index == bins - 1 and probability == 1.0)
        ]
        if members:
            confidence = sum(probability for _, probability in members) / len(members)
            accuracy = sum(label for label, _ in members) / len(members)
            error += len(members) / len(labels) * abs(confidence - accuracy)
    return error


def _average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    positives = sum(labels)
    if not positives:
        return 0.0
    ranked = sorted(zip(scores, labels, strict=True), key=lambda pair: -pair[0])
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positives
