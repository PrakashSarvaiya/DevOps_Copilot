import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.schemas.schemas import JenkinsWebhookPayload
from app.models.models import AgentAction, AnalysisResult, Build, Incident, JenkinsServer, Job
from app.services.jenkins_client import JenkinsClient
from app.services.notifier import send_failure_email
from app.services.parser import parse_log_content
from app.services.rca_engine import analyze_log_rca

logger = logging.getLogger("DevOps_agent")

TRANSIENT_ERROR_PATTERNS = [
    "connection reset",
    "connection timed out",
    "timeout",
    "temporary failure",
    "temporarily unavailable",
    "network is unreachable",
    "503",
    "502",
    "rate limit",
    "agent went offline",
    "node disconnected",
    "workspace is locked",
]


def is_transient_failure(log_text: str, parsed_errors: List[Dict[str, Any]]) -> bool:
    haystack = "\n".join([log_text[-5000:], *[item.get("content", "") for item in parsed_errors]]).lower()
    return any(pattern in haystack for pattern in TRANSIENT_ERROR_PATTERNS)


async def _save_build(db: AsyncSession, job: Job, build_data: Dict[str, Any]) -> Build:
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


async def _count_agent_actions(db: AsyncSession, build_id: int, action_type: Optional[str] = None) -> int:
    query = select(AgentAction).filter(AgentAction.build_id == build_id)
    if action_type:
        query = query.filter(AgentAction.action_type == action_type)
    result = await db.execute(query)
    return len(result.scalars().all())


async def handle_failed_build(
    db: AsyncSession,
    build: Build,
    client: JenkinsClient,
    developer_email: Optional[str] = None,
) -> Dict[str, Any]:
    if build.analysis:
        return {"build_id": build.id, "action": "already_analyzed"}

    console_log = await client.get_console_output(build.job.name, build.number, build.job.url)
    build.console_output = console_log
    parsed_errors = parse_log_content(console_log)

    if settings.AGENT_AUTO_RERUN_ENABLED and is_transient_failure(console_log, parsed_errors):
        rerun_count = await _count_agent_actions(db, build.id, "RERUN")
        if rerun_count < settings.AGENT_MAX_RERUNS_PER_BUILD:
            triggered = await client.trigger_build(build.job.name, build.job.url)
            db.add(AgentAction(
                build_id=build.id,
                action_type="RERUN",
                status="Triggered" if triggered else "Failed",
                reason="Transient failure detected from Jenkins log.",
            ))
            await db.commit()
            return {"build_id": build.id, "action": "rerun_triggered" if triggered else "rerun_failed"}

    rca = await analyze_log_rca(console_log, parsed_errors)
    incident_uid = f"INC-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"
    incident = Incident(
        incident_uid=incident_uid,
        severity=rca.get("priority_level", "High"),
        system="Jenkins",
        status="Open",
        root_cause=rca.get("root_cause"),
        suggested_fix=rca.get("recommendations")[0] if rca.get("recommendations") else "Investigate Jenkins logs.",
    )
    db.add(incident)
    await db.flush()

    analysis = AnalysisResult(
        build_id=build.id,
        incident_id=incident.id,
        root_cause=rca.get("root_cause"),
        possible_issues=rca.get("possible_issues"),
        recommendations=rca.get("recommendations"),
        confidence_score=rca.get("confidence_score"),
        parsed_errors=parsed_errors,
        priority_level=rca.get("priority_level", "High"),
    )
    db.add(analysis)
    await db.flush()

    details = await client.get_build_details(build.job.name, build.number, build.job.url)
    recipient = developer_email or details.get("developer_email") or settings.DEFAULT_ALERT_EMAIL
    email_sent = False
    if recipient:
        body = (
            f"Pipeline: {build.job.name}\n"
            f"Build: #{build.number}\n"
            f"Status: {build.status}\n\n"
            f"Root cause:\n{analysis.root_cause}\n\n"
            f"Recommended fix:\n{incident.suggested_fix}\n"
        )
        email_sent = send_failure_email(
            recipient=recipient,
            subject=f"Jenkins failure: {build.job.name} #{build.number}",
            body=body,
        )

    db.add(AgentAction(
        build_id=build.id,
        action_type="NOTIFY",
        status="Sent" if email_sent else "Skipped",
        reason="Non-transient failure analyzed by DevOps Copilot.",
        developer_email=recipient,
    ))
    await db.commit()
    return {"build_id": build.id, "action": "notified" if email_sent else "analyzed_notification_skipped"}


async def run_agent_once(db: AsyncSession) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Job).options(selectinload(Job.server), selectinload(Job.builds).selectinload(Build.analysis))
    )
    jobs = result.scalars().all()
    actions: List[Dict[str, Any]] = []

    for job in jobs:
        server: JenkinsServer = job.server
        client = JenkinsClient(
            url=server.url,
            username=server.username,
            api_token=server.api_token,
            use_mock=settings.USE_MOCK_JENKINS,
        )
        try:
            builds = await client.get_builds(job.name, job.url)
            for build_data in builds:
                job.last_status = build_data["status"]
                build = await _save_build(db, job, build_data)
                await db.flush()
                if build.status == "FAILURE":
                    loaded_build_result = await db.execute(
                        select(Build).filter(Build.id == build.id).options(
                            selectinload(Build.job).selectinload(Job.server),
                            selectinload(Build.analysis),
                        )
                    )
                    loaded_build = loaded_build_result.scalars().first()
                    if loaded_build:
                        actions.append(await handle_failed_build(db, loaded_build, client))
            await db.commit()
        except Exception as exc:
            logger.warning("Agent skipped job %s: %s", job.name, exc)
            actions.append({"job_id": job.id, "job_name": job.name, "action": "error", "detail": str(exc)})

    return actions


async def process_jenkins_webhook(db: AsyncSession, payload: JenkinsWebhookPayload) -> Dict[str, Any]:
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

    client = JenkinsClient(
        url=server.url,
        username=server.username,
        api_token=server.api_token,
        use_mock=settings.USE_MOCK_JENKINS,
    )

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
        loaded_build_result = await db.execute(
            select(Build).filter(Build.id == build.id).options(
                selectinload(Build.job).selectinload(Job.server),
                selectinload(Build.analysis),
            )
        )
        loaded_build = loaded_build_result.scalars().first()
        if loaded_build:
            result = await handle_failed_build(
                db,
                loaded_build,
                client,
                developer_email=payload.developer_email,
            )
            return {
                "accepted": True,
                "action": result.get("action", "failure_processed"),
                "detail": "Failure processed from Jenkins webhook.",
                "build_id": build.id,
            }

    await db.commit()
    return {
        "accepted": True,
        "action": "build_recorded",
        "detail": f"Recorded {build.status.lower()} build from Jenkins webhook.",
        "build_id": build.id,
    }
