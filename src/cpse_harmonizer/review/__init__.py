"""Human review and decision pipeline for harmonized materials."""

__all__ = ["ReviewQueue"]


class ReviewQueue:
    """Placeholder review queue for governance workflows."""

    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, item: dict[str, object]) -> None:
        self.items.append(item)
