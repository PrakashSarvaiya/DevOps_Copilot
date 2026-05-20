from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Table, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="DevOps Engineer")  # Admin, DevOps Engineer, Viewer
    created_at = Column(DateTime, default=datetime.utcnow)

    jenkins_servers = relationship("JenkinsServer", back_populates="owner", cascade="all, delete-orphan")

class JenkinsServer(Base):
    __tablename__ = "jenkins_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(255), nullable=False)
    username = Column(String(100), nullable=True)
    api_token = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="jenkins_servers")
    jobs = relationship("Job", back_populates="server", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(255), nullable=True)
    last_status = Column(String(50), nullable=True)  # SUCCESS, FAILURE, ABORTED
    server_id = Column(Integer, ForeignKey("jenkins_servers.id"), nullable=False)

    server = relationship("JenkinsServer", back_populates="jobs")
    builds = relationship("Build", back_populates="job", cascade="all, delete-orphan")

class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False)  # SUCCESS, FAILURE, ABORTED, RUNNING
    duration = Column(Integer, default=0)         # in ms
    timestamp = Column(DateTime, default=datetime.utcnow)
    console_output = Column(Text, nullable=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    job = relationship("Job", back_populates="builds")
    analysis = relationship("AnalysisResult", uselist=False, back_populates="build", cascade="all, delete-orphan")

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    root_cause = Column(Text, nullable=False)
    possible_issues = Column(JSON, nullable=True)  # List of alternate possible issues
    recommendations = Column(JSON, nullable=False)  # List of dynamic steps/fixes
    confidence_score = Column(Float, default=0.0)
    parsed_errors = Column(JSON, nullable=True)    # Extracted raw error lines/severities
    priority_level = Column(String(50), default="Medium")  # Low, Medium, High, Critical
    created_at = Column(DateTime, default=datetime.utcnow)

    build = relationship("Build", back_populates="analysis")
    incident = relationship("Incident", back_populates="analyses")

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_uid = Column(String(100), unique=True, index=True, nullable=False) # e.g. INC-2026-0001
    timestamp = Column(DateTime, default=datetime.utcnow)
    severity = Column(String(50), default="High")  # Low, Medium, High, Critical
    system = Column(String(100), nullable=False)   # Jenkins, Windows-VM, Linux-VM, Docker, K8s
    status = Column(String(50), default="Open")    # Open, Investigating, Resolved, Closed
    root_cause = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    analyses = relationship("AnalysisResult", back_populates="incident")

class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False)
    action_type = Column(String(50), nullable=False)  # RERUN, NOTIFY, IGNORE
    status = Column(String(50), nullable=False, default="Completed")
    reason = Column(Text, nullable=True)
    developer_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    build = relationship("Build")
