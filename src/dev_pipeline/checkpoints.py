"""Compact contracts for owner checkpoints and bounded reviews."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
DECISIONS = frozenset({"approved", "rework_required", "blocked", "rejected"})
REVIEW_TYPES = frozenset({"scenario", "architecture", "increment"})
DEPENDENCY_SURFACES = (
    "source_repositories", "runtime_entrypoints", "services_and_processes",
    "containers_and_images", "host_identities_and_permissions", "configuration_and_secrets",
    "durable_storage", "backup_restore_and_retention", "deployment_update_and_rollback",
    "observability", "network", "scheduled_jobs", "external_integrations", "security_boundaries",
)


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
    inventory = record.get("dependency_inventory")
    if not isinstance(inventory, list):
        raise ValueError("Scenario checkpoint requires a dependency_inventory list")
    found: set[str] = set()
    for dependency in inventory:
        item = _object(dependency, "Dependency inventory item")
        surface = _string(item, "surface", "Dependency inventory item")
        if surface not in DEPENDENCY_SURFACES:
            raise ValueError(f"Unsupported dependency surface: {surface}")
        if surface in found:
            raise ValueError(f"Duplicate dependency surface: {surface}")
        found.add(surface)
        if item.get("applicability") not in {"applicable", "not_applicable"}:
            raise ValueError(f"Dependency surface {surface} requires applicable or not_applicable")
        _string(item, "owner", f"Dependency surface {surface}")
        _strings(item, "evidence_refs", f"Dependency surface {surface}")
        _string(item, "change_impact", f"Dependency surface {surface}")
    missing = set(DEPENDENCY_SURFACES) - found
    if missing:
        raise ValueError(f"Dependency inventory is incomplete; missing: {', '.join(sorted(missing))}")
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
    known_failures = {
        failure for scenario in scenarios for failure in scenario["failure_modes"]
    }
    branches = record.get("production_branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError("Scenario checkpoint requires a non-empty production_branches list")
    branch_ids: set[str] = set()
    for branch in branches:
        item = _object(branch, "Scenario production branch")
        branch_id = _string(item, "id", "Scenario production branch")
        if branch_id in branch_ids:
            raise ValueError(f"Duplicate scenario production branch: {branch_id}")
        branch_ids.add(branch_id)
        for field in ("mode", "boundary", "expected_behavior"):
            _string(item, field, f"Scenario production branch {branch_id}")
        if item.get("applicability") not in {"applicable", "not_applicable"}:
            raise ValueError(f"Scenario production branch {branch_id} requires applicability")
        failures = _strings(
            item, "failure_mode_ids", f"Scenario production branch {branch_id}", allow_empty=True
        )
        unknown = set(failures) - known_failures
        if unknown:
            raise ValueError(
                f"Scenario production branch {branch_id} references unknown failure mode: {sorted(unknown)[0]}"
            )
        security_path = item.get("security_path", "not_applicable")
        if security_path not in {"not_applicable", "permitted", "denied"}:
            raise ValueError(f"Scenario production branch {branch_id} has unsupported security_path")
        if security_path != "not_applicable":
            if item["applicability"] != "applicable":
                raise ValueError(f"Security branch {branch_id} must be applicable")
            _string(item, "isolation_boundary", f"Scenario production branch {branch_id}")
            if security_path == "denied":
                _string(item, "safety_basis", f"Scenario production branch {branch_id}")
    intent = _object(record.get("product_intent"), "Scenario product intent")
    if intent.get("applicability") not in {"applicable", "not_applicable"}:
        raise ValueError("Scenario product intent requires applicability")
    _strings(intent, "intent_categories", "Scenario product intent", allow_empty=True)
    if intent.get("capability_matrix_applicability") not in {"applicable", "not_applicable"}:
        raise ValueError("Scenario product intent requires capability_matrix_applicability")
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
    boundaries = record.get("isolation_boundaries")
    if not isinstance(boundaries, list):
        raise ValueError("Architecture checkpoint requires an isolation_boundaries list")
    for boundary in boundaries:
        item = _object(boundary, "Isolation boundary")
        name = _string(item, "name", "Isolation boundary")
        _string(item, "production_boundary", f"Isolation boundary {name}")
        _strings(item, "allowed_operations", f"Isolation boundary {name}")
        _strings(item, "denied_operations", f"Isolation boundary {name}")
        probes = item.get("safe_negative_probes")
        if not isinstance(probes, list) or not probes:
            raise ValueError(f"Isolation boundary {name} requires safe_negative_probes")
        for probe in probes:
            probe_item = _object(probe, f"Isolation boundary {name} probe")
            for field in ("operation", "expected_denial", "safety_basis", "evidence_path"):
                _string(probe_item, field, f"Isolation boundary {name} probe")
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
    task_contract: Path | None = None, evidence_checkpoint: Path | None = None,
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
    if task_contract is not None or evidence_checkpoint is not None:
        if task_contract is None or evidence_checkpoint is None:
            raise ValueError("Review closure requires both task contract and evidence checkpoint")
        if not task_contract.is_file() or not evidence_checkpoint.is_file():
            raise ValueError("Review closure artifacts must exist")
        packet["closure_bindings"] = {
            "task_contract": {"path": str(task_contract.resolve()), "digest": artifact_digest(task_contract)},
            "evidence_checkpoint": {
                "path": str(evidence_checkpoint.resolve()),
                "digest": artifact_digest(evidence_checkpoint),
            },
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
    bindings = packet.get("closure_bindings")
    if bindings is not None:
        bindings = _object(bindings, "Review closure bindings")
        for name in ("task_contract", "evidence_checkpoint"):
            binding = _object(bindings.get(name), f"Review closure {name}")
            _string(binding, "path", f"Review closure {name}")
            _digest(binding, "digest", f"Review closure {name}")
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
