import re
from typing import List, Dict, Any

# Regex compilations for performance and accuracy
ERROR_PATTERNS = [
    (re.compile(r"(fatal|critical|oom|panic|crash|locked|connection refused|refused)", re.IGNORECASE), "CRITICAL"),
    (re.compile(r"(error|failed|exception|denied|ioerror|err|failed with exit code)", re.IGNORECASE), "ERROR"),
    (re.compile(r"(warn|warning|deprecat|alert)", re.IGNORECASE), "WARNING"),
]

CATEGORY_PATTERNS = [
    (re.compile(r"(docker|daemon|container|image|pull|manifest)", re.IGNORECASE), "Docker"),
    (re.compile(r"(kube|pod|kubectl|rollout|liveness|probe|crashloopbackoff)", re.IGNORECASE), "Kubernetes"),
    (re.compile(r"(connection|port|bind|socket|network|reach|refused|address already in use|502|503|http)", re.IGNORECASE), "Network"),
    (re.compile(r"(permission|access|denied|owner|uid|chmod|chown)", re.IGNORECASE), "Permission"),
    (re.compile(r"(dll|lock|process cannot access|iis|apppool|webapppool|msbuild|w3wp)", re.IGNORECASE), "Windows-IIS"),
]

def parse_log_content(log_text: str) -> List[Dict[str, Any]]:
    """
    Parses raw log content, extracts error lines, cleans noise,
    and classifies severity and systems categories.
    """
    if not log_text:
        return []

    lines = log_text.splitlines()
    parsed_errors = []

    for idx, line in enumerate(lines):
        line_num = idx + 1
        clean_line = line.strip()

        # Skip obviously empty lines or extremely short noise
        if not clean_line or len(clean_line) < 5:
            continue

        # Check for severities
        matched_severity = None
        for pattern, severity in ERROR_PATTERNS:
            if pattern.search(clean_line):
                matched_severity = severity
                break

        if not matched_severity:
            continue

        # Check for system category
        matched_category = "System"
        for pattern, category in CATEGORY_PATTERNS:
            if pattern.search(clean_line):
                matched_category = category
                break

        parsed_errors.append({
            "line_number": line_num,
            "content": clean_line,
            "severity": matched_severity,
            "category": matched_category
        })

    # Noise reduction: If we have too many errors (e.g. long stack trace),
    # limit to the most severe and unique alerts up to 30 items
    parsed_errors.sort(key=lambda x: (
        0 if x["severity"] == "CRITICAL" else (1 if x["severity"] == "ERROR" else 2)
    ))
    
    # Cap total returned errors to avoid overloading payloads, keeping order of appearance
    capped_errors = parsed_errors[:30]
    capped_errors.sort(key=lambda x: x["line_number"])
    
    return capped_errors
