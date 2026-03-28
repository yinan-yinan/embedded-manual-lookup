---
name: Embedded Lookup
description: This skill should be used when the user asks to search a local embedded manual, inspect a datasheet or reference manual, answer a technical question from a local PDF, or retrieve grounded evidence from a local hardware document. Use it for queries like "look up this manual", "check this PDF", "find the UART pins", "which register enables SPI DMA", or "what is the voltage range in this datasheet".
version: 0.1.0
---

Use the bundled standalone embedded manual lookup workflow to answer questions from local manuals with grounded evidence.

## What this skill does

- searches local text files and text-based PDFs
- narrows by device, document type, and revision when provided
- returns grounded answers with source evidence
- refuses unsupported Phase 1 inputs such as OCR-heavy PDFs, schematics, netlists, and remote crawling

## How to use it

When this skill is triggered:

1. Require a local file path or folder path.
2. Prefer the standalone CLI in this repository:
   - `python ./scripts/embedded_lookup.py <source> <question>`
3. Add `--device`, `--document-type`, or `--revision` if the user already provided them.
4. Prefer grounded evidence over freeform answering.
5. If evidence is partial or ambiguous, say so clearly.

## Output shape

Return:
- a short grounded answer
- key evidence bullets with source tags
- source details when available
- open questions or uncertainty if evidence is incomplete

## Notes

- Direct CLI usage remains supported through `scripts/embedded_lookup.py`.
- PDF support requires the Python package `pypdf`.
- See `README.md` for installation and standalone usage details.
