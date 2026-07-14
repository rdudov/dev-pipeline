from __future__ import annotations

import json

import pytest

from dev_pipeline import lifecycle
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity
from dev_pipeline.events import validate_event

START_PAYLOAD = {"attempt_origin": "new_owner_session", "repository": "/example"}


def test_store_orders_events_and_projects_separate_outcomes(tmp_path):
    store = LifecycleStore(tmp_path)
    identity = RunIdentity.create("example-task")

    first = store.append(
        identity,
        "attempt_started",
        {"attempt_origin": "new_owner_session", "repository": "/example"},
    )
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "session-1"})
    store.append(identity, "run_completed", {"exit_code": 0})
    last = store.append(identity, "attempt_completed")

    assert first["sequence"] == 1
    assert last["sequence"] == 5
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["attempt"]["outcome"] == "completed"
    assert state["attempt"]["native_session_id"] == "session-1"
    assert state["run"]["outcome"] == "completed"
    assert state["run"]["run_operation"] == "native_session_start"


def test_store_refuses_to_advance_corrupt_ledger(tmp_path):
    (tmp_path / "events.jsonl").write_text('{"sequence": 1}\nnot-json\n')
    store = LifecycleStore(tmp_path)

    with pytest.raises(RuntimeError, match="corrupt at line 2"):
        store.append(RunIdentity.create("example-task"), "attempt_started", START_PAYLOAD)

    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2


def test_store_rejects_reuse_by_another_attempt(tmp_path):
    store = LifecycleStore(tmp_path)
    first = RunIdentity.create("example-task")
    store.append(first, "attempt_started", START_PAYLOAD)

    with pytest.raises(RuntimeError, match="different attempt"):
        store.append(RunIdentity.create("example-task"), "attempt_started", START_PAYLOAD)

    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_store_retries_short_writes(tmp_path, monkeypatch):
    real_write = lifecycle.os.write
    write_sizes: list[int] = []

    def short_write(descriptor, content):
        limited = content[: max(1, len(content) // 2)]
        written = real_write(descriptor, limited)
        write_sizes.append(written)
        return written

    monkeypatch.setattr(lifecycle.os, "write", short_write)
    store = LifecycleStore(tmp_path)
    event = store.append(RunIdentity.create("example-task"), "attempt_started", START_PAYLOAD)

    assert len(write_sizes) > 1
    assert json.loads((tmp_path / "events.jsonl").read_text()) == event


def test_neutral_checkpoint_and_hitl_vocabulary_is_adapter_safe(tmp_path):
    store = LifecycleStore(tmp_path)
    identity = RunIdentity.create("task-360")
    store.append(identity, "attempt_started", START_PAYLOAD)
    checkpoint = store.append(
        identity,
        "checkpoint_completed",
        {"checkpoint": "architecture", "next_step": "Build the walking skeleton"},
    )
    blocked = store.append(
        identity,
        "blocked_on_user_decision",
        {
            "question": "Which rollout policy should apply?",
            "options": [{"label": "Opt in", "consequence": "Existing default stays unchanged"}],
            "artifact": "architecture-delta.md",
        },
    )

    assert validate_event(checkpoint)["kind"] == "checkpoint_completed"
    assert validate_event(blocked)["payload"]["question"].startswith("Which")


def test_event_vocabulary_rejects_incomplete_hitl_payload(tmp_path):
    store = LifecycleStore(tmp_path)
    identity = RunIdentity.create("task-360")

    with pytest.raises(ValueError, match="requires non-empty question"):
        store.append(identity, "blocked_on_user_decision", {"artifact": "plan.md"})


@pytest.mark.parametrize(
    "field,value",
    [("sequence", 0), ("schema_version", "2.0"), ("task_ref", 7)],
)
def test_event_envelope_rejects_invalid_types(field, value):
    event = {
        "schema_version": "1.0", "event_id": "event-1", "sequence": 1,
        "timestamp": "2026-07-14T00:00:00+00:00", "task_ref": "task-1",
        "attempt_id": "attempt-1", "run_id": "run-1", "kind": "attempt_started", "payload": {},
    }
    event[field] = value

    with pytest.raises(ValueError):
        validate_event(event)


@pytest.mark.parametrize(
    "kind,payload",
    [("native_session_discovered", {}), ("process_started", {"pid": "7"}), ("run_completed", {})],
)
def test_existing_event_kinds_require_typed_payloads(tmp_path, kind, payload):
    with pytest.raises(ValueError):
        LifecycleStore(tmp_path).append(RunIdentity.create("task-1"), kind, payload)
