"""Command-line entrypoint for the development pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codex import build_owner_prompt, start_codex_owner
from .lifecycle import LifecycleStore, RunIdentity


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event, sort_keys=True), flush=True)


def owner_start(args: argparse.Namespace) -> int:
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

    identity = RunIdentity.create(args.task_ref)
    store = LifecycleStore(args.state_dir)

    def record(kind: str, payload: dict[str, object] | None = None) -> None:
        emit(store.append(identity, kind, payload))

    record(
        "attempt_started",
        {
            "attempt_origin": "new_owner_session",
            "repository": str(repository),
            "worktree": args.worktree,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("owner", help="Manage a native Codex owner lifecycle")
    owner_commands = owner.add_subparsers(dest="owner_command", required=True)
    start = owner_commands.add_parser("start", help="Start a new native owner session")
    start.add_argument("--task-ref", required=True, help="Opaque stable caller task reference")
    start.add_argument("--instruction-file", required=True, type=Path)
    start.add_argument("--artifact", action="append", default=[], type=Path)
    start.add_argument("--repo", required=True, type=Path)
    start.add_argument("--worktree", help="Optional caller-provided worktree identity")
    start.add_argument("--state-dir", required=True, type=Path)
    start.add_argument("--codex-bin", default="codex")
    start.add_argument("--model")
    start.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    start.set_defaults(handler=owner_start)
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
