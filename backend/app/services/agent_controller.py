"""
Agent Controller — implements the seven-stage agent loop.

    Event -> Observe -> Understand Context -> Plan -> Choose Action ->
    Execute -> Verify -> Report

The controller's job is to behave like a junior/mid DevOps engineer: when a
build fails, classify it, recall what's worked for this pipeline before,
pick the obvious safe fix, run it through the ToolRegistry (so the
safe/blocked allowlist is enforced), verify, and report.

All heuristics ("what would a junior try?") live in agent_knowledge.py. All
"what's worked before?" queries live in agent_memory.py. This file is the
state machine that wires them together.

Every stage writes one AgentAction row. The ledger is the source of truth
for both the UI activity feed and the memory layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.models.models import AgentAction, Build
from app.services import agent_memory
from app.services.agent_knowledge import (
    FailureClass,
    PlanStep,
    classify_failure,
    playbook_for,
    rationale_for,
    release_playbook,
    resolve_args,
)
from app.services.agent_tools import (
    SafetyClass,
    ToolBlockedError,
    ToolRegistry,
    default_registry,
)
from app.services.email_renderer import render_email, truncate_console
from app.services.jenkins_client import JenkinsClient

logger = logging.getLogger("DevOps_agent_controller")


# Escalation guards used by the planner. Tuning lives at the top of this
# module so it's easy to find.
ESCALATE_AFTER_CONSECUTIVE_FAILURES = 2  # of the same tool on the same job
LOW_SUCCESS_RATE_THRESHOLD = 0.2
LOW_SUCCESS_RATE_MIN_ATTEMPTS = 5


@dataclass
class PlanDecision:
    """
    What the Plan stage decided.

    `action` is a high-level label ("RETRY", "RETRY_AFTER_CLEAN",
    "NOTIFY_ONLY", "ESCALATE") that the UI and ledger can show as a chip.
    `steps` is the ordered tool sequence the Execute stage will walk —
    empty means "no autonomous action."
    `failure_class` is the classifier's verdict, copied into PLAN.reason so
    the memory layer can later answer "what worked for this class?"
    """

    action: str
    rationale: str
    failure_class: FailureClass
    steps: List[PlanStep] = field(default_factory=list)


class AgentController:
    """
    Drives one build event through the full agent loop.

    Construct once per process (or per request) and call handle_build_event
    for each failed build the observation layer discovers. The controller is
    stateless across calls; all state lives in the AgentAction ledger.
    """

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry or default_registry

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def handle_build_event(
        self,
        db: AsyncSession,
        build: Build,
        client: JenkinsClient,
    ) -> Dict[str, Any]:
        """
        Run the seven-stage loop against a single Build.

        The Build object must come pre-loaded with `build.job` and
        `build.job.server` (the caller is responsible for the eager-load).

        Idempotent: if a REPORT row already exists for this build the
        controller returns immediately without writing any new ledger
        rows. This makes tight polling intervals and webhook re-deliveries
        safe — every build is processed exactly once.
        """
        outcome: Dict[str, Any] = {"build_id": build.id, "stages": []}

        if await self._already_handled(db, build.id):
            outcome["result"] = "already_handled"
            return outcome

        # 1. OBSERVE
        await self._record(
            db, build,
            action_type="OBSERVE",
            status="Observed",
            reason=f"Build #{build.number} of job '{build.job.name}' status={build.status}.",
        )
        outcome["stages"].append("OBSERVE")

        if build.status != "FAILURE":
            await db.commit()
            outcome["result"] = "no_action_non_failure"
            return outcome

        # 2. UNDERSTAND CONTEXT
        context = await self._understand_context(db, build, client)
        outcome["stages"].append("UNDERSTAND_CONTEXT")

        # 3. PLAN
        plan = await self._plan(db, build, context)
        outcome["stages"].append("PLAN")
        outcome["plan"] = plan.action
        outcome["failure_class"] = plan.failure_class.value

        # 4. CHOOSE
        validated_steps = await self._choose(db, build, plan)
        outcome["stages"].append("CHOOSE")

        # 5. EXECUTE
        execute_summary = await self._execute(db, build, client, plan, validated_steps)
        outcome["stages"].append("EXECUTE")
        outcome["execute"] = execute_summary

        # 6. VERIFY
        verify_status = await self._verify(db, build, plan, execute_summary)
        outcome["stages"].append("VERIFY")
        outcome["verify"] = verify_status

        # 7. NOTIFY (conditional — only fires when a human needs to look).
        # See _should_notify for the policy table. Passes the full context so
        # the renderer can include parsed errors + log tail in the email body.
        notify_status = await self._notify(
            db, build, client, plan, execute_summary, verify_status, context,
        )
        if notify_status is not None:
            outcome["stages"].append("NOTIFY")
            outcome["notify"] = notify_status

        await db.commit()
        outcome["result"] = "handled"
        return outcome

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    async def _understand_context(
        self,
        db: AsyncSession,
        build: Build,
        client: JenkinsClient,
    ) -> Dict[str, Any]:
        """Fetch console + parse errors via the registry. Persist log on Build."""
        console_result = await self.registry.call(
            "jenkins.fetch_console",
            {
                "client": client,
                "job_name": build.job.name,
                "build_number": build.number,
                "job_url": build.job.url,
            },
        )
        console = console_result["output"] or "" if console_result["ok"] else ""
        if console:
            build.console_output = console

        parsed_result = await self.registry.call(
            "context.parse_errors",
            {"log_text": console},
        )
        parsed_errors: List[Dict[str, Any]] = (
            parsed_result["output"] if parsed_result["ok"] and parsed_result["output"] else []
        )

        await self._record(
            db, build,
            action_type="UNDERSTAND_CONTEXT",
            status="Completed",
            tool_name="context.parse_errors",
            reason=(
                f"Fetched {len(console)} bytes of console log; "
                f"parser flagged {len(parsed_errors)} error line(s)."
            ),
        )

        return {"console": console, "parsed_errors": parsed_errors}

    async def _plan(
        self,
        db: AsyncSession,
        build: Build,
        context: Dict[str, Any],
    ) -> PlanDecision:
        """
        Junior-judgement planner.

        Walks a hard-coded decision tree:
          a. Classify the failure.
          b. Pick the canonical playbook for that class.
          c. Apply the global guards (RELEASE pipelines never auto-act, the
             AGENT_AUTO_RERUN_ENABLED kill-switch, per-build retry cap).
          d. Apply the memory-driven guards (escalation streak, low success
             rate) and demote the plan to NOTIFY_ONLY if any fire.
          e. Record the PLAN row including the failure class so future
             planners can reason about "what worked for this class before."
        """
        failure_class = classify_failure(context.get("console") or "", context.get("parsed_errors") or [])
        base_rationale = rationale_for(failure_class)
        is_release = build.job.pipeline_type == "RELEASE"

        # Playbook selection:
        #   RELEASE → universal single-retry playbook regardless of failure class.
        #   BUILD   → class-specific playbook from DEFAULT_PLAYBOOKS.
        if is_release:
            playbook = release_playbook()
            base_rationale = (
                f"RELEASE pipeline: always retry once before escalating. "
                f"Underlying class detected: {failure_class.value} ({base_rationale})"
            )
        else:
            playbook = playbook_for(failure_class)

        # Empty playbook → nothing to do autonomously. Skip the action guards;
        # NOTIFY stage will decide whether to email.
        if not playbook:
            return self._planned(
                db, build,
                action="NOTIFY_ONLY",
                failure_class=failure_class,
                rationale=f"[{failure_class.value}] {base_rationale}",
                steps=[],
            )

        if not settings.AGENT_AUTO_RERUN_ENABLED:
            return self._planned(
                db, build,
                action="NOTIFY_ONLY",
                failure_class=failure_class,
                rationale=(
                    f"[{failure_class.value}] Auto-action globally disabled "
                    f"(AGENT_AUTO_RERUN_ENABLED=false); notify only."
                ),
                steps=[],
            )

        prior_retries = await agent_memory.retries_for_build(db, build.id)
        if prior_retries >= settings.AGENT_MAX_RERUNS_PER_BUILD:
            return self._planned(
                db, build,
                action="NOTIFY_ONLY",
                failure_class=failure_class,
                rationale=(
                    f"[{failure_class.value}] Already retried this build "
                    f"{prior_retries} time(s); cap is "
                    f"{settings.AGENT_MAX_RERUNS_PER_BUILD}. Notify only."
                ),
                steps=[],
            )

        # --- Memory-driven guards -----------------------------------------
        retry_streak = await agent_memory.consecutive_failures_of_action(
            db, build.job_id, "jenkins.retry_build"
        )
        if retry_streak >= ESCALATE_AFTER_CONSECUTIVE_FAILURES and any(
            s.tool_name == "jenkins.retry_build" for s in playbook
        ):
            return self._planned(
                db, build,
                action="ESCALATE",
                failure_class=failure_class,
                rationale=(
                    f"[{failure_class.value}] Last {retry_streak} retries on "
                    f"this pipeline have failed in a row; refusing to retry "
                    f"again. Escalating to a human."
                ),
                steps=[],
            )

        success_stats = await agent_memory.retry_success_rate(db, build.job_id)
        if (
            success_stats.attempts >= LOW_SUCCESS_RATE_MIN_ATTEMPTS
            and success_stats.rate < LOW_SUCCESS_RATE_THRESHOLD
            and any(s.tool_name == "jenkins.retry_build" for s in playbook)
        ):
            return self._planned(
                db, build,
                action="ESCALATE",
                failure_class=failure_class,
                rationale=(
                    f"[{failure_class.value}] Historical retry success on "
                    f"this pipeline is {success_stats.describe()} — below the "
                    f"{LOW_SUCCESS_RATE_THRESHOLD:.0%} threshold. Notify only."
                ),
                steps=[],
            )

        # --- All guards passed — keep the playbook ------------------------
        # Pick a friendlier action label when multiple steps are involved.
        if len(playbook) == 1 and playbook[0].tool_name == "jenkins.retry_build":
            action_label = "RETRY"
        elif any(s.tool_name == "jenkins.clean_workspace" for s in playbook):
            action_label = "RETRY_AFTER_CLEAN"
        else:
            action_label = "ACT"

        # Memory-informed rationale: include past success stats so the
        # ledger explains *why* we're choosing to act.
        memory_note = (
            f" Memory: {success_stats.describe()}."
            if success_stats.attempts > 0
            else " Memory: no prior data on this pipeline."
        )
        return self._planned(
            db, build,
            action=action_label,
            failure_class=failure_class,
            rationale=f"[{failure_class.value}] {base_rationale}{memory_note}",
            steps=playbook,
        )

    def _planned(
        self,
        db: AsyncSession,
        build: Build,
        *,
        action: str,
        rationale: str,
        failure_class: FailureClass,
        steps: List[PlanStep],
    ) -> PlanDecision:
        # Build a compact one-line summary of the planned steps for the
        # ledger; full args are recorded later on each EXECUTE row.
        if steps:
            steps_summary = " -> ".join(s.tool_name for s in steps)
            tool_name_for_row: Optional[str] = steps[0].tool_name
        else:
            steps_summary = "(no autonomous steps)"
            tool_name_for_row = None
        db.add(AgentAction(
            build_id=build.id,
            action_type="PLAN",
            status=action,
            tool_name=tool_name_for_row,
            reason=f"{rationale} Steps: {steps_summary}",
        ))
        return PlanDecision(
            action=action,
            rationale=rationale,
            failure_class=failure_class,
            steps=steps,
        )

    async def _choose(
        self,
        db: AsyncSession,
        build: Build,
        plan: PlanDecision,
    ) -> List[PlanStep]:
        """
        Validate every planned step against the registry up front, BEFORE we
        start executing. If any step references an unknown or BLOCKED tool,
        refuse the whole plan — partial execution is worse than none.
        """
        if not plan.steps:
            await self._record(
                db, build,
                action_type="CHOOSE",
                status="NoTool",
                reason=f"Plan '{plan.action}' requires no tool invocation.",
            )
            return []

        for step in plan.steps:
            try:
                tool = self.registry.get(step.tool_name)
            except KeyError:
                await self._record(
                    db, build,
                    action_type="CHOOSE",
                    status="UnknownTool",
                    tool_name=step.tool_name,
                    reason=f"Plan referenced unknown tool '{step.tool_name}'; aborting whole plan.",
                )
                return []
            if tool.safety == SafetyClass.BLOCKED:
                await self._record(
                    db, build,
                    action_type="CHOOSE",
                    status="Blocked",
                    tool_name=step.tool_name,
                    reason=f"Tool '{step.tool_name}' is BLOCKED; refusing whole plan.",
                )
                return []

        steps_summary = " -> ".join(s.tool_name for s in plan.steps)
        await self._record(
            db, build,
            action_type="CHOOSE",
            status="Selected",
            tool_name=plan.steps[0].tool_name,
            reason=f"Validated {len(plan.steps)} step(s): {steps_summary}.",
        )
        return list(plan.steps)

    async def _execute(
        self,
        db: AsyncSession,
        build: Build,
        client: JenkinsClient,
        plan: PlanDecision,
        steps: List[PlanStep],
    ) -> Dict[str, Any]:
        """
        Walk the validated step list in order. One EXECUTE row per step. Halt
        on the first failure so later steps don't run on a broken precondition.
        """
        if not steps:
            await self._record(
                db, build,
                action_type="EXECUTE",
                status="Skipped",
                reason=f"No execution for plan '{plan.action}'.",
            )
            return {"executed": False, "steps": [], "halted": False}

        step_results: List[Dict[str, Any]] = []
        halted = False
        last_ok = False
        last_tool: Optional[str] = None
        last_error: Optional[str] = None

        for step in steps:
            args = resolve_args(
                step.args,
                client=client,
                job_name=build.job.name,
                job_url=build.job.url,
                build_number=build.number,
            )
            try:
                result = await self.registry.call(step.tool_name, args)
            except ToolBlockedError as exc:
                # Defense in depth — Choose already filtered BLOCKED, but if a
                # blocked keyword sneaks into args we want to halt cleanly.
                await self._record(
                    db, build,
                    action_type="EXECUTE",
                    status="Blocked",
                    tool_name=step.tool_name,
                    reason=str(exc),
                )
                step_results.append({"tool": step.tool_name, "ok": False, "blocked": True, "error": str(exc)})
                halted = True
                last_ok = False
                last_tool = step.tool_name
                last_error = str(exc)
                break

            ok = bool(result["ok"]) and self._step_succeeded(step.tool_name, result["output"])
            status = "Triggered" if (ok and step.tool_name == "jenkins.retry_build") else \
                     "Wiped" if (ok and step.tool_name == "jenkins.clean_workspace") else \
                     "Sent" if (ok and step.tool_name == "notify.email") else \
                     ("OK" if ok else "Failed")

            await self._record(
                db, build,
                action_type="EXECUTE",
                status=status,
                tool_name=step.tool_name,
                reason=(
                    f"[{step.label}] tool={step.tool_name} ok={result['ok']} "
                    f"output={result['output']} error={result['error']}."
                ),
            )
            step_results.append({
                "tool": step.tool_name,
                "ok": ok,
                "status": status,
                "output": result["output"],
                "error": result["error"],
            })
            last_ok = ok
            last_tool = step.tool_name
            last_error = result["error"]
            if not ok:
                halted = True
                break

        return {
            "executed": True,
            "steps": step_results,
            "halted": halted,
            "ok": last_ok,
            "tool": last_tool,
            "error": last_error,
        }

    async def _verify(
        self,
        db: AsyncSession,
        build: Build,
        plan: PlanDecision,
        execute_summary: Dict[str, Any],
    ) -> str:
        """
        Best-effort verification. Step 1 just confirms the last executed
        step didn't error out and (for retry) that the trigger really fired.
        A deeper verifier — poll the next build, assert SUCCESS — is a later
        slice.
        """
        if not execute_summary.get("executed"):
            status, reason = "Skipped", f"No execution to verify for plan '{plan.action}'."
        elif execute_summary.get("halted") and not execute_summary.get("ok"):
            status = "Failed"
            reason = (
                f"Tool '{execute_summary.get('tool')}' returned ok=False "
                f"(error={execute_summary.get('error')}). Halted the plan."
            )
        elif execute_summary.get("ok"):
            steps = execute_summary.get("steps") or []
            status = "Verified"
            reason = (
                f"Last step '{execute_summary.get('tool')}' returned ok=True; "
                f"completed {len(steps)} step(s)."
            )
        else:
            status = "Inconclusive"
            reason = "Execute summary missing ok flag."

        await self._record(
            db, build,
            action_type="VERIFY",
            status=status,
            tool_name=execute_summary.get("tool"),
            reason=reason,
        )
        return status

    async def _notify(
        self,
        db: AsyncSession,
        build: Build,
        client: JenkinsClient,
        plan: PlanDecision,
        execute_summary: Dict[str, Any],
        verify_status: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        Decide whether to email humans, then render + send.

        Returns the status string we wrote to the ledger, or None if no email
        was warranted (the NOTIFY stage doesn't fire and no row is written).

        Policy (matches user direction):
            - RELEASE pipelines:
                VERIFY=Verified -> silent
                otherwise       -> email DEFAULT_ALERT_EMAIL (DevOps fallback)
            - BUILD pipelines:
                CODE_ERROR or empty-playbook plan -> email commit authors
                playbook ran and VERIFY=Verified  -> silent (agent fixed it)
                playbook ran and VERIFY=Failed    -> email commit authors
        """
        if not self._should_notify(build, plan, verify_status):
            return None

        recipients = await self._resolve_recipients(client, build)
        if not recipients:
            await self._record(
                db, build,
                action_type="NOTIFY",
                status="NoRecipient",
                reason="No commit-author email and no DEFAULT_ALERT_EMAIL configured; nothing to do.",
            )
            return "no_recipient"
        recipient_str = ", ".join(recipients)

        if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
            await self._record(
                db, build,
                action_type="NOTIFY",
                status="SmtpUnconfigured",
                developer_email=recipient_str[:255],
                reason=(
                    f"Would have emailed {recipient_str} but SMTP_HOST or "
                    f"SMTP_FROM_EMAIL is empty."
                ),
            )
            return "smtp_unconfigured"

        scenario = self._pick_scenario(build, plan)
        ctx = self._build_render_context(
            build=build,
            plan=plan,
            execute_summary=execute_summary,
            verify_status=verify_status,
            context=context,
            recipient_count=len(recipients),
        )
        subject, plain_body, html_body = render_email(scenario, ctx)

        result = await self.registry.call(
            "notify.email",
            {
                "recipient": recipient_str,
                "subject": subject,
                "body": plain_body,
                "html_body": html_body,
            },
        )
        sent = bool(result["ok"] and result["output"] and result["output"].get("sent"))
        await self._record(
            db, build,
            action_type="NOTIFY",
            status="Sent" if sent else "Failed",
            tool_name="notify.email",
            developer_email=recipient_str[:255],
            reason=(
                f"Emailed {len(recipients)} recipient(s) with template "
                f"'{scenario}': sent={sent}, error={result.get('error')}."
            ),
        )
        return "sent" if sent else "failed"

    @staticmethod
    def _should_notify(build: Build, plan: PlanDecision, verify_status: str) -> bool:
        is_release = build.job.pipeline_type == "RELEASE"
        if is_release:
            # On release, only stay silent when the retry actually worked.
            return verify_status != "Verified"
        # BUILD pipelines:
        #   - Plan had no autonomous steps (e.g. CODE_ERROR) -> always email.
        #   - Plan ran but didn't fix it -> email.
        #   - Plan ran and Verified -> silent.
        if plan.action in ("NOTIFY_ONLY", "ESCALATE"):
            return True
        if verify_status != "Verified":
            return True
        return False

    @staticmethod
    def _pick_scenario(build: Build, plan: PlanDecision) -> str:
        """Map (pipeline_type, failure_class) to a template key."""
        if build.job.pipeline_type == "RELEASE":
            return "release_escalation"
        if plan.failure_class == FailureClass.CODE_ERROR:
            return "code_error"
        return "recovery_failed"

    async def _resolve_recipients(
        self,
        client: JenkinsClient,
        build: Build,
    ) -> List[str]:
        """
        Resolve recipients as an ordered, de-duplicated list of email addresses.

        - RELEASE failures -> DEFAULT_ALERT_EMAIL only (DevOps fallback).
        - BUILD failures   -> ALL commit authors from Jenkins changeSets if
                              available (so a 3-author batch build pings all
                              3 contributors), else DEFAULT_ALERT_EMAIL.
        """
        fallback_raw = settings.DEFAULT_ALERT_EMAIL or ""
        fallback = [e.strip() for e in fallback_raw.replace(";", ",").split(",") if e.strip()]

        if build.job.pipeline_type == "RELEASE":
            return fallback

        try:
            details = await self.registry.call(
                "jenkins.fetch_build_details",
                {
                    "client": client,
                    "job_name": build.job.name,
                    "build_number": build.number,
                    "job_url": build.job.url,
                },
            )
            if details["ok"] and details["output"]:
                dev_list = details["output"].get("developer_emails") or []
                # Already deduped + ordered by the client; defensive recheck.
                cleaned: List[str] = []
                seen = set()
                for addr in dev_list:
                    a = (addr or "").strip()
                    if a and a not in seen:
                        cleaned.append(a)
                        seen.add(a)
                if cleaned:
                    return cleaned
        except Exception as exc:
            logger.warning("Could not fetch developer emails for %s#%s: %s",
                           build.job.name, build.number, exc)

        return fallback

    @staticmethod
    def _build_render_context(
        *,
        build: Build,
        plan: PlanDecision,
        execute_summary: Dict[str, Any],
        verify_status: str,
        context: Dict[str, Any],
        recipient_count: int,
    ) -> Dict[str, Any]:
        """Assemble the dict the Jinja2 templates consume."""
        steps_taken = [s["tool"] for s in execute_summary.get("steps", [])]
        return {
            "pipeline_name": build.job.name,
            "pipeline_type": build.job.pipeline_type or "BUILD",
            "build_number": build.number,
            "build_status": build.status,
            "build_url": (build.job.url or "").rstrip("/") + f"/{build.number}" if build.job.url else "",
            "failure_class": plan.failure_class.value,
            "plan_action": plan.action,
            "plan_rationale": plan.rationale,
            "steps_taken": steps_taken,
            "verify_status": verify_status,
            "parsed_errors": context.get("parsed_errors") or [],
            "console_tail": truncate_console(context.get("console") or "", max_lines=30),
            "recipient_count": recipient_count,
            "recipient_name": None,  # could resolve to first author's name; left for future
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _already_handled(db: AsyncSession, build_id: int) -> bool:
        """
        True if this build has already been through the full agent loop —
        detected by the presence of a VERIFY row (the terminal stage now
        that REPORT has been removed from the loop).

        Cheap single-row lookup; safe to call on every poll tick.
        """
        result = await db.execute(
            select(AgentAction.id)
            .filter(
                AgentAction.build_id == build_id,
                AgentAction.action_type == "VERIFY",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _step_succeeded(tool_name: str, output: Any) -> bool:
        """Tool-specific success interpretation of a ToolResult.output."""
        if output is None:
            return False
        if tool_name == "jenkins.retry_build":
            return bool(output.get("triggered"))
        if tool_name == "jenkins.clean_workspace":
            return bool(output.get("wiped"))
        if tool_name == "notify.email":
            return bool(output.get("sent"))
        return True

    async def _record(
        self,
        db: AsyncSession,
        build: Build,
        *,
        action_type: str,
        status: str,
        tool_name: Optional[str] = None,
        reason: Optional[str] = None,
        developer_email: Optional[str] = None,
    ) -> None:
        db.add(AgentAction(
            build_id=build.id,
            action_type=action_type,
            status=status,
            tool_name=tool_name,
            reason=reason,
            developer_email=developer_email,
        ))
        await db.flush()
