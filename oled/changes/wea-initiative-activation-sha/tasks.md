# Tasks

Bindings: Outcome 1, Spec 1, Design 1.

- [x] Reproduce original SHA conflict and obtain explicit repair authority.
- [x] Retain accepted BDD delta, historical scope and versioned design.
- [x] Implement AS-01..03 in the existing activation path and repair masked negative tests.
- [x] Add pure, historical-prefix and trusted-workflow tests with independent invalid conditions.
- [x] Run focused tests, Access/initiative/Tide regression coverage, lint and document checks.
- [ ] Obtain independent review and fix actionable findings.
- [ ] Publish a separate draft PR, run native review and retain exact-head CI.
- [ ] Present the reviewed candidate for separate merge and protected installation decisions.

No live journal action belongs to these tasks. Local commands use Python pytest with no cache and disabled bytecode.
Proving surfaces: tests/vnext/test_initiatives.py, new test_initiative_activation.py, existing Access and protocol-transition tests.
