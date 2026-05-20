from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Any
from datetime import datetime

# --- Auth Schemas ---
class UserBase(BaseModel):
    username: str
    email: EmailStr
    role: Optional[str] = "DevOps Engineer"

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

# --- Jenkins Schemas ---
class JenkinsServerBase(BaseModel):
    name: str
    url: str
    username: Optional[str] = None
    api_token: Optional[str] = None

class JenkinsServerCreate(JenkinsServerBase):
    pass

class JenkinsServerResponse(JenkinsServerBase):
    id: int

    class Config:
        from_attributes = True

class JenkinsJobCandidate(BaseModel):
    name: str
    url: str
    last_status: Optional[str] = None
    monitored: bool = False

class JenkinsMonitorSelection(BaseModel):
    jobs: List[JenkinsJobCandidate]

class JenkinsWebhookPayload(BaseModel):
    jenkins_url: str
    job_name: str
    build_number: int
    status: str
    job_url: Optional[str] = None
    build_url: Optional[str] = None
    branch_name: Optional[str] = None
    triggered_by: Optional[str] = None
    developer_email: Optional[str] = None

class WebhookAck(BaseModel):
    accepted: bool
    action: str
    detail: str
    build_id: Optional[int] = None

class JobResponse(BaseModel):
    id: int
    name: str
    url: Optional[str] = None
    last_status: Optional[str] = None
    server_id: int

    class Config:
        from_attributes = True

class BuildResponse(BaseModel):
    id: int
    number: int
    status: str
    duration: int
    timestamp: datetime
    job_id: int

    class Config:
        from_attributes = True

class BuildDetailsResponse(BuildResponse):
    console_output: Optional[str] = None

    class Config:
        from_attributes = True

# --- Log Analysis & RCA Schemas ---
class LogUploadRequest(BaseModel):
    log_content: str
    source_name: Optional[str] = "Manual Log Upload"
    system_type: Optional[str] = "Jenkins" # Jenkins, Windows-VM, Linux-VM, Nginx, Docker

class ParsedError(BaseModel):
    line_number: int
    content: str
    severity: str # INFO, WARNING, ERROR, CRITICAL
    category: str # Docker, Kubernetes, Network, Permission, System

class AnalysisResultResponse(BaseModel):
    id: int
    build_id: Optional[int] = None
    incident_id: Optional[int] = None
    root_cause: str
    possible_issues: List[str]
    recommendations: List[str]
    confidence_score: float
    parsed_errors: List[ParsedError]
    priority_level: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Incident Schemas ---
class IncidentBase(BaseModel):
    severity: str
    system: str
    status: str
    root_cause: Optional[str] = None
    suggested_fix: Optional[str] = None
    resolution_notes: Optional[str] = None

class IncidentCreate(IncidentBase):
    incident_uid: str

class IncidentResponse(IncidentBase):
    id: int
    incident_uid: str
    timestamp: datetime
    analyses: List[AnalysisResultResponse] = []

    class Config:
        from_attributes = True

class IncidentExportResponse(BaseModel):
    incident_uid: str
    timestamp: str
    severity: str
    system: str
    status: str
    root_cause: str
    suggested_fix: str
    resolution_notes: Optional[str] = None
