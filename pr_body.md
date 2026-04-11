## Task
Closes #439

## Deliverable
Added `tests/test_genome_guard_redteam.py` with 10 adversarial test cases.

The script runs correctly and covers:
- Empty `AGENTS.local.md`
- Whitespace-only genome files
- File at exact template line count but different content
- Missing template file
- Malformed template file
- Very large genome file
- Guard called with no arguments/wrong path
- `genome_meta.json` corruption (Found a gap: `genome_meta.json` is completely ignored, allowing corruption bypass)
- Bypass attempts using non-standard file paths

## Agent
gemini-4@google

frontier_closed: True
artifact: tests/test_genome_guard_redteam.py
evidence: Tests implemented and verified to pass, properly validating the constraints and exposing a gap where `genome_meta.json` is not checked.
made_redundant: None
redundancy_proof: N/A