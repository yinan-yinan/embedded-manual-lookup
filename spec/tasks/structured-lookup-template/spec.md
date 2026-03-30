# Structured Lookup Template Spec

## Goal

Document a future-friendly answer template for the most common embedded lookup requests while preserving the current retrieval workflow and evidence requirements.

## Supported query classes

### 1. Register lookup

Use when the user asks for a register name, bit, field, enable path, reset value, or related control detail.

Preferred response shape:

1. Short answer
2. Register summary
3. Key evidence bullets
4. Source details
5. Uncertainty or follow-up questions

Recommended register summary fields:

- peripheral
- register
- field or bit
- purpose
- access notes if explicit in source

### 2. Pin mapping

Use when the user asks for package pins, alternate functions, board nets, or interface routing clues found in local documents.

Preferred response shape:

1. Short answer
2. Pin summary
3. Key evidence bullets
4. Source details
5. Uncertainty or package-variant caveats

Recommended pin summary fields:

- signal or function
- pin name
- package or variant
- direction or role if explicit in source

### 3. Electrical parameter lookup

Use when the user asks for limits, recommended conditions, timing values, voltages, currents, or thresholds.

Preferred response shape:

1. Short answer
2. Parameter summary
3. Key evidence bullets
4. Source details
5. Uncertainty or condition caveats

Recommended parameter summary fields:

- parameter name
- value or range
- unit
- test or operating conditions if explicit in source

## Cross-cutting rules

- Keep the first line concise and directly answer the question when evidence is sufficient.
- Do not invent structured fields that are not grounded in the source.
- Omit unknown fields instead of filling them with guesses.
- Keep source details citation-first.
- Preserve explicit uncertainty when documents conflict, omit key context, or describe multiple device/package variants.

## Compatibility with current skill behavior

- This template extends the existing output shape; it does not replace the current grounded-answer workflow.
- The current generic sections remain valid when the query does not fit one of the supported classes.
- No script change is required by this spec alone.

## Validation notes for a future implementation task

- Check one register question, one pin question, and one electrical-parameter question.
- Confirm that any added structure is still backed by evidence bullets and source details.
- Confirm that unsupported or ambiguous documents still surface uncertainty instead of fabricated structure.
