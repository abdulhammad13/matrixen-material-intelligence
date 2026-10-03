"""Spend graph signals for procurement and material intelligence."""

from __future__ import annotations

from typing import Any


class SpendGraph:
    """Lightweight graph container for procurement demand signals."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []

    def add_material_signal(self, material: str, quantity: float | None, uom: str, source: str) -> None:
        self.nodes.append({"id": material, "label": material, "source": source})
        if quantity is not None:
            self.edges.append({"source": source, "target": material, "value": float(quantity), "uom": uom})
