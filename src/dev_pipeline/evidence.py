"""Task-contract evidence checkpoints and closure truthfulness gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .checkpoints import (
    SCHEMA_VERSION,
    _digest,
    _object,
    _string,
    _strings,
    _version,
    artifact_digest,
    canonical_digest,
)
from .increments import EVIDENCE_LEVELS, WEAK_LEVELS


SUBJECT_KINDS = frozenset(
    {"scenario", "failure_mode", "production_branch", "product_job", "capability"}
)
EVIDENCE_STATUSES = frozenset({"passed", "failed", "blocked", "missing", "stale"})
DOUBLE_KINDS = frozenset({"none", "mock", "stub", "fake_provider", "fake_model", "harness"})
CAPABILITY_CATEGORIES = frozenset(
    {
        "input", "processing_environment", "dependency_policy", "output",
        "multi_artifact_delivery", "validation_completeness", "safety",
    }
)
PRODUCT_INTENTS = frozenset({"code", "file", "data", "document", "media", "service", "infrastructure"})
MATRIX_TRIGGER_INTENTS = frozenset({"file", "data", "document", "media"})
ARTIFACT_KINDS = frozenset({"behavioral_trace", "runtime_output", "validated_deliverable"})


def _bound_evidence_artifact(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError("Evidence artifact path must be relative to the owning artifact root")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("Evidence artifact path escapes the owning artifact root")
    return resolved


def scenario_branch_digest(branch: dict[str, Any]) -> str:
    contract = {
        key: branch[key] for key in (
            "id", "mode", "boundary", "expected_behavior", "applicability",
            "failure_mode_ids",
        )
    }
    security_path = branch.get("security_path", "not_applicable")
    contract["security_path"] = security_path
    if security_path != "not_applicable":
        contract["isolation_boundary"] = branch["isolation_boundary"]
    if security_path == "denied":
        contract["safety_basis"] = branch["safety_basis"]
    return canonical_digest(contract)


def validate_evidence_checkpoint(
    value: Any, *, artifact_root: Path | None = None,
    required_branches: dict[str, str] | None = None,
    required_product_intent_digest: str | None = None,
) -> dict[str, Any]:
    record = _object(value, "Evidence checkpoint")
    _version(record, "evidence checkpoint")
    _string(record, "artifact_id", "Evidence checkpoint")
    _string(record, "artifact_version", "Evidence checkpoint")
    _digest(record, "task_contract_digest", "Evidence checkpoint")
    _digest(record, "scenario_artifact_digest", "Evidence checkpoint")
    _digest(record, "architecture_artifact_digest", "Evidence checkpoint")

    subjects = record.get("required_subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("Evidence checkpoint requires non-empty required_subjects")
    subject_ids: set[str] = set()
    subject_kinds: dict[str, str] = {}
    for raw in subjects:
        item = _object(raw, "Required evidence subject")
        subject_id = _string(item, "id", "Required evidence subject")
        if subject_id in subject_ids:
            raise ValueError(f"Duplicate required evidence subject: {subject_id}")
        subject_ids.add(subject_id)
        if item.get("kind") not in SUBJECT_KINDS:
            raise ValueError(f"Required subject {subject_id} has unsupported kind")
        subject_kinds[subject_id] = item["kind"]
        if item.get("mandatory") is not True:
            raise ValueError(f"Required subject {subject_id} must be explicitly mandatory")

    branches = record.get("production_branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError("Evidence checkpoint requires a non-empty production_branches inventory")
    branch_ids: set[str] = set()
    isolation_paths: dict[str, set[str]] = {}
    for raw in branches:
        item = _object(raw, "Production branch")
        branch_id = _string(item, "id", "Production branch")
        if branch_id in branch_ids:
            raise ValueError(f"Duplicate production branch: {branch_id}")
        branch_ids.add(branch_id)
        for field in ("mode", "boundary", "expected_behavior"):
            _string(item, field, f"Production branch {branch_id}")
        if item.get("applicability") not in {"applicable", "not_applicable"}:
            raise ValueError(f"Production branch {branch_id} requires applicability")
        refs = _strings(
            item, "evidence_refs", f"Production branch {branch_id}",
            allow_empty=item["applicability"] == "not_applicable",
        )
        _strings(item, "failure_mode_ids", f"Production branch {branch_id}", allow_empty=True)
        path_kind = item.get("security_path", "not_applicable")
        if path_kind not in {"not_applicable", "permitted", "denied"}:
            raise ValueError(f"Production branch {branch_id} has unsupported security_path")
        if path_kind != "not_applicable":
            if item["applicability"] != "applicable":
                raise ValueError(f"Security branch {branch_id} must be applicable")
            boundary_id = _string(item, "isolation_boundary", f"Production branch {branch_id}")
            isolation_paths.setdefault(boundary_id, set()).add(path_kind)
            if path_kind == "denied":
                _string(item, "safety_basis", f"Production branch {branch_id}")
        if item.get("scenario_branch_digest") != scenario_branch_digest(item):
            raise ValueError(f"Production branch {branch_id} does not match its scenario branch digest")
    if required_branches is not None and branch_ids != set(required_branches):
        missing = set(required_branches) - branch_ids
        extra = branch_ids - set(required_branches)
        detail = f"missing {sorted(missing)[0]}" if missing else f"unknown {sorted(extra)[0]}"
        raise ValueError(f"Evidence production branch inventory does not match scenario: {detail}")
    if required_branches is not None:
        for branch in branches:
            if branch["scenario_branch_digest"] != required_branches[branch["id"]]:
                raise ValueError(f"Evidence production branch changed scenario-owned behavior: {branch['id']}")

    usage = _object(record.get("product_usage"), "Product usage")
    if usage.get("applicability") not in {"applicable", "not_applicable"}:
        raise ValueError("Product usage requires applicability")
    intents = _strings(usage, "intent_categories", "Product usage", allow_empty=True)
    unknown_intents = set(intents) - PRODUCT_INTENTS
    if unknown_intents:
        raise ValueError(f"Product usage has unsupported intent: {sorted(unknown_intents)[0]}")
    intent_contract = {
        "applicability": usage["applicability"],
        "intent_categories": intents,
        "capability_matrix_applicability": usage.get("capability_matrix_applicability"),
    }
    _digest(usage, "scenario_product_intent_digest", "Product usage")
    if usage["scenario_product_intent_digest"] != canonical_digest(intent_contract):
        raise ValueError("Product usage does not match its scenario product-intent digest")
    if required_product_intent_digest is not None and usage["scenario_product_intent_digest"] != required_product_intent_digest:
        raise ValueError("Product usage changed scenario-owned intent applicability")
    jobs = usage.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Product usage requires a jobs list")
    if usage["applicability"] == "applicable" and not jobs:
        raise ValueError("Applicable product usage requires representative jobs")
    for raw in jobs:
        item = _object(raw, "Product job")
        job_id = _string(item, "id", "Product job")
        for field in ("intended_outcome", "representative_input", "requested_deliverable", "persistence", "delivery"):
            _string(item, field, f"Product job {job_id}")
        _strings(item, "required_capability_ids", f"Product job {job_id}")
        _strings(item, "limits", f"Product job {job_id}", allow_empty=True)
        _strings(item, "unsupported_cases", f"Product job {job_id}", allow_empty=True)
        _strings(item, "evidence_refs", f"Product job {job_id}")

    capabilities = usage.get("capabilities")
    if not isinstance(capabilities, list):
        raise ValueError("Product usage requires a capabilities list")
    if usage["applicability"] == "applicable" and not capabilities:
        raise ValueError("Applicable product usage requires a capability matrix")
    capability_ids: set[str] = set()
    capability_categories: set[str] = set()
    for raw in capabilities:
        item = _object(raw, "Capability")
        capability_id = _string(item, "id", "Capability")
        if capability_id in capability_ids:
            raise ValueError(f"Duplicate capability: {capability_id}")
        capability_ids.add(capability_id)
        if item.get("category") not in CAPABILITY_CATEGORIES:
            raise ValueError(f"Capability {capability_id} has unsupported category")
        capability_categories.add(item["category"])
        if item.get("status") not in {"supported", "constrained", "blocked", "not_applicable"}:
            raise ValueError(f"Capability {capability_id} has unsupported status")
        _string(item, "constraint_or_evidence", f"Capability {capability_id}")
        _strings(item, "evidence_refs", f"Capability {capability_id}", allow_empty=True)
    for job in jobs:
        unknown = set(job["required_capability_ids"]) - capability_ids
        if unknown:
            raise ValueError(f"Product job {job['id']} references unknown capability: {sorted(unknown)[0]}")
    unresolved = [item["id"] for item in capabilities if item["status"] == "blocked"]
    if unresolved:
        raise ValueError(f"Required capability is blocked: {unresolved[0]}")
    matrix_applicability = usage.get("capability_matrix_applicability")
    if matrix_applicability not in {"applicable", "not_applicable"}:
        raise ValueError("Product usage requires capability_matrix_applicability")
    if set(intents) & MATRIX_TRIGGER_INTENTS and matrix_applicability != "applicable":
        raise ValueError("File/data/document/media intent requires an applicable capability matrix")
    if matrix_applicability == "applicable":
        missing_categories = CAPABILITY_CATEGORIES - capability_categories
        if missing_categories:
            raise ValueError(
                f"Capability matrix is incomplete; missing: {sorted(missing_categories)[0]}"
            )

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Evidence checkpoint requires a non-empty evidence list")
    covered: set[str] = set()
    seen_evidence_ids: set[str] = set()
    for raw in evidence:
        item = _object(raw, "Evidence record")
        evidence_id = _string(item, "id", "Evidence record")
        if evidence_id in seen_evidence_ids:
            raise ValueError(f"Duplicate evidence id: {evidence_id}")
        seen_evidence_ids.add(evidence_id)
        subject_id = _string(item, "subject_id", f"Evidence {evidence_id}")
        if subject_id not in subject_ids:
            raise ValueError(f"Evidence {evidence_id} maps unknown subject: {subject_id}")
        if subject_id in covered:
            raise ValueError(f"Required subject has aggregate or duplicate evidence: {subject_id}")
        covered.add(subject_id)
        if item.get("status") not in EVIDENCE_STATUSES:
            raise ValueError(f"Evidence {evidence_id} has unsupported status")
        if item["status"] != "passed":
            raise ValueError(f"Mandatory evidence is not passed: {subject_id}")
        level = item.get("level")
        if level not in EVIDENCE_LEVELS or level in WEAK_LEVELS:
            raise ValueError(f"Evidence {evidence_id} has weak or unsupported level")
        command = _strings(item, "command", f"Evidence {evidence_id}")
        if len(command) == 1 and command[0].strip().isdigit():
            raise ValueError(f"Evidence {evidence_id} cannot be an aggregate count")
        _strings(item, "observed_behavior", f"Evidence {evidence_id}")
        if item.get("scope") != "branch_specific":
            raise ValueError(f"Evidence {evidence_id} must be branch_specific, not aggregate-only")
        mapped_branches = _strings(item, "branch_ids", f"Evidence {evidence_id}")
        if len(mapped_branches) != 1:
            raise ValueError(f"Evidence {evidence_id} must bind exactly one production branch")
        if not set(mapped_branches).issubset(branch_ids):
            raise ValueError(f"Evidence {evidence_id} maps an unknown production branch")
        fixture = _object(item.get("fixture"), f"Evidence {evidence_id} fixture")
        _string(fixture, "description", f"Evidence {evidence_id} fixture")
        if fixture.get("representative") is not True:
            raise ValueError(f"Evidence {evidence_id} requires a representative fixture")
        entrypoint = _object(item.get("entrypoint"), f"Evidence {evidence_id} entrypoint")
        _string(entrypoint, "name", f"Evidence {evidence_id} entrypoint")
        if entrypoint.get("real") is not True or entrypoint.get("production_boundary") is not True:
            raise ValueError(f"Evidence {evidence_id} must use the real production entrypoint")
        double_kind = item.get("test_double")
        if double_kind not in DOUBLE_KINDS:
            raise ValueError(f"Evidence {evidence_id} has unsupported test_double")
        if double_kind != "none":
            raise ValueError(f"Mandatory production evidence cannot be {double_kind}-only: {evidence_id}")
        refs = item.get("artifacts")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"Evidence {evidence_id} requires durable artifacts")
        for raw_ref in refs:
            ref = _object(raw_ref, f"Evidence {evidence_id} artifact")
            path_text = _string(ref, "path", f"Evidence {evidence_id} artifact")
            expected = _digest(ref, "digest", f"Evidence {evidence_id} artifact")
            if ref.get("kind") not in ARTIFACT_KINDS:
                raise ValueError(f"Evidence {evidence_id} artifact must contain branch behavior")
            if artifact_root is not None:
                path = _bound_evidence_artifact(artifact_root, path_text)
                if not path.is_file():
                    raise ValueError(f"Evidence artifact does not exist: {path}")
                if artifact_digest(path) != expected:
                    raise ValueError(f"Evidence artifact is stale: {path}")
    missing = subject_ids - covered
    if missing:
        raise ValueError(f"Required evidence subject is uncovered: {sorted(missing)[0]}")
    evidence_ids = {item["id"] for item in evidence}
    evidence_by_id = {item["id"]: item for item in evidence}
    artifact_owners: dict[tuple[str, str], str] = {}
    for item in evidence:
        branch_id = item["branch_ids"][0]
        for ref in item["artifacts"]:
            key = (ref["path"], ref["digest"])
            prior = artifact_owners.setdefault(key, branch_id)
            if prior != branch_id:
                raise ValueError("One behavioral artifact cannot close multiple production branches")
    for branch in branches:
        if branch["applicability"] == "applicable":
            unknown_refs = set(branch["evidence_refs"]) - evidence_ids
            if unknown_refs:
                raise ValueError(
                    f"Production branch {branch['id']} references unknown evidence: {sorted(unknown_refs)[0]}"
                )
            for evidence_id in branch["evidence_refs"]:
                if branch["id"] not in evidence_by_id[evidence_id]["branch_ids"]:
                    raise ValueError(
                        f"Production branch {branch['id']} is not reciprocally mapped by evidence {evidence_id}"
                    )
            mapped_ids = {
                evidence_id for evidence_id, item in evidence_by_id.items()
                if item["branch_ids"] == [branch["id"]]
            }
            if set(branch["evidence_refs"]) != mapped_ids:
                raise ValueError(f"Production branch {branch['id']} evidence mapping is incomplete")
    for boundary_id, paths in isolation_paths.items():
        if paths != {"permitted", "denied"}:
            raise ValueError(
                f"Isolation boundary {boundary_id} requires both permitted and denied evidence branches"
            )
        boundary_branches = [
            branch for branch in branches if branch.get("isolation_boundary") == boundary_id
        ]
        permitted_refs = {
            ref for branch in boundary_branches if branch.get("security_path") == "permitted"
            for ref in branch["evidence_refs"]
        }
        denied_refs = {
            ref for branch in boundary_branches if branch.get("security_path") == "denied"
            for ref in branch["evidence_refs"]
        }
        if permitted_refs & denied_refs:
            raise ValueError(f"Isolation boundary {boundary_id} requires distinct denied evidence")
        for evidence_id in denied_refs:
            negative = _object(
                evidence_by_id[evidence_id].get("negative_probe"),
                f"Denied evidence {evidence_id} negative_probe",
            )
            _string(negative, "safety_basis", f"Denied evidence {evidence_id}")
            for field in ("harmless", "disposable_fixture", "production_state_preserved"):
                if negative.get(field) is not True:
                    raise ValueError(f"Denied evidence {evidence_id} requires {field}=true")
    for capability in capabilities:
        refs = capability["evidence_refs"]
        if subject_kinds.get(capability["id"]) != "capability":
            raise ValueError(f"Capability is not a mandatory evidence subject: {capability['id']}")
        if not refs:
            raise ValueError(f"Capability requires bound applicability/evidence: {capability['id']}")
        unknown_refs = set(refs) - evidence_ids
        if unknown_refs:
            raise ValueError(
                f"Capability {capability['id']} references unknown evidence: {sorted(unknown_refs)[0]}"
            )
        for evidence_id in refs:
            if evidence_by_id[evidence_id]["subject_id"] != capability["id"]:
                raise ValueError(
                    f"Capability {capability['id']} is not reciprocally mapped by evidence {evidence_id}"
                )
    for job in jobs:
        if subject_kinds.get(job["id"]) != "product_job":
            raise ValueError(f"Product job is not a mandatory evidence subject: {job['id']}")
        unknown_refs = set(job["evidence_refs"]) - evidence_ids
        if unknown_refs:
            raise ValueError(
                f"Product job {job['id']} references unknown evidence: {sorted(unknown_refs)[0]}"
            )
        for evidence_id in job["evidence_refs"]:
            if evidence_by_id[evidence_id]["subject_id"] != job["id"]:
                raise ValueError(
                    f"Product job {job['id']} is not reciprocally mapped by evidence {evidence_id}"
                )
    return record
