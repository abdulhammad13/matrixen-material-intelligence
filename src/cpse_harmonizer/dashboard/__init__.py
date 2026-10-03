"""Dashboard and analytics package for the harmonization workflow."""

__all__ = ["DashboardApp"]


class DashboardApp:
    """Minimal dashboard placeholder used for smoke validation."""

    def __init__(self) -> None:
        self.panels: list[str] = []

    def add_panel(self, panel: str) -> None:
        self.panels.append(panel)
