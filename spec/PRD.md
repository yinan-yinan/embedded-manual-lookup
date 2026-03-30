# Embedded Lookup Skill PRD

## Summary

`embedded-lookup` is a local embedded-document retrieval skill that answers hardware questions from local manuals with grounded evidence. The runtime entry remains `SKILL.md`; development-facing product intent and task specs live under `spec/`.

## Problem

The skill already has a clear runtime path, but it lacks a dedicated place for maintainers to record product intent, enhancement scope, and task-level specs. Without that layer, implementation notes risk leaking into `SKILL.md`, `references/`, or ad hoc discussion.

## Goals

- Keep `SKILL.md` focused on runtime triggering, workflow, and output shape.
- Keep `references/` focused on runtime usage and operator-facing documentation.
- Add a stable `spec/` layer for product and task planning.
- Define a task-level spec pattern that always includes both `PRD.md` and `spec.md`.

## Non-goals

- Do not change retrieval logic or CLI behavior.
- Do not move runtime usage material out of `references/usage.md`.
- Do not turn this skill into a full project-management workspace.

## Users

- Runtime user: another Codex instance using the skill to answer manual questions.
- Maintainer: a contributor extending the skill without polluting runtime entry docs.

## Information architecture

Use these folders by role:

- `SKILL.md`: runtime entry, trigger metadata, minimal workflow, output contract.
- `references/`: runtime usage details loaded only when needed.
- `scripts/`: executable retrieval logic and CLI entrypoints.
- `spec/`: product intent, task PRDs, and implementation-facing specs for maintainers.

## Required structure

```text
embedded-lookup/
├── SKILL.md
├── references/
├── scripts/
└── spec/
    ├── PRD.md
    └── tasks/
        └── <task-name>/
            ├── PRD.md
            └── spec.md
```

## Maintainer rules

- Add new enhancement work under `spec/tasks/<task-name>/`.
- Give every task both a `PRD.md` and a `spec.md`.
- Keep task PRDs focused on user value, scope, and acceptance.
- Keep task specs focused on concrete behavior, output contracts, and validation notes.
- Do not store implementation-only planning in `SKILL.md`.

## Initial task seed

The first example task documents a structured answer template for register, pin, and electrical-parameter questions. It is intentionally limited to product/spec definition and does not require a code change yet.
