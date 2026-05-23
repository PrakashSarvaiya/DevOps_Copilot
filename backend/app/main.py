from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.database.db import Base, engine
from app.api.endpoints import agent, auth, jenkins, sites
from app.database.db import SessionLocal
from app.services.agent import run_agent_once
from app.services.site_monitor import run_site_monitor_once
import logging
import asyncio

# Configure production-ready structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("DevOps_main")

async def agent_poll_loop():
    while True:
        try:
            async with SessionLocal() as session:
                await run_agent_once(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Agent poll loop failed: %s", exc)
        await asyncio.sleep(settings.AGENT_POLL_INTERVAL_SECONDS)


async def site_monitor_loop():
    while True:
        try:
            async with SessionLocal() as session:
                await run_site_monitor_once(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Site monitor loop failed: %s", exc)
        await asyncio.sleep(settings.SITE_MONITOR_POLL_INTERVAL_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous lifespan manager. Executes table creations during application startup
    and ensures clean connection pools at termination.
    """
    logger.info("Initializing Database structures...")
    async with engine.begin() as conn:
        # Automatically creates tables under targeted SQLite or PostgreSQL engine
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully.")
    agent_task = None
    if settings.AGENT_ENABLED:
        logger.info("Starting autonomous Jenkins agent loop.")
        agent_task = asyncio.create_task(agent_poll_loop())

    site_task = None
    if settings.SITE_MONITOR_ENABLED:
        logger.info("Starting site monitor loop.")
        site_task = asyncio.create_task(site_monitor_loop())

    yield

    for task in (agent_task, site_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    logger.info("Shutting down DevOps Copilot API engine.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-powered DevOps troubleshooting and deployment assistant",
    version="1.0.0",
    lifespan=lifespan
)

# Robust CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In dev, allow wide reach. Secure in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route integrations
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(jenkins.router, prefix=f"{settings.API_V1_STR}/jenkins", tags=["Jenkins Integration"])
app.include_router(agent.router, prefix=f"{settings.API_V1_STR}/agent", tags=["Autonomous Agent"])
app.include_router(sites.router, prefix=f"{settings.API_V1_STR}/sites", tags=["Site Monitor"])

@app.get("/health", tags=["Health Checker"])
async def health_check():
    """
    Standard heartbeat check.
    """
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT
    }
