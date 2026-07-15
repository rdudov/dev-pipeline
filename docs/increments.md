# Walking-skeleton and vertical-increment lifecycle

Increment artifacts are canonical English JSON using schema version `1.0`. They are caller-owned durable artifacts; the lifecycle ledger records their submitted and accepted digests.

## Contract

Every increment names its sequence and kind, binds the completed scenario and architecture artifact digests, and records:

- named scenario IDs and named failure modes;
- the observable behavior, concrete source delta, and deletion performed;
- temporary seams, including kind, allowed boundary, reason, and replacement milestone;
- an evidence gate and evidence items mapped to both scenarios and failure modes.

Sequence 1 is the `walking_skeleton`. It must traverse a real entrypoint and require at least `skeleton` evidence. Sequences after 1 are `vertical_increment` and require at least `integrated` evidence.

Temporary seam kinds are `stub` and `temporary_adapter`. Their boundary must be `new_boundary` or `unavailable_external`; an existing exercisable integration cannot be reclassified as a permitted seam. Every seam has an explicit replacement milestone.

## Evidence levels

Evidence levels are ordered:

1. `structural`: a file, schema, symbol, or shape exists;
2. `unit`: isolated logic, including mocks or fakes;
3. `skeleton`: the real entrypoint/routing with only declared permitted seams;
4. `integrated`: real internal production components with a controlled external boundary;
5. `live`: the real production-relevant external/runtime path;
6. `deployed`: the target launch mode and user-visible running outcome.

The declared gate selects required evidence IDs and a minimum level. Required evidence must pass, use a real entrypoint, meet that level, and collectively cover every named scenario and failure mode. Structural and unit evidence are always too weak to close the gate. A lower level is never promoted in status or lifecycle output.

## Review and advancement

`increment submit` validates prerequisites and emits `increment_ready_for_review`. Scenario and architecture digests must match completed lifecycle checkpoints. A later sequence also requires the immediately preceding increment to be completed.

A bounded review packet uses `review_type=increment` and binds the submitted artifact’s version and SHA-256 digest. It must also bind the current task contract and completed evidence checkpoint. `increment accept` rehashes those closure artifacts, validates evidence and scenario/failure coverage, verifies that the artifact is the current submitted candidate, and emits `increment_completed` only for `approved`. Missing, failed, blocked, stale, weak, unrepresentative, wrong-entrypoint, mock/stub/fake/harness-only or uncovered mandatory evidence makes completion impossible regardless of reviewer prose. Rework requires fresh digest-bound evidence and review.

This lifecycle does not implement routed conventions or agent scheduling. Those remain a later increment.
