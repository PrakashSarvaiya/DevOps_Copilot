from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
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
    sites = relationship("Site", back_populates="owner", cascade="all, delete-orphan")

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
    pipeline_type = Column(String(50), nullable=True, default="BUILD")  # BUILD or RELEASE
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

class Site(Base):
    """
    A site / endpoint the user wants the monitor to keep an eye on.

    One row per site. The site_monitor service GETs `url` every
    `check_interval_seconds` and upserts `last_status` / `last_response_ms` /
    `last_error` in place. `last_status_changed_at` only moves when the
    status actually flips — used by the UI to show "down for N minutes" and
    by the monitor itself to decide whether to fire a DOWN alert email
    (we only email on UP/UNKNOWN -> DOWN transitions, not every tick).
    """
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    url = Column(String(500), nullable=False)
    check_interval_seconds = Column(Integer, default=60, nullable=False)
    timeout_seconds = Column(Integer, default=10, nullable=False)
    # HTTP responses in [expected_status_min, expected_status_max] count as UP.
    expected_status_min = Column(Integer, default=200, nullable=False)
    expected_status_max = Column(Integer, default=399, nullable=False)
    # Comma-separated extra status codes that should also count as UP for
    # this specific site (e.g. "401" for an authenticated API that returns
    # 401 to unauthenticated probes — the server is alive, just rejecting
    # the request). Empty string means "no extras". Sites:
    #   - default range covers 200-399
    #   - additional codes get added on top of that range
    additional_ok_codes = Column(String(100), default="", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_checked_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), default="UNKNOWN", nullable=False)  # UP | DOWN | UNKNOWN
    last_response_ms = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    last_status_changed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="sites")


class AgentPoll(Base):
    """
    Current-state cache of the agent's most recent fetch per monitored job.

    Exactly one row per Job (enforced by `unique=True` on job_id). The agent
    upserts this row on every poll tick — overwriting the previous value
    instead of appending — so the table size stays bounded at N rows for N
    monitored jobs, regardless of poll frequency.

    `created_at` is bumped on every upsert and is what the dashboard's
    "polled Ns ago" counter reads. If the fetch itself raised, `status` is
    null and `error` carries the message.
    """
    __tablename__ = "agent_polls"

    id = Column(Integer, primary_key=True, index=True)
    # Unique so a fresh DB enforces "one row per job" at the schema level.
    # The application code in services/agent.py also enforces it via
    # fetch-then-update, so existing DBs without the constraint still behave.
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, unique=True, index=True)
    build_number = Column(Integer, nullable=True)
    status = Column(String(50), nullable=True)          # SUCCESS / FAILURE / ABORTED / RUNNING / null
    error = Column(Text, nullable=True)                  # populated when the fetch raised
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    job = relationship("Job")


class AgentAction(Base):
    """
    Audit ledger for the agent loop.

    Every stage the Agent Controller executes (Observe → Understand Context →
    Plan → Choose → Execute → Verify → Report) writes one row here so the
    controller's behaviour is fully inspectable. The `tool_name` column records
    which registered Tool was invoked at the Execute stage (and at any other
    stage that goes through the ToolRegistry).
    """
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False)
    # Stage / verb. One of:
    #   OBSERVE, UNDERSTAND_CONTEXT, PLAN, CHOOSE, EXECUTE, VERIFY, REPORT
    # Legacy aliases also accepted: RETRY, NOTIFY, IGNORE.
    action_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="Completed")
    tool_name = Column(String(100), nullable=True)  # e.g. "jenkins.retry_build"
    reason = Column(Text, nullable=True)
    developer_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    build = relationship("Build")
