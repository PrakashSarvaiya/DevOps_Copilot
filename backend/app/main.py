from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.database.db import Base, engine
from app.api.endpoints import agent, auth, jenkins, analyze, incidents
from app.database.db import SessionLocal
from app.services.agent import run_agent_once
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
    yield
    if agent_task:
        agent_task.cancel()
        try:
            await agent_task
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
app.include_router(analyze.router, prefix=f"{settings.API_V1_STR}/analyze", tags=["Ad-hoc Parser Engine"])
app.include_router(incidents.router, prefix=f"{settings.API_V1_STR}/incidents", tags=["Incident Center"])
app.include_router(agent.router, prefix=f"{settings.API_V1_STR}/agent", tags=["Autonomous Agent"])

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
