"""Validation-set calibration adapters; calibrated probabilities stay separate from scores."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path


class PairCalibrator:
    def __init__(self, method: str = "platt") -> None:
        if method not in {"platt", "isotonic"}:
            raise ValueError("Calibration method must be 'platt' or 'isotonic'.")
        self.method = method
        self._estimator = None
        self._parameters: dict[str, object] = {}

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> PairCalibrator:
        if len(scores) != len(labels) or len(scores) < 4:
            raise ValueError("Calibration needs at least four aligned validation examples.")
        if set(labels) != {0, 1}:
            raise ValueError("Calibration validation examples must contain both classes.")
        if any(not 0.0 <= score <= 1.0 for score in scores):
            raise ValueError("Calibration input scores must lie in [0, 1].")
        if self.method == "platt":
            from sklearn.linear_model import LogisticRegression

            estimator = LogisticRegression(random_state=0, solver="lbfgs")
            estimator.fit([[score] for score in scores], list(labels))
            self._parameters = {
                "coefficient": float(estimator.coef_[0][0]),
                "intercept": float(estimator.intercept_[0]),
            }
        else:
            from sklearn.isotonic import IsotonicRegression

            estimator = IsotonicRegression(out_of_bounds="clip")
            estimator.fit(list(scores), list(labels))
            self._parameters = {
                "x_thresholds": [float(value) for value in estimator.X_thresholds_],
                "y_thresholds": [float(value) for value in estimator.y_thresholds_],
            }
        self._estimator = estimator
        return self

    def predict(self, scores: Sequence[float]) -> list[float]:
        if not self._parameters:
            raise RuntimeError("Calibrator must be fitted on a validation dataset before prediction.")
        if self.method == "platt":
            coefficient = float(self._parameters["coefficient"])
            intercept = float(self._parameters["intercept"])
            return [
                1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, coefficient * score + intercept))))
                for score in scores
            ]
        thresholds = self._parameters["x_thresholds"]
        outcomes = self._parameters["y_thresholds"]
        import numpy as np

        return [float(value) for value in np.interp(list(scores), thresholds, outcomes)]

    def save(self, path: str | Path) -> None:
        if not self._parameters:
            raise RuntimeError("Cannot save an unfitted calibrator.")
        payload = {"method": self.method, "parameters": self._parameters}
        payload["calibration_version"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> PairCalibrator:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload.pop("calibration_version", None)
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        if version != expected:
            raise ValueError("Calibration metadata checksum is invalid.")
        instance = cls(method=payload["method"])
        instance._parameters = payload["parameters"]
        return instance
