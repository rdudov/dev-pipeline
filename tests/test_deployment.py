from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_pipeline.checkpoints import artifact_digest, canonical_digest
from dev_pipeline.deployment import (
    READINESS_KINDS,
    RESOURCE_KINDS,
    ROLLBACK_KINDS,
    UPDATE_KINDS,
    deployment_impact_digest,
    validate_deployment_checkpoint,
)
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity
from test_increments import closure_files, increment, prepared_state, review_files, run_cli


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def inventory(kinds, applicable=()):
    return [
        {
            "kind": kind,
            "applicability": "applicable" if kind in applicable else "not_applicable",
            "owner": "deployment owner",
            "rationale": "covered by the deployment profile",
            "evidence_refs": ["E-APPLICABILITY"],
        }
        for kind in kinds
    ]


def deployment(tmp_path: Path, *, applicable: bool = True):
    script = tmp_path / "bootstrap.sh"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--denied\" ]; then exit 23; fi\n"
        "[ \"$1\" = \"--permitted\" ] || exit 2\n"
    )
    script.chmod(script.stat().st_mode | 0o111)
    command = [str(script), "--permitted"]
    denied_command = [str(script), "--denied"]
    source_artifacts = [{"path": script.name, "digest": artifact_digest(script)}]
    revision = canonical_digest(source_artifacts)
    evidence_records = []

    def add_evidence(evidence_id, gate_id, branch="permitted", branch_command=None, environment="disposable"):
        branch_command = branch_command or command
        result = subprocess.run(branch_command, text=True, capture_output=True, check=False)
        trace = tmp_path / f"{evidence_id.lower()}.json"
        evidence_record = {
            "id": evidence_id, "status": "passed",
            "level": "deployed" if applicable else "integrated",
            "command": branch_command, "entrypoint": "tracked deployment bootstrap",
            "real_entrypoint": True, "exit_code": result.returncode,
            "expected_exit_code": result.returncode, "source_revision": revision,
            "branch": branch, "gate_id": gate_id, "environment": environment,
            "observed_behavior": [f"{gate_id} {branch} branch matched its expected result"],
        }
        trace.write_text(json.dumps({
            key: evidence_record[key] for key in (
                "command", "exit_code", "source_revision", "branch", "gate_id", "environment",
                "entrypoint", "real_entrypoint", "expected_exit_code", "observed_behavior",
            )
        }) + "\n")
        evidence_record["artifacts"] = [{"path": trace.name, "digest": artifact_digest(trace)}]
        evidence_records.append(evidence_record)

    resources = inventory(RESOURCE_KINDS, {"packages"} if applicable else set())
    if applicable:
        add_evidence("E-RESOURCE", "resource:packages")
        add_evidence("E-UPDATE", "update:no_op")
        add_evidence("E-READY-PERMIT", "readiness:packages")
        add_evidence("E-READY-DENY", "readiness:packages", "denied", denied_command)
        add_evidence("E-ROLLBACK", "rollback:uninstall_data_preservation")
        add_evidence("E-CLEAN", "clean_environment", environment="clean_disposable")
        add_evidence("E-DRIFT", "drift_detection")
        resources[0].update({
            "tracked_artifact": {"path": script.name, "digest": artifact_digest(script)},
            "runtime_inventory": ["package:podman"],
            "update_kinds": ["no_op"],
            "readiness_kinds": ["packages"],
            "rollback_kinds": ["uninstall_data_preservation"],
            "evidence_refs": ["E-RESOURCE"],
        })
    updates = inventory(UPDATE_KINDS, {"no_op"} if applicable else set())
    readiness = inventory(READINESS_KINDS, {"packages"} if applicable else set())
    rollback = inventory(ROLLBACK_KINDS, {"uninstall_data_preservation"} if applicable else set())
    if applicable:
        updates[-1].update({"command": command, "evidence_refs": ["E-UPDATE"]})
        readiness[0].update({
            "permitted_command": command,
            "denied_command": denied_command,
            "protected_asset": "disposable package root",
            "production_boundary": "disposable clean environment",
            "permitted_operation": "read disposable package metadata",
            "denied_operation": "mutate host packages when readiness fails",
            "safety_basis": "fixture has no production mounts",
            "evidence_path": "e-ready-deny.json",
            "pre_mutation": True,
            "harmless": True,
            "disposable_fixture": True,
            "production_state_preserved": True,
            "permitted_evidence_ref": "E-READY-PERMIT",
            "denied_evidence_ref": "E-READY-DENY",
            "evidence_refs": ["E-READY-PERMIT", "E-READY-DENY"],
        })
        rollback[-1].update({
            "command": command,
            "disposable_fixture": True,
            "production_state_preserved": True,
            "evidence_refs": ["E-ROLLBACK"],
        })
    for prefix, values in (
        ("RESOURCE", resources), ("UPDATE", updates), ("READINESS", readiness),
        ("ROLLBACK", rollback),
    ):
        for item in values:
            if item["applicability"] == "not_applicable":
                evidence_id = f"E-{prefix}-{item['kind'].upper()}-NA"
                gate_id = f"{prefix.lower()}:{item['kind']}"
                add_evidence(evidence_id, gate_id, branch="not_applicable")
                item["evidence_refs"] = [evidence_id]
    def proof(enabled, evidence_ref, gate_id):
        if not enabled:
            add_evidence(evidence_ref, gate_id, branch="not_applicable")
        return {
        "applicability": "applicable" if enabled else "not_applicable",
        "rationale": "required for applicable deployment" if enabled else "no resources apply",
        "evidence_refs": [evidence_ref],
        **({"command": command} if enabled else {}),
        }
    clean = proof(applicable, "E-CLEAN" if applicable else "E-CLEAN-NA", "clean_environment")
    if applicable:
        clean.update({"disposable_fixture": True, "production_state_preserved": True})
    impacts = [{key: item[key] for key in ("kind", "applicability", "owner", "rationale", "evidence_refs")} for item in resources]
    return {
        "schema_version": "1.0",
        "artifact_id": "deployment-1",
        "artifact_version": "1",
        "increment_artifact_digest": DIGEST_A,
        "evidence_checkpoint_digest": DIGEST_B,
        "scenario_artifact_digest": "sha256:" + "c" * 64,
        "architecture_artifact_digest": "sha256:" + "d" * 64,
        "increment_deployment_impacts_digest": deployment_impact_digest({"deployment_impacts": impacts}),
        "source_revision": revision,
        "source_artifacts": source_artifacts,
        "applicability": "applicable" if applicable else "not_applicable",
        "resources": resources,
        "update_operations": updates,
        "readiness_checks": readiness,
        "rollback_targets": rollback,
        "clean_environment": clean,
        "drift_detection": proof(applicable, "E-DRIFT" if applicable else "E-DRIFT-NA", "drift_detection"),
        "durable_roots": [],
        "evidence": evidence_records,
        "blocking_questions": [],
    }


def test_complete_applicable_deployment_is_revision_and_evidence_bound(tmp_path):
    value = deployment(tmp_path)
    assert validate_deployment_checkpoint(value, artifact_root=tmp_path) == value


def test_not_applicable_profile_still_requires_complete_evidenced_inventories(tmp_path):
    value = deployment(tmp_path, applicable=False)
    assert validate_deployment_checkpoint(value, artifact_root=tmp_path) == value
    value["resources"].pop()
    with pytest.raises(ValueError, match="inventory is incomplete"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_readiness_negative_probe_requires_safe_pre_mutation_plan(tmp_path):
    value = deployment(tmp_path)
    value["readiness_checks"][0]["production_state_preserved"] = False
    with pytest.raises(ValueError, match="production_state_preserved=true"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_durable_resource_cannot_pass_without_backup_restore_integrity(tmp_path):
    value = deployment(tmp_path)
    durable = next(item for item in value["resources"] if item["kind"] == "durable_roots")
    package = next(item for item in value["resources"] if item["kind"] == "packages")
    durable.update({
        "applicability": "applicable", "tracked_artifact": package["tracked_artifact"],
        "runtime_inventory": ["/var/lib/example"],
        "update_kinds": ["data_migration"], "readiness_kinds": ["backup"],
        "rollback_kinds": ["uninstall_data_preservation"],
    })
    migration = next(item for item in value["update_operations"] if item["kind"] == "data_migration")
    migration.update({
        "applicability": "applicable", "command": value["update_operations"][-1]["command"],
        "evidence_refs": ["E-MIGRATION"],
    })
    backup = next(item for item in value["readiness_checks"] if item["kind"] == "backup")
    package_readiness = value["readiness_checks"][0]
    backup.update({
        **{key: package_readiness[key] for key in (
            "permitted_command", "denied_command", "protected_asset", "production_boundary",
            "permitted_operation", "denied_operation", "safety_basis", "evidence_path",
            "pre_mutation", "harmless", "disposable_fixture", "production_state_preserved",
        )},
        "applicability": "applicable", "permitted_evidence_ref": "E-BACKUP-PERMIT",
        "denied_evidence_ref": "E-BACKUP-DENY",
        "evidence_refs": ["E-BACKUP-PERMIT", "E-BACKUP-DENY"],
    })
    with pytest.raises(ValueError, match="backup/restore coverage"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_stale_deployment_evidence_is_rejected(tmp_path):
    value = deployment(tmp_path)
    (tmp_path / "e-resource.json").write_text("changed\n")
    with pytest.raises(ValueError, match="missing or stale"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_clean_environment_rejects_production_host_evidence(tmp_path):
    value = deployment(tmp_path)
    clean_ref = value["clean_environment"]["evidence_refs"][0]
    clean = next(item for item in value["evidence"] if item["id"] == clean_ref)
    clean["environment"] = "production"
    trace = tmp_path / clean["artifacts"][0]["path"]
    execution = json.loads(trace.read_text())
    execution["environment"] = "production"
    trace.write_text(json.dumps(execution))
    clean["artifacts"][0]["digest"] = artifact_digest(trace)
    with pytest.raises(ValueError, match="clean_disposable"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_bound_artifacts_cannot_escape_checkpoint_root(tmp_path):
    value = deployment(tmp_path)
    value["source_artifacts"][0]["path"] = "../outside"
    value["source_revision"] = canonical_digest(value["source_artifacts"])
    with pytest.raises(ValueError, match="escapes the artifact root"):
        validate_deployment_checkpoint(value, artifact_root=tmp_path)


def test_real_cli_refuses_deployment_checkpoint_without_completed_evidence(tmp_path):
    state = tmp_path / "state"
    store = LifecycleStore(state)
    identity = RunIdentity.create("task-deploy")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(tmp_path),
    })
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "opaque"})
    store.append(identity, "run_completed", {"exit_code": 0})
    store.append(identity, "attempt_completed")
    increment = tmp_path / "increment.json"
    evidence = tmp_path / "evidence.json"
    evidence.write_text("evidence\n")
    value = deployment(tmp_path)
    impacts = [
        {key: item[key] for key in ("kind", "applicability", "owner", "rationale", "evidence_refs")}
        for item in value["resources"]
    ]
    increment.write_text(json.dumps({"deployment_impacts": impacts}))
    value["increment_artifact_digest"] = artifact_digest(increment)
    value["increment_deployment_impacts_digest"] = deployment_impact_digest(json.loads(increment.read_text()))
    value["evidence_checkpoint_digest"] = artifact_digest(evidence)
    checkpoint = tmp_path / "deployment.json"
    checkpoint.write_text(json.dumps(value))
    result = subprocess.run([
        str(Path(sys.executable).with_name("dev-pipeline")), "checkpoint", "deployment",
        "--task-ref", "task-deploy", "--state-dir", str(state), "--input", str(checkpoint),
        "--increment", str(increment), "--evidence-checkpoint", str(evidence),
        "--next-step", "Deployed acceptance",
    ], text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert "requires the completed evidence checkpoint" in result.stderr
    assert "deployment" not in json.loads((state / "state.json").read_text()).get("checkpoints", {})


def test_real_cli_completes_digest_bound_deployment_checkpoint(tmp_path):
    state = tmp_path / "state"
    store = LifecycleStore(state)
    identity = RunIdentity.create("task-deploy")
    store.append(identity, "attempt_started", {
        "attempt_origin": "new_owner_session", "runtime": "codex", "repository": str(tmp_path),
    })
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "opaque"})
    store.append(identity, "run_completed", {"exit_code": 0})
    store.append(identity, "attempt_completed")
    increment = tmp_path / "increment.json"
    evidence = tmp_path / "evidence.json"
    evidence.write_text("evidence\n")
    value = deployment(tmp_path)
    impacts = [
        {key: item[key] for key in ("kind", "applicability", "owner", "rationale", "evidence_refs")}
        for item in value["resources"]
    ]
    increment.write_text(json.dumps({"deployment_impacts": impacts}))
    value["increment_artifact_digest"] = artifact_digest(increment)
    value["increment_deployment_impacts_digest"] = deployment_impact_digest(json.loads(increment.read_text()))
    value["evidence_checkpoint_digest"] = artifact_digest(evidence)
    for name, field in (
        ("scenario", "scenario_artifact_digest"),
        ("architecture", "architecture_artifact_digest"),
    ):
        prior_artifact = tmp_path / f"{name}.json"
        prior_artifact.write_text(f"{name}\n")
        value[field] = artifact_digest(prior_artifact)
        store.append(identity, "checkpoint_completed", {
            "checkpoint": name, "artifact": str(prior_artifact),
            "artifact_digest": value[field], "next_step": "next",
        })
    store.append(identity, "checkpoint_completed", {
        "checkpoint": "evidence", "artifact": str(evidence),
        "artifact_digest": artifact_digest(evidence), "next_step": "deployment",
    })
    checkpoint = tmp_path / "deployment.json"
    checkpoint.write_text(json.dumps(value))
    result = subprocess.run([
        str(Path(sys.executable).with_name("dev-pipeline")), "checkpoint", "deployment",
        "--task-ref", "task-deploy", "--state-dir", str(state), "--input", str(checkpoint),
        "--increment", str(increment), "--evidence-checkpoint", str(evidence),
        "--next-step", "Deployed acceptance",
    ], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["kind"] == "checkpoint_completed"
    assert event["payload"]["checkpoint"] == "deployment"


def test_real_cli_accepts_deployed_increment_only_with_current_applicable_checkpoint(tmp_path):
    scenario_artifact = tmp_path / "scenario.json"
    architecture_artifact = tmp_path / "architecture.json"
    scenario_artifact.write_text("scenario\n")
    architecture_artifact.write_text("architecture\n")
    scenario_digest = artifact_digest(scenario_artifact)
    architecture_digest = artifact_digest(architecture_artifact)
    state = tmp_path / "state"
    prepared_state(
        state, scenario_digest, architecture_digest, scenario_artifact, architecture_artifact,
    )
    deployment_value = deployment(tmp_path)
    impacts = [
        {key: item[key] for key in ("kind", "applicability", "owner", "rationale", "evidence_refs")}
        for item in deployment_value["resources"]
    ]
    increment_value = increment(
        level="deployed", scenario_digest=scenario_digest,
        architecture_digest=architecture_digest,
    )
    increment_value["deployment_impacts"] = impacts
    increment_path = tmp_path / "increment-deployed.json"
    increment_path.write_text(json.dumps(increment_value))
    assert run_cli(
        "increment", "submit", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(increment_path),
    ).returncode == 0
    contract, evidence_path = closure_files(
        tmp_path, state, scenario_digest, architecture_digest,
    )
    deployment_value.update({
        "increment_artifact_digest": artifact_digest(increment_path),
        "evidence_checkpoint_digest": artifact_digest(evidence_path),
        "scenario_artifact_digest": scenario_digest,
        "architecture_artifact_digest": architecture_digest,
        "increment_deployment_impacts_digest": deployment_impact_digest(increment_value),
    })
    deployment_path = tmp_path / "deployment.json"
    deployment_path.write_text(json.dumps(deployment_value))
    applied = subprocess.run([
        str(Path(sys.executable).with_name("dev-pipeline")), "checkpoint", "deployment",
        "--task-ref", "task-360", "--state-dir", str(state), "--input", str(deployment_path),
        "--increment", str(increment_path), "--evidence-checkpoint", str(evidence_path),
        "--next-step", "Deployed acceptance",
    ], text=True, capture_output=True, check=False)
    assert applied.returncode == 0, applied.stderr
    packet, decision = review_files(
        tmp_path, increment_path, contract=contract, evidence_checkpoint=evidence_path,
    )
    accepted = run_cli(
        "increment", "accept", "--task-ref", "task-360", "--state-dir", str(state),
        "--input", str(increment_path), "--packet", str(packet), "--decision", str(decision),
        "--next-step", "Complete", "--task-contract", str(contract),
        "--evidence-checkpoint", str(evidence_path),
        "--deployment-checkpoint", str(deployment_path),
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["payload"]["evidence_level"] == "deployed"
