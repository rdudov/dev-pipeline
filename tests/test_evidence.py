from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_pipeline.checkpoints import DEPENDENCY_SURFACES, artifact_digest, canonical_digest
from dev_pipeline.evidence import (
    CAPABILITY_CATEGORIES,
    scenario_branch_digest,
    validate_evidence_checkpoint,
)
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity


SCENARIO_DIGEST = "sha256:" + "a" * 64
ARCHITECTURE_DIGEST = "sha256:" + "b" * 64


def checkpoint(tmp_path: Path) -> tuple[dict, Path, Path]:
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"required_live_evidence": [{"id": "SC-1"}, {"id": "FM-1"}]}))
    result = tmp_path / "result.json"
    result.write_text('{"observed":"real behavior"}\n')
    branch = {
        "id": "cli-happy", "mode": "installed CLI", "boundary": "checkpoint evidence",
        "expected_behavior": "accept complete evidence", "applicability": "applicable",
        "failure_mode_ids": ["FM-1"], "evidence_refs": ["E-SC", "E-FM"],
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
    value = {
        "schema_version": "1.0", "artifact_id": "evidence", "artifact_version": "1",
        "task_contract_digest": artifact_digest(contract),
        "scenario_artifact_digest": SCENARIO_DIGEST,
        "architecture_artifact_digest": ARCHITECTURE_DIGEST,
        "required_subjects": [
            {"id": "SC-1", "kind": "scenario", "mandatory": True},
            {"id": "FM-1", "kind": "failure_mode", "mandatory": True},
        ],
        "production_branches": [branch], "product_usage": product_usage,
        "evidence": [
            evidence("E-SC", "SC-1", result), evidence("E-FM", "FM-1", result),
        ],
    }
    return value, contract, result


def evidence(evidence_id: str, subject_id: str, result: Path) -> dict:
    return {
        "id": evidence_id, "subject_id": subject_id, "status": "passed", "level": "integrated",
        "command": ["dev-pipeline", "checkpoint", "evidence"],
        "observed_behavior": [f"{subject_id} produced its expected branch result"],
        "scope": "branch_specific", "branch_ids": ["cli-happy"],
        "fixture": {"description": "representative task state", "representative": True},
        "entrypoint": {"name": "dev-pipeline", "real": True, "production_boundary": True},
        "test_double": "none",
        "artifacts": [{
            "path": result.name, "digest": artifact_digest(result), "kind": "behavioral_trace",
        }],
    }


def refresh_usage_digest(value: dict) -> None:
    usage = value["product_usage"]
    usage["scenario_product_intent_digest"] = canonical_digest({
        key: usage[key] for key in (
            "applicability", "intent_categories", "capability_matrix_applicability"
        )
    })


def prepared_state(path: Path) -> tuple[str, str]:
    store = LifecycleStore(path)
    identity = RunIdentity.create("task-1")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(path),
    })
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "opaque"})
    store.append(identity, "run_completed", {"exit_code": 0})
    store.append(identity, "attempt_completed")
    scenario_path = path.parent / "scenario.json"
    scenario_path.write_text(json.dumps({
        "schema_version": "1.0", "artifact_id": "scenario", "artifact_version": "1",
        "source_refs": ["request"],
        "dependency_inventory": [{
            "surface": surface, "applicability": "not_applicable", "owner": "task owner",
            "evidence_refs": [f"inventory:{surface}"], "change_impact": "no change",
        } for surface in DEPENDENCY_SURFACES],
        "scenarios": [{
            "id": "SC-1", "actor": "owner", "trigger": "evidence review",
            "expected_outcome": "evidence is bound", "acceptance": ["checkpoint completes"],
            "failure_modes": ["FM-1"],
        }],
        "production_branches": [{
            "id": "cli-happy", "mode": "installed CLI", "boundary": "checkpoint evidence",
            "expected_behavior": "accept complete evidence", "applicability": "applicable",
            "failure_mode_ids": ["FM-1"],
        }],
        "product_intent": {
            "applicability": "not_applicable", "intent_categories": [],
            "capability_matrix_applicability": "not_applicable",
        },
        "reversible_assumptions": [], "blocking_questions": [],
    }))
    architecture_path = path.parent / "architecture.json"
    architecture_path.write_text('{"architecture":"complete"}\n')
    scenario_digest = artifact_digest(scenario_path)
    architecture_digest = artifact_digest(architecture_path)
    for name, digest, artifact in (
        ("scenario", scenario_digest, scenario_path),
        ("architecture", architecture_digest, architecture_path),
    ):
        store.append(identity, "checkpoint_completed", {
            "checkpoint": name, "artifact": str(artifact), "artifact_digest": digest,
            "next_step": "next",
        })
    return scenario_digest, architecture_digest


def run_cli(*args: str):
    return subprocess.run(
        [str(Path(sys.executable).with_name("dev-pipeline")), *args],
        text=True, capture_output=True, check=False,
    )


def test_real_cli_accepts_complete_digest_bound_evidence_checkpoint(tmp_path):
    value, contract, _ = checkpoint(tmp_path)
    state = tmp_path / "state"
    value["scenario_artifact_digest"], value["architecture_artifact_digest"] = prepared_state(state)
    artifact = tmp_path / "evidence.json"
    artifact.write_text(json.dumps(value))
    result = run_cli(
        "checkpoint", "evidence", "--task-ref", "task-1", "--state-dir", str(state),
        "--input", str(artifact), "--task-contract", str(contract), "--next-step", "review",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["kind"] == "checkpoint_completed"


def test_checkpoint_rejects_incomplete_task_contract_coverage(tmp_path):
    value, contract, _ = checkpoint(tmp_path)
    value["required_subjects"].pop()
    value["evidence"].pop()
    value["production_branches"][0]["evidence_refs"].remove("E-FM")
    state = tmp_path / "state"
    value["scenario_artifact_digest"], value["architecture_artifact_digest"] = prepared_state(state)
    artifact = tmp_path / "evidence.json"
    artifact.write_text(json.dumps(value))
    result = run_cli(
        "checkpoint", "evidence", "--task-ref", "task-1", "--state-dir", str(state),
        "--input", str(artifact), "--task-contract", str(contract), "--next-step", "review",
    )
    assert result.returncode == 2
    assert "omits task-contract evidence: FM-1" in result.stderr


def test_real_cli_rejects_caller_selected_branch_inventory(tmp_path):
    value, contract, _ = checkpoint(tmp_path)
    value["production_branches"][0]["id"] = "different-branch"
    value["production_branches"][0]["scenario_branch_digest"] = scenario_branch_digest(
        value["production_branches"][0]
    )
    for item in value["evidence"]:
        item["branch_ids"] = ["different-branch"]
    state = tmp_path / "state"
    value["scenario_artifact_digest"], value["architecture_artifact_digest"] = prepared_state(state)
    artifact = tmp_path / "evidence.json"
    artifact.write_text(json.dumps(value))
    result = run_cli(
        "checkpoint", "evidence", "--task-ref", "task-1", "--state-dir", str(state),
        "--input", str(artifact), "--task-contract", str(contract), "--next-step", "review",
    )
    assert result.returncode == 2
    assert "branch inventory does not match scenario: missing cli-happy" in result.stderr


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda item: item.update(status="failed"), "not passed"),
        (lambda item: item.update(level="unit"), "weak or unsupported"),
        (lambda item: item["fixture"].update(representative=False), "representative fixture"),
        (lambda item: item["entrypoint"].update(real=False), "real production entrypoint"),
        (lambda item: item.update(test_double="mock"), "mock-only"),
        (lambda item: item.update(test_double="stub"), "stub-only"),
        (lambda item: item.update(test_double="fake_provider"), "fake_provider-only"),
        (lambda item: item.update(test_double="fake_model"), "fake_model-only"),
        (lambda item: item.update(test_double="harness"), "harness-only"),
        (lambda item: item.update(scope="aggregate"), "branch_specific, not aggregate-only"),
    ],
)
def test_mandatory_evidence_truthfulness_rejections(tmp_path, mutation, message):
    value, _, _ = checkpoint(tmp_path)
    mutation(value["evidence"][0])
    with pytest.raises(ValueError, match=message):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_evidence_artifact_must_stay_in_owning_artifact_root(tmp_path):
    value, _, result = checkpoint(tmp_path)
    value["evidence"][0]["artifacts"][0]["path"] = str(result.resolve())
    with pytest.raises(ValueError, match="relative to the owning artifact root"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)

    outside = tmp_path.parent / "outside-evidence.txt"
    outside.write_text("outside\n")
    value["evidence"][0]["artifacts"][0].update(
        path="../outside-evidence.txt", digest=artifact_digest(outside)
    )
    with pytest.raises(ValueError, match="escapes the owning artifact root"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_real_cli_rejects_evidence_artifact_in_target_repository(tmp_path):
    value, contract, result = checkpoint(tmp_path)
    target_repo = tmp_path / "target-repository"
    target_repo.mkdir()
    misplaced = target_repo / "task-artifacts" / "verification.md"
    misplaced.parent.mkdir()
    misplaced.write_text("misplaced evidence\n")
    value["evidence"][0]["artifacts"][0].update(
        path=str(misplaced), digest=artifact_digest(misplaced)
    )
    state = tmp_path / "state"
    value["scenario_artifact_digest"], value["architecture_artifact_digest"] = prepared_state(state)
    artifact = tmp_path / "evidence.json"
    artifact.write_text(json.dumps(value))
    outcome = run_cli(
        "checkpoint", "evidence", "--task-ref", "task-1", "--state-dir", str(state),
        "--input", str(artifact), "--task-contract", str(contract), "--next-step", "review",
    )
    assert outcome.returncode == 2
    assert "relative to the owning artifact root" in outcome.stderr
    assert result.is_file()


@pytest.mark.parametrize(
    "mutation,message",
    [
        (
            lambda item: item.update(
                level="structural",
                observed_behavior=["prompt includes the required behavioral acceptance text"],
            ),
            "weak or unsupported level",
        ),
        (
            lambda item: item.update(
                level="unit",
                observed_behavior=["parser recognizes every required evidence field"],
            ),
            "weak or unsupported level",
        ),
        (
            lambda item: item["entrypoint"].update(
                name="tests/check_evidence.py", real=False, production_boundary=False,
            ),
            "must use the real production entrypoint",
        ),
    ],
)
def test_real_cli_rejects_weak_or_test_only_acceptance_evidence(tmp_path, mutation, message):
    value, contract, _ = checkpoint(tmp_path)
    mutation(value["evidence"][0])
    state = tmp_path / "state"
    value["scenario_artifact_digest"], value["architecture_artifact_digest"] = prepared_state(state)
    artifact = tmp_path / "evidence.json"
    artifact.write_text(json.dumps(value))

    result = run_cli(
        "checkpoint", "evidence", "--task-ref", "task-1", "--state-dir", str(state),
        "--input", str(artifact), "--task-contract", str(contract), "--next-step", "review",
    )

    assert result.returncode == 2
    assert message in result.stderr


def test_stale_artifact_is_rejected(tmp_path):
    value, _, result = checkpoint(tmp_path)
    result.write_text("changed\n")
    with pytest.raises(ValueError, match="artifact is stale"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_duplicate_evidence_identity_is_rejected(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    value["evidence"][1]["id"] = value["evidence"][0]["id"]
    with pytest.raises(ValueError, match="Duplicate evidence id"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_security_boundary_requires_permitted_and_denied_branches(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    value["production_branches"][0].update(
        security_path="permitted", isolation_boundary="sandbox",
    )
    value["production_branches"][0]["scenario_branch_digest"] = scenario_branch_digest(
        value["production_branches"][0]
    )
    with pytest.raises(ValueError, match="both permitted and denied"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_security_boundary_cannot_reuse_positive_evidence_for_denial(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    permitted = value["production_branches"][0]
    permitted.update(security_path="permitted", isolation_boundary="sandbox")
    permitted["scenario_branch_digest"] = scenario_branch_digest(permitted)
    denied = copy.deepcopy(permitted)
    denied.update(
        id="cli-denied", security_path="denied",
        expected_behavior="deny harmless out-of-scope write", safety_basis="disposable marker only",
    )
    denied["scenario_branch_digest"] = scenario_branch_digest(denied)
    value["production_branches"].append(denied)
    for item in value["evidence"]:
        item["branch_ids"].append("cli-denied")
    with pytest.raises(ValueError, match="exactly one production branch"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_distinct_denied_evidence_requires_harmless_probe_contract(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    permitted = value["production_branches"][0]
    permitted.update(security_path="permitted", isolation_boundary="sandbox")
    permitted["scenario_branch_digest"] = scenario_branch_digest(permitted)
    denied = copy.deepcopy(permitted)
    denied.update(
        id="cli-denied", security_path="denied", evidence_refs=["E-DENIED"],
        expected_behavior="deny harmless out-of-scope write", safety_basis="disposable marker only",
    )
    denied["scenario_branch_digest"] = scenario_branch_digest(denied)
    value["production_branches"].append(denied)
    denied_result = tmp_path / "denied-result.json"
    denied_result.write_text('{"denied":true}\n')
    denied_evidence = evidence("E-DENIED", "FM-1", denied_result)
    denied_evidence["subject_id"] = "FM-2"
    value["required_subjects"].append({"id": "FM-2", "kind": "failure_mode", "mandatory": True})
    denied_evidence["branch_ids"] = ["cli-denied"]
    value["evidence"].append(denied_evidence)
    with pytest.raises(ValueError, match="negative_probe"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_applicable_capability_matrix_requires_every_generic_category(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    value["product_usage"].update(
        applicability="applicable", capability_matrix_applicability="applicable",
        intent_categories=["document"],
        jobs=[{
            "id": "JOB-1", "intended_outcome": "produce requested artifact",
            "representative_input": "non-trivial user data", "requested_deliverable": "artifact",
            "persistence": "survives continuation", "delivery": "returned to requester",
            "required_capability_ids": ["CAP-input"], "limits": [], "unsupported_cases": [],
            "evidence_refs": ["E-JOB"],
        }],
        capabilities=[{
            "id": "CAP-input", "category": "input", "status": "supported",
            "constraint_or_evidence": "real parser evidence", "evidence_refs": ["E-SC"],
        }],
    )
    refresh_usage_digest(value)
    with pytest.raises(ValueError, match="Capability matrix is incomplete"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_document_intent_cannot_opt_out_of_capability_matrix(tmp_path):
    value, _, _ = checkpoint(tmp_path)
    value["product_usage"]["intent_categories"] = ["document"]
    refresh_usage_digest(value)
    with pytest.raises(ValueError, match="requires an applicable capability matrix"):
        validate_evidence_checkpoint(value, artifact_root=tmp_path)


def test_complete_generic_capability_matrix_is_accepted(tmp_path):
    value, _, result = checkpoint(tmp_path)
    capabilities = [{
        "id": f"CAP-{category}", "category": category, "status": "supported",
        "constraint_or_evidence": f"evidence for {category}",
        "evidence_refs": [f"E-CAP-{category}"],
    } for category in sorted(CAPABILITY_CATEGORIES)]
    value["product_usage"].update(
        applicability="applicable", capability_matrix_applicability="applicable",
        intent_categories=["document"],
        jobs=[{
            "id": "JOB-1", "intended_outcome": "produce requested artifact",
            "representative_input": "non-trivial user data", "requested_deliverable": "artifact",
            "persistence": "survives continuation", "delivery": "returned to requester",
            "required_capability_ids": [item["id"] for item in capabilities],
            "limits": ["declared resource limit"], "unsupported_cases": ["declared unsupported case"],
            "evidence_refs": ["E-JOB"],
        }], capabilities=capabilities,
    )
    refresh_usage_digest(value)
    value["required_subjects"].append({
        "id": "JOB-1", "kind": "product_job", "mandatory": True,
    })
    value["evidence"].append(evidence("E-JOB", "JOB-1", result))
    value["production_branches"][0]["evidence_refs"].append("E-JOB")
    for capability in capabilities:
        value["required_subjects"].append({
            "id": capability["id"], "kind": "capability", "mandatory": True,
        })
        value["evidence"].append(evidence(
            capability["evidence_refs"][0], capability["id"], result,
        ))
        value["production_branches"][0]["evidence_refs"].append(
            capability["evidence_refs"][0]
        )
    assert validate_evidence_checkpoint(value, artifact_root=tmp_path) == value
