from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.database.db import get_db
from app.models.models import User, JenkinsServer, Job, Build
from app.schemas.schemas import JenkinsServerCreate, JenkinsServerResponse, JenkinsJobCandidate, JenkinsMonitorSelection, JobResponse, BuildResponse
from app.api.deps import get_current_user
from app.services.jenkins_client import JenkinsClient
from typing import List

router = APIRouter()

@router.post("/connect", response_model=JenkinsServerResponse)
async def connect_jenkins(
    server_in: JenkinsServerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Validates connection parameters, establishes links,
    and saves the Jenkins Server credentials to the user profile.
    """
    client = JenkinsClient(
        url=server_in.url,
        username=server_in.username,
        api_token=server_in.api_token,
    )
    try:
        await client.get_jobs()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc

    server = JenkinsServer(
        name=server_in.name,
        url=server_in.url,
        username=server_in.username,
        api_token=server_in.api_token,
        user_id=current_user.id
    )
    
    # Simple ping check in real life. Here, we add it to database
    db.add(server)
    await db.commit()
    await db.refresh(server)

    return server

@router.get("/servers", response_model=List[JenkinsServerResponse])
async def list_servers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(JenkinsServer).filter(JenkinsServer.user_id == current_user.id))
    return result.scalars().all()

@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(JenkinsServer).filter(JenkinsServer.id == server_id, JenkinsServer.user_id == current_user.id)
    )
    server = result.scalars().first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jenkins server not found")

    await db.delete(server)
    await db.commit()

@router.get("/servers/{server_id}/available-jobs", response_model=List[JenkinsJobCandidate])
async def list_available_jobs(
    server_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result_server = await db.execute(
        select(JenkinsServer).filter(JenkinsServer.id == server_id, JenkinsServer.user_id == current_user.id)
    )
    server = result_server.scalars().first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jenkins server not found")

    result_jobs = await db.execute(select(Job).filter(Job.server_id == server_id))
    monitored_jobs = result_jobs.scalars().all()
    monitored_lookup = {job.url: job for job in monitored_jobs}

    client = JenkinsClient(
        url=server.url,
        username=server.username,
        api_token=server.api_token,
    )
    jenkins_jobs = await client.get_jobs()

    return [
        JenkinsJobCandidate(
            name=job_data["name"],
            url=job_data["url"],
            last_status=job_data.get("last_status"),
            monitored=job_data["url"] in monitored_lookup,
            pipeline_type=monitored_lookup.get(job_data["url"]).pipeline_type if job_data["url"] in monitored_lookup else "BUILD",
        )
        for job_data in jenkins_jobs
    ]

@router.put("/servers/{server_id}/monitored-jobs", response_model=List[JobResponse])
async def save_monitored_jobs(
    server_id: int,
    selection: JenkinsMonitorSelection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result_server = await db.execute(
        select(JenkinsServer).filter(JenkinsServer.id == server_id, JenkinsServer.user_id == current_user.id)
    )
    server = result_server.scalars().first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jenkins server not found")

    result_existing = await db.execute(select(Job).filter(Job.server_id == server_id))
    existing_jobs = {job.url: job for job in result_existing.scalars().all()}
    selected_urls = {job.url for job in selection.jobs}

    for url, job in existing_jobs.items():
        if url not in selected_urls:
            await db.delete(job)

    for job_data in selection.jobs:
        existing = existing_jobs.get(job_data.url)
        pipeline_type = job_data.pipeline_type or "BUILD"
        if existing:
            existing.name = job_data.name
            existing.last_status = job_data.last_status
            existing.pipeline_type = pipeline_type
        else:
            db.add(Job(
                name=job_data.name,
                url=job_data.url,
                last_status=job_data.last_status,
                pipeline_type=pipeline_type,
                server_id=server.id,
            ))

    await db.commit()

    result_jobs = await db.execute(select(Job).filter(Job.server_id == server_id))
    return result_jobs.scalars().all()

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    server_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result_server = await db.execute(
        select(JenkinsServer).filter(JenkinsServer.id == server_id, JenkinsServer.user_id == current_user.id)
    )
    server = result_server.scalars().first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jenkins server not found")
        
    result_jobs = await db.execute(select(Job).filter(Job.server_id == server_id))
    return result_jobs.scalars().all()

@router.get("/jobs/{job_id}/builds", response_model=List[BuildResponse])
async def list_builds(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result_job = await db.execute(
        select(Job).filter(Job.id == job_id).options(selectinload(Job.server))
    )
    job = result_job.scalars().first()
    if not job or job.server.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    # Fetch builds from Jenkins or Mock
    client = JenkinsClient(
        url=job.server.url,
        username=job.server.username,
        api_token=job.server.api_token,
    )
    
    try:
        jenkins_builds = await client.get_builds(job.name, job.url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)
        ) from exc
    
    # Save/sync with local DB representation
    synchronized_builds = []
    for build_data in jenkins_builds:
        # Check if build already synced
        result_build = await db.execute(
            select(Build).filter(Build.job_id == job.id, Build.number == build_data["number"])
        )
        db_build = result_build.scalars().first()
        
        if not db_build:
            db_build = Build(
                number=build_data["number"],
                status=build_data["status"],
                duration=build_data["duration"],
                timestamp=build_data["timestamp"],
                job_id=job.id
            )
            db.add(db_build)
            await db.commit()
            await db.refresh(db_build)
        else:
            db_build.status = build_data["status"]
            db_build.duration = build_data["duration"]
            db_build.timestamp = build_data["timestamp"]
        
        synchronized_builds.append(db_build)

    return synchronized_builds
