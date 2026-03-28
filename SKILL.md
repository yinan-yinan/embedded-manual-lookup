---
name: Embedded Lookup
description: Search local embedded manuals, datasheets, and reference manuals with grounded evidence. Use this skill when the user wants answers from a local PDF, datasheet, or technical document such as register names, pin mappings, voltage ranges, or timing limits.
version: 0.2.0
---

Use this skill to answer embedded-documentation questions from local manuals with grounded evidence.

## What this skill does

- searches local text files and text-based PDFs
- narrows by device, document type, and revision when provided
- returns short grounded answers with evidence
- keeps uncertainty explicit when evidence is partial, missing, ambiguous, or conflicting
- refuses unsupported inputs such as OCR-heavy PDFs, schematics, netlists, and remote crawling

## When to use it

Use this skill when the user asks things like:

- “look up this manual”
- “check this PDF”
- “find the UART pins”
- “which register enables SPI DMA”
- “what is the voltage range in this datasheet”

## How to use it

1. Require a local file path or folder path when the question depends on a specific manual.
2. Prefer the bundled standalone CLI:
   - `python ${CLAUDE_PLUGIN_ROOT}/scripts/embedded_lookup.py <source> <question>`
3. Add `--device`, `--document-type`, or `--revision` if the user already provided them.
4. Prefer grounded evidence over freeform answering.
5. If evidence is partial or ambiguous, say so clearly.

## Additional resources

- For standalone installation and repository usage, see `@${CLAUDE_PLUGIN_ROOT}/references/usage.md`.

## Output shape

Return:
- a short grounded answer
- key evidence bullets with source tags
- source details when available
- open questions or uncertainty if evidence is incomplete

## Notes

- Direct CLI usage remains supported through `${CLAUDE_PLUGIN_ROOT}/scripts/embedded_lookup.py`.
- PDF support requires the Python package `pypdf`.
- Keep answers citation-first and avoid inventing register names, electrical values, or timing limits.
