from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.schemas.schemas import LogUploadRequest, AnalysisResultResponse
from app.api.deps import get_current_user
from app.models.models import User, AnalysisResult, Incident
from app.services.parser import parse_log_content
from app.services.rca_engine import analyze_log_rca
from datetime import datetime
import uuid

router = APIRouter()

@router.post("/log", response_model=AnalysisResultResponse)
async def analyze_uploaded_log(
    request: LogUploadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Direct text paste log analyzer. Validates payload, extracts errors,
    triggers AI model analysis, and maps findings to ad-hoc Incident tickets.
    """
    console_log = request.log_content
    
    # 1. Regex parsing
    parsed_errors = parse_log_content(console_log)
    
    # 2. AI RCA Analysis
    rca = await analyze_log_rca(console_log, parsed_errors)
    
    # 3. Create active Incident
    incident_uid = f"INC-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"
    db_incident = Incident(
        incident_uid=incident_uid,
        severity=rca.get("priority_level", "High"),
        system=request.system_type,
        status="Open",
        root_cause=rca.get("root_cause"),
        suggested_fix=rca.get("recommendations")[0] if rca.get("recommendations") else "Verify logs manually",
    )
    db.add(db_incident)
    await db.commit()
    await db.refresh(db_incident)
    
    # 4. Create Analysis Result
    db_analysis = AnalysisResult(
        incident_id=db_incident.id,
        root_cause=rca.get("root_cause"),
        possible_issues=rca.get("possible_issues"),
        recommendations=rca.get("recommendations"),
        confidence_score=rca.get("confidence_score"),
        parsed_errors=parsed_errors,
        priority_level=rca.get("priority_level", "High")
    )
    
    db.add(db_analysis)
    await db.commit()
    await db.refresh(db_analysis)
    
    return db_analysis

@router.post("/file", response_model=AnalysisResultResponse)
async def analyze_file_upload(
    file: UploadFile = File(...),
    system_type: str = Form("Manual File Upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Binary or text log file uploader (.txt, .log, .json).
    Decodes content and pipes to the log parsing engine.
    """
    # Verify file extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in ["txt", "log", "json", "yaml", "xml"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Supported formats: .txt, .log, .json, .yaml, .xml"
        )
        
    content = await file.read()
    try:
        log_content = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            log_content = content.decode("latin-1")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to decode file content. Please upload plain text logs."
            )
            
    # Pipe to upload endpoint logic
    upload_req = LogUploadRequest(
        log_content=log_content,
        source_name=file.filename,
        system_type=system_type
    )
    return await analyze_uploaded_log(upload_req, db, current_user)
