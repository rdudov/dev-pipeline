"""Command-line entrypoint for the development pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codex import build_owner_prompt, resume_codex_owner, start_codex_owner
from .conventions import (
    AGENT_ROLES,
    GATES,
    RISKS,
    build_context_packet,
    render_agent_prompt,
    render_conventions,
    route_conventions,
    validate_context_packet,
)
from .checkpoints import (
    artifact_digest,
    build_review_packet,
    canonical_digest,
    validate_architecture_checkpoint,
    validate_decision,
    validate_review_packet,
    validate_scenario_checkpoint,
)
from .lifecycle import LifecycleStore, RunIdentity
from .increments import achieved_evidence_level, validate_increment
from .evidence import scenario_branch_digest, validate_evidence_checkpoint


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event, sort_keys=True), flush=True)


def _validated_inputs(args: argparse.Namespace) -> tuple[Path, Path, list[Path]]:
    repository = args.repo.resolve()
    instruction_file = args.instruction_file.resolve()
    artifacts = [path.resolve() for path in args.artifact]
    if not repository.is_dir():
        raise ValueError(f"Repository does not exist: {repository}")
    if not instruction_file.is_file():
        raise ValueError(f"Instruction file does not exist: {instruction_file}")
    missing = [path for path in artifacts if not path.exists()]
    if missing:
        raise ValueError(f"Artifact does not exist: {missing[0]}")

    return repository, instruction_file, artifacts


def _run_start(args: argparse.Namespace, *, attempt_origin: str, previous_attempt_id: str | None = None) -> int:
    repository, instruction_file, artifacts = _validated_inputs(args)
    identity = RunIdentity.create(args.task_ref)
    store = LifecycleStore(args.state_dir)

    def record(kind: str, payload: dict[str, object] | None = None) -> None:
        emit(store.append(identity, kind, payload))

    record(
        "attempt_started",
        {
            "attempt_origin": attempt_origin,
            "runtime": "codex",
            "repository": str(repository),
            "worktree": args.worktree,
            **({"previous_attempt_id": previous_attempt_id} if previous_attempt_id else {}),
        },
    )
    record("run_started", {"run_operation": "native_session_start"})
    prompt = build_owner_prompt(
        args.task_ref,
        instruction_file.read_text(encoding="utf-8"),
        artifacts,
        render_conventions(route_conventions(args.gate, args.risk)),
    )
    try:
        result = start_codex_owner(
            codex_bin=args.codex_bin,
            repository=repository,
            sandbox=args.sandbox,
            model=args.model,
            prompt=prompt,
            on_process_started=lambda pid: record("process_started", {"pid": pid}),
            on_session_discovered=lambda session_id: record(
                "native_session_discovered", {"native_session_id": session_id}
            ),
            diagnostics_prefix=store.root / "diagnostics" / identity.run_id,
        )
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        record("run_failed", {"reason": reason})
        record("attempt_failed", {"reason": reason})
        print(reason, file=sys.stderr)
        return 1

    if result.exit_code != 0 or result.native_session_id is None:
        reason = (
            f"Codex exited with code {result.exit_code}"
            if result.exit_code != 0
            else "Codex completed without emitting a native session identifier"
        )
        record("run_failed", {"exit_code": result.exit_code, "reason": reason})
        record("attempt_failed", {"reason": reason})
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return 1

    record("run_completed", {"exit_code": result.exit_code})
    record("attempt_completed", {})
    return 0


def owner_start(args: argparse.Namespace) -> int:
    return _run_start(args, attempt_origin="new_owner_session")


def owner_retry(args: argparse.Namespace) -> int:
    previous_identity, previous = LifecycleStore(args.previous_state_dir).load_attempt()
    if previous_identity.task_ref != args.task_ref:
        raise ValueError("Previous lifecycle state belongs to a different task")
    if args.state_dir.resolve() == args.previous_state_dir.resolve():
        raise ValueError("Retry requires a new state directory so the prior attempt remains immutable")
    return _run_start(
        args,
        attempt_origin="retry_existing_artifacts",
        previous_attempt_id=previous["attempt"]["attempt_id"],
    )


def owner_resume(args: argparse.Namespace) -> int:
    repository = args.repo.resolve()
    instruction_file = args.instruction_file.resolve()
    if not repository.is_dir() or not instruction_file.is_file():
        raise ValueError("Resume repository and instruction file must exist")
    store = LifecycleStore(args.state_dir)
    prior_identity, state = store.load_attempt()
    attempt = state["attempt"]
    if prior_identity.task_ref != args.task_ref:
        raise ValueError("Lifecycle state belongs to a different task")
    if Path(attempt["repository"]).resolve() != repository:
        raise ValueError("Resume repository differs from the recorded attempt repository")
    identity = prior_identity.next_run()

    def record(kind: str, payload: dict[str, object] | None = None) -> None:
        emit(store.append(identity, kind, payload))

    record("run_started", {"run_operation": "native_session_resume"})
    prompt = (
        render_conventions(route_conventions(args.gate, args.risk))
        + "\n\nContinuation instruction:\n"
        + instruction_file.read_text(encoding="utf-8")
    )
    expected_session = attempt["native_session_id"]
    try:
        result = resume_codex_owner(
            codex_bin=args.codex_bin,
            repository=repository,
            sandbox=args.sandbox,
            model=args.model,
            native_session_id=expected_session,
            prompt=prompt,
            on_process_started=lambda pid: record("process_started", {"pid": pid}),
            on_session_discovered=lambda session_id: None,
            diagnostics_prefix=store.root / "diagnostics" / identity.run_id,
        )
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        record("run_failed", {"reason": reason})
        print(reason, file=sys.stderr)
        return 1
    if result.exit_code != 0 or result.native_session_id != expected_session:
        if result.exit_code != 0:
            reason = f"Codex native session is unavailable (exit code {result.exit_code})"
        elif result.native_session_id is None:
            reason = "Codex resume emitted no native session identifier"
        else:
            reason = "Codex resume returned a different native session identifier"
        record("native_resume_unavailable", {"reason": reason})
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return 1
    record("run_completed", {"exit_code": 0})
    record("attempt_completed", {})
    return 0


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"JSON input does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must contain an object: {path}")
    return value


def checkpoint_apply(args: argparse.Namespace) -> int:
    artifact = args.input.resolve()
    value = _read_json(artifact)
    if args.checkpoint_type == "scenario":
        checkpoint = validate_scenario_checkpoint(value)
    elif args.checkpoint_type == "architecture":
        checkpoint = validate_architecture_checkpoint(value)
    else:
        checkpoint = validate_evidence_checkpoint(value, artifact_root=artifact.parent)
    store = LifecycleStore(args.state_dir)
    prior_identity, state = store.load_attempt()
    if prior_identity.task_ref != args.task_ref:
        raise ValueError("Lifecycle state belongs to a different task")
    identity = prior_identity
    if args.checkpoint_type == "architecture":
        scenario_state = state.get("checkpoints", {}).get("scenario", {})
        if scenario_state.get("status") != "completed":
            raise ValueError("Architecture checkpoint requires a completed scenario checkpoint")
        if checkpoint["scenario_artifact_digest"] != scenario_state.get("artifact_digest"):
            raise ValueError("Architecture checkpoint scenario digest does not match lifecycle state")
        scenario_artifact = Path(str(scenario_state.get("artifact", "")))
        scenario = validate_scenario_checkpoint(_read_json(scenario_artifact))
        security = next(
            item for item in scenario["dependency_inventory"]
            if item["surface"] == "security_boundaries"
        )
        if security["applicability"] == "applicable" and not checkpoint["isolation_boundaries"]:
            raise ValueError(
                "Architecture checkpoint requires isolation_boundaries because scenario discovery "
                "marked security_boundaries applicable"
            )
    if args.checkpoint_type == "evidence":
        checkpoints = state.get("checkpoints", {})
        for name, digest_field in (
            ("scenario", "scenario_artifact_digest"),
            ("architecture", "architecture_artifact_digest"),
        ):
            prior = checkpoints.get(name, {})
            if prior.get("status") != "completed" or prior.get("artifact_digest") != checkpoint[digest_field]:
                raise ValueError(f"Evidence checkpoint {name} digest does not match lifecycle state")
            prior_path = Path(str(prior.get("artifact", "")))
            if not prior_path.is_file() or artifact_digest(prior_path) != prior.get("artifact_digest"):
                raise ValueError(f"Completed {name} checkpoint artifact is stale")
        scenario_path = Path(str(checkpoints["scenario"].get("artifact", "")))
        scenario_value = validate_scenario_checkpoint(_read_json(scenario_path))
        checkpoint = validate_evidence_checkpoint(
            value,
            artifact_root=artifact.parent,
            required_branches={
                item["id"]: scenario_branch_digest(item)
                for item in scenario_value["production_branches"]
            },
            required_product_intent_digest=canonical_digest(scenario_value["product_intent"]),
        )
        contract = args.task_contract.resolve()
        if not contract.is_file() or artifact_digest(contract) != checkpoint["task_contract_digest"]:
            raise ValueError("Evidence checkpoint task contract digest does not match")
        contract_value = _read_json(contract)
        required_live = contract_value.get("required_live_evidence")
        if not isinstance(required_live, list):
            raise ValueError("Task contract requires a required_live_evidence list")
        required_ids = {
            item.get("id") for item in required_live
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if len(required_ids) != len(required_live):
            raise ValueError("Task contract required_live_evidence entries require unique string ids")
        subject_ids = {item["id"] for item in checkpoint["required_subjects"]}
        missing = required_ids - subject_ids
        if missing:
            raise ValueError(f"Evidence checkpoint omits task-contract evidence: {sorted(missing)[0]}")
    questions = checkpoint.get("blocking_questions", [])
    if questions:
        first = questions[0]
        event = store.append(identity, "blocked_on_user_decision", {
            "question": first["question"],
            "options": first.get("options", []),
            "artifact": str(artifact),
            "checkpoint": args.checkpoint_type,
            "reason": "material_product_semantics",
        })
        emit(event)
        return 3
    event = store.append(identity, "checkpoint_completed", {
        "checkpoint": args.checkpoint_type,
        "artifact": str(artifact),
        "artifact_digest": artifact_digest(artifact),
        "next_step": args.next_step,
    })
    emit(event)
    return 0


def review_packet(args: argparse.Namespace) -> int:
    packet = build_review_packet(
        review_type=args.review_type, artifact=args.artifact.resolve(),
        artifact_version=args.artifact_version, question=args.question,
        constraints=args.constraint, instructions=args.instruction,
        evidence=args.evidence, exclusions=args.exclude,
        task_contract=args.task_contract.resolve() if args.task_contract else None,
        evidence_checkpoint=args.evidence_checkpoint.resolve() if args.evidence_checkpoint else None,
    )
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, sort_keys=True))
    return 0


def review_decision(args: argparse.Namespace) -> int:
    packet = validate_review_packet(_read_json(args.packet))
    decision = validate_decision(_read_json(args.decision), packet)
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision["decision"] == "approved" else 4


def _increment_prerequisites(checkpoint: dict[str, object], state: dict[str, object]) -> None:
    checkpoints = state.get("checkpoints", {})
    for name, digest_field in (
        ("scenario", "scenario_artifact_digest"),
        ("architecture", "architecture_artifact_digest"),
    ):
        prior = checkpoints.get(name, {})
        if prior.get("status") != "completed" or prior.get("artifact_digest") != checkpoint[digest_field]:
            raise ValueError(f"Increment {name} digest does not match completed lifecycle state")
    increments = state.get("increments", {})
    sequence = checkpoint["sequence"]
    if sequence > 1:
        prior = increments.get(str(sequence - 1), {})
        if prior.get("status") != "completed":
            raise ValueError("Previous increment requires approved review before advancing")
    future = [int(item) for item in increments if int(item) > sequence]
    if future:
        raise ValueError("Cannot revise an increment after a later increment exists")


def increment_submit(args: argparse.Namespace) -> int:
    artifact = args.input.resolve()
    checkpoint = validate_increment(_read_json(artifact))
    store = LifecycleStore(args.state_dir)
    identity, state = store.load_attempt()
    if identity.task_ref != args.task_ref:
        raise ValueError("Lifecycle state belongs to a different task")
    _increment_prerequisites(checkpoint, state)
    current = state.get("increments", {}).get(str(checkpoint["sequence"]), {})
    if current.get("status") == "completed":
        raise ValueError("Completed increment cannot be resubmitted")
    event = store.append(identity, "increment_ready_for_review", {
        "increment": str(checkpoint["sequence"]),
        "increment_kind": checkpoint["increment_kind"],
        "artifact": str(artifact),
        "artifact_digest": artifact_digest(artifact),
        "scenario_ids": checkpoint["scenario_ids"],
        "evidence_level": achieved_evidence_level(checkpoint),
    })
    emit(event)
    return 0


def increment_accept(args: argparse.Namespace) -> int:
    artifact = args.input.resolve()
    checkpoint = validate_increment(_read_json(artifact))
    packet = validate_review_packet(_read_json(args.packet))
    decision = validate_decision(_read_json(args.decision), packet)
    if packet["review_type"] != "increment":
        raise ValueError("Increment acceptance requires an increment review packet")
    digest = artifact_digest(artifact)
    if packet["artifact"]["digest"] != digest:
        raise ValueError("Increment review packet does not bind the submitted artifact")
    if packet["artifact"]["version"] != checkpoint["artifact_version"]:
        raise ValueError("Increment review packet version does not match the submitted artifact")
    if decision["decision"] != "approved":
        raise ValueError("Increment requires approved focused review before completion")
    bindings = packet.get("closure_bindings")
    if not isinstance(bindings, dict):
        raise ValueError("Increment acceptance requires task-contract evidence closure bindings")
    contract_path = args.task_contract.resolve()
    evidence_path = args.evidence_checkpoint.resolve()
    if artifact_digest(contract_path) != bindings["task_contract"]["digest"]:
        raise ValueError("Review packet task contract binding is stale")
    if artifact_digest(evidence_path) != bindings["evidence_checkpoint"]["digest"]:
        raise ValueError("Review packet evidence checkpoint binding is stale")
    evidence_checkpoint = validate_evidence_checkpoint(
        _read_json(evidence_path), artifact_root=evidence_path.parent
    )
    if evidence_checkpoint["task_contract_digest"] != artifact_digest(contract_path):
        raise ValueError("Evidence checkpoint does not bind the current task contract")
    evidence_subjects = {item["id"] for item in evidence_checkpoint["required_subjects"]}
    increment_subjects = set(checkpoint["scenario_ids"]) | {
        item["id"] for item in checkpoint["failure_modes"]
    }
    uncovered = increment_subjects - evidence_subjects
    if uncovered:
        raise ValueError(
            f"Evidence checkpoint does not cover increment subject: {sorted(uncovered)[0]}"
        )
    store = LifecycleStore(args.state_dir)
    identity, state = store.load_attempt()
    if identity.task_ref != args.task_ref:
        raise ValueError("Lifecycle state belongs to a different task")
    _increment_prerequisites(checkpoint, state)
    evidence_state = state.get("checkpoints", {}).get("evidence", {})
    if evidence_state.get("status") != "completed" or evidence_state.get("artifact_digest") != artifact_digest(evidence_path):
        raise ValueError("Increment acceptance requires the completed evidence checkpoint")
    pending = state.get("increments", {}).get(str(checkpoint["sequence"]), {})
    if pending.get("status") != "ready_for_review" or pending.get("artifact_digest") != digest:
        raise ValueError("Increment artifact is not the current submitted review candidate")
    event = store.append(identity, "increment_completed", {
        "increment": str(checkpoint["sequence"]),
        "increment_kind": checkpoint["increment_kind"],
        "artifact": str(artifact),
        "artifact_digest": digest,
        "review_artifact_digest": packet["artifact"]["digest"],
        "scenario_ids": checkpoint["scenario_ids"],
        "evidence_level": achieved_evidence_level(checkpoint),
        "next_step": args.next_step,
    })
    emit(event)
    return 0


def context_build(args: argparse.Namespace) -> int:
    packet = build_context_packet(
        role=args.role, purpose=args.purpose, question=args.question,
        artifacts=[path.resolve() for path in args.artifact], evidence=args.evidence,
        exclusions=args.exclude, risks=args.risk,
        artifact_version=args.artifact_version,
    )
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, sort_keys=True))
    return 0


def agent_run(args: argparse.Namespace) -> int:
    packet = validate_context_packet(_read_json(args.packet))
    result = start_codex_owner(
        codex_bin=args.codex_bin, repository=args.repo.resolve(), sandbox=args.sandbox,
        model=args.model, prompt=render_agent_prompt(packet),
        on_process_started=lambda pid: None, on_session_discovered=lambda session: None,
        diagnostics_prefix=args.diagnostics_prefix,
    )
    output: dict[str, object] = {
        "schema_version": "1.0", "runtime": "codex", "role": packet["role"],
        "packet_digest": packet["packet_digest"], "native_session_id": result.native_session_id,
        "exit_code": result.exit_code,
    }
    response_ok = bool(result.final_message)
    if packet["role"] in {"scenario_review", "architecture_review", "diff_review"} and result.final_message:
        try:
            decision = json.loads(result.final_message)
        except json.JSONDecodeError as exc:
            raise ValueError("Bounded review response is not a JSON decision envelope") from exc
        artifact = packet["artifacts"][0]
        review_packet = {
            "schema_version": "1.0", "review_type": packet["decision_review_type"],
            "question": packet["question"],
            "artifact": {"path": artifact["path"], "version": packet["artifact_version"],
                         "digest": artifact["digest"]},
            "original_constraints": [rule for pack in packet["convention_packs"] for rule in pack["rules"]],
            "target_instructions": [packet["purpose"]], "evidence": packet["evidence"],
            "exclusions": packet["exclusions"], "decision_schema_version": "1.0",
        }
        output["decision"] = validate_decision(decision, review_packet)
    else:
        output["response"] = result.final_message
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    return 0 if result.exit_code == 0 and response_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("owner", help="Manage a native Codex owner lifecycle")
    owner_commands = owner.add_subparsers(dest="owner_command", required=True)
    def add_start_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--task-ref", required=True, help="Opaque stable caller task reference")
        command.add_argument("--instruction-file", required=True, type=Path)
        command.add_argument("--artifact", action="append", default=[], type=Path)
        command.add_argument("--repo", required=True, type=Path)
        command.add_argument("--worktree", help="Optional caller-provided worktree identity")
        command.add_argument("--state-dir", required=True, type=Path)
        command.add_argument("--codex-bin", default="codex")
        command.add_argument("--model")
        command.add_argument("--gate", choices=tuple(sorted(GATES)), default="core")
        command.add_argument("--risk", action="append", choices=tuple(sorted(RISKS)), default=[])
        command.add_argument(
            "--sandbox",
            choices=("read-only", "workspace-write", "danger-full-access"),
            default="workspace-write",
        )

    start = owner_commands.add_parser("start", help="Start a new native owner session")
    add_start_arguments(start)
    start.set_defaults(handler=owner_start)
    resume = owner_commands.add_parser("resume", help="Continue the recorded native Codex session")
    resume.add_argument("--task-ref", required=True)
    resume.add_argument("--instruction-file", required=True, type=Path)
    resume.add_argument("--repo", required=True, type=Path)
    resume.add_argument("--state-dir", required=True, type=Path)
    resume.add_argument("--codex-bin", default="codex")
    resume.add_argument("--model")
    resume.add_argument("--gate", choices=tuple(sorted(GATES)), default="core")
    resume.add_argument("--risk", action="append", choices=tuple(sorted(RISKS)), default=[])
    resume.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    resume.set_defaults(handler=owner_resume)
    retry = owner_commands.add_parser("retry", help="Start a new attempt over existing artifacts")
    add_start_arguments(retry)
    retry.add_argument("--previous-state-dir", required=True, type=Path)
    retry.set_defaults(handler=owner_retry)
    checkpoint = commands.add_parser("checkpoint", help="Apply an owner checkpoint contract")
    checkpoint_commands = checkpoint.add_subparsers(dest="checkpoint_type", required=True)
    for checkpoint_type in ("scenario", "architecture", "evidence"):
        command = checkpoint_commands.add_parser(checkpoint_type)
        command.add_argument("--task-ref", required=True)
        command.add_argument("--state-dir", required=True, type=Path)
        command.add_argument("--input", required=True, type=Path)
        command.add_argument("--next-step", required=True)
        if checkpoint_type == "evidence":
            command.add_argument("--task-contract", required=True, type=Path)
        command.set_defaults(handler=checkpoint_apply)
    review = commands.add_parser("review", help="Build and validate bounded review contracts")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    packet = review_commands.add_parser("packet")
    packet.add_argument("--review-type", required=True, choices=("scenario", "architecture", "increment"))
    packet.add_argument("--artifact", required=True, type=Path)
    packet.add_argument("--artifact-version", required=True)
    packet.add_argument("--question", required=True)
    packet.add_argument("--constraint", action="append", required=True)
    packet.add_argument("--instruction", action="append", required=True)
    packet.add_argument("--evidence", action="append", default=[])
    packet.add_argument("--exclude", action="append", required=True)
    packet.add_argument("--output", required=True, type=Path)
    packet.add_argument("--task-contract", type=Path)
    packet.add_argument("--evidence-checkpoint", type=Path)
    packet.set_defaults(handler=review_packet)
    decision = review_commands.add_parser("decision")
    decision.add_argument("--packet", required=True, type=Path)
    decision.add_argument("--decision", required=True, type=Path)
    decision.set_defaults(handler=review_decision)
    increment = commands.add_parser("increment", help="Submit and accept reviewed increments")
    increment_commands = increment.add_subparsers(dest="increment_command", required=True)
    submit = increment_commands.add_parser("submit")
    submit.add_argument("--task-ref", required=True)
    submit.add_argument("--state-dir", required=True, type=Path)
    submit.add_argument("--input", required=True, type=Path)
    submit.set_defaults(handler=increment_submit)
    accept = increment_commands.add_parser("accept")
    accept.add_argument("--task-ref", required=True)
    accept.add_argument("--state-dir", required=True, type=Path)
    accept.add_argument("--input", required=True, type=Path)
    accept.add_argument("--packet", required=True, type=Path)
    accept.add_argument("--decision", required=True, type=Path)
    accept.add_argument("--next-step", required=True)
    accept.add_argument("--task-contract", required=True, type=Path)
    accept.add_argument("--evidence-checkpoint", required=True, type=Path)
    accept.set_defaults(handler=increment_accept)
    context = commands.add_parser("context", help="Build one bounded Codex agent context")
    context.add_argument("--role", required=True, choices=tuple(AGENT_ROLES))
    context.add_argument("--purpose", required=True)
    context.add_argument("--question", required=True)
    context.add_argument("--artifact", action="append", required=True, type=Path)
    context.add_argument("--artifact-version")
    context.add_argument("--evidence", action="append", default=[])
    context.add_argument("--exclude", action="append", required=True)
    context.add_argument("--risk", action="append", choices=tuple(sorted(RISKS)), default=[])
    context.add_argument("--output", required=True, type=Path)
    context.set_defaults(handler=context_build)
    agent = commands.add_parser("agent", help="Explicitly run one bounded Codex agent")
    agent.add_argument("--packet", required=True, type=Path)
    agent.add_argument("--repo", required=True, type=Path)
    agent.add_argument("--output", required=True, type=Path)
    agent.add_argument("--diagnostics-prefix", required=True, type=Path)
    agent.add_argument("--codex-bin", default="codex")
    agent.add_argument("--model")
    agent.add_argument(
        "--sandbox", choices=("read-only", "workspace-write", "danger-full-access"),
        default="read-only",
    )
    agent.set_defaults(handler=agent_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
