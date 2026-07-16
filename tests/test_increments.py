from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_pipeline.checkpoints import artifact_digest, build_review_packet, canonical_digest
from dev_pipeline.evidence import scenario_branch_digest
from dev_pipeline.increments import validate_increment
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity


SCENARIO_DIGEST = "sha256:" + "a" * 64
ARCHITECTURE_DIGEST = "sha256:" + "b" * 64


def increment(
    sequence=1, kind="walking_skeleton", level="skeleton",
    scenario_digest=SCENARIO_DIGEST, architecture_digest=ARCHITECTURE_DIGEST,
):
    return {
        "schema_version": "1.0",
        "artifact_id": f"increment-{sequence}",
        "artifact_version": "1",
        "sequence": sequence,
        "increment_kind": kind,
        "scenario_artifact_digest": scenario_digest,
        "architecture_artifact_digest": architecture_digest,
        "scenario_ids": ["SC-07"],
        "failure_modes": [{
            "id": "FM-1",
            "description": "A test-only entrypoint is mistaken for the real pipeline",
        }],
        "observable_delta": "The installed CLI traverses the increment review gate.",
        "source_delta": ["dev_pipeline CLI and lifecycle"],
        "deletion_performed": ["No superseded increment path exists"],
        "temporary_seams": [],
        "retired_seams": [],
        "evidence_gate": {"required_level": level, "required_evidence_ids": ["E-1"]},
        "evidence": [{
            "id": "E-1", "level": level, "description": "Installed CLI evidence",
            "scenario_ids": ["SC-07"], "failure_mode_ids": ["FM-1"],
            "result": "passed", "real_entrypoint": True,
            "artifact": "events.jsonl",
        }],
    }


def prepared_state(
    path: Path, scenario_digest=SCENARIO_DIGEST, architecture_digest=ARCHITECTURE_DIGEST,
    scenario_artifact="scenario.json", architecture_artifact="architecture.json",
) -> None:
    store = LifecycleStore(path)
    identity = RunIdentity.create("task-360")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(path),
    })
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "opaque"})
    store.append(identity, "run_completed", {"exit_code": 0})
    store.append(identity, "attempt_completed")
    store.append(identity, "checkpoint_completed", {
        "checkpoint": "scenario", "artifact": str(scenario_artifact),
        "artifact_digest": scenario_digest, "next_step": "Architecture",
    })
    store.append(identity, "checkpoint_completed", {
        "checkpoint": "architecture", "artifact": str(architecture_artifact),
        "artifact_digest": architecture_digest, "next_step": "Walking skeleton",
    })


def run_cli(*args: str):
    return subprocess.run(
        [str(Path(sys.executable).with_name("dev-pipeline")), *args],
        text=True, capture_output=True, check=False,
    )


def closure_files(
    tmp_path: Path, state: Path,
    scenario_digest=SCENARIO_DIGEST, architecture_digest=ARCHITECTURE_DIGEST,
):
    contract = tmp_path / "task-contract.json"
    contract.write_text(json.dumps({"required_live_evidence": [{"id": "SC-07"}, {"id": "FM-1"}]}))
    result = tmp_path / "real-cli-result.json"
    result.write_text('{"kind":"increment_ready_for_review"}\n')
    evidence = tmp_path / "evidence.json"
    branch = {
        "id": "cli", "mode": "increment accept", "boundary": "installed CLI",
        "expected_behavior": "complete reviewed increment", "applicability": "applicable",
        "failure_mode_ids": ["FM-1"], "evidence_refs": ["E-1", "E-FM"],
    }
    branch["scenario_branch_digest"] = scenario_branch_digest(branch)
    product_usage = {
        "applicability": "not_applicable", "capability_matrix_applicability": "not_applicable",
        "intent_categories": [], "jobs": [], "capabilities": [],
    }
    product_usage["scenario_product_intent_digest"] = canonical_digest({
        key: product_usage[key] for key in (
            "applicability", "intent_categories", "capability_matrix_applicability"
        )
    })
    evidence.write_text(json.dumps({
        "schema_version": "1.0", "artifact_id": "evidence-1", "artifact_version": "1",
        "task_contract_digest": artifact_digest(contract),
        "scenario_artifact_digest": scenario_digest,
        "architecture_artifact_digest": architecture_digest,
        "required_subjects": [
            {"id": "SC-07", "kind": "scenario", "mandatory": True},
            {"id": "FM-1", "kind": "failure_mode", "mandatory": True},
        ],
        "production_branches": [branch], "product_usage": product_usage,
        "evidence": [{
            "id": "E-1", "subject_id": "SC-07", "status": "passed", "level": "skeleton",
            "command": ["dev-pipeline", "increment", "submit"],
            "observed_behavior": ["increment_ready_for_review was durably emitted"],
            "scope": "branch_specific", "branch_ids": ["cli"],
            "fixture": {"description": "prepared lifecycle state", "representative": True},
            "entrypoint": {"name": "dev-pipeline", "real": True, "production_boundary": True},
            "test_double": "none",
            "artifacts": [{"path": result.name, "digest": artifact_digest(result), "kind": "behavioral_trace"}],
        }, {
            "id": "E-FM", "subject_id": "FM-1", "status": "passed", "level": "skeleton",
            "command": ["dev-pipeline", "increment", "submit"],
            "observed_behavior": ["test-only entrypoint evidence was rejected"],
            "scope": "branch_specific", "branch_ids": ["cli"],
            "fixture": {"description": "prepared invalid entrypoint evidence", "representative": True},
            "entrypoint": {"name": "dev-pipeline", "real": True, "production_boundary": True},
            "test_double": "none",
            "artifacts": [{"path": result.name, "digest": artifact_digest(result), "kind": "behavioral_trace"}],
        }],
    }))
    store = LifecycleStore(state)
    identity, _ = store.load_attempt()
    store.append(identity, "checkpoint_completed", {
        "checkpoint": "evidence", "artifact": str(evidence),
        "artifact_digest": artifact_digest(evidence), "next_step": "Focused review",
    })
    return contract, evidence


def review_files(
    tmp_path: Path, artifact: Path, decision_name="approved",
    contract: Path | None = None, evidence_checkpoint: Path | None = None,
):
    packet = build_review_packet(
        review_type="increment", artifact=artifact, artifact_version="1",
        question="Does this observable increment satisfy its scenarios and evidence gate?",
        constraints=["Weak evidence cannot close acceptance"],
        instructions=["Review the concrete increment only"], evidence=["events.jsonl"],
        exclusions=["Bootstrap 5 conventions"],
        task_contract=contract, evidence_checkpoint=evidence_checkpoint,
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    approved = decision_name == "approved"
    blocked = decision_name == "blocked"
    decision = {
        "schema_version": "1.0", "review_type": "increment",
        "artifact_digest": packet["artifact"]["digest"], "artifact_version": "1",
        "decision": decision_name,
        "findings": [] if approved else [{
            "id": "F-1", "severity": "major", "summary": "Evidence gap",
            "evidence_ref": "events.jsonl",
        }],
        "blocking_questions": ["Which policy applies?"] if blocked else [],
        "evidence_checked": ["events.jsonl"],
    }
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision))
    return packet_path, decision_path


def test_walking_skeleton_rejects_structural_or_mock_only_gate_evidence():
    value = increment(level="structural")
    with pytest.raises(ValueError, match="requires evidence level skeleton"):
        validate_increment(value)
    value = increment()
    value["evidence"][0]["real_entrypoint"] = False
    with pytest.raises(ValueError, match="real entrypoint"):
        validate_increment(value)


def test_vertical_increment_requires_integrated_or_stronger_evidence():
    with pytest.raises(ValueError, match="requires evidence level integrated"):
        validate_increment(increment(sequence=2, kind="vertical_increment", level="skeleton"))


def test_temporary_seam_requires_allowed_boundary_and_replacement_milestone():
    value = increment()
    value["temporary_seams"] = [{
        "id": "SEAM-1", "name": "fake existing integration", "kind": "stub",
        "boundary": "existing_component", "reason": "convenient",
        "replacement_milestone": "increment 2", "replacement_increment": 2,
    }]
    with pytest.raises(ValueError, match="new_boundary or unavailable_external"):
        validate_increment(value)


def test_legacy_seam_artifact_is_rejected_without_inference_or_rewrite():
    value = increment()
    legacy_seam = {
        "name": "historical placeholder", "kind": "stub", "boundary": "new_boundary",
        "reason": "old schema", "replacement_milestone": "later",
    }
    value["temporary_seams"] = [legacy_seam.copy()]
    with pytest.raises(ValueError, match="requires non-empty id"):
        validate_increment(value)
    assert value["temporary_seams"] == [legacy_seam]


def test_historical_seam_free_artifact_remains_compatible_without_retired_seams():
    value = increment()
    value.pop("retired_seams")
    assert validate_increment(value) == value


def test_real_cli_requires_approved_review_before_increment_completion(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment.json"
    artifact.write_text(json.dumps(increment()))
    submit = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    )
    assert submit.returncode == 0, submit.stderr
    assert json.loads(submit.stdout)["kind"] == "increment_ready_for_review"
    packet, decision = review_files(tmp_path, artifact, "rework_required")
    contract = tmp_path / "unused-contract.json"
    checkpoint = tmp_path / "unused-evidence.json"
    contract.write_text("{}")
    checkpoint.write_text("{}")
    rejected = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Vertical increment 2", "--task-contract", str(contract),
        "--evidence-checkpoint", str(checkpoint),
    )
    assert rejected.returncode == 2
    assert "requires approved focused review" in rejected.stderr
    snapshot = json.loads((state / "state.json").read_text())
    assert snapshot["increments"]["1"]["status"] == "ready_for_review"


@pytest.mark.parametrize("decision_name", ["blocked", "rejected"])
def test_nonapproved_review_cannot_advance_increment_lifecycle(tmp_path, decision_name):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment.json"
    artifact.write_text(json.dumps(increment()))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    ).returncode == 0
    ledger_before = (state / "events.jsonl").read_bytes()
    snapshot_before = (state / "state.json").read_bytes()
    packet, decision = review_files(tmp_path, artifact, decision_name)
    unused_contract = tmp_path / "unused-contract.json"
    unused_evidence = tmp_path / "unused-evidence.json"
    unused_contract.write_text("{}")
    unused_evidence.write_text("{}")

    result = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "next", "--task-contract", str(unused_contract),
        "--evidence-checkpoint", str(unused_evidence),
    )

    assert result.returncode == 2
    assert "requires approved focused review" in result.stderr
    assert (state / "events.jsonl").read_bytes() == ledger_before
    assert (state / "state.json").read_bytes() == snapshot_before


def test_real_cli_accepts_reviewed_skeleton_then_allows_vertical_increment(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment-1.json"
    artifact.write_text(json.dumps(increment()))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    ).returncode == 0
    contract, evidence_checkpoint = closure_files(tmp_path, state)
    packet, decision = review_files(tmp_path, artifact, contract=contract, evidence_checkpoint=evidence_checkpoint)
    accepted = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Vertical increment 2", "--task-contract", str(contract),
        "--evidence-checkpoint", str(evidence_checkpoint),
    )
    assert accepted.returncode == 0, accepted.stderr
    event = json.loads(accepted.stdout)
    assert event["kind"] == "increment_completed"
    assert event["payload"]["evidence_level"] == "skeleton"

    reopened = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    )
    assert reopened.returncode == 2
    assert "cannot be resubmitted" in reopened.stderr

    second = tmp_path / "increment-2.json"
    second.write_text(json.dumps(increment(2, "vertical_increment", "integrated")))
    submitted = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(second),
    )
    assert submitted.returncode == 0, submitted.stderr


def test_deployed_increment_cannot_be_accepted_without_completed_deployment_checkpoint(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment-deployed.json"
    artifact.write_text(json.dumps(increment(level="deployed")))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    ).returncode == 0
    contract, evidence_checkpoint = closure_files(tmp_path, state)
    packet, decision = review_files(
        tmp_path, artifact, contract=contract, evidence_checkpoint=evidence_checkpoint,
    )
    accepted = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Complete", "--task-contract", str(contract),
        "--evidence-checkpoint", str(evidence_checkpoint),
    )
    assert accepted.returncode == 2
    assert "requires a deployment checkpoint" in accepted.stderr
    assert json.loads((state / "state.json").read_text())["increments"]["1"]["status"] == "ready_for_review"


def test_allowed_temporary_seam_must_be_removed_by_its_replacement_increment(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    first_value = increment()
    first_value["temporary_seams"] = [{
        "id": "SEAM-NEW-BOUNDARY", "name": "new delivery boundary placeholder",
        "kind": "temporary_adapter", "boundary": "new_boundary",
        "reason": "The downstream boundary is introduced in the next vertical increment",
        "replacement_milestone": "Vertical increment 2 integrates the real boundary",
        "replacement_increment": 2,
    }]
    first = tmp_path / "increment-1.json"
    first.write_text(json.dumps(first_value))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(first),
    ).returncode == 0
    contract, evidence_checkpoint = closure_files(tmp_path, state)
    packet, decision = review_files(
        tmp_path, first, contract=contract, evidence_checkpoint=evidence_checkpoint,
    )
    accepted = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(first), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Replace the temporary boundary", "--task-contract", str(contract),
        "--evidence-checkpoint", str(evidence_checkpoint),
    )
    assert accepted.returncode == 0, accepted.stderr

    second_value = increment(2, "vertical_increment", "integrated")
    second = tmp_path / "increment-2.json"
    second.write_text(json.dumps(second_value))
    overdue = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(second),
    )
    assert overdue.returncode == 2
    assert "reached its replacement milestone: SEAM-NEW-BOUNDARY" in overdue.stderr

    second_value["retired_seams"] = [{
        "id": "SEAM-NEW-BOUNDARY",
        "removal": "Removed the temporary adapter and traversed the integrated boundary",
        "evidence_id": "E-1",
    }]
    second.write_text(json.dumps(second_value))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(second),
    ).returncode == 0
    packet, decision = review_files(
        tmp_path, second, contract=contract, evidence_checkpoint=evidence_checkpoint,
    )
    accepted = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(second), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Continue without temporary seams", "--task-contract", str(contract),
        "--evidence-checkpoint", str(evidence_checkpoint),
    )
    assert accepted.returncode == 0, accepted.stderr
    snapshot = json.loads((state / "state.json").read_text())
    assert snapshot["increments"]["1"]["temporary_seams"][0]["id"] == "SEAM-NEW-BOUNDARY"
    assert snapshot["increments"]["2"]["retired_seams"][0]["id"] == "SEAM-NEW-BOUNDARY"

    third_value = increment(3, "vertical_increment", "integrated")
    third_value["temporary_seams"] = [{
        "id": "SEAM-NEW-BOUNDARY", "name": "reused identity",
        "kind": "temporary_adapter", "boundary": "new_boundary",
        "reason": "incorrectly recycling a retired seam identity",
        "replacement_milestone": "Vertical increment 4", "replacement_increment": 4,
    }]
    third = tmp_path / "increment-3.json"
    third.write_text(json.dumps(third_value))
    redeclared = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(third),
    )
    assert redeclared.returncode == 2
    assert "seam id was already declared: SEAM-NEW-BOUNDARY" in redeclared.stderr


def test_next_increment_is_blocked_while_prior_review_is_pending(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    first = tmp_path / "increment-1.json"
    first.write_text(json.dumps(increment()))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(first),
    ).returncode == 0
    second = tmp_path / "increment-2.json"
    second.write_text(json.dumps(increment(2, "vertical_increment", "integrated")))
    result = run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(second),
    )
    assert result.returncode == 2
    assert "approved review before advancing" in result.stderr


def test_approved_review_cannot_bypass_missing_closure_bindings(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment.json"
    artifact.write_text(json.dumps(increment()))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    ).returncode == 0
    contract, evidence_checkpoint = closure_files(tmp_path, state)
    packet, decision = review_files(tmp_path, artifact)
    result = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--task-contract", str(contract), "--evidence-checkpoint", str(evidence_checkpoint),
        "--next-step", "next",
    )
    assert result.returncode == 2
    assert "requires task-contract evidence closure bindings" in result.stderr


def test_approved_review_cannot_close_stale_evidence_binding(tmp_path):
    state = tmp_path / "state"
    prepared_state(state)
    artifact = tmp_path / "increment.json"
    artifact.write_text(json.dumps(increment()))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact),
    ).returncode == 0
    contract, evidence_checkpoint = closure_files(tmp_path, state)
    packet, decision = review_files(
        tmp_path, artifact, contract=contract, evidence_checkpoint=evidence_checkpoint,
    )
    evidence_checkpoint.write_text(evidence_checkpoint.read_text() + "\n")
    result = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(artifact), "--packet", str(packet), "--decision", str(decision),
        "--task-contract", str(contract), "--evidence-checkpoint", str(evidence_checkpoint),
        "--next-step", "next",
    )
    assert result.returncode == 2
    assert "evidence checkpoint binding is stale" in result.stderr
