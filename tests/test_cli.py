from __future__ import annotations

import json
from pathlib import Path

from dev_pipeline import cli
from dev_pipeline.codex import CodexStartResult
from dev_pipeline.codex import start_codex_owner
from dev_pipeline.codex import resume_codex_owner


def base_args(tmp_path: Path) -> list[str]:
    repository = tmp_path / "repo"
    repository.mkdir(exist_ok=True)
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


def test_resume_appends_run_to_same_attempt_and_session(tmp_path, monkeypatch):
    args = base_args(tmp_path)

    def fake_start(**kwargs):
        kwargs["on_process_started"](10)
        kwargs["on_session_discovered"]("session-a")
        return CodexStartResult(0, "session-a", "")

    monkeypatch.setattr(cli, "start_codex_owner", fake_start)
    assert cli.main(args) == 0
    before = json.loads((tmp_path / "state" / "state.json").read_text())
    continuation = tmp_path / "continue.md"
    continuation.write_text("Continue verification.")

    def fake_resume(**kwargs):
        assert kwargs["native_session_id"] == "session-a"
        assert kwargs["sandbox"] == "danger-full-access"
        kwargs["on_process_started"](11)
        return CodexStartResult(0, "session-a", "")

    monkeypatch.setattr(cli, "resume_codex_owner", fake_resume)
    result = cli.main([
        "owner", "resume", "--task-ref", "task-1", "--instruction-file", str(continuation),
        "--repo", str(tmp_path / "repo"), "--state-dir", str(tmp_path / "state"),
        "--sandbox", "danger-full-access",
    ])

    assert result == 0
    after = json.loads((tmp_path / "state" / "state.json").read_text())
    assert after["attempt"]["attempt_id"] == before["attempt"]["attempt_id"]
    assert after["attempt"]["native_session_id"] == "session-a"
    assert after["run"]["run_id"] != before["run"]["run_id"]
    assert after["run"]["run_operation"] == "native_session_resume"


def test_unavailable_resume_does_not_implicitly_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "start_codex_owner", lambda **kwargs: (
        kwargs["on_session_discovered"]("session-a") or CodexStartResult(0, "session-a", "")
    ))
    assert cli.main(base_args(tmp_path)) == 0
    continuation = tmp_path / "continue.md"
    continuation.write_text("Continue.")
    monkeypatch.setattr(cli, "resume_codex_owner", lambda **kwargs: CodexStartResult(1, None, "not found"))

    assert cli.main([
        "owner", "resume", "--task-ref", "task-1", "--instruction-file", str(continuation),
        "--repo", str(tmp_path / "repo"), "--state-dir", str(tmp_path / "state"),
    ]) == 1
    events = [json.loads(line) for line in (tmp_path / "state" / "events.jsonl").read_text().splitlines()]
    assert events[-1]["kind"] == "native_resume_unavailable"
    assert {event["attempt_id"] for event in events} == {events[0]["attempt_id"]}
    assert sum(event["kind"] == "attempt_started" for event in events) == 1


def test_explicit_retry_creates_linked_new_attempt(tmp_path, monkeypatch):
    sessions = iter(("session-a", "session-b"))

    def fake_start(**kwargs):
        session = next(sessions)
        kwargs["on_session_discovered"](session)
        return CodexStartResult(0, session, "")

    monkeypatch.setattr(cli, "start_codex_owner", fake_start)
    assert cli.main(base_args(tmp_path)) == 0
    prior = json.loads((tmp_path / "state" / "state.json").read_text())
    retry_args = base_args(tmp_path)
    retry_args[1] = "retry"
    retry_args[retry_args.index("--state-dir") + 1] = str(tmp_path / "retry-state")
    retry_args.extend(["--previous-state-dir", str(tmp_path / "state")])
    assert cli.main(retry_args) == 0

    retried = json.loads((tmp_path / "retry-state" / "state.json").read_text())
    assert retried["attempt"]["attempt_origin"] == "retry_existing_artifacts"
    assert retried["attempt"]["attempt_id"] != prior["attempt"]["attempt_id"]
    assert retried["attempt"]["previous_attempt_id"] == prior["attempt"]["attempt_id"]
    assert retried["attempt"]["native_session_id"] == "session-b"


def test_real_resume_adapter_constructs_codex_only_command(tmp_path):
    executable = tmp_path / "fake-codex"
    capture = tmp_path / "argv.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(capture)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'opaque-id'}), flush=True)\n"
    )
    executable.chmod(0o755)
    result = resume_codex_owner(
        codex_bin=str(executable), repository=tmp_path, sandbox="danger-full-access", model=None,
        native_session_id="opaque-id", prompt="continue",
        on_process_started=lambda pid: None, on_session_discovered=lambda session: None,
    )
    assert result.exit_code == 0
    assert json.loads(capture.read_text()) == [
        "exec", "--sandbox", "danger-full-access", "resume", "opaque-id", "--json", "-"
    ]


def test_codex_boundary_persists_raw_diagnostics_on_conflicting_identity(tmp_path):
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'first'}), flush=True)\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'second'}), flush=True)\n"
        "print('raw diagnostic', file=sys.stderr, flush=True)\n"
    )
    executable.chmod(0o755)
    prefix = tmp_path / "diagnostics" / "run-1"
    import pytest
    with pytest.raises(RuntimeError, match="conflicting"):
        start_codex_owner(
            codex_bin=str(executable), repository=tmp_path, sandbox="workspace-write",
            model=None, prompt="test", on_process_started=lambda pid: None,
            on_session_discovered=lambda session: None, diagnostics_prefix=prefix,
        )
    assert '"thread_id": "first"' in prefix.with_suffix(".stdout.jsonl").read_text()
    assert prefix.with_suffix(".stderr.log").is_file()
