"""
Email renderer for the NOTIFY stage.

Picks one of three Jinja2 templates based on the failure scenario, fills in
context, returns a tuple of (subject, plain_text_body, html_body) that the
notifier turns into a multipart/alternative SMTP message.

Templates live in services/email_templates/ and are designed for cross-client
HTML email (inline CSS, table layout, no remote assets). Add a new template
file there + a new scenario case in `render_email()` to extend.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "email_templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Map scenario keys → (template_filename, subject_template)
SCENARIOS: Dict[str, Tuple[str, str]] = {
    "code_error": (
        "code_error.html",
        "[DevOps Copilot] {pipeline_name} #{build_number} failed — looks like a code/test issue",
    ),
    "recovery_failed": (
        "recovery_failed.html",
        "[DevOps Copilot] {pipeline_name} #{build_number} failed — agent couldn't recover",
    ),
    "release_escalation": (
        "release_escalation.html",
        "[DevOps Copilot] RELEASE {pipeline_name} #{build_number} failed — needs DevOps attention",
    ),
    "site_down": (
        "site_down.html",
        "[DevOps Copilot] Site DOWN: {site_name}",
    ),
}


def render_email(scenario: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Render the chosen scenario.

    Returns (subject, plain_text, html). The plain-text body is generated from
    the HTML by stripping tags — keeps the two versions trivially in sync.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown email scenario: {scenario!r}. Known: {list(SCENARIOS)}")
    template_name, subject_template = SCENARIOS[scenario]

    # `format_map` over a dict that returns "?" for missing keys — keeps the
    # subject lines templated without forcing every scenario to populate the
    # same context fields.
    class _Defaulting(dict):
        def __missing__(self, key):
            return "?"
    subject = subject_template.format_map(_Defaulting(ctx))
    html = _env.get_template(template_name).render(**ctx)
    plain = _html_to_plain(html)
    return subject, plain, html


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _html_to_plain(html: str) -> str:
    """
    Strip tags + collapse whitespace into a readable plain-text alternative.

    Cheap and good enough — we control the templates, so we don't need a full
    HTML→text converter. The result is what gets shown by mail clients that
    refuse to render HTML.
    """
    # Insert newlines for block-level closers so structure survives.
    text = re.sub(r"</(p|div|tr|li|h\d|br\s*/?)\s*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    # Decode the few HTML entities our templates emit.
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip() + "\n"


def truncate_console(console: str, max_lines: int = 30) -> List[str]:
    """
    Return the last `max_lines` non-empty lines of the console log, in order.
    Used by templates to show the failure tail without dumping a 100K-line file.
    """
    if not console:
        return []
    lines = [ln.rstrip() for ln in console.splitlines() if ln.strip()]
    return lines[-max_lines:]
