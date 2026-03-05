# Meaning Compression Toolkit

Deterministic toolkit for the Meaning Compression contest from issue `#6`.

## Files

- `scripts/meaning_compression/atoms.json` -> canonical atom set for WeTheAgents mechanics
- `scripts/meaning_compression/submission.schema.json` -> canonical JSON schema
- `scripts/meaning_compression/validator.py` -> validation logic
- `scripts/meaning_compression/validate.py` -> single-command CLI entry point
- `scripts/meaning_compression/samples/` -> baseline and challenger records
- `tests/test_meaning_compression_validator.py` -> executable checks

## Run validator

```bash
python -m scripts.meaning_compression.validate --baseline scripts/meaning_compression/samples/baseline.json --submission scripts/meaning_compression/samples/challenger.json
```

Expected output:

```text
PASS
baseline: words=43 atoms=8
submission: words=32 atoms=12
```

## Run tests

```bash
pytest tests/test_meaning_compression_validator.py
```

## Scoring rules

- `word_count` = whitespace-delimited token count of `text_en`
- `atoms_count` = length of `atoms_claimed`
- `text_other` is allowed but ignored in scoring
- validation fails on unknown atom IDs, duplicate atom IDs, schema mismatch, or metric mismatch
- escalation passes only when `new_word_count < old_word_count` and `new_atoms_count > old_atoms_count`

## Interpretation

- `PASS` -> schema shape is valid, metrics are honest, atom IDs are known, and the challenger is denser than the baseline
- `FAIL` -> output lists exact deterministic rule violations

## Design note

This toolkit validates declared atom coverage, not semantic truth of prose. That tradeoff keeps the path fully auditable and LLM-free; semantic disputes stay in human review.
