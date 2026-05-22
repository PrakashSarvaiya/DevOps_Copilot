import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "DevOps Copilot API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Security
    JWT_SECRET: str = "supersecretjwtkeyshouldbechangedinproduction123"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # Database
    # Standard SQLite fallback for zero-dependency local runs.
    # Docker/prod can still override this with DATABASE_URL.
    DATABASE_URL: str = "sqlite+aiosqlite:///./DevOps_copilot.db"

    # Gemini AI
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "")

    JENKINS_TIMEOUT_SECONDS: int = 30

    # Autonomous agent controls
    AGENT_ENABLED: bool = False
    AGENT_POLL_INTERVAL_SECONDS: int = 120
    AGENT_AUTO_RERUN_ENABLED: bool = False
    AGENT_MAX_RERUNS_PER_BUILD: int = 1
    AGENT_WEBHOOK_SECRET: str = ""

    # Email notification controls
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True
    # DevOps escalation fallback recipients for alerts when developer email is unavailable.
    DEFAULT_ALERT_EMAIL: str = "prakash.sarvaiya@vijyafintech.com,gaurav.talodhikar@vijyafintech.com"

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
