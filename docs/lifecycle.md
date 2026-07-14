# Lifecycle schema

Lifecycle events use schema version `1.0`. `events.jsonl` is authoritative; `state.json` is an atomic derived projection.

Every event contains:

- `schema_version`, `event_id`, monotonically increasing `sequence`, and UTC `timestamp`;
- caller `task_ref`, generated `attempt_id`, and generated `run_id`;
- a neutral `kind` and typed `payload`.

Bootstrap 1 event kinds are `attempt_started`, `run_started`, `process_started`, `native_session_discovered`, `run_completed`, `run_failed`, `attempt_completed`, and `attempt_failed`.

The ledger is opened with append semantics while an exclusive store lock is held, the complete JSON line is written (retrying short writes) and synced, and the projection is written to a temporary file, synced, and atomically replaced. On invalid JSON, broken sequence ordering, or an attempt to reuse the directory for a different task/attempt, the store refuses to append. It does not infer or repair identity from partial data.

Run outcome and attempt outcome are distinct. The initial run operation is `native_session_start`, while the attempt origin is `new_owner_session`. These fields are shaped for later continuation without redefining start semantics.
