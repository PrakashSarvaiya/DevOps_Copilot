from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_devops
from app.core.config import settings
from app.database.db import get_db
from app.models.models import User
from app.schemas.schemas import JenkinsWebhookPayload, WebhookAck
from app.services.agent import process_jenkins_webhook, run_agent_once

router = APIRouter()


@router.post("/run-once", response_model=List[Dict[str, Any]])
async def run_agent_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_devops),
):
    return await run_agent_once(db)


@router.post("/webhook/jenkins", response_model=WebhookAck)
async def jenkins_webhook(
    payload: JenkinsWebhookPayload,
    db: AsyncSession = Depends(get_db),
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    if settings.AGENT_WEBHOOK_SECRET:
        if not x_webhook_secret or x_webhook_secret != settings.AGENT_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret",
            )

    result = await process_jenkins_webhook(db, payload)
    return WebhookAck(**result)
