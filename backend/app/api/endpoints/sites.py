"""CRUD + manual-check endpoints for user-registered sites."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user
from app.database.db import get_db
from app.models.models import Site, User
from app.schemas.schemas import (
    SiteCheckResult,
    SiteCreate,
    SiteResponse,
    SiteUpdate,
)
from app.services.site_monitor import check_site_now, parse_additional_ok_codes

router = APIRouter()


@router.get("/", response_model=List[SiteResponse])
async def list_sites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all sites the current user is monitoring."""
    result = await db.execute(
        select(Site).filter(Site.user_id == current_user.id).order_by(Site.id.asc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new site for monitoring."""
    if not payload.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )
    additional_codes_str = (payload.additional_ok_codes or "").strip()
    if additional_codes_str:
        try:
            parse_additional_ok_codes(additional_codes_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"additional_ok_codes invalid: {exc}",
            ) from exc
    site = Site(
        user_id=current_user.id,
        name=payload.name.strip(),
        url=payload.url.strip(),
        check_interval_seconds=max(10, payload.check_interval_seconds or 60),
        timeout_seconds=max(1, payload.timeout_seconds or 10),
        enabled=payload.enabled if payload.enabled is not None else True,
        additional_ok_codes=additional_codes_str,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


@router.put("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: int,
    payload: SiteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await _load_owned(db, site_id, current_user.id)
    if payload.name is not None:
        site.name = payload.name.strip()
    if payload.url is not None:
        if not payload.url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL must start with http:// or https://",
            )
        site.url = payload.url.strip()
    if payload.check_interval_seconds is not None:
        site.check_interval_seconds = max(10, payload.check_interval_seconds)
    if payload.timeout_seconds is not None:
        site.timeout_seconds = max(1, payload.timeout_seconds)
    if payload.enabled is not None:
        site.enabled = payload.enabled
    if payload.additional_ok_codes is not None:
        cleaned = payload.additional_ok_codes.strip()
        if cleaned:
            try:
                parse_additional_ok_codes(cleaned)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"additional_ok_codes invalid: {exc}",
                ) from exc
        site.additional_ok_codes = cleaned
    await db.commit()
    await db.refresh(site)
    return site


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await _load_owned(db, site_id, current_user.id)
    await db.delete(site)
    await db.commit()


@router.post("/{site_id}/check", response_model=SiteCheckResult)
async def check_site_endpoint(
    site_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force an immediate check against this site, ignoring the interval.
    Useful for verifying a freshly-added URL or testing the alert path."""
    site = await _load_owned(db, site_id, current_user.id)
    outcome = await check_site_now(db, site)
    return SiteCheckResult(
        site_id=site.id,
        status=outcome["status"],
        http_status=outcome["http_status"],
        response_ms=outcome["response_ms"],
        error=outcome["error"],
        emailed=outcome["emailed"],
    )


async def _load_owned(db: AsyncSession, site_id: int, user_id: int) -> Site:
    result = await db.execute(
        select(Site).filter(Site.id == site_id, Site.user_id == user_id)
    )
    site = result.scalars().first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site
