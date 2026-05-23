"""
Agent knowledge base — failure classification and class → action mappings.

This is the "stuff a junior DevOps engineer has memorised": which log
signatures look like which kind of failure, and what the obvious first-line
fix is for each. The Agent Controller imports from here and treats it as
read-only configuration.

Keep it deterministic. No LLM. No fuzziness. The whole point of this layer
is that the agent's reasoning is auditable and tunable by editing this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class FailureClass(str, Enum):
    """High-level category of a Jenkins build failure."""

    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    WORKER_OFFLINE = "WORKER_OFFLINE"
    WORKSPACE_LOCKED = "WORKSPACE_LOCKED"
    DISK_FULL = "DISK_FULL"
    PORT_CONFLICT = "PORT_CONFLICT"
    CODE_ERROR = "CODE_ERROR"
    UNKNOWN = "UNKNOWN"


# Order matters: classification stops at the first matching class. More
# *specific* signatures must come before more *generic* ones (e.g. DISK_FULL
# before WORKSPACE_LOCKED, because a disk-full log will often also mention
# "unable to delete").
FAILURE_PATTERNS: List[tuple[FailureClass, List[str]]] = [
    (FailureClass.DISK_FULL, [
        "no space left on device",
        "out of disk",
        "disk quota exceeded",
        "no space left",
    ]),
    (FailureClass.PORT_CONFLICT, [
        "address already in use",
        "port already in use",
        "bind: address already in use",
    ]),
    (FailureClass.WORKSPACE_LOCKED, [
        "workspace is locked",
        "unable to delete",
        "cannot access workspace",
        "the process cannot access the file",
        "could not lock workspace",
    ]),
    (FailureClass.WORKER_OFFLINE, [
        "agent went offline",
        "node disconnected",
        "executor lost",
        "channel was closed",
        "agent is offline",
    ]),
    (FailureClass.NETWORK_TRANSIENT, [
        "connection reset",
        "connection timed out",
        "connect timeout",
        "temporary failure",
        "temporarily unavailable",
        "network is unreachable",
        "503 service unavailable",
        "502 bad gateway",
        "rate limit",
        "etimedout",
    ]),
    (FailureClass.CODE_ERROR, [
        "nullpointerexception",
        "noclassdeffounderror",
        "assertionerror",
        "syntaxerror",
        "importerror",
        "modulenotfounderror",
        "test failed",
        "tests failed",
        "compilation failure",
        "compilation error",
        "build failed with an exception",
        "failed tests:",
    ]),
]


def classify_failure(log_text: str, parsed_errors: List[Dict[str, Any]]) -> FailureClass:
    """
    Return the most specific FailureClass that matches the log + parsed errors.

    Scans the tail of the log (where the actual failure tends to be) plus the
    text of every parser-flagged line, case-insensitively. Falls back to
    UNKNOWN if nothing matches.
    """
    haystack_parts: List[str] = []
    if log_text:
        haystack_parts.append(log_text[-8000:])
    for item in parsed_errors or []:
        content = item.get("content")
        if content:
            haystack_parts.append(str(content))
    haystack = "\n".join(haystack_parts).lower()

    if not haystack.strip():
        return FailureClass.UNKNOWN

    for cls, patterns in FAILURE_PATTERNS:
        for p in patterns:
            if p in haystack:
                return cls
    return FailureClass.UNKNOWN


# ---------------------------------------------------------------------------
# Class → action sequence
#
# Each FailureClass maps to an ordered list of PlanStep templates. The
# planner copies one of these, fills in job/build context, and hands it to
# the controller's Execute stage.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanStep:
    """One tool invocation in a plan. The args dict is a template — the
    planner fills in any value equal to the string ``"$build"`` /
    ``"$job_name"`` / ``"$job_url"`` / ``"$client"`` at execution time. This
    keeps the knowledge file free of runtime objects."""

    tool_name: str
    args: Dict[str, Any]
    label: str


# Canonical "what would a junior try?" sequences. Empty list means "no
# autonomous fix — notify a human."
DEFAULT_PLAYBOOKS: Dict[FailureClass, List[PlanStep]] = {
    FailureClass.NETWORK_TRANSIENT: [
        PlanStep(
            tool_name="jenkins.retry_build",
            args={"client": "$client", "job_name": "$job_name", "job_url": "$job_url"},
            label="Retry pipeline (transient network)",
        ),
    ],
    FailureClass.WORKER_OFFLINE: [
        PlanStep(
            tool_name="jenkins.retry_build",
            args={"client": "$client", "job_name": "$job_name", "job_url": "$job_url"},
            label="Retry pipeline (worker came back)",
        ),
    ],
    FailureClass.WORKSPACE_LOCKED: [
        PlanStep(
            tool_name="jenkins.clean_workspace",
            args={"client": "$client", "job_name": "$job_name", "job_url": "$job_url"},
            label="Wipe workspace",
        ),
        PlanStep(
            tool_name="jenkins.retry_build",
            args={"client": "$client", "job_name": "$job_name", "job_url": "$job_url"},
            label="Retry pipeline after wipe",
        ),
    ],
    # DISK_FULL and PORT_CONFLICT need a host-side fix that we can only do
    # by triggering a pre-approved Jenkins fix-it job. That's a future slice
    # — for now, classify but escalate.
    FailureClass.DISK_FULL: [],
    FailureClass.PORT_CONFLICT: [],
    FailureClass.CODE_ERROR: [],
    FailureClass.UNKNOWN: [],
}


def playbook_for(failure_class: FailureClass) -> List[PlanStep]:
    """Return a *copy* of the default playbook so callers can safely mutate it."""
    return list(DEFAULT_PLAYBOOKS.get(failure_class, []))


# ---------------------------------------------------------------------------
# RELEASE-pipeline policy
#
# Release builds get one universal playbook regardless of failure class — the
# operator's choice is "always try retry first; if that doesn't recover, ping
# DevOps." (Per user direction.) The retry is still gated by the controller's
# memory + per-build-cap guards so a chronically broken release isn't retried
# forever.
# ---------------------------------------------------------------------------
RELEASE_RETRY_PLAYBOOK: List[PlanStep] = [
    PlanStep(
        tool_name="jenkins.retry_build",
        args={"client": "$client", "job_name": "$job_name", "job_url": "$job_url"},
        label="Retry release pipeline",
    ),
]


def release_playbook() -> List[PlanStep]:
    """Copy of the canonical RELEASE-pipeline playbook (single retry step)."""
    return list(RELEASE_RETRY_PLAYBOOK)


# Reason text used by the planner — kept here so it's easy to audit what a
# junior would "say" for each class.
CLASS_RATIONALE: Dict[FailureClass, str] = {
    FailureClass.NETWORK_TRANSIENT: "Network-style transient failure detected; retry pipeline.",
    FailureClass.WORKER_OFFLINE: "Build worker disconnected; the next attempt should land on a healthy node.",
    FailureClass.WORKSPACE_LOCKED: "Workspace files are locked or undeletable; wipe and retry.",
    FailureClass.DISK_FULL: "Host appears to be out of disk; needs a cleanup job (not yet wired). Notify.",
    FailureClass.PORT_CONFLICT: "Port is already bound on the host; needs a restart job (not yet wired). Notify.",
    FailureClass.CODE_ERROR: "Looks like a real code/test failure; notify the developer.",
    FailureClass.UNKNOWN: "No matching failure signature; notify the developer to investigate.",
}


def rationale_for(failure_class: FailureClass) -> str:
    return CLASS_RATIONALE.get(failure_class, "Unclassified failure.")


# Sentinel strings the planner uses to mark dynamic arg slots in playbook
# templates. Exposed for tests and for the controller.
ARG_BUILD = "$build"
ARG_CLIENT = "$client"
ARG_JOB_NAME = "$job_name"
ARG_JOB_URL = "$job_url"
ARG_BUILD_NUMBER = "$build_number"


def resolve_args(
    template: Dict[str, Any],
    *,
    client: Any,
    job_name: str,
    job_url: Optional[str],
    build_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Replace sentinel strings in a PlanStep.args template with real values."""
    mapping = {
        ARG_CLIENT: client,
        ARG_JOB_NAME: job_name,
        ARG_JOB_URL: job_url,
        ARG_BUILD_NUMBER: build_number,
    }
    return {k: (mapping[v] if isinstance(v, str) and v in mapping else v) for k, v in template.items()}
