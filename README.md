# dev-pipeline

`dev-pipeline` is an experimental, Codex-centered software-development pipeline. One native Codex session owns the path from prepared requirements to implementation evidence. Independent agents are intended for bounded review and verification, not a mandatory document handoff chain.

The current Bootstrap 1 release implements one walking-skeleton operation: start a new owner attempt through the real `codex exec --json` boundary, capture the runtime-emitted native session ID, and persist ordered lifecycle state. Native session resume, retry over existing artifacts, checkpoints, review orchestration, and application-specific adapters are deliberately not implemented yet.

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

## Scope and trust boundary

The pipeline invokes Codex with the requested sandbox and working repository. Review Codex's own authentication, configuration, sandbox, and approval setup before use. Lifecycle state does not store prompts or raw model events, but caller-supplied paths and runtime identifiers are operational metadata and should be protected accordingly.

Application integrations belong outside this repository. An adapter may resolve application-specific tasks and project selected lifecycle events into its own status artifacts, but only this core interprets Codex events and transitions attempt/run state.

See [Architecture](docs/architecture.md), [Lifecycle schema](docs/lifecycle.md), [Contributing](CONTRIBUTING.md), and [Security](SECURITY.md).

## Development

```bash
python -m pip install -e '.[test]'
pytest
```

This project is licensed under the [MIT License](LICENSE).
