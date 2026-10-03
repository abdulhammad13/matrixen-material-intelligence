"""Durable review queue with explicit maker-checker transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from cpse_harmonizer.domain.models import MaterialPair, PairRelation, ReviewStatus, ReviewTask
from cpse_harmonizer.persistence.database import (
    Database,
    MaterialPairRow,
    ReviewDecisionRow,
    ReviewTaskRow,
)


class ReviewWorkflowError(ValueError):
    """Raised when a requested review transition is invalid."""


class ReviewQueue:
    """Persistent queue; approvals require a different checker than the reviewer."""

    def __init__(self, database: Database | None = None) -> None:
        self.database = database or Database()
        self.database.initialize()

    def add(self, item: dict[str, Any] | ReviewTask) -> ReviewTask:
        task = item if isinstance(item, ReviewTask) else ReviewTask.model_validate(item)
        with self.database.sessions.begin() as session:
            pair_row = session.get(MaterialPairRow, task.pair.id)
            if pair_row is None:
                pair_row = MaterialPairRow(
                    id=task.pair.id,
                    material_a=task.pair.material_a,
                    material_b=task.pair.material_b,
                )
                session.add(pair_row)
            existing = session.get(ReviewTaskRow, task.id)
            if existing is None:
                session.add(ReviewTaskRow(
                    id=task.id,
                    pair_id=task.pair.id,
                    status=task.status.value,
                    assigned_to=task.assigned_to,
                    created_by=task.created_by,
                    priority=task.priority,
                    rationale=task.rationale,
                    created_at=task.created_at,
                    updated_at=task.created_at,
                ))
        return self.get(task.id)

    def assign(self, task_id: str, reviewer_id: str) -> ReviewTask:
        with self.database.sessions.begin() as session:
            task = self._required(session, task_id)
            if task.status != ReviewStatus.PENDING.value:
                raise ReviewWorkflowError(f"Only PENDING tasks may be assigned; task is {task.status}.")
            task.status = ReviewStatus.ASSIGNED.value
            task.assigned_to = reviewer_id
            task.updated_at = datetime.now(UTC)
        return self.get(task_id)

    def decide(
        self,
        task_id: str,
        reviewer_id: str,
        reviewer_role: str,
        relation: PairRelation,
        reason_codes: list[str] | None = None,
        notes: str = "",
    ) -> ReviewTask:
        if reviewer_role not in {"COMMODITY_EXPERT", "DATA_STEWARD", "ADMIN"}:
            raise ReviewWorkflowError("Only a commodity expert, data steward, or admin may submit a review decision.")
        with self.database.sessions.begin() as session:
            task = self._required(session, task_id)
            if task.status != ReviewStatus.ASSIGNED.value:
                raise ReviewWorkflowError(f"Only ASSIGNED tasks may be reviewed; task is {task.status}.")
            if task.assigned_to and task.assigned_to != reviewer_id:
                raise ReviewWorkflowError("Only the assigned reviewer may submit this decision.")
            if reviewer_id == task.created_by and task.created_by != "system":
                raise ReviewWorkflowError("The task maker cannot act as its reviewer.")
            session.add(ReviewDecisionRow(
                review_id=task_id,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                relation=relation.value,
                reason_codes=reason_codes or [],
                notes=notes,
            ))
            task.status = ReviewStatus.CHECKER_PENDING.value
            task.updated_at = datetime.now(UTC)
        return self.get(task_id)

    def approve(
        self,
        task_id: str,
        checker_id: str,
        checker_role: str,
        *,
        approved: bool,
    ) -> ReviewTask:
        if checker_role not in {"CHECKER", "ADMIN"}:
            raise ReviewWorkflowError("Only a checker or admin may approve/reject a reviewed task.")
        with self.database.sessions.begin() as session:
            task = self._required(session, task_id)
            if task.status != ReviewStatus.CHECKER_PENDING.value:
                raise ReviewWorkflowError(f"Only CHECKER_PENDING tasks may be resolved; task is {task.status}.")
            latest = session.scalar(
                select(ReviewDecisionRow)
                .where(ReviewDecisionRow.review_id == task_id)
                .order_by(ReviewDecisionRow.id.desc())
                .limit(1)
            )
            if latest is None:
                raise ReviewWorkflowError("No maker decision exists for this task.")
            if checker_id == latest.reviewer_id:
                raise ReviewWorkflowError("Maker-checker separation prohibits self-approval.")
            latest.checker_id = checker_id
            latest.checker_role = checker_role
            latest.approved = approved
            task.status = ReviewStatus.APPROVED.value if approved else ReviewStatus.REJECTED.value
            task.updated_at = datetime.now(UTC)
        return self.get(task_id)

    def get(self, task_id: str) -> ReviewTask:
        with self.database.sessions() as session:
            row = self._required(session, task_id)
            pair = session.get(MaterialPairRow, row.pair_id)
            if pair is None:
                raise ReviewWorkflowError(f"Review task {task_id} has no material pair.")
            return ReviewTask(
                id=row.id,
                pair=MaterialPair(material_a=pair.material_a, material_b=pair.material_b, id=pair.id),
                status=ReviewStatus(row.status),
                assigned_to=row.assigned_to,
                created_by=row.created_by,
                priority=row.priority,
                rationale=row.rationale or [],
                created_at=row.created_at,
            )

    def list(self, status: ReviewStatus | None = None, limit: int = 100) -> list[ReviewTask]:
        if limit < 1 or limit > 1000:
            raise ValueError("Review task limit must be between 1 and 1000.")
        with self.database.sessions() as session:
            statement = select(ReviewTaskRow).order_by(ReviewTaskRow.created_at.desc()).limit(limit)
            if status:
                statement = statement.where(ReviewTaskRow.status == status.value)
            ids = list(session.scalars(statement))
            return [self.get(row.id) for row in ids]

    @staticmethod
    def _required(session, task_id: str) -> ReviewTaskRow:
        task = session.get(ReviewTaskRow, task_id)
        if task is None:
            raise KeyError(f"Review task not found: {task_id}")
        return task
