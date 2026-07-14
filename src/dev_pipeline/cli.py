"""Command-line entrypoint for the development pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codex import build_owner_prompt, resume_codex_owner, start_codex_owner
from .lifecycle import LifecycleStore, RunIdentity


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
    prompt = instruction_file.read_text(encoding="utf-8")
    expected_session = attempt["native_session_id"]
    try:
        result = resume_codex_owner(
            codex_bin=args.codex_bin,
            repository=repository,
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
    resume.set_defaults(handler=owner_resume)
    retry = owner_commands.add_parser("retry", help="Start a new attempt over existing artifacts")
    add_start_arguments(retry)
    retry.add_argument("--previous-state-dir", required=True, type=Path)
    retry.set_defaults(handler=owner_retry)
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
