# Embedded Lookup

[中文说明](./README.md)

A lightweight local manual lookup tool for embedded development.

It answers questions from local datasheets, reference manuals, and other technical text/PDF files with citation-ready evidence, without loading the whole manual into context.

## Included files

This repository keeps the upload scope minimal:

- `README.md`
- `README.en.md`
- `scripts/embedded_lookup.py`
- `.claude-plugin/plugin.json`
- `skills/embedded-lookup/SKILL.md`

## What it does

- searches local files or folders
- supports text files and text-based PDFs
- supports optional filters for device, document type, and revision
- returns grounded short answers with evidence
- supports JSON output for scripting

## Installation

### Requirements

- Python 3.10+
- Optional: `pypdf` for PDF parsing

### Install optional PDF dependency

If you need PDF support:

```bash
python -m pip install pypdf
```

On some Windows environments, you can also use:

```bash
py -m pip install pypdf
```

If you only query `.txt`, `.md`, or `.rst` manuals, no extra package is required.

## Verify installation

```bash
python ./scripts/embedded_lookup.py --help
```

If help text prints successfully, the CLI is ready.

## CLI usage

### Basic usage

```bash
python ./scripts/embedded_lookup.py <source-or-question> [question] [--device <device>] [--document-type <type>] [--revision <rev>] [--json]
```

### Query a specific manual

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "What is the VDD operating voltage range?"
```

### Query with filters

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "Which register enables SPI DMA?" --device STM32F103x8B --document-type "reference manual"
```

### Get JSON output

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "What I2C pins are used on this board?" --json
```

### Use default manual folders

If only one positional argument is passed, it is treated as the question and the tool will try default local source folders.

```bash
python ./scripts/embedded_lookup.py "Which register enables SPI DMA?"
```

## Skill packaging

This repository also includes a minimal Claude skill/plugin structure:

- `.claude-plugin/plugin.json`
- `skills/embedded-lookup/SKILL.md`

The implementation stays in `scripts/embedded_lookup.py`, while `SKILL.md` acts as a thin wrapper.

## Notes

- Supported inputs are local text files and text-based PDFs.
- This tool is for manual lookup only.
- OCR-heavy PDFs, schematics, netlists, and remote crawling are out of scope.
