# Routed conventions and bounded Codex agents

The canonical machine-facing conventions are compact English rules in `dev_pipeline.conventions`. They are derived from the frozen standalone `agents` baseline at commit `41e16ac401f182f4cd3a102929c11391f61f3255`; that repository is provenance only and is not a runtime dependency.

## Progressive routing

An owner prompt loads `core`, its one active gate, and only explicitly triggered risk packs:

```bash
dev-pipeline owner start ... --gate architecture --risk security
```

Gates are `core`, `discovery`, `scenario`, `architecture`, `increment`, `diff_review`, `live`, and `recovery`. Risk packs are `compatibility`, `security`, `service`, `provider`, `media`, `cross_repo`, and `publication`. With no flags, an ordinary owner receives only `core`; it never receives the full frozen role prompts or their examples.

The `scout` role is routed to `discovery`. It must trace both source dependencies and the operational lifecycle, producing evidence for every dependency surface required by the scenario checkpoint. This prevents an application-only source scan from silently omitting deployment, backup, restore, identity, storage, or isolation owners. The security risk pack adds a separate evidence rule: both allowed and denied branches must be exercised at the real boundary using explicitly harmless negative probes.

Each pack records source file/section provenance. The router preserves behavioral invariants while retiring these universal patterns:

- the mandatory analyst → architect → planner → developer role chain;
- universal review counts and serial stage transitions;
- comprehensive architecture templates for every task;
- stub/hard-coded output credited as acceptance evidence;
- compatibility inferred without a contract or explicit risk trigger;
- the frozen README role catalog injected as working context.

The frozen baseline is never imported, discovered, or read by installed pipeline code.

## Bounded role packets

An explicit caller can build one context for `scout`, `scenario_review`, `architecture_review`, `diff_review`, or `live_verification`:

```bash
dev-pipeline context \
  --role diff_review \
  --purpose "Review the concrete increment" \
  --question "Does this diff satisfy SC-08?" \
  --artifact /path/to/diff-or-artifact \
  --artifact-version 2 \
  --evidence /path/to/installed-cli-sequence-17.jsonl \
  --exclude "Bootstrap 6" \
  --risk publication \
  --output /path/to/context.json
```

The packet records artifact digests, one purpose/question, digest-bound evidence files, exclusions, active gate, triggered risks, routed packs, `runtime=codex`, and `legacy_prompt_included=false`. Free-form evidence text and unbounded task or conversation history are rejected; every supplied evidence item must be an explicitly named file with a captured digest. The packet digest covers all content. Referenced artifacts and evidence are rehashed immediately before execution, so a stale packet is refused. Review roles require an artifact version and are instructed to return the existing canonical decision envelope.

Run exactly that packet with an explicit Codex invocation:

```bash
dev-pipeline agent \
  --packet /path/to/context.json \
  --repo /path/to/repository \
  --sandbox read-only \
  --diagnostics-prefix /path/to/diagnostics/review \
  --output /path/to/result.json
```

Codex command/event/final-message parsing remains localized in `dev_pipeline.codex`. The command starts one bounded native Codex session and returns its opaque ID and response. Review-role responses must parse and pass the existing structured decision validator before the command succeeds or persists a decision. The command does not discover agents, schedule roles, retry decisions, advance lifecycle gates, or form a team.

## Provenance coverage

The routed packs cover the good patterns from `00_agent_development.md` through `10_agent_blocker_rescuer.md`, including the targeted repair prompts. `RETIRED_PATTERNS` records explicit bad/mixed dispositions. Automated coverage checks require every frozen source filename and the frozen README catalog to remain represented, while ordinary-owner tests prove non-active gates and legacy role names are absent.
