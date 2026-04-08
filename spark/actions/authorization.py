"""Authorization flow for agent actions.

When Spark wants to do something (write code, push a branch), it asks
for permission first - unless the user has set agency_level to 'full'.
This module manages pending proposals and their approval/rejection.

Phase 4: Proposals are now persisted to the database via AgentTask
records, so they survive daemon restarts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

from spark.config import AgencyLevel
from spark.db.connection import get_session
from spark.db.models import AgentTask, TaskStatus, TaskType

logger = logging.getLogger(__name__)


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ActionProposal:
    """A proposed action awaiting user approval."""

    def __init__(
        self,
        project_id: str,
        project_name: str,
        action_type: str,
        description: str,
        details: str = "",
        task_id: str | None = None,
    ):
        self.project_id = project_id
        self.project_name = project_name
        self.action_type = action_type
        self.description = description
        self.details = details
        self.task_id = task_id
        self.status = ProposalStatus.PENDING
        self.created_at = datetime.utcnow()


# In-memory cache of proposals (backed by DB for persistence)
_pending_proposals: list[ActionProposal] = []


def _load_pending_from_db() -> None:
    """Load pending proposals from the database on startup.

    This allows proposals to survive daemon restarts.
    """
    from spark.db.models import Project

    _pending_proposals.clear()

    with get_session() as session:
        pending_tasks = (
            session.query(AgentTask)
            .filter(AgentTask.status == TaskStatus.PENDING.value)
            .order_by(AgentTask.created_at.asc())
            .all()
        )

        for task in pending_tasks:
            project = session.query(Project).filter(Project.id == task.project_id).first()
            project_name = project.name if project else "Unknown"

            proposal = ActionProposal(
                project_id=task.project_id,
                project_name=project_name,
                action_type=task.task_type,
                description=task.description,
                details=task.result.get("details", "") if task.result else "",
                task_id=task.id,
            )
            proposal.created_at = task.created_at
            _pending_proposals.append(proposal)

    if _pending_proposals:
        logger.info(f"Loaded {len(_pending_proposals)} pending proposals from database")


def needs_approval(agency_level: AgencyLevel, action_type: str) -> bool:
    """Check whether an action type requires user approval at the given agency level.

    Returns False (no approval needed) when the user's agency level permits the action.
    """
    if agency_level == AgencyLevel.FULL:
        return False

    if agency_level == AgencyLevel.LIGHT:
        # Light can do drafts and stubs without approval, but not push/PR
        no_approval_needed = {TaskType.CODE_GEN.value, TaskType.RESEARCH.value}
        return action_type not in no_approval_needed

    # Suggest level: everything needs approval (but we shouldn't even propose code)
    return True


def propose_action(
    project_id: str,
    project_name: str,
    action_type: str,
    description: str,
    details: str = "",
) -> ActionProposal:
    """Create a proposal for an action and store it for approval."""
    # Create a pending task record in DB
    with get_session() as session:
        task = AgentTask(
            project_id=project_id,
            task_type=action_type,
            description=description,
            status=TaskStatus.PENDING.value,
            result={"details": details} if details else None,
        )
        session.add(task)
        session.flush()
        task_id = task.id

    proposal = ActionProposal(
        project_id=project_id,
        project_name=project_name,
        action_type=action_type,
        description=description,
        details=details,
        task_id=task_id,
    )
    _pending_proposals.append(proposal)

    logger.info(f"Proposed action: {action_type} for {project_name}: {description}")
    return proposal


def format_proposal_message(proposal: ActionProposal) -> str:
    """Format a proposal into a user-friendly message for Telegram."""
    action_labels = {
        TaskType.CODE_GEN.value: "Write code",
        TaskType.PR.value: "Create branch & push",
        TaskType.RESEARCH.value: "Research",
        TaskType.ISSUE.value: "Create issue",
    }
    label = action_labels.get(proposal.action_type, proposal.action_type)

    msg = f"I'd like to {label.lower()} for {proposal.project_name}:\n\n"
    msg += f"{proposal.description}"
    if proposal.details:
        msg += f"\n\n{proposal.details}"
    msg += "\n\nReply 'go' to approve or 'skip' to pass."
    return msg


def get_pending_proposals() -> list[ActionProposal]:
    """Get all pending proposals."""
    return [p for p in _pending_proposals if p.status == ProposalStatus.PENDING]


def approve_latest() -> ActionProposal | None:
    """Approve the most recent pending proposal."""
    pending = get_pending_proposals()
    if not pending:
        return None

    proposal = pending[-1]
    proposal.status = ProposalStatus.APPROVED

    with get_session() as session:
        if proposal.task_id:
            task = session.query(AgentTask).filter(AgentTask.id == proposal.task_id).first()
            if task:
                task.status = TaskStatus.IN_PROGRESS.value

    logger.info(f"Approved proposal: {proposal.description}")
    return proposal


def reject_latest() -> ActionProposal | None:
    """Reject the most recent pending proposal."""
    pending = get_pending_proposals()
    if not pending:
        return None

    proposal = pending[-1]
    proposal.status = ProposalStatus.REJECTED

    with get_session() as session:
        if proposal.task_id:
            task = session.query(AgentTask).filter(AgentTask.id == proposal.task_id).first()
            if task:
                task.status = TaskStatus.FAILED.value
                task.completed_at = datetime.utcnow()

    logger.info(f"Rejected proposal: {proposal.description}")
    return proposal


def clear_expired(max_age_hours: float = 24.0) -> int:
    """Clear proposals older than max_age_hours.

    Also marks expired tasks in the database.
    """
    cutoff = datetime.utcnow()
    cleared = 0
    for proposal in _pending_proposals[:]:
        age_hours = (cutoff - proposal.created_at).total_seconds() / 3600
        if age_hours > max_age_hours and proposal.status == ProposalStatus.PENDING:
            proposal.status = ProposalStatus.EXPIRED

            # Also update DB record
            if proposal.task_id:
                with get_session() as session:
                    task = session.query(AgentTask).filter(
                        AgentTask.id == proposal.task_id
                    ).first()
                    if task:
                        task.status = TaskStatus.FAILED.value
                        task.completed_at = cutoff

            cleared += 1
    return cleared
