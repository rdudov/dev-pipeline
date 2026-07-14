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

## Bootstrap 1 flow

1. Validate caller paths and create immutable attempt/run identifiers.
2. Append `attempt_started` and `run_started` records.
3. launch `codex exec --json` in the supplied repository.
4. Append the process ID and the runtime-emitted `thread_id` when observed.
5. Record run and attempt outcomes separately.

The native session ID is accepted only from a `thread.started` JSON event. A non-zero process exit or a zero exit without that event fails both the run and current attempt visibly.

## Bootstrap 1A event boundary

The core defines and validates a compact neutral vocabulary for start,
checkpoint/increment progress, human-decision blockers, failure, and completion.
It does not select notification destinations or deliver messages. External
adapters subscribe to emitted JSONL and retain their own projection/delivery
cursor. Later checkpoint orchestration will produce the corresponding events;
defining the vocabulary does not prematurely implement those gates.

## Deferred behavior

Native resume and retry are intentionally absent. A future native resume will append a new run to the same attempt and prove the same runtime session identity. A retry over existing artifacts will create a new attempt and new session; it will never be labeled resume. Checkpoint schemas, bounded review, convention routing, recovery operations, and adapters are later vertical increments.
