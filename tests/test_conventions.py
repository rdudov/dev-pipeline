from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_pipeline import cli
from dev_pipeline.codex import CodexStartResult, build_owner_prompt, start_codex_owner
from dev_pipeline.conventions import (
    AGENT_ROLES, FROZEN_AGENTS_COMMIT, PACKS, RETIRED_PATTERNS,
    build_context_packet, render_agent_prompt, render_conventions, route_conventions,
    validate_context_packet,
)


def test_owner_routing_loads_only_core_active_gate_and_triggered_risk():
    packs = route_conventions("architecture", ["security"])
    assert [pack["id"] for pack in packs] == ["core", "architecture", "risk:security"]
    rendered = render_conventions(packs)
    assert "[scenario]" not in rendered
    assert "[increment]" not in rendered
    assert "analyst" not in rendered.lower()


def test_scout_gets_cross_cutting_discovery_contract():
    rendered = render_conventions(route_conventions(AGENT_ROLES["scout"], []))
    assert "backup/restore/retention" in rendered
    assert "not applicable only with evidence" in rendered
    assert "operational lifecycle" in rendered


def test_security_contract_requires_safe_negative_real_boundary_evidence():
    rendered = render_conventions(route_conventions("live", ["security"]))
    assert "positive path cannot close" in rendered
    assert "real production boundary" in rendered
    assert "never mutate production data" in rendered


def test_normal_owner_prompt_does_not_aggregate_legacy_roles():
    prompt = build_owner_prompt("task-1", "Do the work.", [], render_conventions(route_conventions("core", [])))
    assert "[core]" in prompt
    for legacy_role in ("analyst", "architect", "planner", "developer", "orchestrator"):
        assert legacy_role not in prompt.lower()
    assert len(prompt) < 2_500


def test_every_bounded_role_gets_only_its_gate_and_explicit_risks(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("observable delta")
    for role, gate in AGENT_ROLES.items():
        packet = build_context_packet(
            role=role, purpose="Answer one bounded question", question="Is the delta valid?",
            artifacts=[artifact], evidence=[artifact], exclusions=["Other bootstraps"],
            risks=["publication"], artifact_version="1" if role.endswith("_review") else None,
        )
        assert [pack["id"] for pack in packet["convention_packs"]] == (
            ["core", "risk:publication"] if gate == "core"
            else ["core", gate, "risk:publication"]
        )
        assert packet["legacy_prompt_included"] is False
        assert "schedule other roles" in render_agent_prompt(packet)


def test_context_packet_rejects_tampering(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="diff_review", purpose="Review", question="Approve?", artifacts=[artifact],
        evidence=[], exclusions=["Bootstrap 6"], risks=[], artifact_version="1",
    )
    packet["question"] = "Different question"
    with pytest.raises(ValueError, match="digest"):
        validate_context_packet(packet)


def test_context_packet_rejects_artifact_changed_after_build(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("first")
    packet = build_context_packet(
        role="scout", purpose="Inspect", question="What owns this?", artifacts=[artifact],
        evidence=[], exclusions=["Implementation"], risks=[],
    )
    artifact.write_text("second")
    with pytest.raises(ValueError, match="stale"):
        validate_context_packet(packet)


def test_context_packet_rejects_unbounded_history_request(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="diff_review", purpose="Review", question="Approve?", artifacts=[artifact],
        evidence=[], exclusions=["Unrelated work"], risks=[], artifact_version="1",
    )
    packet["history_scope"] = "full_task_and_conversation_history"

    with pytest.raises(ValueError, match="exclude unbounded history"):
        validate_context_packet(packet)


def test_rendered_agent_prompt_explicitly_excludes_unbounded_history(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="scenario_review", purpose="Review", question="Approve?", artifacts=[artifact],
        evidence=[artifact], exclusions=["Other tasks"], risks=[],
        artifact_version="1",
    )

    prompt = render_agent_prompt(packet)
    assert "Unbounded task or conversation history is excluded" in prompt
    assert packet["history_scope"] == "excluded_unless_explicitly_bound"
    assert packet["evidence"][0]["digest"].startswith("sha256:")


def test_context_packet_rejects_free_form_history_in_evidence(tmp_path):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="diff_review", purpose="Review", question="Approve?", artifacts=[artifact],
        evidence=[], exclusions=["Other work"], risks=[], artifact_version="1",
    )
    packet["evidence"] = ["entire task and conversation history"]

    with pytest.raises(ValueError, match="digest-bound artifacts"):
        validate_context_packet(packet)


def test_provenance_covers_all_frozen_sources_and_records_retirements():
    assert FROZEN_AGENTS_COMMIT == "41e16ac401f182f4cd3a102929c11391f61f3255"
    text = json.dumps({"packs": PACKS, "retired": RETIRED_PATTERNS})
    for filename in (
        "00_agent_development.md", "01_orchestrator.md", "02_analyst_prompt.md",
        "02a_analysis_repair_prompt.md", "03_tz_reviewer_prompt.md", "04_architect_prompt.md",
        "04a_architecture_repair_prompt.md", "05_architecture_reviewer_prompt.md",
        "06_agent_planner.md", "06a_agent_planning_repair.md", "07_agent_plan_reviewer.md",
        "08_agent_developer.md", "08a_agent_implementation_repair.md",
        "09_agent_code_reviewer.md", "10_agent_blocker_rescuer.md", "README.md",
    ):
        assert filename in text


def test_context_and_agent_commands_use_explicit_codex_path(tmp_path, monkeypatch):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet_path = tmp_path / "packet.json"
    assert cli.main([
        "context", "--role", "scout", "--purpose", "Inspect one path",
        "--question", "Which component owns this?", "--artifact", str(artifact),
        "--exclude", "Implementation", "--output", str(packet_path),
    ]) == 0
    captured = {}
    def fake_start(**kwargs):
        captured.update(kwargs)
        return CodexStartResult(0, "session", "", final_message="Bounded answer")
    monkeypatch.setattr(cli, "start_codex_owner", fake_start)
    output = tmp_path / "result.json"
    assert cli.main([
        "agent", "--packet", str(packet_path), "--repo", str(tmp_path),
        "--output", str(output), "--diagnostics-prefix", str(tmp_path / "diag"),
    ]) == 0
    result = json.loads(output.read_text())
    assert result["runtime"] == "codex" and result["response"] == "Bounded answer"
    assert "bounded Codex scout" in captured["prompt"]


def test_review_agent_validates_canonical_decision(tmp_path, monkeypatch):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="diff_review", purpose="Review", question="Approve?", artifacts=[artifact],
        artifact_version="1", evidence=[artifact], exclusions=["Bootstrap 6"], risks=[],
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    decision = {
        "schema_version": "1.0", "review_type": "increment",
        "artifact_digest": packet["artifacts"][0]["digest"], "artifact_version": "1",
        "decision": "approved", "findings": [], "blocking_questions": [],
        "evidence_checked": ["tests"],
    }
    monkeypatch.setattr(cli, "start_codex_owner", lambda **kwargs: CodexStartResult(
        0, "session", "", final_message=json.dumps(decision)
    ))
    output = tmp_path / "result.json"
    assert cli.main([
        "agent", "--packet", str(packet_path), "--repo", str(tmp_path),
        "--output", str(output), "--diagnostics-prefix", str(tmp_path / "diag"),
    ]) == 0
    assert json.loads(output.read_text())["decision"]["decision"] == "approved"


def test_review_agent_rejects_malformed_decision(tmp_path, monkeypatch):
    artifact = tmp_path / "delta.txt"
    artifact.write_text("delta")
    packet = build_context_packet(
        role="scenario_review", purpose="Review", question="Approve?", artifacts=[artifact],
        artifact_version="1", evidence=[], exclusions=["Architecture"], risks=[],
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    monkeypatch.setattr(cli, "start_codex_owner", lambda **kwargs: CodexStartResult(
        0, "session", "", final_message="not-json"
    ))
    with pytest.raises(SystemExit):
        cli.main([
            "agent", "--packet", str(packet_path), "--repo", str(tmp_path),
            "--output", str(tmp_path / "result.json"),
            "--diagnostics-prefix", str(tmp_path / "diag"),
        ])


def test_codex_boundary_extracts_final_agent_message(tmp_path):
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type':'thread.started','thread_id':'session'}))\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'answer'}}))\n"
    )
    executable.chmod(0o755)
    result = start_codex_owner(
        codex_bin=str(executable), repository=tmp_path, sandbox="read-only", model=None,
        prompt="review", on_process_started=lambda pid: None,
        on_session_discovered=lambda session: None,
    )
    assert result.final_message == "answer"
