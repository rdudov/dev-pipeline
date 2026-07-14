"""Crash-conservative lifecycle persistence for owner attempts and runs."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import EVENT_KINDS, validate_event


SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunIdentity:
    task_ref: str
    attempt_id: str
    run_id: str

    @classmethod
    def create(cls, task_ref: str) -> "RunIdentity":
        return cls(
            task_ref=task_ref,
            attempt_id=f"attempt_{uuid.uuid4().hex}",
            run_id=f"run_{uuid.uuid4().hex}",
        )

    def next_run(self) -> "RunIdentity":
        return RunIdentity(self.task_ref, self.attempt_id, f"run_{uuid.uuid4().hex}")


class LifecycleStore:
    """Append events under a lock and atomically replace a derived snapshot."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.ledger_path = self.root / "events.jsonl"
        self.snapshot_path = self.root / "state.json"
        self.lock_path = self.root / ".lock"
        self.root.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        identity: RunIdentity,
        kind: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        if kind not in EVENT_KINDS:
            raise ValueError(f"Unsupported lifecycle event kind: {kind}")
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            events = self._read_events_unlocked()
            self._validate_identity(events, identity)
            event = {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"event_{uuid.uuid4().hex}",
                "sequence": len(events) + 1,
                "timestamp": utc_now(),
                "task_ref": identity.task_ref,
                "attempt_id": identity.attempt_id,
                "run_id": identity.run_id,
                "kind": kind,
                "payload": payload,
            }
            validate_event(event)
            encoded = (json.dumps(event, sort_keys=True) + "\n").encode()
            descriptor = os.open(
                self.ledger_path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("Lifecycle ledger write made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            events.append(event)
            self._write_snapshot_unlocked(self._project(events))
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return event

    def load_attempt(self) -> tuple[RunIdentity, dict[str, Any]]:
        """Load a complete, internally consistent attempt without repairing it."""
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            events = self._read_events_unlocked()
            if not events:
                raise RuntimeError("Lifecycle state has no attempt to continue")
            for event in events:
                validate_event(event)
            snapshot = self._project(events)
            if not self.snapshot_path.is_file():
                raise RuntimeError("Lifecycle state snapshot is missing; refusing ambiguous continuation")
            persisted = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if persisted != snapshot:
                raise RuntimeError("Lifecycle state snapshot diverges from its ledger; refusing continuation")
            attempt = snapshot["attempt"]
            required = ("attempt_id", "runtime", "repository", "native_session_id")
            missing = [field for field in required if not attempt.get(field)]
            if missing:
                raise RuntimeError(f"Lifecycle attempt is missing {missing[0]}; refusing continuation")
            if attempt["runtime"] != "codex":
                raise RuntimeError("Lifecycle attempt is not a Codex attempt")
            identity = RunIdentity(events[0]["task_ref"], attempt["attempt_id"], events[-1]["run_id"])
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return identity, snapshot

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.ledger_path.open(encoding="utf-8") as ledger:
            for line_number, line in enumerate(ledger, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Lifecycle ledger is corrupt at line {line_number}; refusing to advance state"
                    ) from exc
                expected = len(events) + 1
                if event.get("sequence") != expected:
                    raise RuntimeError(
                        f"Lifecycle ledger sequence is invalid at line {line_number}; refusing to advance state"
                    )
                events.append(event)
        return events

    @staticmethod
    def _validate_identity(events: list[dict[str, Any]], identity: RunIdentity) -> None:
        if not events:
            return
        first = events[0]
        if first.get("task_ref") != identity.task_ref:
            raise RuntimeError("Lifecycle store is bound to a different task; refusing to merge identity")
        if first.get("attempt_id") != identity.attempt_id:
            raise RuntimeError("Lifecycle store is bound to a different attempt; refusing to merge identity")

    def _write_snapshot_unlocked(self, snapshot: dict[str, Any]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".state.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                json.dump(snapshot, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.snapshot_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _project(events: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "last_sequence": 0,
            "task_ref": None,
            "attempt": {},
            "run": {},
        }
        for event in events:
            payload = event["payload"]
            snapshot["last_sequence"] = event["sequence"]
            snapshot["task_ref"] = event["task_ref"]
            snapshot["updated_at"] = event["timestamp"]
            attempt = snapshot["attempt"]
            if snapshot["run"].get("run_id") != event["run_id"]:
                snapshot["run"] = {"run_id": event["run_id"]}
            run = snapshot["run"]
            attempt.setdefault("attempt_id", event["attempt_id"])
            if event["kind"] == "attempt_started":
                attempt.update(payload)
                attempt["outcome"] = "active"
            elif event["kind"] == "run_started":
                run.update(payload)
                run["outcome"] = "running"
                attempt["outcome"] = "active"
            elif event["kind"] == "process_started":
                run.update(payload)
            elif event["kind"] == "native_session_discovered":
                attempt["native_session_id"] = payload["native_session_id"]
            elif event["kind"] == "run_completed":
                run.update(payload)
                run["outcome"] = "completed"
            elif event["kind"] == "run_failed":
                run.update(payload)
                run["outcome"] = "failed"
            elif event["kind"] == "native_resume_unavailable":
                run.update(payload)
                run["outcome"] = "native_resume_unavailable"
            elif event["kind"] == "attempt_completed":
                attempt.update(payload)
                attempt["outcome"] = "completed"
            elif event["kind"] == "attempt_failed":
                attempt.update(payload)
                attempt["outcome"] = "failed"
            elif event["kind"] == "checkpoint_completed":
                snapshot.setdefault("checkpoints", {})[payload["checkpoint"]] = {
                    "status": "completed",
                    "artifact": payload.get("artifact"),
                    "artifact_digest": payload.get("artifact_digest"),
                    "next_step": payload["next_step"],
                }
                blocker = snapshot.get("active_blocker", {})
                if blocker.get("checkpoint") == payload["checkpoint"]:
                    snapshot.pop("active_blocker", None)
            elif event["kind"] == "blocked_on_user_decision":
                snapshot["active_blocker"] = payload
            elif event["kind"] == "increment_ready_for_review":
                snapshot.setdefault("increments", {})[payload["increment"]] = {
                    **payload,
                    "status": "ready_for_review",
                }
            elif event["kind"] == "increment_completed":
                snapshot.setdefault("increments", {})[payload["increment"]] = {
                    **payload,
                    "status": "completed",
                }
        return snapshot
