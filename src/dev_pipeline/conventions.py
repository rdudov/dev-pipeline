"""Compact routed conventions derived from the frozen agents baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
FROZEN_AGENTS_COMMIT = "41e16ac401f182f4cd3a102929c11391f61f3255"

PACKS: dict[str, dict[str, Any]] = {
    "core": {"rules": [
        "One Codex owner retains the causal chain from requirements to runtime evidence.",
        "Stop on material product semantics; label only reversible assumptions.",
        "Prefer the existing owning component and do not create a parallel mechanism.",
        "Structured decisions and durable artifacts are state; prose cannot override them.",
        "Preserve adjacent existing behavior unless the accepted contract explicitly authorizes its change; unresolved compatibility or policy expansion is a blocker.",
        "Keep task, review, verification, and evidence artifacts in the owning task directory, never in the target repository.",
    ], "provenance": ["00_agent_development.md: uncertainty/open questions", "01_orchestrator.md: bounded context"]},
    "discovery": {"rules": [
        "Build the complete cross-cutting dependency inventory before proposing a solution: source and sibling repositories, runtime entrypoints and services, containers and host identities, configuration and secrets, durable storage, backup/restore/retention, deployment/update/rollback, observability, network, scheduled jobs, and external integrations.",
        "For every dependency surface name the owning component, concrete evidence, and change impact; mark a surface not applicable only with evidence, never by omission.",
        "Trace both the intended production path and operational lifecycle. Missing owners, inaccessible evidence, or unresolved deployment, recovery, or isolation semantics are blockers for downstream design.",
    ], "provenance": ["02_analyst_prompt.md: source/context discovery", "04_architect_prompt.md: production path", "08_agent_developer.md: runtime completion"]},
    "scenario": {"rules": [
        "Describe actors, triggers, outcomes, failure modes, and behavioral acceptance proportionally to risk.",
        "Raise compatibility, fallback, source-of-truth, migration, and rollout ambiguity as concrete questions.",
        "Repair only evidence-linked findings and preserve correct scenario content.",
    ], "provenance": ["02_analyst_prompt.md: use cases/assumptions", "02a_analysis_repair_prompt.md", "03_tz_reviewer_prompt.md"]},
    "architecture": {"rules": [
        "Name the production path, owning layer, state sources, reuse plan, deletion plan, and verification path.",
        "Add only task-relevant seams; do not require generic diagrams or deployment sections.",
        "Challenge feasibility with path and artifact evidence, then repair only concrete findings.",
    ], "provenance": ["04_architect_prompt.md", "04a_architecture_repair_prompt.md", "05_architecture_reviewer_prompt.md"]},
    "increment": {"rules": [
        "Build a real-entrypoint walking skeleton before vertical increments.",
        "Map every increment to named scenarios, failure modes, source/deletion deltas, and evidence.",
        "Allow stubs only at new or unavailable boundaries and record a replacement milestone.",
    ], "provenance": ["06_agent_planner.md", "06a_agent_planning_repair.md", "07_agent_plan_reviewer.md", "08_agent_developer.md"]},
    "diff_review": {"rules": [
        "Review only the concrete diff against requirements, owning architecture, regressions, tests, and docs.",
        "Flag duplicate mechanisms, test-only production paths, swallowed errors, unrelated scope, adjacent semantic changes, and task artifacts written into the target repository.",
        "Require evidence references for findings and use the canonical structured decision envelope.",
    ], "provenance": ["08a_agent_implementation_repair.md", "09_agent_code_reviewer.md: concrete review"]},
    "live": {"rules": [
        "Do not credit structural, mock-only, stub-only, harness-only, or degenerate-fixture checks as live evidence.",
        "Exercise each production-relevant mode, provider, threshold, credential, flag, transport, and fallback branch.",
        "Report evidence at its actual level: skeleton, integrated, live, or deployed.",
    ], "provenance": ["00_agent_development.md: branch evidence", "08_agent_developer.md: runtime", "09_agent_code_reviewer.md: weak tests"]},
    "recovery": {"rules": [
        "Repair only environment, evidence, or stale-artifact blockers using explicit machine evidence.",
        "Never change product semantics, fallback policy, compatibility, migration, rollout, or source code as recovery.",
        "Return resolved, still blocked, or human escalation with a concrete continuation recommendation.",
    ], "provenance": ["01_orchestrator.md: rescuer boundary", "10_agent_blocker_rescuer.md"]},
    "risk:compatibility": {"rules": ["Require an explicit compatibility/migration decision; absent policy is a blocker, not permission to retain legacy behavior."], "provenance": ["09_agent_code_reviewer.md: compatibility wording (constrained)"]},
    "risk:security": {"rules": [
        "Identify authorization, isolation, secret, destructive-operation, and data-loss branches, including both allowed and denied behavior.",
        "A positive path cannot close a security or isolation gate: execute representative safe negative probes at the real production boundary.",
        "Negative probes must use disposable markers, denied reads, or harmless writes and must never mutate production data, disrupt services, or attempt a destructive command merely to prove it is denied.",
    ], "provenance": ["03_tz_reviewer_prompt.md: critical operations", "09_agent_code_reviewer.md: runtime branches"]},
    "risk:service": {"rules": ["Verify the actual service/daemon/worker entrypoint, process lifecycle, restart behavior, and clean logs."], "provenance": ["08_agent_developer.md: real application entrypoint"]},
    "risk:provider": {"rules": ["Verify provider, credential, model, transport, and fallback branches separately at their real boundary."], "provenance": ["00_agent_development.md: branch evidence", "09_agent_code_reviewer.md: provider branches"]},
    "risk:media": {"rules": ["Use semantically representative media; container validity or degenerate samples do not prove behavior."], "provenance": ["09_agent_code_reviewer.md: representative media fixtures"]},
    "risk:cross_repo": {"rules": ["Name repository ownership and dependency direction; keep product adapters thin and prevent private data leakage."], "provenance": ["08_agent_developer.md: existing ownership/reuse"]},
    "risk:publication": {"rules": ["Before publication inspect outgoing diff/history, secrets, dependencies/licenses, generated artifacts, and repository health."], "provenance": ["08_agent_developer.md: docs/runtime completion", "09_agent_code_reviewer.md: concrete diff review"]},
}

GATES = frozenset({"core", "discovery", "scenario", "architecture", "increment", "diff_review", "live", "recovery"})
RISKS = frozenset(key.removeprefix("risk:") for key in PACKS if key.startswith("risk:"))
AGENT_ROLES = {
    "scout": "discovery", "scenario_review": "scenario", "architecture_review": "architecture",
    "diff_review": "diff_review", "live_verification": "live",
}
ROLE_REVIEW_TYPES = {
    "scenario_review": "scenario",
    "architecture_review": "architecture",
    "diff_review": "increment",
}

RETIRED_PATTERNS = [
    {"source": "00_agent_development.md: fixed role chain", "reason": "A continuous owner invokes bounded roles only for concrete questions."},
    {"source": "01_orchestrator.md: universal retry/stage counts", "reason": "Rework policy belongs to the concrete checkpoint and material semantics escalate to a human."},
    {"source": "04_architect_prompt.md: comprehensive universal template", "reason": "Architecture packets contain only the task-relevant delta."},
    {"source": "06_agent_planner.md: stub output as acceptance", "reason": "Stub evidence is limited to skeleton level and cannot close integrated/live gates."},
    {"source": "09_agent_code_reviewer.md: implicit compatibility", "reason": "Compatibility is loaded only by explicit contract or risk trigger."},
    {"source": "README.md: full role catalog", "reason": "The catalog is provenance only and is never injected into normal context."},
]


def route_conventions(gate: str, risks: list[str]) -> list[dict[str, Any]]:
    if gate not in GATES:
        raise ValueError(f"Unsupported convention gate: {gate}")
    unknown = [risk for risk in risks if risk not in RISKS]
    if unknown:
        raise ValueError(f"Unsupported convention risk: {unknown[0]}")
    pack_ids = ["core"]
    if gate != "core":
        pack_ids.append(gate)
    pack_ids.extend(f"risk:{risk}" for risk in dict.fromkeys(risks))
    return [{"id": pack_id, **PACKS[pack_id]} for pack_id in pack_ids]


def render_conventions(packs: list[dict[str, Any]]) -> str:
    lines = ["Canonical routed conventions:"]
    for pack in packs:
        lines.append(f"[{pack['id']}]")
        lines.extend(f"- {rule}" for rule in pack["rules"])
    return "\n".join(lines)


def _artifact(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Context artifact does not exist: {path}")
    return {"path": str(path.resolve()), "digest": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"}


def build_context_packet(
    *, role: str, purpose: str, question: str, artifacts: list[Path], evidence: list[Path],
    exclusions: list[str], risks: list[str], artifact_version: str | None = None,
) -> dict[str, Any]:
    if role not in AGENT_ROLES:
        raise ValueError(f"Unsupported bounded agent role: {role}")
    if not purpose.strip() or not question.strip():
        raise ValueError("Bounded agent context requires purpose and question")
    if not artifacts or not exclusions:
        raise ValueError("Bounded agent context requires artifacts and explicit exclusions")
    if role.endswith("_review") and (not artifact_version or not artifact_version.strip()):
        raise ValueError("Bounded review context requires artifact_version")
    packet = {
        "schema_version": SCHEMA_VERSION, "packet_type": "bounded_codex_agent", "runtime": "codex",
        "role": role, "purpose": purpose, "question": question,
        "active_gate": AGENT_ROLES[role], "triggered_risks": list(dict.fromkeys(risks)),
        "artifacts": [_artifact(path) for path in artifacts],
        "evidence": [_artifact(path) for path in evidence],
        "artifact_version": artifact_version,
        "history_scope": "excluded_unless_explicitly_bound",
        "exclusions": exclusions, "convention_packs": route_conventions(AGENT_ROLES[role], risks),
        "legacy_prompt_included": False,
    }
    if role in ROLE_REVIEW_TYPES:
        packet["decision_review_type"] = ROLE_REVIEW_TYPES[role]
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    packet["packet_digest"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return packet


def validate_context_packet(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported bounded context packet")
    if value.get("packet_type") != "bounded_codex_agent" or value.get("runtime") != "codex":
        raise ValueError("Context packet must target a bounded Codex agent")
    if value.get("role") not in AGENT_ROLES or value.get("legacy_prompt_included") is not False:
        raise ValueError("Context packet has an invalid role or legacy prompt flag")
    for field in ("purpose", "question", "packet_digest"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"Context packet requires non-empty {field}")
    if not isinstance(value.get("artifacts"), list) or not value["artifacts"]:
        raise ValueError("Context packet requires artifacts")
    if not isinstance(value.get("exclusions"), list) or not value["exclusions"]:
        raise ValueError("Context packet requires exclusions")
    if value.get("history_scope") != "excluded_unless_explicitly_bound":
        raise ValueError("Context packet must exclude unbounded history")
    expected = route_conventions(AGENT_ROLES[value["role"]], value.get("triggered_risks", []))
    if value.get("active_gate") != AGENT_ROLES[value["role"]] or value.get("convention_packs") != expected:
        raise ValueError("Context packet convention routing is invalid")
    if value.get("decision_review_type") != ROLE_REVIEW_TYPES.get(value["role"]):
        if value["role"] in ROLE_REVIEW_TYPES or "decision_review_type" in value:
            raise ValueError("Context packet review decision type is invalid")
    for artifact in value["artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or _artifact(path)["digest"] != artifact.get("digest"):
            raise ValueError(f"Context artifact digest is stale: {path}")
    if not isinstance(value.get("evidence"), list):
        raise ValueError("Context packet evidence must be a list of bound artifacts")
    for evidence in value["evidence"]:
        if not isinstance(evidence, dict):
            raise ValueError("Context packet evidence must be digest-bound artifacts")
        path = Path(evidence.get("path", ""))
        if not path.is_file() or _artifact(path)["digest"] != evidence.get("digest"):
            raise ValueError(f"Context evidence digest is stale: {path}")
    unsigned = dict(value)
    digest = unsigned.pop("packet_digest")
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    if digest != f"sha256:{hashlib.sha256(encoded).hexdigest()}":
        raise ValueError("Context packet digest does not match its content")
    return value


def render_agent_prompt(packet: dict[str, Any]) -> str:
    validate_context_packet(packet)
    artifacts = "\n".join(f"- {item['path']} ({item['digest']})" for item in packet["artifacts"])
    evidence = "\n".join(
        f"- {item['path']} ({item['digest']})" for item in packet["evidence"]
    ) or "- None supplied"
    exclusions = "\n".join(f"- {item}" for item in packet["exclusions"])
    output_contract = "Return a concise evidence-linked answer."
    if packet["role"].endswith("_review"):
        output_contract = (
            "Return one JSON decision envelope with schema_version, review_type, "
            "artifact_digest, artifact_version, decision, findings, blocking_questions, "
            "and evidence_checked. Use only approved, rework_required, blocked, or rejected; "
            f"set review_type to {packet['decision_review_type']}, bind the first artifact digest, "
            f"and use artifact version {packet['artifact_version']}. Each finding requires id, "
            "severity, summary, and evidence_ref."
        )
    elif packet["role"] == "live_verification":
        output_contract = "Return observed branches, actual evidence levels, gaps, and a pass/blocked/failed conclusion."
    return f"""You are a bounded Codex {packet['role']}.

Purpose: {packet['purpose']}
Question: {packet['question']}

{render_conventions(packet['convention_packs'])}

Reviewed artifacts:
{artifacts}

Evidence:
{evidence}

Explicit exclusions:
{exclusions}

Unbounded task or conversation history is excluded. Use only the digest-bound artifacts and explicitly named evidence above.

Answer only the named question. Cite concrete artifact/evidence references. {output_contract} Do not modify files, expand scope, schedule other roles, or treat prose as a structured approval.
"""
