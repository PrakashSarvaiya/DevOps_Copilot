"""
Tool Registry for the Agent Controller.

The controller never calls Jenkins/SMTP/parser code directly — it goes through
the ToolRegistry. This gives us one place to enforce the safe/blocked-action
allowlist defined by the DevOps_Copilot vision and to record what the agent
attempted.

Safety classes
--------------
- READ_ONLY:   observation / context-understanding only. No side effects.
- SAFE_ACTION: has side effects but appears on the project's allowlist
               (retry pipeline, restart service, clean workspace, docker
               cleanup, validate deployment, check status, fetch logs,
               notify by email).
- BLOCKED:     destructive operations that the agent must never perform
               (delete production resources, destroy infrastructure, drop
               databases, modify production configs, remove clusters).
               Registered as placeholders so the catalog is complete; any
               attempt to call them raises ToolBlockedError.

`assert_safe()` also scans tool arguments for blocked-keyword substrings as
a defense-in-depth measure (e.g. an LLM-driven planner trying to pass
"DROP TABLE" through a shell tool).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from app.services.jenkins_client import JenkinsClient
from app.services.notifier import send_failure_email
from app.services.parser import parse_log_content

logger = logging.getLogger("DevOps_agent_tools")


class SafetyClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_ACTION = "SAFE_ACTION"
    BLOCKED = "BLOCKED"


class ToolResult(TypedDict, total=False):
    ok: bool
    output: Any
    error: Optional[str]


class ToolBlockedError(RuntimeError):
    """Raised when the controller tries to invoke a BLOCKED tool or pass
    blocked keywords through a SAFE tool's arguments."""


# Substring patterns (lowercased) that must never appear in tool arguments,
# regardless of which tool is being called. Defense-in-depth for the day a
# planner generates free-form commands.
BLOCKED_KEYWORDS: List[str] = [
    "drop database",
    "drop table",
    "delete cluster",
    "destroy cluster",
    "remove cluster",
    "delete namespace",
    "remove namespace",
    "destroy infrastructure",
    "terraform destroy",
    "rm -rf /",
    "delete production",
    "kubectl delete pv",
    "kubectl delete pvc",
    "modify production config",
]


@dataclass
class Tool:
    name: str
    safety: SafetyClass
    description: str
    handler: Optional[Callable[..., Awaitable[Any]]] = None
    # Optional metadata for UI/introspection
    parameters: Dict[str, str] = field(default_factory=dict)


class ToolRegistry:
    """Holds Tools and enforces the safety guard at call-time."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        if tool.safety != SafetyClass.BLOCKED and tool.handler is None:
            raise ValueError(f"Tool {tool.name} is not BLOCKED but has no handler")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list(self) -> List[Tool]:
        return list(self._tools.values())

    def assert_safe(self, name: str, arguments: Dict[str, Any]) -> Tool:
        """Raises ToolBlockedError if the call must not proceed."""
        tool = self.get(name)
        if tool.safety == SafetyClass.BLOCKED:
            raise ToolBlockedError(
                f"Tool '{name}' is BLOCKED: {tool.description}"
            )
        # Scan stringified arguments for blocked keywords.
        haystack = " ".join(str(v) for v in arguments.values()).lower()
        for kw in BLOCKED_KEYWORDS:
            if kw in haystack:
                raise ToolBlockedError(
                    f"Argument to '{name}' contains blocked keyword: '{kw}'"
                )
        return tool

    async def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> ToolResult:
        """
        Invoke a tool by name. Returns a ToolResult — never raises for the
        tool's own runtime errors (those become {ok: False, error: ...}).
        Raises ToolBlockedError if the tool is BLOCKED or the args contain
        blocked keywords; that is intentional — the controller should treat
        attempted blocked calls as a programming error or hostile plan.
        """
        arguments = arguments or {}
        tool = self.assert_safe(name, arguments)
        assert tool.handler is not None  # assert_safe filters BLOCKED out
        try:
            output = await tool.handler(**arguments)
            return {"ok": True, "output": output, "error": None}
        except Exception as exc:
            logger.warning("Tool %s raised: %s", name, exc)
            return {"ok": False, "output": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool handlers
#
# Handlers are thin wrappers around existing services. They accept keyword
# arguments only (so the controller can spread an arbitrary args dict) and
# return JSON-serialisable values whenever possible — the audit ledger and
# any future plan-tracing UI will want to display them.
# ---------------------------------------------------------------------------


async def _jenkins_fetch_console(
    *,
    client: JenkinsClient,
    job_name: str,
    build_number: int,
    job_url: Optional[str] = None,
) -> str:
    return await client.get_console_output(job_name, build_number, job_url)


async def _jenkins_fetch_build_details(
    *,
    client: JenkinsClient,
    job_name: str,
    build_number: int,
    job_url: Optional[str] = None,
) -> Dict[str, Any]:
    return await client.get_build_details(job_name, build_number, job_url)


async def _jenkins_retry_build(
    *,
    client: JenkinsClient,
    job_name: str,
    job_url: Optional[str] = None,
) -> Dict[str, Any]:
    triggered = await client.trigger_build(job_name, job_url)
    return {"triggered": triggered, "job_name": job_name}


async def _jenkins_clean_workspace(
    *,
    client: JenkinsClient,
    job_name: str,
    job_url: Optional[str] = None,
) -> Dict[str, Any]:
    wiped = await client.wipe_workspace(job_name, job_url)
    return {"wiped": wiped, "job_name": job_name}


async def _context_parse_errors(*, log_text: str) -> List[Dict[str, Any]]:
    return parse_log_content(log_text)


async def _notify_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> Dict[str, Any]:
    sent = send_failure_email(
        recipient=recipient,
        subject=subject,
        body=body,
        html_body=html_body,
    )
    return {"sent": sent, "recipient": recipient}


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def build_default_registry() -> ToolRegistry:
    """
    Construct the registry with the tools we can back today plus BLOCKED
    placeholders for destructive operations the vision explicitly forbids.
    """
    reg = ToolRegistry()

    # --- READ_ONLY: observation / context tools ---
    reg.register(Tool(
        name="jenkins.fetch_console",
        safety=SafetyClass.READ_ONLY,
        description="Fetch the raw console log for a specific Jenkins build.",
        handler=_jenkins_fetch_console,
        parameters={"client": "JenkinsClient", "job_name": "str", "build_number": "int", "job_url": "Optional[str]"},
    ))
    reg.register(Tool(
        name="jenkins.fetch_build_details",
        safety=SafetyClass.READ_ONLY,
        description="Fetch metadata (status, building flag, developer email) for a build.",
        handler=_jenkins_fetch_build_details,
        parameters={"client": "JenkinsClient", "job_name": "str", "build_number": "int", "job_url": "Optional[str]"},
    ))
    reg.register(Tool(
        name="context.parse_errors",
        safety=SafetyClass.READ_ONLY,
        description="Run severity/category regex over log text and return classified error lines.",
        handler=_context_parse_errors,
        parameters={"log_text": "str"},
    ))

    # --- SAFE_ACTION: allowlisted side effects ---
    reg.register(Tool(
        name="jenkins.retry_build",
        safety=SafetyClass.SAFE_ACTION,
        description="Trigger a new build of the given Jenkins job (used for transient-failure retry).",
        handler=_jenkins_retry_build,
        parameters={"client": "JenkinsClient", "job_name": "str", "job_url": "Optional[str]"},
    ))
    reg.register(Tool(
        name="jenkins.clean_workspace",
        safety=SafetyClass.SAFE_ACTION,
        description="Wipe the job's Jenkins workspace via doWipeOutWorkspace (used before retry on WORKSPACE_LOCKED).",
        handler=_jenkins_clean_workspace,
        parameters={"client": "JenkinsClient", "job_name": "str", "job_url": "Optional[str]"},
    ))
    reg.register(Tool(
        name="notify.email",
        safety=SafetyClass.SAFE_ACTION,
        description="Send a failure-notification email through the configured SMTP server. Optional html_body for multipart/alternative.",
        handler=_notify_email,
        parameters={"recipient": "str", "subject": "str", "body": "str", "html_body": "Optional[str]"},
    ))

    # --- BLOCKED placeholders ---
    # These exist so the catalog is honest about what the agent will never do,
    # and so attempts to call them surface as ToolBlockedError instead of
    # silently succeeding because the handler doesn't exist.
    blocked = [
        ("infra.drop_database", "Drop a database. Forbidden by the safe-action allowlist."),
        ("infra.delete_cluster", "Delete a Kubernetes cluster. Forbidden."),
        ("infra.delete_production_resource", "Delete production resources of any kind. Forbidden."),
        ("infra.modify_production_config", "Mutate production configuration. Forbidden."),
        ("infra.destroy_infrastructure", "Run terraform destroy / destroy infra. Forbidden."),
    ]
    for name, desc in blocked:
        reg.register(Tool(name=name, safety=SafetyClass.BLOCKED, description=desc))

    return reg


# Module-level default registry. Tests/controller import this; if a test wants
# to inject a stubbed registry it can construct its own via build_default_registry().
default_registry: ToolRegistry = build_default_registry()
