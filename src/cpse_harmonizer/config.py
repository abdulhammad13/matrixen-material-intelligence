"""Layer 0 configuration for the CPSE material harmonization stack.

This module centralizes threshold values so the project avoids "magic numbers" in
matching or review logic.
"""

from __future__ import annotations

# These are unvalidated ranking/review bands only. They are not probabilities
# and must not be used to publish nationally approved mappings.
AUTO_ACCEPT_SCORE = 1.01
HUMAN_REVIEW_MIN_SCORE = 0.0
HUMAN_REVIEW_MAX_SCORE = 1.01
REJECT_SCORE = 0.0
DEFAULT_MATCH_THRESHOLD = 0.70
DEFAULT_MODEL_VERSION = "rule-baseline-0.1"
SOVEREIGN_MODE = True

MATCH_WEIGHTS = {
    "dense": 0.35,
    "sparse": 0.25,
    "attribute": 0.30,
    "cross_encoder": 0.10,
}

TECHNICAL_COMPATIBILITY_TOLERANCE = 0.05
MAX_VOLTAGE_DIFF_FRACTION = 0.05
