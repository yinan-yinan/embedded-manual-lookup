# Embedded Lookup

[中文说明](./README.md)

A lightweight local manual lookup skill for embedded development, designed for Claude Code or codex style skill installation and local grounded manual retrieval.

## Features

- search local files or folders
- support text files and text-based PDFs
- support optional filters for device, document type, and revision
- return grounded short answers with evidence
- support `--json` output for scripting
- preserve direct standalone Python CLI usage

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

After installation, you can ask Claude things like:

- "Look up the VDD operating voltage range in this PDF"
- "Which register bit enables SPI DMA?"
- "What I2C pins are used on this board?"

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
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "What I2C pins are used on this board?" --json
```

## Workflow

1. Identify candidate local manuals or folders
2. Retrieve only the most relevant sections and chunks
3. Answer with grounded evidence
4. Surface ambiguity, conflict, or missing evidence clearly

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

## Compatibility

- fits `npx skills add` style installation flows
- keeps direct local Python CLI usage
- currently scoped to local text and text-based PDF manual retrieval

## Notes

- Supported inputs are local text files and text-based PDFs.
- This tool is for manual lookup usually.
- OCR-heavy PDFs, schematics, netlists, and remote crawling are out of scope.
