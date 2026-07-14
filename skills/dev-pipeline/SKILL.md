---
name: dev-pipeline
description: "Use this skill to run an engineering task through the Codex-centered owner workflow: native owner start/resume, scenario and architecture checkpoints, reviewed walking-skeleton or vertical increments, bounded Codex reviewers, and evidence gates. Trigger it when the user asks for dev-pipeline, an owner pipeline, scenario/architecture gates, or reviewed vertical increments."
---

# Dev Pipeline

Use the installed `dev-pipeline` CLI as the workflow authority. Keep one native Codex owner session responsible for the causal chain; invoke bounded agents only for a concrete question or observable delta.

## Run the workflow

1. Preserve the user's original instruction in a durable task artifact and identify the target repository.
2. Inspect `dev-pipeline owner start --help`, then start through the real CLI entrypoint. Record the returned attempt and opaque Codex session metadata.
3. Before scenario approval, use bounded scout discovery to fill every cross-cutting dependency surface with an owner, evidence, and change impact. Evidence an explicit `not_applicable`; never omit runtime, deployment, storage, backup/restore, identity, network, observability, scheduler, integration, or security surfaces merely because the request names application code.
4. Complete the scenario checkpoint before architecture. Stop and surface a blocking question when product semantics or an unresolved dependency owner materially affect the implementation.
5. Complete the architecture checkpoint with the production path, owning layer, reuse plan, deletion plan, verification plan, and any applicable isolation boundaries.
6. Submit the first executable change as a walking skeleton through the real entrypoint. Map every increment to named scenarios and failure modes, declare temporary seams, and attach evidence at its honest level: `skeleton`, `integrated`, `live`, or `deployed`.
7. Build a bounded packet with `dev-pipeline context` only when a scout, scenario, architecture, diff, or live-verification question is triggered. Run exactly that packet with `dev-pipeline agent`; do not assemble a standing role pipeline.
8. Accept an increment only after focused review is approved and its required evidence gate passes. For security or isolation boundaries, require both the permitted path and harmless denied-path probes at the real boundary; never test denial with destructive production operations.
9. Use `dev-pipeline owner resume` only to continue the recorded native Codex session. Use the explicit retry operation for a new attempt over existing artifacts; never label a new session as resume.

Inspect `dev-pipeline <command> --help` for exact arguments. Read the installed package documentation for checkpoint and increment schemas rather than recreating them in prompts.

## Boundaries

- Codex is the only supported runtime. Do not introduce a runtime plugin layer or another scheduler.
- Machine-facing prompts, schemas, conventions, packets, and decisions are canonical English.
- Stubs are allowed only at newly introduced or genuinely unavailable boundaries and must be declared and retired.
- Structural, mock-only, or one-off evidence does not establish live acceptance.
- Keep transport credentials, local task history, and product-specific notification policy outside the public pipeline.
