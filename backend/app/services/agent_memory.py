"""
Memory layer for the Agent Controller.

This is the "what's worked before on this pipeline?" surface the Plan stage
queries to act like a junior engineer with experience instead of an
amnesiac one. Every function reads from the AgentAction audit ledger — it
is the *only* persistence layer the agent has.

All queries are scoped by job_id so judgement is per-pipeline. A job that
flakes a lot on network does not pollute decisions for a different job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import AgentAction, Build


# ---------------------------------------------------------------------------
# Existing, retained for the controller's lighter-weight checks.
# ---------------------------------------------------------------------------


async def retries_for_build(db: AsyncSession, build_id: int) -> int:
    """Count how many retry attempts the agent has already made on this build."""
    result = await db.execute(
        select(AgentAction).filter(
            AgentAction.build_id == build_id,
            AgentAction.tool_name == "jenkins.retry_build",
            AgentAction.action_type == "EXECUTE",
        )
    )
    return len(result.scalars().all())


async def last_retry_outcome_for_job(
    db: AsyncSession, job_id: int
) -> Optional[Dict[str, Any]]:
    """
    Return the most recent retry attempt for *any* build of this job, as
    {"build_id": int, "status": "Triggered"|"Failed", "reason": str}, or None
    if the agent has never retried this job.
    """
    result = await db.execute(
        select(AgentAction, Build)
        .join(Build, Build.id == AgentAction.build_id)
        .filter(
            Build.job_id == job_id,
            AgentAction.tool_name == "jenkins.retry_build",
            AgentAction.action_type == "EXECUTE",
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        return None
    action, build = row
    return {
        "build_id": build.id,
        "status": action.status,
        "reason": action.reason,
    }


async def recent_actions_for_job(
    db: AsyncSession, job_id: int, limit: int = 20
) -> List[AgentAction]:
    """Return the most recent agent actions across all builds of this job."""
    result = await db.execute(
        select(AgentAction)
        .join(Build, Build.id == AgentAction.build_id)
        .filter(Build.job_id == job_id)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Junior-judgement queries
# ---------------------------------------------------------------------------


@dataclass
class RetrySuccessStats:
    """Outcome rollup for `retry_success_rate` — easier to print/log than a tuple."""

    attempts: int
    successes: int

    @property
    def rate(self) -> float:
        return (self.successes / self.attempts) if self.attempts else 0.0

    def describe(self) -> str:
        if self.attempts == 0:
            return "no prior retry attempts on this pipeline"
        return (
            f"retry recovered {self.successes}/{self.attempts} "
            f"prior failures (rate={self.rate:.0%})"
        )


async def retry_success_rate(db: AsyncSession, job_id: int) -> RetrySuccessStats:
    """
    Did retry actually *fix* past failures on this job?

    For every `EXECUTE` action with tool=jenkins.retry_build and status=Triggered
    on this job, look for the *next* Build (by number) on the same job and
    count it as a success if that next build ended SUCCESS.

    Returns counts, not just a rate, so the planner can tell "0/0" (no data)
    apart from "0/5" (always fails).
    """
    # Pull all RETRY-Triggered actions for this job, oldest first.
    retry_rows = await db.execute(
        select(AgentAction, Build)
        .join(Build, Build.id == AgentAction.build_id)
        .filter(
            Build.job_id == job_id,
            AgentAction.tool_name == "jenkins.retry_build",
            AgentAction.action_type == "EXECUTE",
            AgentAction.status == "Triggered",
        )
        .order_by(AgentAction.created_at.asc())
    )
    retries = retry_rows.all()
    if not retries:
        return RetrySuccessStats(attempts=0, successes=0)

    # Pull every build for this job once, keyed by number.
    build_rows = await db.execute(
        select(Build).filter(Build.job_id == job_id).order_by(Build.number.asc())
    )
    builds_by_number: Dict[int, Build] = {b.number: b for b in build_rows.scalars().all()}

    attempts = 0
    successes = 0
    for _action, retried_build in retries:
        next_build = builds_by_number.get(retried_build.number + 1)
        if next_build is None:
            # Retry hasn't produced a follow-up build yet; doesn't count
            # for or against.
            continue
        attempts += 1
        if next_build.status == "SUCCESS":
            successes += 1

    return RetrySuccessStats(attempts=attempts, successes=successes)


async def consecutive_failures_of_action(
    db: AsyncSession, job_id: int, tool_name: str
) -> int:
    """
    Count how many of the most recent EXECUTE rows for this (job, tool) ended
    with status="Failed" *in a row*, walking from newest backwards. Returns 0
    if the most recent one succeeded.

    Used by the planner as a hard escalation guard: "this tool just keeps
    failing on this pipeline — stop choosing it."
    """
    result = await db.execute(
        select(AgentAction)
        .join(Build, Build.id == AgentAction.build_id)
        .filter(
            Build.job_id == job_id,
            AgentAction.tool_name == tool_name,
            AgentAction.action_type == "EXECUTE",
        )
        .order_by(AgentAction.created_at.desc())
    )
    streak = 0
    for action in result.scalars().all():
        if action.status == "Failed":
            streak += 1
        else:
            break
    return streak


async def last_action_outcome_by_class(
    db: AsyncSession, job_id: int, failure_class: str
) -> Optional[Dict[str, Any]]:
    """
    "Last time this job failed with this class, what action did the agent take
    and how did it end up?"

    Looks up the most recent PLAN row on this job whose `reason` mentions the
    failure class (the controller embeds the class string in the rationale),
    then returns the EXECUTE outcome that immediately followed it on the same
    build, if any.

    Returns a dict {tool_name, execute_status, plan_status} or None.
    """
    # Find the most recent PLAN row referencing this class.
    plan_result = await db.execute(
        select(AgentAction, Build)
        .join(Build, Build.id == AgentAction.build_id)
        .filter(
            Build.job_id == job_id,
            AgentAction.action_type == "PLAN",
            AgentAction.reason.ilike(f"%{failure_class}%"),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
    )
    plan_row = plan_result.first()
    if not plan_row:
        return None
    plan_action, build = plan_row

    # Find the first EXECUTE on the same build whose timestamp >= the PLAN row.
    exec_result = await db.execute(
        select(AgentAction)
        .filter(
            AgentAction.build_id == build.id,
            AgentAction.action_type == "EXECUTE",
            AgentAction.created_at >= plan_action.created_at,
        )
        .order_by(AgentAction.created_at.asc())
        .limit(1)
    )
    exec_action = exec_result.scalars().first()

    return {
        "build_id": build.id,
        "plan_status": plan_action.status,
        "plan_reason": plan_action.reason,
        "tool_name": exec_action.tool_name if exec_action else None,
        "execute_status": exec_action.status if exec_action else None,
    }
