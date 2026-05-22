"""
Agent service — observation + dispatch layer.

This module is the *entry* surface the rest of the app talks to:

  - `run_agent_once` — polled by the lifespan loop in main.py
  - `process_jenkins_webhook` — Jenkins push notifications

For each FAILURE event it discovers, it constructs an AgentController and
delegates the full Observe → ... → Report loop. SUCCESS / ABORTED / RUNNING
events are just recorded in the local DB (the controller's first OBSERVE
stage handles those branches too, but for cheap polls we avoid building a
controller when there's nothing to do).

The seven-stage loop, tool registry, and safe/blocked allowlist live in
agent_controller.py and agent_tools.py — this file is intentionally thin.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.models import Build, JenkinsServer, Job
from app.schemas.schemas import JenkinsWebhookPayload
from app.services.agent_controller import AgentController
from app.services.jenkins_client import JenkinsClient

logger = logging.getLogger("DevOps_agent")


async def _save_build(db: AsyncSession, job: Job, build_data: Dict[str, Any]) -> Build:
    """Idempotently upsert a Build row from Jenkins data."""
    result = await db.execute(
        select(Build).filter(Build.job_id == job.id, Build.number == build_data["number"])
    )
    build = result.scalars().first()
    if build:
        build.status = build_data["status"]
        build.duration = build_data["duration"]
        build.timestamp = build_data["timestamp"]
        return build

    build = Build(
        number=build_data["number"],
        status=build_data["status"],
        duration=build_data["duration"],
        timestamp=build_data["timestamp"],
        job_id=job.id,
    )
    db.add(build)
    await db.flush()
    return build


async def _load_build_with_relations(db: AsyncSession, build_id: int) -> Build:
    """Return a Build with `job` and `job.server` eagerly loaded."""
    result = await db.execute(
        select(Build).filter(Build.id == build_id).options(
            selectinload(Build.job).selectinload(Job.server),
        )
    )
    return result.scalars().first()


def _client_for(server: JenkinsServer) -> JenkinsClient:
    return JenkinsClient(
        url=server.url,
        username=server.username,
        api_token=server.api_token,
    )


async def run_agent_once(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Poll all monitored jobs, sync builds, and dispatch the controller for
    failures. Returns a list of per-build outcome summaries.
    """
    controller = AgentController()
    result = await db.execute(
        select(Job).options(selectinload(Job.server), selectinload(Job.builds))
    )
    jobs = result.scalars().all()
    outcomes: List[Dict[str, Any]] = []

    for job in jobs:
        client = _client_for(job.server)
        try:
            builds = await client.get_builds(job.name, job.url)
            for build_data in builds:
                job.last_status = build_data["status"]
                build = await _save_build(db, job, build_data)
                await db.flush()
                if build.status == "FAILURE":
                    loaded = await _load_build_with_relations(db, build.id)
                    if loaded:
                        outcome = await controller.handle_build_event(db, loaded, client)
                        outcomes.append(outcome)
            await db.commit()
        except Exception as exc:
            logger.warning("Agent skipped job %s: %s", job.name, exc)
            outcomes.append({
                "job_id": job.id,
                "job_name": job.name,
                "action": "error",
                "detail": str(exc),
            })

    return outcomes


async def process_jenkins_webhook(
    db: AsyncSession, payload: JenkinsWebhookPayload
) -> Dict[str, Any]:
    """
    Handle an inbound Jenkins push: record the build, and on FAILURE run the
    controller. Returns the WebhookAck payload shape.
    """
    normalized_server_url = payload.jenkins_url.rstrip("/")
    normalized_job_url = payload.job_url.rstrip("/") if payload.job_url else None

    server_result = await db.execute(
        select(JenkinsServer).filter(JenkinsServer.url == normalized_server_url)
    )
    server = server_result.scalars().first()
    if not server:
        return {
            "accepted": False,
            "action": "server_not_found",
            "detail": "No Jenkins server matched the webhook URL.",
        }

    if payload.job_url:
        job_result = await db.execute(
            select(Job).filter(Job.server_id == server.id, Job.url == normalized_job_url)
        )
    else:
        job_result = await db.execute(
            select(Job).filter(Job.server_id == server.id, Job.name == payload.job_name)
        )
    job = job_result.scalars().first()
    if not job:
        return {
            "accepted": False,
            "action": "job_not_found",
            "detail": "No monitored job matched the webhook payload.",
        }

    build_data = {
        "number": payload.build_number,
        "status": payload.status.upper(),
        "duration": 0,
        "timestamp": datetime.utcnow(),
    }

    build = await _save_build(db, job, build_data)
    job.last_status = build_data["status"]
    await db.flush()

    if build.status == "FAILURE":
        loaded = await _load_build_with_relations(db, build.id)
        if loaded:
            controller = AgentController()
            client = _client_for(server)
            outcome = await controller.handle_build_event(db, loaded, client)
            return {
                "accepted": True,
                "action": outcome.get("result", "handled"),
                "detail": (
                    f"Controller ran stages: {','.join(outcome.get('stages', []))} "
                    f"plan={outcome.get('plan')}."
                ),
                "build_id": build.id,
            }

    await db.commit()
    return {
        "accepted": True,
        "action": "build_recorded",
        "detail": f"Recorded {build.status.lower()} build from Jenkins webhook.",
        "build_id": build.id,
    }


async def handle_build_manually(db: AsyncSession, build_id: int) -> Dict[str, Any]:
    """
    Fire the controller on demand for an existing build. Used by the
    POST /agent/build/{build_id}/handle endpoint so operators can replay
    the loop without waiting for the poll cycle.
    """
    loaded = await _load_build_with_relations(db, build_id)
    if not loaded:
        return {"build_id": build_id, "result": "not_found"}

    controller = AgentController()
    client = _client_for(loaded.job.server)
    return await controller.handle_build_event(db, loaded, client)
