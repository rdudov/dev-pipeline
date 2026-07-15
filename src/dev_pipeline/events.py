"""Canonical neutral lifecycle event vocabulary."""

from __future__ import annotations

from typing import Any


EVENT_KINDS = frozenset(
    {
        "attempt_started",
        "run_started",
        "process_started",
        "native_session_discovered",
        "native_resume_unavailable",
        "checkpoint_completed",
        "increment_ready_for_review",
        "increment_completed",
        "blocked_on_user_decision",
        "run_failed",
        "attempt_failed",
        "run_completed",
        "attempt_completed",
    }
)

REQUIRED_PAYLOAD_FIELDS = {
    "attempt_started": ("attempt_origin", "repository"),
    "run_started": ("run_operation",),
    "native_session_discovered": ("native_session_id",),
    "checkpoint_completed": ("checkpoint", "next_step"),
    "increment_ready_for_review": ("increment", "artifact", "artifact_digest"),
    "increment_completed": ("increment", "next_step"),
    "blocked_on_user_decision": ("question", "artifact"),
    "run_failed": ("reason",),
    "attempt_failed": ("reason",),
    "native_resume_unavailable": ("reason",),
}

INTEGER_PAYLOAD_FIELDS = {
    "process_started": ("pid",),
    "run_completed": ("exit_code",),
}

RESUME_UNAVAILABILITY_CONDITIONS = frozenset(
    {"missing_session_id", "archived", "not_found", "runtime_unavailable", "missing_runtime_identity", "identity_mismatch"}
)


def validate_event(
    event: dict[str, Any], *, allow_legacy_unclassified_resume: bool = False
) -> dict[str, Any]:
    """Validate the stable adapter-facing envelope and return it unchanged."""
    required = (
        "schema_version",
        "event_id",
        "sequence",
        "timestamp",
        "task_ref",
        "attempt_id",
        "run_id",
        "kind",
        "payload",
    )
    missing = [field for field in required if field not in event]
    if missing:
        raise ValueError(f"Lifecycle event is missing required field: {missing[0]}")
    if event["schema_version"] != "1.0":
        raise ValueError("Unsupported lifecycle event schema_version")
    for field in ("event_id", "timestamp", "task_ref", "attempt_id", "run_id", "kind"):
        if not isinstance(event[field], str) or not event[field].strip():
            raise ValueError(f"Lifecycle event {field} must be a non-empty string")
    if not isinstance(event["sequence"], int) or isinstance(event["sequence"], bool) or event["sequence"] < 1:
        raise ValueError("Lifecycle event sequence must be a positive integer")
    kind = event["kind"]
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unsupported lifecycle event kind: {kind}")
    if not isinstance(event["payload"], dict):
        raise ValueError("Lifecycle event payload must be an object")
    for field in REQUIRED_PAYLOAD_FIELDS.get(kind, ()):
        if not isinstance(event["payload"].get(field), str) or not event["payload"][field].strip():
            raise ValueError(f"{kind} payload requires non-empty {field}")
    for field in INTEGER_PAYLOAD_FIELDS.get(kind, ()):
        value = event["payload"].get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{kind} payload requires non-negative integer {field}")
    options = event["payload"].get("options")
    if options is not None:
        if not isinstance(options, list):
            raise ValueError("blocked_on_user_decision options must be a list")
        for option in options:
            if not isinstance(option, dict) or not all(
                isinstance(option.get(field), str) and option[field].strip()
                for field in ("label", "consequence")
            ):
                raise ValueError("Each decision option requires non-empty label and consequence")
    if kind == "native_resume_unavailable":
        condition = event["payload"].get("condition")
        if condition is None and not allow_legacy_unclassified_resume:
            raise ValueError("native_resume_unavailable payload requires non-empty condition")
        if condition is not None and condition not in RESUME_UNAVAILABILITY_CONDITIONS:
            raise ValueError("native_resume_unavailable payload has unsupported condition")
    return event
