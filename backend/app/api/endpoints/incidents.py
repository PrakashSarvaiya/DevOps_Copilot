from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.database.db import get_db
from app.models.models import Incident, User
from app.schemas.schemas import IncidentResponse, IncidentExportResponse
from app.api.deps import get_current_user
from typing import List

router = APIRouter()

@router.get("/", response_model=List[IncidentResponse])
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lists all logged Incidents in the system.
    Includes active analysis associations.
    """
    result = await db.execute(
        select(Incident).options(selectinload(Incident.analyses)).order_by(Incident.timestamp.desc())
    )
    return result.scalars().all()

@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Incident).filter(Incident.id == incident_id).options(selectinload(Incident.analyses))
    )
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident

@router.put("/{incident_id}/status", response_model=IncidentResponse)
async def update_incident_status(
    incident_id: int,
    status: str,
    resolution_notes: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Modifies status (Open, Investigating, Resolved, Closed).
    Attaches resolution post-mortem notes when closing.
    """
    valid_statuses = ["Open", "Investigating", "Resolved", "Closed"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
        
    result = await db.execute(
        select(Incident).filter(Incident.id == incident_id).options(selectinload(Incident.analyses))
    )
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
        
    incident.status = status
    if resolution_notes:
        incident.resolution_notes = resolution_notes
        
    await db.commit()
    await db.refresh(incident)
    return incident

@router.get("/{incident_id}/export", response_model=IncidentExportResponse)
async def export_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Compiles incident and analysis result metadata into a structured report.
    """
    result = await db.execute(
        select(Incident).filter(Incident.id == incident_id).options(selectinload(Incident.analyses))
    )
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
        
    # Get primary analysis details
    root_cause = "No AI analysis performed yet"
    suggested_fix = "No remediation suggested yet"
    if incident.analyses:
        primary_analysis = incident.analyses[0]
        root_cause = primary_analysis.root_cause
        suggested_fix = ", ".join(primary_analysis.recommendations) if primary_analysis.recommendations else suggested_fix
        
    return IncidentExportResponse(
        incident_uid=incident.incident_uid,
        timestamp=incident.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
        severity=incident.severity,
        system=incident.system,
        status=incident.status,
        root_cause=root_cause,
        suggested_fix=suggested_fix,
        resolution_notes=incident.resolution_notes
    )
