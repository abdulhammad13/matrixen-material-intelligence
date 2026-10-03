"""Layer 5 matching: weighted hybrid matching score for material harmonization."""

from __future__ import annotations

from cpse_harmonizer.config import AUTO_ACCEPT_SCORE, HUMAN_REVIEW_MAX_SCORE, HUMAN_REVIEW_MIN_SCORE, MATCH_WEIGHTS


class HybridScorer:
    """Blend dense, sparse, attribute and cross-encoder signals into a single score."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = MATCH_WEIGHTS.copy() if weights is None else weights

    def score(self, dense: float, sparse: float, attribute: float, cross_encoder: float = 0.0) -> float:
        value = (
            self.weights.get("dense", 0.35) * float(dense)
            + self.weights.get("sparse", 0.25) * float(sparse)
            + self.weights.get("attribute", 0.30) * float(attribute)
            + self.weights.get("cross_encoder", 0.10) * float(cross_encoder)
        )
        return max(0.0, min(1.0, value))

    @staticmethod
    def confidence_band(score: float) -> str:
        if score >= AUTO_ACCEPT_SCORE:
            return "Auto-accept"
        if HUMAN_REVIEW_MIN_SCORE <= score < HUMAN_REVIEW_MAX_SCORE:
            return "Human Review"
        return "Reject"

    def score_match(self, dense: float, sparse: float, attribute: float, cross_encoder: float = 0.0) -> dict[str, float | str]:
        score = self.score(dense, sparse, attribute, cross_encoder)
        return {
            "score": score,
            "confidence_band": self.confidence_band(score),
        }


def score_match(dense: float, sparse: float, attribute: float, cross_encoder: float = 0.0) -> dict[str, float | str]:
    return HybridScorer().score_match(dense, sparse, attribute, cross_encoder)
