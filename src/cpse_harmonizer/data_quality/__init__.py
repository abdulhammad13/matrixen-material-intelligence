"""Data quality checks and validation routines for source material records."""

__all__ = ["DataQualityChecker"]


class DataQualityChecker:
    """A minimal data quality layer for material ingest validation."""

    def __init__(self) -> None:
        self.rules: list[str] = []

    def add_rule(self, rule: str) -> None:
        self.rules.append(rule)
