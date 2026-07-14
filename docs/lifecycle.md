# Lifecycle schema

Lifecycle events use schema version `1.0`. `events.jsonl` is authoritative; `state.json` is an atomic derived projection.

Every event contains:

- `schema_version`, `event_id`, monotonically increasing `sequence`, and UTC `timestamp`;
- caller `task_ref`, generated `attempt_id`, and generated `run_id`;
- a neutral `kind` and typed `payload`.

Owner lifecycle event kinds are `attempt_started`, `run_started`, `process_started`, `native_session_discovered`, `native_resume_unavailable`, `run_completed`, `run_failed`, `attempt_completed`, and `attempt_failed`.

The ledger is opened with append semantics while an exclusive store lock is held, the complete JSON line is written (retrying short writes) and synced, and the projection is written to a temporary file, synced, and atomically replaced. On invalid JSON, broken sequence ordering, or an attempt to reuse the directory for a different task/attempt, the store refuses to append. It does not infer or repair identity from partial data.

Run outcome and attempt outcome are distinct. The initial run operation is `native_session_start`, while the attempt origin is `new_owner_session`. These fields are shaped for later continuation without redefining start semantics.

Every attempt records `runtime=codex`. A successful native continuation appends a new `run_id` with `run_operation=native_session_resume` while retaining the attempt and native session IDs. An unavailable continuation leaves the attempt intact and gives the run outcome `native_resume_unavailable`; it does not append another `attempt_started` event.

An explicit retry has `attempt_origin=retry_existing_artifacts`, a new attempt ID, an initial `native_session_start` run, and a caller-selected new state directory. `previous_attempt_id` links it to the prior immutable attempt.

Raw Codex streams are retained per run under `diagnostics/`. They may contain model output and runtime metadata, so operators should protect them like other attempt state. The neutral ledger never derives transitions by reparsing these files.

## Adapter-facing event vocabulary

Every event uses the same versioned envelope. The canonical kinds are owner/run
start and terminal events plus `checkpoint_completed`, `increment_completed`,
and `blocked_on_user_decision`. Checkpoint and increment events name the completed
unit and `next_step`. A blocker carries a concrete `question` and may include
structured `options` (`label` and `consequence`) plus an `artifact` reference.
Failures carry a `reason`.

The validator requires schema version `1.0`, non-empty string identities, a
positive integer sequence, object payloads, kind-specific required strings, and
typed decision options. A decision blocker always points to its relevant
artifact; options are included when the owner has concrete alternatives.

These events are transport-neutral. Product adapters decide which transitions
are worth notifying, resolve authorized destinations, and handle delivery
deduplication. Credentials, chat identifiers, and bot payloads never belong in
this schema.

The derived snapshot includes a `checkpoints` map. A completed checkpoint records
its artifact reference/digest and next step. A material semantic question records
`active_blocker` and does not create a completed checkpoint. The append-only event
ledger remains authoritative; checkpoint JSON stays a caller-owned artifact.

Increment submission emits `increment_ready_for_review` and projects the sequence
as `ready_for_review` with artifact digest, mapped scenarios, and achieved evidence
level. Only a matching approved bounded review permits `increment_completed` and a
`completed` projection. The next sequence cannot advance while its predecessor is
pending review. Increment artifacts and reviewer prose are not independent state
machines; the ledger projection remains authoritative.
