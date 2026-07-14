# dev-pipeline

`dev-pipeline` is an experimental, Codex-centered software-development pipeline. One native Codex session owns the path from prepared requirements to implementation evidence. Independent agents are intended for bounded review and verification, not a mandatory document handoff chain.

The Bootstrap 2 CLI starts a new owner attempt, genuinely continues its recorded Codex session, or explicitly starts a linked new attempt over existing artifacts. Checkpoints, review orchestration, and application-specific adapters are deliberately not implemented yet.

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

Resume never falls back to start. An unavailable session emits `native_resume_unavailable`; retry records `attempt_origin=retry_existing_artifacts`, a new attempt ID, and a new Codex-issued session ID.

## Scope and trust boundary

The pipeline invokes Codex with the requested sandbox and working repository. Review Codex's own authentication, configuration, sandbox, and approval setup before use. Lifecycle state does not store prompts or raw model events, but caller-supplied paths and runtime identifiers are operational metadata and should be protected accordingly.

Application integrations belong outside this repository. An adapter may resolve application-specific tasks and project selected lifecycle events into its own status artifacts, but only this core interprets Codex events and transitions attempt/run state.

The neutral adapter-facing vocabulary covers meaningful run start, checkpoint or
increment completion, a structured `blocked_on_user_decision`, failure, and
completion. Transport credentials and destination policy remain outside the core.

See [Architecture](docs/architecture.md), [Lifecycle schema](docs/lifecycle.md), [Contributing](CONTRIBUTING.md), and [Security](SECURITY.md).

## Runtime support

This product intentionally supports Codex only. Command construction and native JSON event parsing are localized in `dev_pipeline.codex`. A fork targeting another coding runtime should replace that module and map its real session guarantees into lifecycle outcomes; no drop-in runtime protocol or Cursor/Claude compatibility is promised.

## Development

```bash
python -m pip install -e '.[test]'
pytest
```

This project is licensed under the [MIT License](LICENSE).
