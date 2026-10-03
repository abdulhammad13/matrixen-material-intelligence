"""Integration adapters for ERP, SAP, and external interfaces."""

__all__ = ["ERPAdapter"]


class ERPAdapter:
    """Minimal ERP adapter placeholder."""

    def __init__(self) -> None:
        self.config: dict[str, str] = {}

    def register(self, key: str, value: str) -> None:
        self.config[key] = value
