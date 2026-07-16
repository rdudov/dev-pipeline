# Checkpoint and review contracts

Machine-facing checkpoint, packet, and decision documents are canonical English JSON using schema version `1.0`. Human translations may explain them but are not parsed as state.

## Scenario checkpoint

A scenario checkpoint contains `artifact_id`, `artifact_version`, `source_refs`, `dependency_inventory`, `scenarios`, `production_branches`, `product_intent`, `reversible_assumptions`, and `blocking_questions`. Each scenario has a unique `id`, `actor`, `trigger`, `expected_outcome`, non-empty behavioral `acceptance`, and a `failure_modes` list. The scenario-owned branch inventory records each mode, boundary, expected behavior, applicability and named failure modes, including permitted/denied isolation classification. `product_intent` records generic intent categories and whether a capability matrix applies.

`dependency_inventory` is a completeness gate produced from discovery evidence. It contains exactly one entry for every supported cross-cutting surface: source repositories, runtime entrypoints, services/processes, containers/images, host identities/permissions, configuration/secrets, durable storage, backup/restore/retention, deployment/update/rollback, observability, network, scheduled jobs, external integrations, and security boundaries. Each entry records `applicability` (`applicable` or `not_applicable`), the `owner`, non-empty `evidence_refs`, and `change_impact`. “Not applicable” is an evidenced conclusion, not permission to omit the surface. An unknown owner or missing evidence must become a blocking question instead of an assumption.

`blocking_questions` contains unresolved material product semantics. Each item has a concrete `question` and optional choices with `label` and `consequence`. A non-empty list blocks the checkpoint; it is not an assumption list or a general backlog.

## Architecture checkpoint

An architecture checkpoint contains artifact identity and `scenario_artifact_digest`, then requires:

- `production_path`: the real entrypoint/call path being changed;
- `owning_layer`: the existing component responsible for the behavior;
- `reuse_plan`: components and behavior retained;
- `deletion_plan`: superseded paths removed, or an explicit statement that none exists;
- `forbidden_parallel_mechanism`: the duplicate mechanism the increment must avoid;
- `verification_path`: real boundaries that prove the delta;
- `isolation_boundaries`: zero or more security boundaries, each naming its production boundary, allowed and denied operations, and one or more `safe_negative_probes` with the operation, expected denial, safety basis, and evidence path;
- `blocking_questions`: unresolved compatibility, migration, source-of-truth, or failure semantics.

Whenever discovery marks a security boundary applicable, architecture and live review must require an isolation-boundary record. A safe negative probe uses only disposable test markers, denied reads, or harmless writes. It must not delete or overwrite production data, alter permissions, signal processes, restart services, or execute a destructive operation in the hope that the boundary rejects it. Positive-path evidence cannot close that gate.

These fields are gates, not a generic architecture template. Bootstrap 3 requires bounded scenario and architecture review, but does not decide a universal review policy for future small tasks.

## Bounded review packet

`review packet` accepts `scenario`, `architecture`, or `increment`. It records one question, the reviewed artifact’s absolute runtime path/version/digest, original constraints, target instructions, evidence, explicit exclusions, and the required decision schema version. Increment closure additionally binds the task contract and evidence-checkpoint digests. Paths are caller runtime data and are not embedded in package fixtures or defaults.

## Test and evidence checkpoint

`checkpoint evidence` is the owning acceptance-evidence gate. It requires completed scenario and architecture digests plus the current task-contract digest. Its `required_subjects` and individual evidence records bind mandatory scenarios and failure modes to exact commands, representative fixtures, real production entrypoints, observed behavior and durable SHA-256 artifacts. Prompt-substring assertions and parser-mechanics-only checks honestly declare a weak `structural` or `unit` level and cannot close behavioral acceptance. One-off and test-only scripts declare `entrypoint.real=false` or `entrypoint.production_boundary=false` and cannot stand in for the production entrypoint. These structured fields, rather than claims in `observed_behavior`, determine eligibility. Scenario-owned branch and product-intent digests prevent the evidence author from narrowing applicability. Each evidence record binds exactly one branch, and one artifact cannot close different branches. Every isolation boundary requires distinct permitted and harmless denied evidence; denied probes declare a safety basis, disposable fixture and preservation of production state.

## Infrastructure and deployment checkpoint

`checkpoint deployment` is required before an applicable increment can claim `deployed` evidence. It binds the increment, its complete deployment-impact inventory, completed scenario/architecture/evidence checkpoints and a digest-verified source-artifact manifest whose canonical digest is the source revision. Fixed inventories cover packages, Unix identities, containers/images, services, host directories, durable roots, credential bindings, network policy, schedulers and backup ownership; source sync, image rebuild, data migration, restart/reload and no-op updates; readiness branches; and service/image/identity/host-resource/uninstall rollback. Every category is explicitly `applicable` or `not_applicable`, with an owner, rationale and evidence. The deployment resource applicability must exactly match the reviewed increment inventory.

An applicable deployment requires digest-verified tracked artifacts and runtime inventory, resource-specific update/readiness/rollback mappings, a disposable clean-environment bootstrap, drift detection, and distinct permitted and denied pre-mutation readiness executions. The minimum mappings prevent irrelevant proof: services require restart/reload, service readiness and service rollback; images require rebuild/image readiness/image rollback; identities and host resources require their matching readiness and rollback; durable roots and backup ownership require migration, backup readiness and data-preserving rollback. Readiness probes identify the protected asset, production boundary, permitted and denied operation, safety basis and evidence path. They must be harmless, use disposable fixtures and preserve production state. Durable roots additionally require backup ownership, restore layout, distinct exact backup and restore commands, and separate executed evidence. Every gate, including each `not_applicable` decision, has specifically identified evidence with the matching branch; an unrelated success record cannot be reused. Every evidence record binds its source revision, gate, environment, command, expected/observed exit code, branch, observed behavior and a rehashed execution record; denied readiness must demonstrate a nonzero refusal. Current-host state, aggregate success, stale files and reviewer prose cannot satisfy the gate.

`product_usage` remains generic. Applicable product work records intended jobs, representative inputs, exact deliverables, persistence, delivery, limits and unsupported cases. When a capability matrix applies, all generic categories—input, processing environment, dependency policy, output, multi-artifact delivery, validation/completeness and safety—must be present. Concrete formats and workload profiles remain caller or product-adapter data.

The reviewer returns one decision envelope with matching `review_type`, `artifact_version`, and `artifact_digest`; one decision from `approved`, `rework_required`, `blocked`, or `rejected`; evidence-linked findings; blocking questions; and evidence checked. Prose may explain the review but cannot override this envelope. Approval cannot contain findings or blocking questions, and a blocked decision must contain a question.

Review execution remains bounded and external to the core state machine. The core builds and validates contracts; it does not introduce a role pipeline, reviewer scheduler, or runtime plugin abstraction.
