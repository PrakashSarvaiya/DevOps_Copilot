"""
Site monitor — periodic UP/DOWN check for user-registered sites.

Runs as a separate lifespan loop (next to the Jenkins agent poll), wakes every
SITE_MONITOR_POLL_INTERVAL_SECONDS, picks any Site whose per-row
check_interval_seconds has elapsed, GETs the URL, and updates the Site in
place. Emails the DevOps fallback list on UP/UNKNOWN -> DOWN transitions.

Same upsert-in-place pattern as AgentPoll: no log table, just the current
state on the Site row. `last_status_changed_at` gives us "down for N minutes"
without keeping a full history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.models.models import Site
from app.services.agent_tools import default_registry
from app.services.email_renderer import render_email

logger = logging.getLogger("DevOps_site_monitor")


def parse_additional_ok_codes(raw: str) -> Set[int]:
    """
    Parse a `additional_ok_codes` string ("401", "401,403", "401, 403, 405")
    into a set of ints.

    Used both by the live check (decide if response.status_code counts as UP)
    and by the create/update endpoints (validation — surface a clear error to
    the user instead of letting a bad value silently misbehave). Raises
    ValueError with a human-readable message if any token can't be parsed or
    is outside the 100..599 HTTP-status range.
    """
    out: Set[int] = set()
    if not raw or not raw.strip():
        return out
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            code = int(token)
        except ValueError as exc:
            raise ValueError(f"'{token}' is not a valid HTTP status code") from exc
        if not 100 <= code <= 599:
            raise ValueError(f"{code} is out of the HTTP status code range (100-599)")
        out.add(code)
    return out


async def check_site(
    site: Site,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Run one UP/DOWN check against a Site.

    Returns the new state we should write back to the row:
        {"status": "UP"|"DOWN", "http_status": int|None, "response_ms": int|None, "error": str|None}

    Does NOT mutate the row itself — the caller (run_site_monitor_once) writes
    the result and decides whether to fire a transition email.
    """
    start = datetime.utcnow()
    own_client = http_client is None
    if own_client:
        http_client = httpx.AsyncClient(timeout=site.timeout_seconds, verify=False, follow_redirects=True)
    try:
        try:
            response = await http_client.get(site.url, timeout=site.timeout_seconds)
        except httpx.TimeoutException as exc:
            return {
                "status": "DOWN", "http_status": None, "response_ms": None,
                "error": f"Timed out after {site.timeout_seconds}s: {exc}"[:500],
            }
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            return {
                "status": "DOWN", "http_status": None, "response_ms": None,
                "error": f"Connection error: {exc}"[:500],
            }
        except Exception as exc:
            return {
                "status": "DOWN", "http_status": None, "response_ms": None,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }

        elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        extras = parse_additional_ok_codes(site.additional_ok_codes or "")
        in_range = site.expected_status_min <= response.status_code <= site.expected_status_max
        ok = in_range or response.status_code in extras
        if ok:
            return {
                "status": "UP", "http_status": response.status_code,
                "response_ms": elapsed_ms, "error": None,
            }
        expected_msg = f"{site.expected_status_min}-{site.expected_status_max}"
        if extras:
            expected_msg += " or " + ",".join(str(c) for c in sorted(extras))
        return {
            "status": "DOWN", "http_status": response.status_code,
            "response_ms": elapsed_ms,
            "error": f"HTTP {response.status_code} (expected {expected_msg})",
        }
    finally:
        if own_client:
            await http_client.aclose()


def _is_due(site: Site, now: datetime) -> bool:
    """True if `site` is due for another check based on its own interval."""
    if not site.enabled:
        return False
    if site.last_checked_at is None:
        return True
    return (now - site.last_checked_at) >= timedelta(seconds=site.check_interval_seconds)


async def run_site_monitor_once(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    One iteration of the site monitor loop. Walks every enabled Site whose
    per-row interval has elapsed, checks it, writes the result back, fires
    a DOWN-transition email if appropriate.

    Returns one outcome dict per site actually checked.
    """
    now = datetime.utcnow()
    result = await db.execute(select(Site).filter(Site.enabled.is_(True)))
    sites = list(result.scalars().all())

    outcomes: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as http_client:
        for site in sites:
            if not _is_due(site, now):
                continue
            outcome = await _check_and_persist(db, site, http_client)
            outcomes.append(outcome)
    await db.commit()
    return outcomes


async def check_site_now(db: AsyncSession, site: Site) -> Dict[str, Any]:
    """Force a check on a specific Site, regardless of interval. Used by the
    manual `POST /sites/{id}/check` endpoint."""
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as http_client:
        outcome = await _check_and_persist(db, site, http_client)
    await db.commit()
    return outcome


async def _check_and_persist(
    db: AsyncSession,
    site: Site,
    http_client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """Run the check, write the new state to the Site row, fire alerts on
    UP/UNKNOWN -> DOWN transitions. Returns a summary dict."""
    previous_status = site.last_status
    result = await check_site(site, http_client=http_client)
    now = datetime.utcnow()

    site.last_checked_at = now
    site.last_response_ms = result["response_ms"]
    site.last_error = result["error"]
    new_status = result["status"]
    if new_status != previous_status:
        site.last_status = new_status
        site.last_status_changed_at = now

    emailed = False
    if new_status == "DOWN" and previous_status != "DOWN":
        emailed = await _fire_down_alert(site, result)

    return {
        "site_id": site.id,
        "site_name": site.name,
        "status": new_status,
        "http_status": result["http_status"],
        "response_ms": result["response_ms"],
        "error": result["error"],
        "emailed": emailed,
        "transition": previous_status != new_status,
    }


async def _fire_down_alert(site: Site, check_result: Dict[str, Any]) -> bool:
    """Send the site_down email via the agent's notify.email tool. Returns
    True if SMTP accepted the message."""
    recipient = settings.DEFAULT_ALERT_EMAIL or ""
    if not recipient:
        logger.warning("Site %s went DOWN but DEFAULT_ALERT_EMAIL is empty — skipping alert.", site.name)
        return False
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        logger.warning("Site %s went DOWN but SMTP is not configured — skipping alert.", site.name)
        return False

    ctx = {
        "site_name": site.name,
        "site_url": site.url,
        "http_status": check_result["http_status"],
        "response_ms": check_result["response_ms"],
        "error_message": check_result["error"],
        "timeout_seconds": site.timeout_seconds,
        "expected_status_min": site.expected_status_min,
        "expected_status_max": site.expected_status_max,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    subject, plain, html = render_email("site_down", ctx)

    tool_result = await default_registry.call(
        "notify.email",
        {
            "recipient": recipient,
            "subject": subject,
            "body": plain,
            "html_body": html,
        },
    )
    sent = bool(tool_result["ok"] and tool_result["output"] and tool_result["output"].get("sent"))
    if not sent:
        logger.warning("Site %s DOWN alert failed to send: %s", site.name, tool_result.get("error"))
    return sent
