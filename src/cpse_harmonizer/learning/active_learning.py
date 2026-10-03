"""Layer 7 learning: feedback-driven pair mining and model promotion workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class FeedbackEvent:
    entity_id: str
    material_a: str
    material_b: str
    accepted: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ActiveLearningLoop:
    """Collect pair-level feedback and produce candidate training examples."""

    def __init__(self) -> None:
        self.events: list[FeedbackEvent] = []

    def add_feedback(self, event: FeedbackEvent) -> None:
        self.events.append(event)

    def mine_contrastive_pairs(self) -> list[tuple[str, str, bool]]:
        return [
            (event.material_a, event.material_b, event.accepted)
            for event in self.events
        ]

    def shadow_eval(self) -> dict[str, float]:
        positive = sum(1 for event in self.events if event.accepted)
        return {"positive_examples": positive, "total_examples": len(self.events), "quality": 1.0 if not self.events else positive / len(self.events)}

    def promote(self) -> bool:
        metrics = self.shadow_eval()
        return metrics["total_examples"] >= 1 and metrics["quality"] >= 0.8
