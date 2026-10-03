"""Layer 8 governance: append-only audit trail for material decisions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuditRecord:
    entity_type: str
    entity_id: str
    event_type: str
    actor: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            import hashlib

            payload = json.dumps({
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "event_type": self.event_type,
                "actor": self.actor,
                "details": self.details,
                "timestamp": self.timestamp,
            }, sort_keys=True).encode("utf-8")
            self.event_id = hashlib.sha256(payload).hexdigest()[:12]


class AuditLog:
    """Append-only audit log storing decisions and actions in JSON lines format."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.entries: list[AuditRecord] = []

    def append(self, entity_type: str, entity_id: str, event_type: str, actor: str, **details: Any) -> AuditRecord:
        record = AuditRecord(entity_type=entity_type, entity_id=entity_id, event_type=event_type, actor=actor, details=dict(details))
        self.entries.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        return record

    def read(self) -> list[AuditRecord]:
        return list(self.entries)


def append_event(log_path: str | Path | None, entity_type: str, entity_id: str, event_type: str, actor: str, **details: Any) -> AuditRecord:
    return AuditLog(log_path).append(entity_type, entity_id, event_type, actor, **details)
