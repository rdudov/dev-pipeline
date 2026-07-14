"""Compact contracts for owner checkpoints and bounded reviews."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
DECISIONS = frozenset({"approved", "rework_required", "blocked", "rejected"})
REVIEW_TYPES = frozenset({"scenario", "architecture", "increment"})


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(record: dict[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} requires non-empty {field}")
    return value


def _strings(record: dict[str, Any], field: str, label: str, *, allow_empty: bool = False) -> list[str]:
    value = record.get(field)
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{label} requires {qualifier} of {field}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} {field} must contain non-empty strings")
    return value


def _version(record: dict[str, Any], label: str) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported {label} schema_version")


def _digest(record: dict[str, Any], field: str, label: str) -> str:
    value = _string(record, field, label)
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{label} {field} must be a sha256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError(f"{label} {field} must be a sha256 digest") from exc
    return value


def _questions(record: dict[str, Any], label: str) -> list[dict[str, Any]]:
    questions = record.get("blocking_questions")
    if not isinstance(questions, list):
        raise ValueError(f"{label} requires a blocking_questions list")
    for question in questions:
        item = _object(question, f"{label} blocking question")
        _string(item, "question", f"{label} blocking question")
        options = item.get("options", [])
        if not isinstance(options, list):
            raise ValueError(f"{label} blocking question options must be a list")
        for option in options:
            option = _object(option, f"{label} question option")
            _string(option, "label", f"{label} question option")
            _string(option, "consequence", f"{label} question option")
    return questions


def validate_scenario_checkpoint(value: Any) -> dict[str, Any]:
    record = _object(value, "Scenario checkpoint")
    _version(record, "scenario checkpoint")
    _string(record, "artifact_id", "Scenario checkpoint")
    _string(record, "artifact_version", "Scenario checkpoint")
    _strings(record, "source_refs", "Scenario checkpoint")
    scenarios = record.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Scenario checkpoint requires a non-empty scenarios list")
    seen: set[str] = set()
    for scenario in scenarios:
        item = _object(scenario, "Scenario")
        scenario_id = _string(item, "id", "Scenario")
        if scenario_id in seen:
            raise ValueError(f"Duplicate scenario id: {scenario_id}")
        seen.add(scenario_id)
        for field in ("actor", "trigger", "expected_outcome"):
            _string(item, field, f"Scenario {scenario_id}")
        _strings(item, "acceptance", f"Scenario {scenario_id}")
        _strings(item, "failure_modes", f"Scenario {scenario_id}", allow_empty=True)
    _strings(record, "reversible_assumptions", "Scenario checkpoint", allow_empty=True)
    _questions(record, "Scenario checkpoint")
    return record


def validate_architecture_checkpoint(value: Any) -> dict[str, Any]:
    record = _object(value, "Architecture checkpoint")
    _version(record, "architecture checkpoint")
    _string(record, "artifact_id", "Architecture checkpoint")
    _string(record, "artifact_version", "Architecture checkpoint")
    _digest(record, "scenario_artifact_digest", "Architecture checkpoint")
    _strings(record, "production_path", "Architecture checkpoint")
    _string(record, "owning_layer", "Architecture checkpoint")
    _strings(record, "reuse_plan", "Architecture checkpoint")
    _strings(record, "deletion_plan", "Architecture checkpoint")
    _string(record, "forbidden_parallel_mechanism", "Architecture checkpoint")
    _strings(record, "verification_path", "Architecture checkpoint")
    _questions(record, "Architecture checkpoint")
    return record


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def artifact_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def build_review_packet(
    *, review_type: str, artifact: Path, artifact_version: str, question: str,
    constraints: list[str], instructions: list[str], evidence: list[str], exclusions: list[str],
) -> dict[str, Any]:
    if review_type not in REVIEW_TYPES:
        raise ValueError(f"Unsupported review type: {review_type}")
    if not artifact.is_file():
        raise ValueError(f"Review artifact does not exist: {artifact}")
    if not question.strip():
        raise ValueError("Review question must be non-empty")
    if not constraints or not instructions or not exclusions:
        raise ValueError("Review packet requires constraints, instructions, and explicit exclusions")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "review_type": review_type,
        "question": question,
        "artifact": {
            "path": str(artifact.resolve()),
            "version": artifact_version,
            "digest": artifact_digest(artifact),
        },
        "original_constraints": constraints,
        "target_instructions": instructions,
        "evidence": evidence,
        "exclusions": exclusions,
        "decision_schema_version": SCHEMA_VERSION,
    }
    return validate_review_packet(packet)


def validate_review_packet(value: Any) -> dict[str, Any]:
    packet = _object(value, "Review packet")
    _version(packet, "review packet")
    if packet.get("review_type") not in REVIEW_TYPES:
        raise ValueError("Review packet has unsupported review_type")
    _string(packet, "question", "Review packet")
    artifact = _object(packet.get("artifact"), "Review packet artifact")
    for field in ("path", "version", "digest"):
        _string(artifact, field, "Review packet artifact")
    _digest(artifact, "digest", "Review packet artifact")
    _strings(packet, "original_constraints", "Review packet")
    _strings(packet, "target_instructions", "Review packet")
    _strings(packet, "evidence", "Review packet", allow_empty=True)
    _strings(packet, "exclusions", "Review packet")
    if packet.get("decision_schema_version") != SCHEMA_VERSION:
        raise ValueError("Review packet has unsupported decision_schema_version")
    return packet


def validate_decision(value: Any, packet: dict[str, Any]) -> dict[str, Any]:
    decision = _object(value, "Review decision")
    _version(decision, "review decision")
    validate_review_packet(packet)
    if decision.get("review_type") != packet["review_type"]:
        raise ValueError("Review decision type does not match its packet")
    artifact = packet["artifact"]
    if decision.get("artifact_digest") != artifact["digest"]:
        raise ValueError("Review decision artifact_digest does not match its packet")
    if decision.get("artifact_version") != artifact["version"]:
        raise ValueError("Review decision artifact_version does not match its packet")
    if decision.get("decision") not in DECISIONS:
        raise ValueError("Review decision has unsupported decision vocabulary")
    findings = decision.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Review decision requires a findings list")
    for finding in findings:
        item = _object(finding, "Review finding")
        for field in ("id", "severity", "summary", "evidence_ref"):
            _string(item, field, "Review finding")
    _strings(decision, "blocking_questions", "Review decision", allow_empty=True)
    _strings(decision, "evidence_checked", "Review decision", allow_empty=True)
    if decision["decision"] == "approved" and (findings or decision["blocking_questions"]):
        raise ValueError("Approved review decision cannot contain findings or blocking questions")
    if decision["decision"] == "blocked" and not decision["blocking_questions"]:
        raise ValueError("Blocked review decision requires a blocking question")
    return decision
