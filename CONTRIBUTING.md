# Contributing

Keep changes vertical and evidence-driven. Each increment should name the scenario it closes, traverse the real CLI entrypoint, and include focused tests plus meaningful runtime evidence. Mock-only, prompt-string, structural, and one-off tests may aid development but do not establish live acceptance.

Before implementation, identify the existing production path, owning component, reuse plan, cleanup plan, and real verification boundary. Do not add a parallel mechanism beside the owning layer. Stop for materially ambiguous product semantics rather than inventing compatibility or fallback policy.

Machine-facing prompts, schemas, status values, and decision vocabulary are canonical English. Public fixtures must not contain private task history, credentials, transport destinations, or machine-specific workspace paths.

Run tests and publication checks before opening a change:

```bash
pytest
python -m build
```

Concrete increments should receive bounded independent review over the relevant diff and runtime evidence.
