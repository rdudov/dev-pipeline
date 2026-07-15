"""Localized command and event boundary for native Codex owner sessions."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CodexStartResult:
    exit_code: int
    native_session_id: str | None
    stderr: str
    stdout: str = ""
    final_message: str | None = None
    resume_unavailability: str | None = None


def build_owner_prompt(
    task_ref: str, instruction: str, artifacts: list[Path], conventions: str = ""
) -> str:
    artifact_lines = "\n".join(f"- {path}" for path in artifacts) or "- None supplied"
    return f"""You are the continuous engineering owner for prepared task {task_ref}.

Own the causal chain from the supplied requirements through implementation and verification. Work directly in the configured repository. Treat the original instruction and supplied artifacts as durable task input, not as conversation history. Stop and report a concrete question if product semantics are materially ambiguous. Prefer the existing owning component over a parallel mechanism, and verify meaningful behavior through the real entrypoint.

{conventions}

Original instruction:
{instruction}

Caller-supplied artifact references:
{artifact_lines}
"""


def start_codex_owner(
    *,
    codex_bin: str,
    repository: Path,
    sandbox: str,
    model: str | None,
    prompt: str,
    on_process_started: Callable[[int], None],
    on_session_discovered: Callable[[str], None],
    diagnostics_prefix: Path | None = None,
) -> CodexStartResult:
    command = [codex_bin, "exec", "--json", "--cd", str(repository), "--sandbox", sandbox]
    if model:
        command.extend(["--model", model])
    command.append("-")
    return _run_codex(command, repository, prompt, on_process_started, on_session_discovered, diagnostics_prefix)


def resume_codex_owner(
    *,
    codex_bin: str,
    repository: Path,
    sandbox: str,
    model: str | None,
    native_session_id: str,
    prompt: str,
    on_process_started: Callable[[int], None],
    on_session_discovered: Callable[[str], None],
    diagnostics_prefix: Path | None = None,
) -> CodexStartResult:
    """Resume exactly one opaque Codex session; never falls back to a new session."""
    command = [
        codex_bin,
        "exec",
        "--sandbox",
        sandbox,
        "resume",
        native_session_id,
        "--json",
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")
    result = _run_codex(
        command, repository, prompt, on_process_started, on_session_discovered,
        diagnostics_prefix,
    )
    if result.exit_code == 0:
        return result
    stderr = result.stderr.lower()
    if " is archived" in stderr and "unarchive" in stderr:
        condition = "archived"
    elif "no rollout found for thread id" in stderr:
        condition = "not_found"
    else:
        condition = "runtime_unavailable"
    return CodexStartResult(
        exit_code=result.exit_code,
        native_session_id=result.native_session_id,
        stderr=result.stderr,
        stdout=result.stdout,
        final_message=result.final_message,
        resume_unavailability=condition,
    )


def _run_codex(
    command: list[str],
    repository: Path,
    prompt: str,
    on_process_started: Callable[[int], None],
    on_session_discovered: Callable[[str], None],
    diagnostics_prefix: Path | None,
) -> CodexStartResult:
    process = subprocess.Popen(
        command,
        cwd=repository,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    on_process_started(process.pid)
    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()

    native_session_id: str | None = None
    final_message: str | None = None
    stderr_parts: list[str] = []
    stdout_parts: list[str] = []
    assert process.stderr is not None

    def drain_stderr() -> None:
        for chunk in iter(lambda: process.stderr.read(8192), ""):
            stderr_parts.append(chunk)

    stderr_thread = threading.Thread(target=drain_stderr, name="codex-stderr", daemon=True)
    stderr_thread.start()
    assert process.stdout is not None
    failure: tuple[type[BaseException], BaseException, object] | None = None
    exit_code = -1
    try:
        for line in process.stdout:
            stdout_parts.append(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                discovered = event["thread_id"]
                if native_session_id is None:
                    native_session_id = discovered
                    on_session_discovered(discovered)
                elif discovered != native_session_id:
                    process.kill()
                    raise RuntimeError("Codex emitted conflicting native session identifiers")
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                final_message = item["text"]
        exit_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        failure = sys.exc_info()
    finally:
        stderr_thread.join()
        if diagnostics_prefix is not None:
            diagnostics_prefix.parent.mkdir(parents=True, exist_ok=True)
            diagnostics_prefix.with_suffix(".stdout.jsonl").write_text(
                "".join(stdout_parts), encoding="utf-8"
            )
            diagnostics_prefix.with_suffix(".stderr.log").write_text(
                "".join(stderr_parts), encoding="utf-8"
            )
    if failure is not None:
        _, error, traceback = failure
        raise error.with_traceback(traceback)  # type: ignore[arg-type]
    return CodexStartResult(
        exit_code=exit_code,
        native_session_id=native_session_id,
        stderr="".join(stderr_parts),
        stdout="".join(stdout_parts),
        final_message=final_message,
    )
