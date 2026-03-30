# PRD: Structured Lookup Template

## Summary

Define a lightweight enhancement for `embedded-lookup` so common embedded question types can return a more predictable answer shape without changing the skill's grounded-evidence posture.

## Problem

The current output shape is intentionally generic. For repeated question classes such as register lookup, pin mapping, and electrical-parameter retrieval, maintainers need a documented target shape before deciding whether any runtime changes are worth making.

## Target user value

- Make answers easier to scan for common embedded tasks.
- Preserve the current citation-first behavior.
- Reduce ambiguity about what fields matter for each question class.

## In scope

- Define structured answer expectations for:
  - register questions
  - pin mapping questions
  - electrical-parameter questions
- Describe how the structure coexists with the current short-answer format.
- Capture acceptance criteria for future implementation work.

## Out of scope

- Changing retrieval ranking or chunking.
- Adding schema enforcement to the CLI.
- Implementing JSON schema validation.

## Acceptance criteria

- A maintainer can read the paired `spec.md` and know what answer sections are expected for each supported question class.
- The template remains optional and does not require a script change in this documentation-only task.
- The design keeps uncertainty and source evidence explicit.
