"""Schema intelligence utilities for material and procurement metadata."""

__all__ = ["SchemaInsight"]


class SchemaInsight:
    """A light, schema-aware metadata helper for evolving data models."""

    def __init__(self) -> None:
        self.columns: list[str] = []

    def register(self, column: str) -> None:
        self.columns.append(column)
