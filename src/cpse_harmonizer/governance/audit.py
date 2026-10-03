"""Append-only JSONL audit events with a verifiable hash chain."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuditRecord:
    entity_type: str
    entity_id: str
    event_type: str
    actor: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_id: str = ""
    input_hash: str = ""
    output_hash: str = ""
    model_version: str = ""
    previous_event_hash: str = ""
    event_hash: str = ""


class AuditLog:
    """Durable event log. Any altered, removed, or reordered event breaks verification."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.entries: list[AuditRecord] = []
        self._lock = threading.RLock()

    def append(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor: str,
        **details: Any,
    ) -> AuditRecord:
        with self._lock:
            current = self.read()
            previous = current[-1].event_hash if current else ""
            timestamp = datetime.now(UTC).isoformat()
            safe_details = dict(details)
            record = AuditRecord(
                entity_type=entity_type,
                entity_id=entity_id,
                event_type=event_type,
                actor=actor,
                details=safe_details,
                timestamp=timestamp,
                input_hash=self._hash_payload(safe_details.get("input")),
                output_hash=self._hash_payload(safe_details.get("output")),
                model_version=str(safe_details.get("model_version", "")),
                previous_event_hash=previous,
            )
            payload = self._event_payload(record)
            record.event_hash = self._hash_payload(payload)
            record.event_id = f"evt_{record.event_hash[:24]}"
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            else:
                self.entries.append(record)
            return record

    def read(self) -> list[AuditRecord]:
        with self._lock:
            if self.path is None:
                return list(self.entries)
            if not self.path.exists():
                return []
            records: list[AuditRecord] = []
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        records.append(AuditRecord(**json.loads(line)))
                    except (json.JSONDecodeError, TypeError) as exc:
                        raise ValueError(f"Invalid audit event at {self.path}:{line_number}") from exc
            return records

    def verify(self) -> bool:
        previous = ""
        for record in self.read():
            if record.previous_event_hash != previous:
                return False
            expected = self._hash_payload(self._event_payload(record))
            if expected != record.event_hash or record.event_id != f"evt_{expected[:24]}":
                return False
            previous = record.event_hash
        return True

    @staticmethod
    def _event_payload(record: AuditRecord) -> dict[str, Any]:
        return {
            "entity_type": record.entity_type,
            "entity_id": record.entity_id,
            "event_type": record.event_type,
            "actor": record.actor,
            "details": record.details,
            "timestamp": record.timestamp,
            "input_hash": record.input_hash,
            "output_hash": record.output_hash,
            "model_version": record.model_version,
            "previous_event_hash": record.previous_event_hash,
        }

    @staticmethod
    def _hash_payload(value: Any) -> str:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def append_event(
    log_path: str | Path | None,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str,
    **details: Any,
) -> AuditRecord:
    return AuditLog(log_path).append(entity_type, entity_id, event_type, actor, **details)
