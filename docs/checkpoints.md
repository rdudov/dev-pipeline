# Checkpoint and review contracts

Machine-facing checkpoint, packet, and decision documents are canonical English JSON using schema version `1.0`. Human translations may explain them but are not parsed as state.

## Scenario checkpoint

A scenario checkpoint contains `artifact_id`, `artifact_version`, `source_refs`, `scenarios`, `reversible_assumptions`, and `blocking_questions`. Each scenario has a unique `id`, `actor`, `trigger`, `expected_outcome`, non-empty behavioral `acceptance`, and a `failure_modes` list.

`blocking_questions` contains unresolved material product semantics. Each item has a concrete `question` and optional choices with `label` and `consequence`. A non-empty list blocks the checkpoint; it is not an assumption list or a general backlog.

## Architecture checkpoint

An architecture checkpoint contains artifact identity and `scenario_artifact_digest`, then requires:

- `production_path`: the real entrypoint/call path being changed;
- `owning_layer`: the existing component responsible for the behavior;
- `reuse_plan`: components and behavior retained;
- `deletion_plan`: superseded paths removed, or an explicit statement that none exists;
- `forbidden_parallel_mechanism`: the duplicate mechanism the increment must avoid;
- `verification_path`: real boundaries that prove the delta;
- `blocking_questions`: unresolved compatibility, migration, source-of-truth, or failure semantics.

These fields are gates, not a generic architecture template. Bootstrap 3 requires bounded scenario and architecture review, but does not decide a universal review policy for future small tasks.

## Bounded review packet

`review packet` accepts only `scenario` or `architecture`. It records one question, the reviewed artifact’s absolute runtime path/version/digest, original constraints, target instructions, evidence, explicit exclusions, and the required decision schema version. The path is caller runtime data and is not embedded in package fixtures or defaults.

The reviewer returns one decision envelope with matching `review_type`, `artifact_version`, and `artifact_digest`; one decision from `approved`, `rework_required`, `blocked`, or `rejected`; evidence-linked findings; blocking questions; and evidence checked. Prose may explain the review but cannot override this envelope. Approval cannot contain findings or blocking questions, and a blocked decision must contain a question.

Review execution remains bounded and external to the core state machine. The core builds and validates contracts; it does not introduce a role pipeline, reviewer scheduler, or runtime plugin abstraction.
