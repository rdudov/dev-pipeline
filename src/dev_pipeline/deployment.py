"""Reproducible infrastructure deployment checkpoint and deployed-acceptance gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checkpoints import (
    _digest,
    _object,
    _questions,
    _string,
    _strings,
    _version,
    artifact_digest,
    canonical_digest,
)


RESOURCE_KINDS = (
    "packages", "unix_identities", "containers_and_images", "services",
    "host_directories", "durable_roots", "credential_bindings", "network_policy",
    "schedulers", "backup_ownership",
)
UPDATE_KINDS = (
    "source_sync", "image_rebuild", "data_migration", "restart_or_reload", "no_op",
)
READINESS_KINDS = (
    "packages", "unix_identities", "images", "services", "host_directories",
    "credentials", "network", "schedulers", "backup",
)
ROLLBACK_KINDS = (
    "service", "image", "identity", "host_resources", "uninstall_data_preservation",
)
EVIDENCE_LEVELS = frozenset({"integrated", "live", "deployed"})
RESOURCE_OBLIGATIONS = {
    "packages": ({"no_op"}, {"packages"}, {"uninstall_data_preservation"}),
    "unix_identities": ({"no_op"}, {"unix_identities"}, {"identity"}),
    "containers_and_images": ({"image_rebuild"}, {"images"}, {"image"}),
    "services": ({"restart_or_reload"}, {"services"}, {"service"}),
    "host_directories": ({"source_sync"}, {"host_directories"}, {"host_resources"}),
    "durable_roots": ({"data_migration"}, {"backup"}, {"uninstall_data_preservation"}),
    "credential_bindings": ({"source_sync"}, {"credentials"}, {"host_resources"}),
    "network_policy": ({"source_sync"}, {"network"}, {"host_resources"}),
    "schedulers": ({"restart_or_reload"}, {"schedulers"}, {"service"}),
    "backup_ownership": ({"data_migration"}, {"backup"}, {"uninstall_data_preservation"}),
}


def _bound_file(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{label} path must be relative to the artifact root")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} path escapes the artifact root")
    return resolved


def deployment_impact_digest(value: Any) -> str:
    record = _object(value, "Increment deployment impacts")
    impacts = _complete_inventory(
        record, "deployment_impacts", "Increment deployment impact", RESOURCE_KINDS
    )
    return canonical_digest([
        {
            "kind": item["kind"], "applicability": item["applicability"],
            "owner": item["owner"], "rationale": item["rationale"],
            "evidence_refs": item["evidence_refs"],
        }
        for item in impacts
    ])


def _applicability_item(
    raw: Any, label: str, *, known_kind: set[str], seen: set[str]
) -> dict[str, Any]:
    item = _object(raw, label)
    kind = _string(item, "kind", label)
    if kind not in known_kind:
        raise ValueError(f"Unsupported {label.lower()} kind: {kind}")
    if kind in seen:
        raise ValueError(f"Duplicate {label.lower()} kind: {kind}")
    seen.add(kind)
    if item.get("applicability") not in {"applicable", "not_applicable"}:
        raise ValueError(f"{label} {kind} requires applicability")
    _string(item, "owner", f"{label} {kind}")
    _string(item, "rationale", f"{label} {kind}")
    _strings(item, "evidence_refs", f"{label} {kind}")
    return item


def _complete_inventory(
    record: dict[str, Any], field: str, label: str, kinds: tuple[str, ...]
) -> list[dict[str, Any]]:
    values = record.get(field)
    if not isinstance(values, list):
        raise ValueError(f"Deployment checkpoint requires a {field} list")
    seen: set[str] = set()
    result = [
        _applicability_item(raw, label, known_kind=set(kinds), seen=seen)
        for raw in values
    ]
    missing = set(kinds) - seen
    if missing:
        raise ValueError(f"{label} inventory is incomplete; missing: {sorted(missing)[0]}")
    return result


def _command(record: dict[str, Any], label: str) -> list[str]:
    return _strings(record, "command", label)


def validate_deployment_checkpoint(
    value: Any, *, artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate an applicability-complete, revision-bound deployment proof."""
    record = _object(value, "Deployment checkpoint")
    _version(record, "deployment checkpoint")
    _string(record, "artifact_id", "Deployment checkpoint")
    _string(record, "artifact_version", "Deployment checkpoint")
    _digest(record, "increment_artifact_digest", "Deployment checkpoint")
    _digest(record, "evidence_checkpoint_digest", "Deployment checkpoint")
    _digest(record, "scenario_artifact_digest", "Deployment checkpoint")
    _digest(record, "architecture_artifact_digest", "Deployment checkpoint")
    _digest(record, "increment_deployment_impacts_digest", "Deployment checkpoint")
    _digest(record, "source_revision", "Deployment checkpoint")
    source_artifacts = record.get("source_artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        raise ValueError("Deployment checkpoint requires source_artifacts")
    for raw in source_artifacts:
        item = _object(raw, "Deployment source artifact")
        path = _string(item, "path", "Deployment source artifact")
        digest = _digest(item, "digest", "Deployment source artifact")
        if artifact_root is not None:
            resolved = _bound_file(artifact_root, path, "Deployment source artifact")
            if not resolved.is_file() or artifact_digest(resolved) != digest:
                raise ValueError(f"Deployment source artifact is missing or stale: {path}")
    if canonical_digest(source_artifacts) != record["source_revision"]:
        raise ValueError("Deployment source revision does not match its source artifact manifest")

    resources = _complete_inventory(record, "resources", "Deployment resource", RESOURCE_KINDS)
    updates = _complete_inventory(record, "update_operations", "Deployment update", UPDATE_KINDS)
    readiness = _complete_inventory(
        record, "readiness_checks", "Deployment readiness check", READINESS_KINDS
    )
    rollback_targets = _complete_inventory(
        record, "rollback_targets", "Deployment rollback target", ROLLBACK_KINDS
    )

    for item in resources:
        if item["applicability"] == "applicable":
            tracked = _object(item.get("tracked_artifact"), f"Deployment resource {item['kind']} tracked artifact")
            path = _string(tracked, "path", f"Deployment resource {item['kind']} tracked artifact")
            digest = _digest(tracked, "digest", f"Deployment resource {item['kind']} tracked artifact")
            if artifact_root is not None:
                resolved = _bound_file(artifact_root, path, "Deployment tracked artifact")
                if not resolved.is_file() or artifact_digest(resolved) != digest:
                    raise ValueError(f"Deployment tracked artifact is missing or stale: {path}")
            _strings(item, "runtime_inventory", f"Deployment resource {item['kind']}")
            for field, known in (
                ("update_kinds", set(UPDATE_KINDS)),
                ("readiness_kinds", set(READINESS_KINDS)),
                ("rollback_kinds", set(ROLLBACK_KINDS)),
            ):
                mapped = _strings(item, field, f"Deployment resource {item['kind']}")
                unknown = set(mapped) - known
                if unknown:
                    raise ValueError(
                        f"Deployment resource {item['kind']} references unsupported {field}: {sorted(unknown)[0]}"
                    )
    for item in updates:
        if item["applicability"] == "applicable":
            _command(item, f"Deployment update {item['kind']}")
    for item in readiness:
        if item["applicability"] == "applicable":
            _strings(item, "permitted_command", f"Deployment readiness check {item['kind']}")
            _strings(item, "denied_command", f"Deployment readiness check {item['kind']}")
            for field in (
                "protected_asset", "production_boundary", "permitted_operation",
                "denied_operation", "safety_basis", "evidence_path",
            ):
                _string(item, field, f"Deployment readiness check {item['kind']}")
            for field in ("pre_mutation", "harmless", "disposable_fixture", "production_state_preserved"):
                if item.get(field) is not True:
                    raise ValueError(
                        f"Deployment readiness check {item['kind']} requires {field}=true"
                    )
            permitted = _string(item, "permitted_evidence_ref", f"Deployment readiness check {item['kind']}")
            denied = _string(item, "denied_evidence_ref", f"Deployment readiness check {item['kind']}")
            if permitted == denied or set(item["evidence_refs"]) != {permitted, denied}:
                raise ValueError(
                    f"Deployment readiness check {item['kind']} requires distinct permitted and denied evidence"
                )

    applicable = any(item["applicability"] == "applicable" for item in resources)
    if record.get("applicability") not in {"applicable", "not_applicable"}:
        raise ValueError("Deployment checkpoint requires applicability")
    if applicable != (record["applicability"] == "applicable"):
        raise ValueError("Deployment applicability must match the resource inventory")
    if applicable and not any(item["applicability"] == "applicable" for item in updates):
        raise ValueError("Applicable deployment requires an applicable update operation")
    if applicable and not any(item["applicability"] == "applicable" for item in readiness):
        raise ValueError("Applicable deployment requires an applicable readiness check")
    if applicable and not any(item["applicability"] == "applicable" for item in rollback_targets):
        raise ValueError("Applicable deployment requires an applicable rollback target")
    applicable_updates = {item["kind"] for item in updates if item["applicability"] == "applicable"}
    applicable_readiness = {item["kind"] for item in readiness if item["applicability"] == "applicable"}
    applicable_rollbacks = {
        item["kind"] for item in rollback_targets if item["applicability"] == "applicable"
    }
    for item in resources:
        if item["applicability"] != "applicable":
            continue
        for field, available in (
            ("update_kinds", applicable_updates),
            ("readiness_kinds", applicable_readiness),
            ("rollback_kinds", applicable_rollbacks),
        ):
            missing = set(item[field]) - available
            if missing:
                raise ValueError(
                    f"Deployment resource {item['kind']} lacks applicable {field} coverage: {sorted(missing)[0]}"
                )
        for field, required in zip(
            ("update_kinds", "readiness_kinds", "rollback_kinds"),
            RESOURCE_OBLIGATIONS[item["kind"]], strict=True,
        ):
            missing = required - set(item[field])
            if missing:
                raise ValueError(
                    f"Deployment resource {item['kind']} lacks required {field}: {sorted(missing)[0]}"
                )

    for item in rollback_targets:
        if item["applicability"] == "applicable":
            _command(item, f"Deployment rollback target {item['kind']}")
            if item.get("disposable_fixture") is not True:
                raise ValueError(
                    f"Deployment rollback target {item['kind']} requires disposable_fixture=true"
                )
            if item.get("production_state_preserved") is not True:
                raise ValueError(
                    f"Deployment rollback target {item['kind']} requires production_state_preserved=true"
                )

    for field, label in (
        ("clean_environment", "Clean environment proof"),
        ("drift_detection", "Drift detection proof"),
    ):
        proof = _object(record.get(field), label)
        if proof.get("applicability") not in {"applicable", "not_applicable"}:
            raise ValueError(f"{label} requires applicability")
        _string(proof, "rationale", label)
        _strings(proof, "evidence_refs", label)
        if applicable and proof["applicability"] != "applicable":
            raise ValueError(f"Applicable deployment requires {field}")
        if proof["applicability"] == "applicable":
            _command(proof, label)
            if field == "clean_environment":
                if proof.get("disposable_fixture") is not True:
                    raise ValueError(f"{label} requires disposable_fixture=true")
                if proof.get("production_state_preserved") is not True:
                    raise ValueError(f"{label} requires production_state_preserved=true")

    durable_roots = record.get("durable_roots")
    if not isinstance(durable_roots, list):
        raise ValueError("Deployment checkpoint requires a durable_roots list")
    ids: set[str] = set()
    for raw in durable_roots:
        root = _object(raw, "Durable root")
        root_id = _string(root, "id", "Durable root")
        if root_id in ids:
            raise ValueError(f"Duplicate durable root: {root_id}")
        ids.add(root_id)
        for field in ("path", "retention_owner", "backup_artifact", "restore_layout"):
            _string(root, field, f"Durable root {root_id}")
        _strings(root, "backup_command", f"Durable root {root_id}")
        _strings(root, "restore_command", f"Durable root {root_id}")
        _strings(root, "evidence_refs", f"Durable root {root_id}")
        backup_ref = _string(root, "backup_evidence_ref", f"Durable root {root_id}")
        restore_ref = _string(root, "restore_evidence_ref", f"Durable root {root_id}")
        if backup_ref == restore_ref or set(root["evidence_refs"]) != {backup_ref, restore_ref}:
            raise ValueError(f"Durable root {root_id} requires distinct backup and restore evidence")
        if root.get("integrity_verified") is not True or root.get("disposable_fixture") is not True:
            raise ValueError(
                f"Durable root {root_id} requires disposable backup/restore integrity evidence"
            )
    durable_applicable = next(
        item for item in resources if item["kind"] == "durable_roots"
    )["applicability"] == "applicable"
    if durable_applicable and not durable_roots:
        raise ValueError("Applicable durable_roots require backup/restore coverage")
    if not durable_applicable and durable_roots:
        raise ValueError("Durable root records require applicable durable_roots")

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Deployment checkpoint requires a non-empty evidence list")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for raw in evidence:
        item = _object(raw, "Deployment evidence")
        evidence_id = _string(item, "id", "Deployment evidence")
        if evidence_id in evidence_by_id:
            raise ValueError(f"Duplicate deployment evidence: {evidence_id}")
        if item.get("status") != "passed":
            raise ValueError(f"Deployment evidence {evidence_id} must be passed")
        if item.get("level") not in EVIDENCE_LEVELS:
            raise ValueError(f"Deployment evidence {evidence_id} requires integrated or stronger level")
        _command(item, f"Deployment evidence {evidence_id}")
        _string(item, "entrypoint", f"Deployment evidence {evidence_id}")
        _string(item, "gate_id", f"Deployment evidence {evidence_id}")
        _strings(item, "observed_behavior", f"Deployment evidence {evidence_id}")
        if item.get("environment") not in {"clean_disposable", "disposable", "production"}:
            raise ValueError(f"Deployment evidence {evidence_id} requires an environment classification")
        exit_code = item.get("exit_code")
        expected_exit_code = item.get("expected_exit_code")
        if (
            not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code < 0
            or not isinstance(expected_exit_code, int) or isinstance(expected_exit_code, bool)
            or expected_exit_code < 0 or exit_code != expected_exit_code
        ):
            raise ValueError(f"Deployment evidence {evidence_id} requires the expected exit code")
        if item.get("source_revision") != record["source_revision"]:
            raise ValueError(f"Deployment evidence {evidence_id} source revision does not match")
        if item.get("branch") not in {"permitted", "denied", "not_applicable"}:
            raise ValueError(f"Deployment evidence {evidence_id} requires a branch classification")
        if item.get("real_entrypoint") is not True:
            raise ValueError(f"Deployment evidence {evidence_id} requires a real entrypoint")
        artifacts = item.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(f"Deployment evidence {evidence_id} requires artifacts")
        for raw_artifact in artifacts:
            artifact = _object(raw_artifact, f"Deployment evidence {evidence_id} artifact")
            path = _string(artifact, "path", f"Deployment evidence {evidence_id} artifact")
            digest = _digest(artifact, "digest", f"Deployment evidence {evidence_id} artifact")
            if artifact_root is not None:
                resolved = _bound_file(artifact_root, path, "Deployment evidence artifact")
                if not resolved.is_file() or artifact_digest(resolved) != digest:
                    raise ValueError(f"Deployment evidence artifact is missing or stale: {path}")
                try:
                    execution = _object(
                        json.loads(resolved.read_text(encoding="utf-8")),
                        f"Deployment evidence {evidence_id} execution record",
                    )
                except (ValueError, OSError) as exc:
                    raise ValueError(
                        f"Deployment evidence {evidence_id} artifact must be an execution record"
                    ) from exc
                if (
                    execution.get("command") != item["command"]
                    or execution.get("exit_code") != item["exit_code"]
                ):
                    raise ValueError(
                        f"Deployment evidence {evidence_id} execution record does not match command/result"
                    )
                if execution.get("source_revision") != record["source_revision"]:
                    raise ValueError(
                        f"Deployment evidence {evidence_id} execution record source revision does not match"
                    )
                if execution.get("branch") != item["branch"]:
                    raise ValueError(
                        f"Deployment evidence {evidence_id} execution record branch does not match"
                    )
                for field in (
                    "gate_id", "environment", "entrypoint", "real_entrypoint",
                    "expected_exit_code", "observed_behavior",
                ):
                    if execution.get(field) != item[field]:
                        raise ValueError(
                            f"Deployment evidence {evidence_id} execution record {field} does not match"
                        )
        evidence_by_id[evidence_id] = item

    referenced: set[str] = set()
    for item in [*resources, *updates, *readiness, *rollback_targets]:
        referenced.update(item["evidence_refs"])
    for field in ("clean_environment", "drift_detection"):
        referenced.update(record[field]["evidence_refs"])
    for root in durable_roots:
        referenced.update(root["evidence_refs"])
    unknown = referenced - set(evidence_by_id)
    if unknown:
        raise ValueError(f"Deployment checkpoint references unknown evidence: {sorted(unknown)[0]}")
    unused = set(evidence_by_id) - referenced
    if unused:
        raise ValueError(f"Deployment evidence is not mapped to a gate: {sorted(unused)[0]}")
    for item in readiness:
        if item["applicability"] != "applicable":
            continue
        if evidence_by_id[item["permitted_evidence_ref"]]["branch"] != "permitted":
            raise ValueError(f"Readiness check {item['kind']} permitted evidence branch does not match")
        if evidence_by_id[item["denied_evidence_ref"]]["branch"] != "denied":
            raise ValueError(f"Readiness check {item['kind']} denied evidence branch does not match")
        if evidence_by_id[item["permitted_evidence_ref"]]["command"] != item["permitted_command"]:
            raise ValueError(f"Readiness check {item['kind']} permitted command evidence does not match")
        if evidence_by_id[item["denied_evidence_ref"]]["command"] != item["denied_command"]:
            raise ValueError(f"Readiness check {item['kind']} denied command evidence does not match")
        if evidence_by_id[item["denied_evidence_ref"]]["exit_code"] == 0:
            raise ValueError(f"Readiness check {item['kind']} denied branch must prove refusal")
    all_gates: list[tuple[str, dict[str, Any]]] = []
    for prefix, values in (
        ("resource", resources), ("update", updates), ("readiness", readiness),
        ("rollback", rollback_targets),
    ):
        all_gates.extend((f"{prefix}:{item['kind']}", item) for item in values)
    for field in ("clean_environment", "drift_detection"):
        all_gates.append((field, record[field]))
    for root in durable_roots:
        all_gates.append((f"durable_root:{root['id']}", root))
    for gate_id, gate in all_gates:
        for ref in gate["evidence_refs"]:
            if evidence_by_id[ref]["gate_id"] != gate_id:
                raise ValueError(f"Deployment gate {gate_id} has non-specific evidence")
            if gate.get("applicability", "applicable") == "applicable" and evidence_by_id[ref]["level"] != "deployed":
                raise ValueError(f"Applicable deployment gate {gate_id} requires deployed evidence")
            expected_branch = (
                "not_applicable"
                if gate.get("applicability") == "not_applicable"
                else None
            )
            if expected_branch and evidence_by_id[ref]["branch"] != expected_branch:
                raise ValueError(f"Deployment gate {gate_id} requires not_applicable evidence")
    for ref in record["clean_environment"]["evidence_refs"]:
        if record["clean_environment"]["applicability"] == "applicable" and evidence_by_id[ref]["environment"] != "clean_disposable":
            raise ValueError("Clean environment proof requires clean_disposable execution evidence")
    command_gates = [
        item for item in [*updates, *rollback_targets]
        if item["applicability"] == "applicable"
    ] + [
        record[field] for field in ("clean_environment", "drift_detection")
        if record[field]["applicability"] == "applicable"
    ]
    for gate in command_gates:
        if not any(evidence_by_id[ref]["command"] == gate["command"] for ref in gate["evidence_refs"]):
            raise ValueError("Deployment gate command is not matched by its execution evidence")
    for root in durable_roots:
        backup = evidence_by_id[root["backup_evidence_ref"]]
        restore = evidence_by_id[root["restore_evidence_ref"]]
        if backup["command"] != root["backup_command"]:
            raise ValueError(f"Durable root {root['id']} backup command evidence does not match")
        if restore["command"] != root["restore_command"]:
            raise ValueError(f"Durable root {root['id']} restore command evidence does not match")

    _questions(record, "Deployment checkpoint")
    return record
