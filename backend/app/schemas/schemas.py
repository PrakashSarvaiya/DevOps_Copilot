from pydantic import BaseModel, EmailStr
from typing import List, Optional
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
    pipeline_type: Optional[str] = "BUILD"

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
    pipeline_type: Optional[str] = "BUILD"
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

# --- Log Parsing Schema ---
# Retained because services/parser.py emits this shape; the Agent
# Controller uses parser.py as a context-understanding tool.
class ParsedError(BaseModel):
    line_number: int
    content: str
    severity: str  # INFO, WARNING, ERROR, CRITICAL
    category: str  # Docker, Kubernetes, Network, Permission, System


# --- Agent Schemas ---
class AgentActionResponse(BaseModel):
    """A single row from the AgentAction audit ledger.

    `build_number` and `job_name` are denormalized for the activity feed so
    the frontend can group by build without a second round-trip per row.
    They are optional because the per-build endpoint may skip the join.
    """
    id: int
    build_id: int
    build_number: Optional[int] = None
    job_name: Optional[str] = None
    action_type: str  # OBSERVE, UNDERSTAND_CONTEXT, PLAN, CHOOSE, EXECUTE, VERIFY, REPORT
    status: str
    tool_name: Optional[str] = None
    reason: Optional[str] = None
    developer_email: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ToolResponse(BaseModel):
    """Registered tool, for the /agent/tools introspection endpoint."""
    name: str
    safety: str  # READ_ONLY | SAFE_ACTION | BLOCKED
    description: str


class AgentHandleResponse(BaseModel):
    """Summary returned by manual controller invocations."""
    build_id: int
    result: Optional[str] = None
    stages: List[str] = []
    plan: Optional[str] = None
    execute: Optional[dict] = None
    verify: Optional[str] = None
    report: Optional[str] = None
