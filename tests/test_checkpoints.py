from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_pipeline.checkpoints import (
    DEPENDENCY_SURFACES,
    build_review_packet,
    validate_architecture_checkpoint,
    validate_decision,
    validate_scenario_checkpoint,
)
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity


def scenario(*, questions=None):
    return {
        "schema_version": "1.0",
        "artifact_id": "scenario-contract",
        "artifact_version": "3",
        "source_refs": ["prepared-request"],
        "dependency_inventory": [{
            "surface": surface,
            "applicability": "applicable" if surface in {"source_repositories", "runtime_entrypoints"} else "not_applicable",
            "owner": "repository owner" if surface == "source_repositories" else "verified task owner",
            "evidence_refs": [f"discovery:{surface}"],
            "change_impact": "inspect and update" if surface == "source_repositories" else "verified no change",
        } for surface in DEPENDENCY_SURFACES],
        "scenarios": [{
            "id": "SC-05", "actor": "owner", "trigger": "requirements are inspected",
            "expected_outcome": "material ambiguity blocks implementation",
            "acceptance": ["a concrete product question is emitted"],
            "failure_modes": ["policy is invented"],
        }],
        "production_branches": [{
            "id": "BR-CLI", "mode": "scenario checkpoint", "boundary": "installed CLI",
            "expected_behavior": "block material ambiguity", "applicability": "applicable",
            "failure_mode_ids": ["policy is invented"],
        }],
        "product_intent": {
            "applicability": "not_applicable", "intent_categories": [],
            "capability_matrix_applicability": "not_applicable",
        },
        "reversible_assumptions": [],
        "blocking_questions": questions or [],
    }


def architecture(scenario_digest="sha256:" + "a" * 64):
    return {
        "schema_version": "1.0", "artifact_id": "architecture-delta",
        "artifact_version": "3", "scenario_artifact_digest": scenario_digest,
        "production_path": ["dev-pipeline CLI", "checkpoint_apply", "LifecycleStore.append"],
        "owning_layer": "dev_pipeline.checkpoints validates contracts; LifecycleStore records outcomes",
        "reuse_plan": ["reuse the CLI and lifecycle event ledger"],
        "deletion_plan": ["remove no branch; no superseded checkpoint mechanism exists"],
        "forbidden_parallel_mechanism": "no reviewer scheduler or second checkpoint state store",
        "verification_path": ["installed dev-pipeline checkpoint command", "persisted lifecycle event"],
        "isolation_boundaries": [],
        "blocking_questions": [],
    }


def completed_store(path: Path) -> None:
    store = LifecycleStore(path)
    identity = RunIdentity.create("task-360")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(path),
    })
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "opaque"})
    store.append(identity, "run_completed", {"exit_code": 0})
    store.append(identity, "attempt_completed")


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "dev_pipeline.cli", *args], text=True,
        capture_output=True, check=False,
    )


def test_scenario_contract_requires_behavioral_acceptance_and_failure_modes():
    value = scenario()
    value["scenarios"][0]["acceptance"] = []
    with pytest.raises(ValueError, match="non-empty list"):
        validate_scenario_checkpoint(value)


def test_scenario_contract_rejects_omitted_cross_cutting_dependency_surface():
    value = scenario()
    value["dependency_inventory"] = [
        item for item in value["dependency_inventory"] if item["surface"] != "backup_restore_and_retention"
    ]
    with pytest.raises(ValueError, match="backup_restore_and_retention"):
        validate_scenario_checkpoint(value)


def test_not_applicable_dependency_still_requires_owner_evidence_and_impact():
    value = scenario()
    item = next(entry for entry in value["dependency_inventory"] if entry["applicability"] == "not_applicable")
    item["evidence_refs"] = []
    with pytest.raises(ValueError, match="non-empty list"):
        validate_scenario_checkpoint(value)


def test_architecture_gate_requires_owning_reuse_deletion_and_verification():
    for field in ("owning_layer", "reuse_plan", "deletion_plan", "verification_path"):
        value = architecture()
        value[field] = "" if field == "owning_layer" else []
        with pytest.raises(ValueError):
            validate_architecture_checkpoint(value)


def test_isolation_boundary_requires_allowed_denied_and_safe_negative_probe():
    value = architecture()
    value["isolation_boundaries"] = [{
        "name": "tenant filesystem",
        "production_boundary": "rootless worker container",
        "allowed_operations": ["write current tenant task directory"],
        "denied_operations": ["read another tenant marker"],
        "safe_negative_probes": [],
    }]
    with pytest.raises(ValueError, match="safe_negative_probes"):
        validate_architecture_checkpoint(value)

    value["isolation_boundaries"][0]["safe_negative_probes"] = [{
        "operation": "read a disposable marker outside the mount",
        "expected_denial": "path is absent",
        "safety_basis": "marker is created solely for the test and no production path is mutated",
        "evidence_path": "isolation-test.log",
    }]
    assert validate_architecture_checkpoint(value)["isolation_boundaries"]


def test_real_cli_blocks_material_semantics_before_checkpoint_completion(tmp_path):
    state = tmp_path / "state"
    completed_store(state)
    artifact = tmp_path / "scenario.json"
    artifact.write_text(json.dumps(scenario(questions=[{
        "question": "Should retries preserve compatibility with the old metadata?",
        "options": [
            {"label": "Preserve", "consequence": "Add a compatibility reader"},
            {"label": "Do not preserve", "consequence": "Keep the new store isolated"},
        ],
    }])))

    result = run_cli(
        "checkpoint", "scenario", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--next-step", "Architecture checkpoint",
    )

    assert result.returncode == 3
    event = json.loads(result.stdout)
    assert event["kind"] == "blocked_on_user_decision"
    assert event["payload"]["reason"] == "material_product_semantics"
    snapshot = json.loads((state / "state.json").read_text())
    assert snapshot["active_blocker"]["question"].startswith("Should retries")
    assert "scenario" not in snapshot.get("checkpoints", {})


def test_real_cli_accepts_complete_architecture_through_lifecycle_entrypoint(tmp_path):
    state = tmp_path / "state"
    completed_store(state)
    scenario_artifact = tmp_path / "scenario.json"
    scenario_artifact.write_text(json.dumps(scenario()))
    scenario_result = run_cli(
        "checkpoint", "scenario", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(scenario_artifact), "--next-step", "Architecture checkpoint",
    )
    assert scenario_result.returncode == 0
    scenario_event = json.loads(scenario_result.stdout)
    artifact = tmp_path / "architecture.json"
    artifact.write_text(json.dumps(architecture(scenario_event["payload"]["artifact_digest"])))

    result = run_cli(
        "checkpoint", "architecture", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--next-step", "Bounded architecture review",
    )

    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["kind"] == "checkpoint_completed"
    snapshot = json.loads((state / "state.json").read_text())
    assert snapshot["checkpoints"]["architecture"]["status"] == "completed"


def test_real_cli_blocks_empty_isolation_plan_when_discovery_marks_security_applicable(tmp_path):
    state = tmp_path / "state"
    completed_store(state)
    scenario_value = scenario()
    next(
        item for item in scenario_value["dependency_inventory"]
        if item["surface"] == "security_boundaries"
    )["applicability"] = "applicable"
    scenario_artifact = tmp_path / "scenario.json"
    scenario_artifact.write_text(json.dumps(scenario_value))
    scenario_result = run_cli(
        "checkpoint", "scenario", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(scenario_artifact), "--next-step", "Architecture checkpoint",
    )
    assert scenario_result.returncode == 0
    scenario_event = json.loads(scenario_result.stdout)
    artifact = tmp_path / "architecture.json"
    artifact.write_text(json.dumps(architecture(scenario_event["payload"]["artifact_digest"])))

    result = run_cli(
        "checkpoint", "architecture", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--next-step", "Review",
    )

    assert result.returncode == 2
    assert "marked security_boundaries applicable" in result.stderr


def test_architecture_refuses_missing_or_stale_scenario_link(tmp_path):
    state = tmp_path / "state"
    completed_store(state)
    artifact = tmp_path / "architecture.json"
    artifact.write_text(json.dumps(architecture()))
    result = run_cli(
        "checkpoint", "architecture", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--next-step", "Review",
    )
    assert result.returncode == 2
    assert "requires a completed scenario checkpoint" in result.stderr


def test_completing_other_checkpoint_does_not_clear_active_blocker(tmp_path):
    store = LifecycleStore(tmp_path)
    identity = RunIdentity.create("task-360")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(tmp_path),
    })
    store.append(identity, "blocked_on_user_decision", {
        "question": "Choose rollout policy", "artifact": "scenario.json", "checkpoint": "scenario",
    })
    store.append(identity, "checkpoint_completed", {
        "checkpoint": "architecture", "artifact": "architecture.json",
        "artifact_digest": "sha256:" + "b" * 64, "next_step": "Review",
    })
    snapshot = json.loads((tmp_path / "state.json").read_text())
    assert snapshot["active_blocker"]["checkpoint"] == "scenario"


def test_decision_envelope_is_bound_to_packet_artifact_and_vocabulary(tmp_path):
    artifact = tmp_path / "scenario.json"
    artifact.write_text(json.dumps(scenario()))
    packet = build_review_packet(
        review_type="scenario", artifact=artifact, artifact_version="3",
        question="Does this checkpoint stop on material ambiguity?",
        constraints=["Do not invent product policy"], instructions=["Codex-only public core"],
        evidence=["CLI blocker run"], exclusions=["Increment orchestration"],
    )
    decision = {
        "schema_version": "1.0", "review_type": "scenario",
        "artifact_digest": packet["artifact"]["digest"], "artifact_version": "3",
        "decision": "approved", "findings": [], "blocking_questions": [],
        "evidence_checked": ["CLI blocker run"],
    }
    assert validate_decision(decision, packet)["decision"] == "approved"
    decision["artifact_digest"] = "sha256:stale"
    with pytest.raises(ValueError, match="does not match"):
        validate_decision(decision, packet)


def test_approved_decision_cannot_hide_prose_findings(tmp_path):
    artifact = tmp_path / "architecture.json"
    artifact.write_text(json.dumps(architecture()))
    packet = build_review_packet(
        review_type="architecture", artifact=artifact, artifact_version="3", question="Approve?",
        constraints=["Reuse owning layer"], instructions=["Review concrete delta"],
        evidence=[], exclusions=["Bootstrap 4"],
    )
    decision = {
        "schema_version": "1.0", "review_type": "architecture",
        "artifact_digest": packet["artifact"]["digest"], "artifact_version": "3",
        "decision": "approved",
        "findings": [{"id": "F-1", "severity": "major", "summary": "Parallel store",
                      "evidence_ref": "diff"}],
        "blocking_questions": [], "evidence_checked": [],
    }
    with pytest.raises(ValueError, match="cannot contain findings"):
        validate_decision(decision, packet)


def test_real_cli_returns_nonzero_for_valid_rework_decision(tmp_path):
    artifact = tmp_path / "scenario.json"
    artifact.write_text(json.dumps(scenario()))
    packet = build_review_packet(
        review_type="scenario", artifact=artifact, artifact_version="3", question="Approve?",
        constraints=["Do not invent policy"], instructions=["Review the checkpoint"],
        evidence=[], exclusions=["Increment orchestration"],
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps({
        "schema_version": "1.0", "review_type": "scenario",
        "artifact_digest": packet["artifact"]["digest"], "artifact_version": "3",
        "decision": "rework_required",
        "findings": [{"id": "F-1", "severity": "major", "summary": "Missing failure mode",
                      "evidence_ref": "scenario.json"}],
        "blocking_questions": [], "evidence_checked": ["scenario.json"],
    }))
    result = run_cli(
        "review", "decision", "--packet", str(packet_path), "--decision", str(decision_path),
    )
    assert result.returncode == 4
    assert json.loads(result.stdout)["decision"] == "rework_required"
