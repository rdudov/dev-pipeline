# dev-pipeline

`dev-pipeline` is an experimental, Codex-centered software-development pipeline. One native Codex session owns the path from prepared requirements to implementation evidence. Independent agents are intended for bounded review and verification, not a mandatory document handoff chain.

The CLI starts a new owner attempt, genuinely continues its recorded Codex session, or explicitly starts a linked new attempt over existing artifacts. It provides compact scenario, architecture, walking-skeleton, and vertical-increment gates, routed convention packs, and bounded review contracts. Application-specific adapters remain outside the public core.

The discoverable [`$dev-pipeline` skill](skills/dev-pipeline/SKILL.md) provides a
compact Codex invocation guide. The CLI and package documentation remain the
canonical workflow and schema authority.

## Requirements

- Python 3.11 or later
- an installed and authenticated Codex CLI
- a prepared instruction file and target Git repository

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

## Start an owner attempt

```bash
dev-pipeline owner start \
  --task-ref issue-123 \
  --instruction-file /path/to/prepared-instruction.md \
  --artifact /path/to/contract.json \
  --repo /path/to/target-repository \
  --state-dir /path/to/caller-owned-state
```

The command emits neutral lifecycle JSONL to stdout and stores `events.jsonl` plus an atomically replaced `state.json` in the caller-selected state directory. The task reference is opaque. Paths are caller values: this package does not discover a task index, prescribe task filenames, or import transport/application policy.

The first attempt always has `attempt_origin=new_owner_session`; the first run always has `run_operation=native_session_start`. A successful start requires a `thread.started` event from Codex. The pipeline never fabricates a native session ID from a process ID or filename.

The owner prompt preserves adjacent production behavior unless the accepted contract explicitly changes it. Compatibility, fallback, parsing, persistence, or delivery-policy expansion requires a concrete blocker rather than an inferred assumption. Task/review/evidence artifacts remain outside the target repository in the caller-owned artifact directory; evidence checkpoints reject absolute or escaping artifact paths.

## Continue or retry

Continue the same attempt and opaque Codex session with a new instruction:

```bash
dev-pipeline owner resume \
  --task-ref issue-123 \
  --instruction-file /path/to/continuation.md \
  --repo /path/to/target-repository \
  --state-dir /path/to/existing-attempt-state
```

If native state is unavailable or intentionally abandoned, retry is a separate explicit operation. It requires a new state directory and links the immutable prior attempt:

```bash
dev-pipeline owner retry \
  --task-ref issue-123 \
  --instruction-file /path/to/prepared-instruction.md \
  --artifact /path/to/contract.json \
  --repo /path/to/target-repository \
  --previous-state-dir /path/to/prior-attempt-state \
  --state-dir /path/to/new-attempt-state
```

Resume never falls back to start. An unavailable session emits `native_resume_unavailable` with a canonical condition (`missing_session_id`, `archived`, `not_found`, `runtime_unavailable`, `missing_runtime_identity`, or `identity_mismatch`); raw Codex output remains localized in diagnostics. Retry records `attempt_origin=retry_existing_artifacts`, a new attempt ID, and a new Codex-issued session ID. Deliberately replacing an available session requires `--retry-reason intentional_replacement`; after a recorded unavailable run, the reason may be inferred as `native_unavailable`.

Historical conditionless unavailability events remain readable as legacy/unclassified append-only history, but cannot authorize automatic retry or condition-specific behavior. Every newly appended event requires a canonical condition.

## Scenario and architecture checkpoints

Checkpoint artifacts are canonical English JSON objects with schema version `1.0`. Apply a scenario checkpoint to an existing owner attempt with:

```bash
dev-pipeline checkpoint scenario \
  --task-ref issue-123 \
  --state-dir /path/to/existing-attempt-state \
  --input /path/to/scenario-checkpoint.json \
  --next-step "Run bounded scenario review"
```

Use `checkpoint architecture` for the architecture delta. Scenario records require actors, triggers, expected outcomes, behavioral acceptance, failure modes, assumptions, and explicit blocking questions. Architecture records require the production path, owning layer, reuse plan, deletion plan, forbidden parallel mechanism, verification path, and a digest link to the scenario artifact.

Before accepting an increment, use `checkpoint evidence` with the current task contract. The checkpoint inventories mandatory scenarios, failure modes and production branches; binds exact argv-style commands, representative fixtures, real production entrypoints and digest-verified artifacts; and rejects weak, stale, aggregate-only, mock/stub/fake/harness-only evidence. Product work also declares intended jobs and a generic capability matrix covering input, processing environment, dependency policy, output, multi-artifact delivery, validation/completeness and safety. Unsupported capabilities are explicit constraints or blockers, never silent omissions.

When an increment creates or changes infrastructure, apply `checkpoint deployment` before claiming deployed evidence. The deployment artifact binds the exact increment, evidence checkpoint and source revision; declares every supported resource, update, readiness and rollback category applicable or not applicable; and requires tracked bootstrap, disposable clean-environment evidence, drift detection and durable-root backup/restore integrity. A live smoke on an already-mutated host is not reproducible deployed evidence. `increment accept --deployment-checkpoint ...` is mandatory for an increment whose achieved evidence level is `deployed`.

An unresolved material question emits `blocked_on_user_decision`, persists an active blocker, and exits with status 3 without completing the checkpoint. A complete contract emits `checkpoint_completed` with its artifact digest. The command validates owner artifacts; it does not infer product semantics from prose.

Build a bounded review packet with `dev-pipeline review packet`. For increment closure, pass both `--task-contract` and `--evidence-checkpoint`; their SHA-256 digests become closure bindings. The command also binds the review question, constraints, target instructions, exclusions, artifact version, and reviewed-artifact digest. Validate the reviewer’s single structured envelope with `dev-pipeline review decision`; only `approved`, `rework_required`, `blocked`, and `rejected` are accepted. A stale artifact digest or an “approved” envelope hiding findings is rejected. Non-approved decisions exit with status 4.

## Walking skeleton and vertical increments

Submit the first observable increment after scenario and architecture checkpoints:

```bash
dev-pipeline increment submit \
  --task-ref issue-123 \
  --state-dir /path/to/existing-attempt-state \
  --input /path/to/increment-1.json
```

The first increment must be `walking_skeleton`; later increments must be `vertical_increment`. Each maps named scenarios and failure modes to required evidence, records source/deletion deltas, and identifies temporary seams. Stubs and temporary adapters are permitted only at a `new_boundary` or `unavailable_external` boundary. Each has a stable ID and later replacement increment; advancement at that milestone requires recorded removal backed by passed real-entrypoint evidence.

Legacy seam-bearing artifacts without those canonical fields are rejected without inference or rewriting. Historical seam-free increment artifacts remain compatible.

Evidence levels are ordered `structural`, `unit`, `skeleton`, `integrated`, `live`, and `deployed`. Structural and unit evidence may support development but cannot satisfy an increment gate. The walking skeleton requires at least real-entrypoint skeleton evidence; vertical increments require at least integrated evidence. Every named scenario and failure mode must be covered by passing required evidence.

Submission records `increment_ready_for_review`. Build an `increment` review packet for that exact artifact, then accept it with the approved envelope:

```bash
dev-pipeline increment accept \
  --task-ref issue-123 \
  --state-dir /path/to/existing-attempt-state \
  --input /path/to/increment-1.json \
  --packet /path/to/increment-review-packet.json \
  --decision /path/to/increment-review-decision.json \
  --task-contract /path/to/task-contract.json \
  --evidence-checkpoint /path/to/evidence.json \
  --next-step "Build vertical increment 2"
```

A rework, blocked, rejected, stale, or mismatched decision cannot complete the increment. The next increment cannot be submitted until the preceding one has approved review, and a completed increment cannot be reopened through resubmission.

## Routed conventions and selective agents

Owner start/resume accepts one `--gate` and repeated explicitly triggered `--risk` values. The default owner context is the compact core pack only. It never aggregates the frozen legacy analyst/architect/planner/developer prompts.

`dev-pipeline context` builds one digest-bound English context for a bounded `scout`, `scenario_review`, `architecture_review`, `diff_review`, or `live_verification`. `dev-pipeline agent` explicitly runs that one packet through Codex, normally read-only. These commands do not create a scheduler or mandatory role chain. See [Routed conventions](docs/conventions.md).

## Scope and trust boundary

The pipeline invokes Codex with the requested sandbox and working repository. Review Codex's own authentication, configuration, sandbox, and approval setup before use. Lifecycle state does not store prompts or raw model events, but caller-supplied paths and runtime identifiers are operational metadata and should be protected accordingly.

Application integrations belong outside this repository. An adapter may resolve application-specific tasks and project selected lifecycle events into its own status artifacts, but only this core interprets Codex events and transitions attempt/run state.

The neutral adapter-facing vocabulary covers meaningful run start, checkpoint or
increment completion, a structured `blocked_on_user_decision`, failure, and
completion. Transport credentials and destination policy remain outside the core.

See [Architecture](docs/architecture.md), [Lifecycle schema](docs/lifecycle.md), [Checkpoint contracts](docs/checkpoints.md), [Increment lifecycle](docs/increments.md), [Routed conventions](docs/conventions.md), [Contributing](CONTRIBUTING.md), and [Security](SECURITY.md).

## Runtime support

This product intentionally supports Codex only. Command construction and native JSON event parsing are localized in `dev_pipeline.codex`. A fork targeting another coding runtime should replace that module and map its real session guarantees into lifecycle outcomes; no drop-in runtime protocol or Cursor/Claude compatibility is promised.

## Development

```bash
python -m pip install -e '.[test]'
pytest
```

This project is licensed under the [MIT License](LICENSE).
