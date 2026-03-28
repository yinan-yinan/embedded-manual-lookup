# Embedded Lookup Usage

This repository supports two usage styles.

## 1. Install as a skill

```bash
npx skills add yinan-yinan/embedded-manual-lookup
```

If needed, explicitly choose the skill:

```bash
npx skills add yinan-yinan/embedded-manual-lookup --skill embedded-lookup
```

This repository is shaped so discovery can work from the repository root `SKILL.md`, which matches the common `npx skills add owner/repo` layout.

## 2. Run the standalone CLI directly

Requirements:

- Python 3.10+
- Optional: `pypdf` for PDF parsing

Install optional PDF dependency:

```bash
python -m pip install pypdf
```

Or on some Windows environments:

```bash
py -m pip install pypdf
```

Verify CLI:

```bash
python ./scripts/embedded_lookup.py --help
```

Basic usage:

```bash
python ./scripts/embedded_lookup.py <source-or-question> [question] [--device <device>] [--document-type <type>] [--revision <rev>] [--json]
```

Examples:

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "What is the VDD operating voltage range?"
```

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "Which register enables SPI DMA?" --device STM32F103x8B --document-type "reference manual"
```
