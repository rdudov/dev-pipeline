from __future__ import annotations

import json
from pathlib import Path

from dev_pipeline import cli
from dev_pipeline.codex import CodexStartResult
from dev_pipeline.codex import start_codex_owner


def base_args(tmp_path: Path) -> list[str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    instruction = tmp_path / "instruction.md"
    instruction.write_text("Inspect the repository and report success.")
    return [
        "owner",
        "start",
        "--task-ref",
        "task-1",
        "--instruction-file",
        str(instruction),
        "--repo",
        str(repository),
        "--state-dir",
        str(tmp_path / "state"),
    ]


def test_owner_start_requires_runtime_session_identity(tmp_path, monkeypatch):
    def fake_start(**kwargs):
        kwargs["on_process_started"](123)
        return CodexStartResult(exit_code=0, native_session_id=None, stderr="")

    monkeypatch.setattr(cli, "start_codex_owner", fake_start)
    result = cli.main(base_args(tmp_path))

    assert result == 1
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["attempt"]["outcome"] == "failed"
    assert "without emitting" in state["attempt"]["reason"]


def test_owner_start_records_runtime_identity_and_terminal_outcomes(tmp_path, monkeypatch):
    def fake_start(**kwargs):
        kwargs["on_process_started"](456)
        kwargs["on_session_discovered"]("runtime-session")
        return CodexStartResult(exit_code=0, native_session_id="runtime-session", stderr="")

    monkeypatch.setattr(cli, "start_codex_owner", fake_start)
    result = cli.main(base_args(tmp_path))

    assert result == 0
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["attempt"]["native_session_id"] == "runtime-session"
    assert state["attempt"]["outcome"] == "completed"
    assert state["run"]["outcome"] == "completed"


def test_codex_adapter_drains_large_stderr_without_deadlock(tmp_path):
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('x' * 200_000)\n"
        "sys.stderr.flush()\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'runtime-session'}), flush=True)\n"
    )
    executable.chmod(0o755)
    sessions: list[str] = []

    result = start_codex_owner(
        codex_bin=str(executable),
        repository=tmp_path,
        sandbox="workspace-write",
        model=None,
        prompt="test",
        on_process_started=lambda pid: None,
        on_session_discovered=sessions.append,
    )

    assert result.exit_code == 0
    assert result.native_session_id == "runtime-session"
    assert len(result.stderr) == 200_000
    assert sessions == ["runtime-session"]
