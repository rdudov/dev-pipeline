"""Walking-skeleton and vertical-increment contracts and evidence gates."""

from __future__ import annotations

from typing import Any

from .checkpoints import SCHEMA_VERSION, _digest, _object, _string, _strings, _version


INCREMENT_KINDS = frozenset({"walking_skeleton", "vertical_increment"})
EVIDENCE_LEVELS = ("structural", "unit", "skeleton", "integrated", "live", "deployed")
WEAK_LEVELS = frozenset({"structural", "unit"})
SEAM_BOUNDARIES = frozenset({"new_boundary", "unavailable_external"})
SEAM_KINDS = frozenset({"stub", "temporary_adapter"})


def _positive_integer(record: dict[str, Any], field: str, label: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} requires positive integer {field}")
    return value


def validate_increment(value: Any) -> dict[str, Any]:
    record = _object(value, "Increment checkpoint")
    _version(record, "increment checkpoint")
    _string(record, "artifact_id", "Increment checkpoint")
    _string(record, "artifact_version", "Increment checkpoint")
    sequence = _positive_integer(record, "sequence", "Increment checkpoint")
    kind = record.get("increment_kind")
    if kind not in INCREMENT_KINDS:
        raise ValueError("Increment checkpoint has unsupported increment_kind")
    if sequence == 1 and kind != "walking_skeleton":
        raise ValueError("The first increment must be a walking_skeleton")
    if sequence > 1 and kind != "vertical_increment":
        raise ValueError("Later increments must be vertical_increment")
    _digest(record, "scenario_artifact_digest", "Increment checkpoint")
    _digest(record, "architecture_artifact_digest", "Increment checkpoint")
    scenario_ids = _strings(record, "scenario_ids", "Increment checkpoint")
    failure_modes = record.get("failure_modes")
    if not isinstance(failure_modes, list) or not failure_modes:
        raise ValueError("Increment checkpoint requires a non-empty failure_modes list")
    failure_mode_ids: list[str] = []
    for failure_mode in failure_modes:
        item = _object(failure_mode, "Failure mode")
        failure_mode_id = _string(item, "id", "Failure mode")
        if failure_mode_id in failure_mode_ids:
            raise ValueError(f"Duplicate failure mode id: {failure_mode_id}")
        failure_mode_ids.append(failure_mode_id)
        _string(item, "description", f"Failure mode {failure_mode_id}")
    _string(record, "observable_delta", "Increment checkpoint")
    _strings(record, "source_delta", "Increment checkpoint")
    _strings(record, "deletion_performed", "Increment checkpoint")

    seams = record.get("temporary_seams")
    if not isinstance(seams, list):
        raise ValueError("Increment checkpoint requires a temporary_seams list")
    for seam in seams:
        item = _object(seam, "Temporary seam")
        _string(item, "name", "Temporary seam")
        if item.get("kind") not in SEAM_KINDS:
            raise ValueError("Temporary seam kind must be stub or temporary_adapter")
        if item.get("boundary") not in SEAM_BOUNDARIES:
            raise ValueError("Temporary seam boundary must be new_boundary or unavailable_external")
        _string(item, "reason", "Temporary seam")
        _string(item, "replacement_milestone", "Temporary seam")

    gate = _object(record.get("evidence_gate"), "Evidence gate")
    required_level = gate.get("required_level")
    if required_level not in EVIDENCE_LEVELS:
        raise ValueError("Evidence gate has unsupported required_level")
    minimum = "skeleton" if kind == "walking_skeleton" else "integrated"
    if EVIDENCE_LEVELS.index(required_level) < EVIDENCE_LEVELS.index(minimum):
        raise ValueError(f"{kind} requires evidence level {minimum} or higher")
    required_ids = _strings(gate, "required_evidence_ids", "Evidence gate")

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Increment checkpoint requires a non-empty evidence list")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for raw_item in evidence:
        item = _object(raw_item, "Evidence item")
        evidence_id = _string(item, "id", "Evidence item")
        if evidence_id in evidence_by_id:
            raise ValueError(f"Duplicate evidence id: {evidence_id}")
        level = item.get("level")
        if level not in EVIDENCE_LEVELS:
            raise ValueError(f"Evidence {evidence_id} has unsupported level")
        _string(item, "description", f"Evidence {evidence_id}")
        mapped = _strings(item, "scenario_ids", f"Evidence {evidence_id}")
        if not set(mapped).issubset(scenario_ids):
            raise ValueError(f"Evidence {evidence_id} maps an unknown scenario")
        mapped_failures = _strings(
            item, "failure_mode_ids", f"Evidence {evidence_id}", allow_empty=True
        )
        if not set(mapped_failures).issubset(failure_mode_ids):
            raise ValueError(f"Evidence {evidence_id} maps an unknown failure mode")
        if item.get("result") not in {"passed", "failed", "blocked"}:
            raise ValueError(f"Evidence {evidence_id} has unsupported result")
        if not isinstance(item.get("real_entrypoint"), bool):
            raise ValueError(f"Evidence {evidence_id} requires boolean real_entrypoint")
        _string(item, "artifact", f"Evidence {evidence_id}")
        evidence_by_id[evidence_id] = item

    missing = [evidence_id for evidence_id in required_ids if evidence_id not in evidence_by_id]
    if missing:
        raise ValueError(f"Evidence gate references unknown evidence: {missing[0]}")
    for evidence_id in required_ids:
        item = evidence_by_id[evidence_id]
        if item["level"] in WEAK_LEVELS:
            raise ValueError(f"Weak evidence cannot satisfy the gate: {evidence_id}")
        if EVIDENCE_LEVELS.index(item["level"]) < EVIDENCE_LEVELS.index(required_level):
            raise ValueError(f"Evidence {evidence_id} is below required level {required_level}")
        if item["result"] != "passed" or not item["real_entrypoint"]:
            raise ValueError(f"Required evidence must pass through a real entrypoint: {evidence_id}")
    covered = {
        scenario_id
        for evidence_id in required_ids
        for scenario_id in evidence_by_id[evidence_id]["scenario_ids"]
    }
    uncovered = [scenario_id for scenario_id in scenario_ids if scenario_id not in covered]
    if uncovered:
        raise ValueError(f"Required evidence does not cover scenario: {uncovered[0]}")
    covered_failures = {
        failure_mode_id
        for evidence_id in required_ids
        for failure_mode_id in evidence_by_id[evidence_id]["failure_mode_ids"]
    }
    uncovered_failures = [item for item in failure_mode_ids if item not in covered_failures]
    if uncovered_failures:
        raise ValueError(f"Required evidence does not cover failure mode: {uncovered_failures[0]}")
    return record


def achieved_evidence_level(record: dict[str, Any]) -> str:
    required = set(record["evidence_gate"]["required_evidence_ids"])
    levels = [item["level"] for item in record["evidence"] if item["id"] in required]
    return min(levels, key=EVIDENCE_LEVELS.index)
