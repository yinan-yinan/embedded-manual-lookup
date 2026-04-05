# Embedded Lookup

[中文说明](./README.md)

This skill is for grounded lookup against local embedded manuals, datasheets, and reference manuals. Its current role is a local evidence-first skill / CLI for questions about registers, pin mappings, and electrical parameters. It is not a remote retrieval backend, a general OCR tool, or a schematic/netlist parser.

## Current capability scope

- It is intended for local technical-document lookup, especially datasheets, reference manuals, and other text-extractable embedded manuals.
- The runtime answer shape is a grounded short answer plus key evidence, source details, and open questions / uncertainty.
- For stable positive hits, the currently implemented structured outputs are:
  - `structured_summary.kind = "register"`
  - `structured_summary.kind = "electrical_parameter"`
  - `structured_summary.kind = "pin"`
- The currently stable positive pin paths are still narrow: the reference-manual `Table 54` lane, plus one hardened datasheet package-constrained sample, `STM32F103x8B + LQFP48 + USART1_TX -> PA9`.
- That does not mean datasheet pin/package handling is broadly stable. Outside those validated samples, wider datasheet pin/package wording should still be treated as a conservative boundary.

## Currently supported input types

- A single local file path
- A local folder path, with recursive discovery of supported manuals
- A single question only, where the CLI will first try default local sources such as `手册参考/` or `manuals/`
- Supported document suffixes:
  - `.txt`
  - `.md`
  - `.rst`
  - `.pdf`
- PDF support currently means text-extractable PDFs. OCR-heavy PDFs are out of scope.
- Optional narrowing filters:
  - `--device`
  - `--document-type`
  - `--revision`

## Current guardrails / conservative fallback

- If a folder query matches multiple plausible manuals and the runtime cannot safely narrow to one answer, it stops and asks for a disambiguating detail.
- If different candidate sources conflict, the runtime surfaces candidate evidence instead of inventing one final answer.
- If a question has pin intent but the evidence is not strong enough for a stable pin mapping, the runtime prevents that path from degrading into an electrical-parameter style answer.
- For datasheet pin queries that are missing a package constraint, the current guardrail stays in refusal mode, for example `Which pin provides USART1_RX on STM32F103x8B?`
- For package / ordering sibling ambiguity such as `STM32F103C8`, the current guardrail also stays in refusal mode, for example `Which package does package code T correspond to for STM32F103C8?`
- For revision-conflict cases, the runtime now keeps the disagreement explicit instead of collapsing it into one value; `PD0` and `PD1` preserve the `Rev 17` vs `Rev 20` disagreement.
- The current contract on these fallback paths is conservative handling: do not mislead, and do not present an unsafe path as a confident structured hit.

## Currently validated stable paths

- `register`: the positive reference-manual path is covered by fixed regression, for example `Which register enables SPI DMA?`
- `electrical_parameter`: the positive datasheet path is covered by fixed regression, for example the `VDD operating voltage range`
- `pin`: the currently frozen positive paths include reference manual `Table 54`, plus one datasheet package-constrained sample, `STM32F103x8B` `LQFP48 USART1_TX -> PA9`

That is why this README should not claim broad support for every chip or every pin/package scenario. The accurate statement today is narrower: register lookup, electrical-parameter lookup, the RM `Table 54` pin-positive lane, and one constrained datasheet `LQFP48 USART1_TX -> PA9` sample are implemented; broader pin/package/ordering sibling cases still rely on conservative handling.

## Installation

### Install the skill

```bash
npx skills add yinan-yinan/embedded-manual-lookup
```

If you want to target only this skill explicitly:

```bash
npx skills add yinan-yinan/embedded-manual-lookup --skill embedded-lookup
```

### Runtime requirements

- Python 3.10+
- Optional PDF dependencies:
  - `pypdf` for the default PDF backend
  - `pdfplumber` for the optional experiment backend

If you need the default PDF path:

```bash
python -m pip install pypdf
```

If you want to try the `pdfplumber` backend:

```bash
python -m pip install pdfplumber
```

On some Windows environments, you can also use:

```bash
py -m pip install pypdf pdfplumber
```

If you only query `.txt`, `.md`, or `.rst` manuals, no extra package is required.

Current backend conclusion:

- `pypdf` remains the default and is still the recommended backend.
- `pdfplumber` remains available as an optional backend for explicit comparison or failure-mode investigation; it is not the current candidate for switching the default.
- On the focused `STM32F103` revision-conflict fixture, `pdfplumber` currently drops the second conflict source, so it does not preserve the `PD0` / `PD1` `Rev 17` vs `Rev 20` disagreement as reliably as `pypdf`.

## Usage

After installation, you can ask Claude / Codex things like:

- "Look up the VDD operating voltage range in this PDF"
- "Which register bit enables SPI DMA?"
- "Which pin provides USART1_TX in Table 54?"

Direct CLI usage is still supported:

```bash
python ./scripts/embedded_lookup.py --help
```

Basic usage:

```bash
python ./scripts/embedded_lookup.py <source-or-question> [question] [--device <device>] [--document-type <type>] [--revision <rev>] [--json]
```

To switch PDF backend explicitly:

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "Which ball is PD0?" --pdf-backend pdfplumber --json
```

You can also override the default globally with an environment variable:

```bash
$env:EMBEDDED_LOOKUP_PDF_BACKEND="pdfplumber"
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "Which ball is PD0?" --json
```

Examples:

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "Which register enables SPI DMA?"
```

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "What is the VDD operating voltage range for STM32F103x8B?" --device STM32F103x8B --document-type datasheet --json
```

```bash
python ./scripts/embedded_lookup.py "E:/path/to/reference-manual.pdf" "Which pin provides USART1_TX on STM32F103x8B in Table 54?" --device STM32F103x8B --document-type "reference manual" --json
```

## Fixed regression entry

The current fixed regression entrypoint is:

```bash
python ../.trellis/scripts/embedded_lookup_fixed_regression.py
```

By default it runs only the `baseline-blocking` tier. To include the datasheet package probes as well, enable the extended tier explicitly:

```bash
python ../.trellis/scripts/embedded_lookup_fixed_regression.py --include-extended
```

The current default blocking baseline includes:

- CLI / help smoke
- register positive
- electrical positive
- ambiguity blocker
- conflict blocker
- RM `Table 54` `USART1_TX` positive
- RM `Table 54` `USART1_RX` positive

Outside the default blocking baseline, the project has also hardened several completed regression points:

- Datasheet package-constrained sample: `LQFP48 USART1_TX` is now frozen to `PA9`, and should not regress to `PA9 / PA9`
- Missing-package refusal guardrail: the `USART1_RX` sibling should continue to ask for a package / variant instead of pretending to have a safe pin answer
- Package-code refusal guardrail: `STM32F103C8 package code T` remains a conservative refusal boundary, not a positive package capability
- Revision-conflict rerun: `PD0` / `PD1` should continue to surface the `Rev 17` vs `Rev 20` disagreement explicitly

Those extra lanes are currently enabled through opt-in flags such as:

```bash
python ../.trellis/scripts/embedded_lookup_fixed_regression.py --include-phase1-table-aware --include-phase2-feature-ordering --include-phase2-stm32f103-revision-conflict-rerun
```

## Workflow

1. Identify candidate local manuals or folders.
2. Retrieve the most relevant sections and chunks for the question.
3. Produce a grounded short answer with evidence and source details.
4. Fall back conservatively when evidence is ambiguous, conflicting, or too weak for stable pin mapping.

## File structure

```text
embedded-manual-lookup/
├── SKILL.md
├── README.md
├── README.en.md
├── references/
│   └── usage.md
├── scripts/
│   └── embedded_lookup.py
└── spec/
    ├── PRD.md
    └── tasks/
        └── structured-lookup-template/
            ├── PRD.md
            └── spec.md
```

The `spec/` layer is for requirements, task breakdown, and maintenance specs for this skill. It is not a runtime dependency, but it defines the capability boundaries, validation framing, and follow-on work.

## Notes

- This is a local manual-lookup skill. It does not rely on network access or a remote retrieval service.
- OCR-heavy PDFs, schematics, netlists, BOMs, screenshots, remote crawling, and retrieval-backend work are outside the current scope.
- The runtime is citation-first: when evidence is incomplete, it should surface uncertainty instead of filling gaps with guesses.
