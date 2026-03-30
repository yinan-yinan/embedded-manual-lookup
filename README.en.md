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
- The currently stable positive pin path is the reference-manual `Table 54` lane. In the fixed regression entry, `USART1_TX` and `USART1_RX` on that lane are part of the baseline-blocking set.
- Datasheet package-worded probes such as `LQFP48 package` are currently classified as `extended-conservative` in fixed regression. They are there to confirm conservative handling and prevent parameter-style drift; they are not the default blocking baseline.

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
- The current contract on these fallback paths is conservative handling: do not mislead, and do not present an unsafe path as a confident structured hit.

## Currently validated stable paths

- `register`: the positive reference-manual path is covered by fixed regression, for example `Which register enables SPI DMA?`
- `electrical_parameter`: the positive datasheet path is covered by fixed regression, for example the `VDD operating voltage range`
- `pin`: the current stable positive path is reference manual `Table 54`, not datasheet package wording

That is why this README should not claim broad support for every chip or every pin scenario. The accurate statement today is narrower: register lookup, electrical-parameter lookup, and one validated RM `Table 54` pin-positive lane are implemented; broader pin/package cases still rely on conservative handling.

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
- Optional: `pypdf` for PDF parsing

If you need PDF support:

```bash
python -m pip install pypdf
```

On some Windows environments, you can also use:

```bash
py -m pip install pypdf
```

If you only query `.txt`, `.md`, or `.rst` manuals, no extra package is required.

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
python ./.trellis/scripts/embedded_lookup_fixed_regression.py
```

By default it runs only the `baseline-blocking` tier. To include the datasheet package probes as well, enable the extended tier explicitly:

```bash
python ./.trellis/scripts/embedded_lookup_fixed_regression.py --include-extended
```

The current default blocking baseline includes:

- CLI / help smoke
- register positive
- electrical positive
- ambiguity blocker
- conflict blocker
- RM `Table 54` `USART1_TX` positive
- RM `Table 54` `USART1_RX` positive

`extended-conservative` is currently where the datasheet `LQFP48 package` probes live. Those probes are advisory conservative checks only and do not change the default blocking verdict.

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
