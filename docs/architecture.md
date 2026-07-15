# Architecture

## Ownership model

The public core owns validation, Codex process launch, native event parsing, owner attempt/run transitions, persistence, and CLI exit semantics. Native Codex owns conversation history and session storage. The target Git worktree owns source state. Caller-owned artifacts retain requirements and evidence.

Callers supply values through the CLI:

- an opaque `task_ref`;
- a prepared instruction file and optional artifact references;
- the target repository and optional worktree identity;
- a writable lifecycle state directory;
- Codex launch configuration.

The core neither scans an application task index nor assumes application filenames. It has no Telegram, credential-routing, authorization, or destination-policy behavior. A companion or product adapter depends on the public core and may project neutral events; the dependency never points back into that product.

## Owner flow

1. Validate caller paths and create immutable attempt/run identifiers.
2. Append `attempt_started` and `run_started` records.
3. launch `codex exec --json` in the supplied repository.
4. Append the process ID and the runtime-emitted `thread_id` when observed.
5. Record run and attempt outcomes separately.

Continuation loads and validates the ledger plus its atomic projection, creates a new run ID on the same attempt, and invokes `codex exec resume <opaque-id> --json`. A missing saved ID is rejected before process launch. The runtime-reported identity must equal the recorded identity. A non-zero exit, missing identity, or changed identity produces `native_resume_unavailable` with a canonical condition and never launches a replacement session. Parsing archived/not-found/runtime failures remains localized in `dev_pipeline.codex`.

Ledger loading alone permits historical conditionless unavailability events for compatibility. They remain unclassified and inert; strict append validation requires every newly emitted unavailability event to carry a canonical condition.

The Codex boundary durably writes each run's raw stdout JSONL and stderr beneath the attempt state's `diagnostics/` directory, including parser/conflicting-identity exception paths. These files are operator diagnostics, not lifecycle input; adapters and lifecycle projection do not parse them.

Explicit retry uses the ordinary start boundary but writes a caller-selected new state directory with a new attempt/session identity and `attempt_origin=retry_existing_artifacts`. Its `previous_attempt_id` links the immutable prior attempt. Retry after recorded unavailability uses `retry_reason=native_unavailable`; replacing an available session requires explicit `intentional_replacement`. Corrupt or divergent prior state remains refused rather than inferred.

The native session ID is accepted only from a `thread.started` JSON event. A non-zero process exit or a zero exit without that event fails both the run and current attempt visibly.

## Bootstrap 1A event boundary

The core defines and validates a compact neutral vocabulary for start,
checkpoint/increment progress, human-decision blockers, failure, and completion.
It does not select notification destinations or deliver messages. External
adapters subscribe to emitted JSONL and retain their own projection/delivery
cursor. Later checkpoint orchestration will produce the corresponding events;
defining the vocabulary does not prematurely implement those gates.

## Deferred behavior

Checkpoint schemas, bounded review, convention routing, richer recovery operations, and adapters are later vertical increments.
