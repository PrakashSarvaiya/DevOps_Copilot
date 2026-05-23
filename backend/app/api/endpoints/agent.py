from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_devops
from app.core.config import settings
from app.database.db import get_db
from app.models.models import AgentAction, AgentPoll, Build, Job, User
from app.schemas.schemas import (
    AgentActionResponse,
    AgentHandleResponse,
    AgentPollResponse,
    JenkinsWebhookPayload,
    ToolResponse,
    WebhookAck,
)
from app.services.agent import (
    handle_build_manually,
    process_jenkins_webhook,
    run_agent_once,
)
from app.services.agent_tools import default_registry

router = APIRouter()


@router.post("/run-once", response_model=List[Dict[str, Any]])
async def run_agent_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_devops),
):
    """Fire one poll cycle: sync builds, dispatch the controller for failures."""
    return await run_agent_once(db)


@router.post("/webhook/jenkins", response_model=WebhookAck)
async def jenkins_webhook(
    payload: JenkinsWebhookPayload,
    db: AsyncSession = Depends(get_db),
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Jenkins push entrypoint. Records the build, runs the controller on FAILURE."""
    if settings.AGENT_WEBHOOK_SECRET:
        if not x_webhook_secret or x_webhook_secret != settings.AGENT_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret",
            )

    result = await process_jenkins_webhook(db, payload)
    return WebhookAck(**result)


@router.get("/tools", response_model=List[ToolResponse])
async def list_tools(
    current_user: User = Depends(get_current_user),
):
    """Introspection: the controller's registered tools and their safety class."""
    return [
        ToolResponse(name=t.name, safety=t.safety.value, description=t.description)
        for t in default_registry.list()
    ]


def _action_to_response(a: AgentAction) -> AgentActionResponse:
    """Build a denormalized AgentActionResponse from an eagerly-loaded action."""
    build = getattr(a, "build", None)
    job = getattr(build, "job", None) if build else None
    return AgentActionResponse(
        id=a.id,
        build_id=a.build_id,
        build_number=build.number if build else None,
        job_name=job.name if job else None,
        action_type=a.action_type,
        status=a.status,
        tool_name=a.tool_name,
        reason=a.reason,
        developer_email=a.developer_email,
        created_at=a.created_at,
    )


@router.get("/actions", response_model=List[AgentActionResponse])
async def list_actions(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Most recent N rows from the agent audit ledger.

    Eagerly loads `build.job` so each row carries the build number and job
    name for the activity-feed UI without an N+1.
    """
    result = await db.execute(
        select(AgentAction)
        .options(selectinload(AgentAction.build).selectinload(Build.job))
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
    )
    return [_action_to_response(a) for a in result.scalars().all()]


@router.get("/actions/build/{build_id}", response_model=List[AgentActionResponse])
async def list_actions_for_build(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full agent trail for one build, oldest first (reads like a stage log)."""
    # 404 if the build doesn't exist so the client sees the difference between
    # "no actions yet" and "no such build".
    build_exists = await db.execute(select(Build.id).filter(Build.id == build_id))
    if not build_exists.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Build not found")

    result = await db.execute(
        select(AgentAction)
        .options(selectinload(AgentAction.build).selectinload(Build.job))
        .filter(AgentAction.build_id == build_id)
        .order_by(AgentAction.created_at.asc())
    )
    return [_action_to_response(a) for a in result.scalars().all()]


@router.get("/polls", response_model=List[AgentPollResponse])
async def list_polls(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Most recent N poll-tick fetches across all monitored jobs.

    One row per (job, poll tick) — populates the dashboard's "Agent Fetch
    Log". Job name is denormalized so the UI doesn't need a separate lookup.
    """
    result = await db.execute(
        select(AgentPoll)
        .options(selectinload(AgentPoll.job))
        .order_by(AgentPoll.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return [
        AgentPollResponse(
            id=p.id,
            job_id=p.job_id,
            job_name=p.job.name if p.job else None,
            build_number=p.build_number,
            status=p.status,
            error=p.error,
            created_at=p.created_at,
        )
        for p in rows
    ]


@router.post("/build/{build_id}/handle", response_model=AgentHandleResponse)
async def handle_build_now(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_devops),
):
    """
    Manually fire the controller against an existing build.

    Useful when an operator wants to replay the loop after fixing config (e.g.
    SMTP credentials) without waiting for the next poll cycle.
    """
    outcome = await handle_build_manually(db, build_id)
    if outcome.get("result") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Build not found")
    return outcome
