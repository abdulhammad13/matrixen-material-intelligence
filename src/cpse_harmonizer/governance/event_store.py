"""Event store wrappers for extraction and decision logging."""

from __future__ import annotations

from cpse_harmonizer.governance.audit import AuditLog


class EventStore(AuditLog):
    """Backward-compatible event log for extraction decision records."""

    pass
