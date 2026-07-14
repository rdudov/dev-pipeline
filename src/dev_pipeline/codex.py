"""Native Codex CLI adapter for the initial owner-session start operation."""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CodexStartResult:
    exit_code: int
    native_session_id: str | None
    stderr: str


def build_owner_prompt(task_ref: str, instruction: str, artifacts: list[Path]) -> str:
    artifact_lines = "\n".join(f"- {path}" for path in artifacts) or "- None supplied"
    return f"""You are the continuous engineering owner for prepared task {task_ref}.

Own the causal chain from the supplied requirements through implementation and verification. Work directly in the configured repository. Treat the original instruction and supplied artifacts as durable task input, not as conversation history. Stop and report a concrete question if product semantics are materially ambiguous. Prefer the existing owning component over a parallel mechanism, and verify meaningful behavior through the real entrypoint.

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
) -> CodexStartResult:
    command = [codex_bin, "exec", "--json", "--cd", str(repository), "--sandbox", sandbox]
    if model:
        command.extend(["--model", model])
    command.append("-")
    process = subprocess.Popen(
        command,
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
    stderr_parts: list[str] = []
    assert process.stderr is not None

    def drain_stderr() -> None:
        for chunk in iter(lambda: process.stderr.read(8192), ""):
            stderr_parts.append(chunk)

    stderr_thread = threading.Thread(target=drain_stderr, name="codex-stderr", daemon=True)
    stderr_thread.start()
    assert process.stdout is not None
    try:
        for line in process.stdout:
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
        exit_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        stderr_thread.join()
    return CodexStartResult(
        exit_code=exit_code,
        native_session_id=native_session_id,
        stderr="".join(stderr_parts),
    )
