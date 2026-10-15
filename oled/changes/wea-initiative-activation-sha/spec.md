# Spec: activation evidence version 2

| Version | Accepted authority | Effective scope |
| --- | --- | --- |
| 1 | Outcome 1, operator approval 2026-10-15 | Candidate repair only, inactive until separate package installation |

## MODIFIED: IR-06 / LRI-07 activation boundary

The old activation form binds the source and workflow to the installed package SHA.
That form and every historical package retain their existing predicates and errors.
The new form separates the installed SHA from the execution SHA.
The policy identifier and outer initiative schema do not change.

### AS-01: exact activation after main advances

- **GIVEN:** A separately installed package declares activation evidence version 2.
- **GIVEN:** The current main has the same complete protocol manifest as that package.
- **WHEN:** The operator supplies the exact new activation source through the trusted current-main workflow dispatch.
- **THEN:** The system MUST accept activation with distinct installed and execution SHAs.
- **THEN:** The source MUST bind the policy, evidence version, installed SHA, execution SHA, and complete manifest hash.
- **THEN:** Retained evidence MUST bind both SHAs and the complete verified manifest.
- **THEN:** Activation MUST create no grant, Domain, financial transfer, or permission.
- **Evidence:** New pure and mocked trusted-workflow activation tests.

### AS-02: independent invalid conditions

- **GIVEN:** One required activation condition differs from an otherwise valid request.
- **WHEN:** The system processes that request.
- **THEN:** The system MUST reject wrong SHAs, version, policy, package hash, missing files, extra files, or changed file hashes.
- **THEN:** The system MUST reject absent evidence, wrong workflow, absent dispatch, wrong operator, edited source, or wrong source hash.
- **THEN:** The trusted handler MUST prevent publication after a stale main, failed required read, or workflow provenance mismatch.
- **Evidence:** Single-variable mutation tests with a positive control and mocked writer tests.

### AS-03: history, retries and separate installation

- **GIVEN:** A historical prefix contains accepted or rejected activation records, including future-shaped evidence under an old package.
- **WHEN:** A fresh reader replays that prefix or a later version 2 package update.
- **THEN:** The system MUST preserve every historical result and original prefix without network or a live clock.
- **THEN:** An exact retry MUST return the original result. A conflicting request ID MUST receive a rejection.
- **THEN:** Package installation MUST NOT activate policy. A separate exact operator activation remains mandatory.
- **THEN:** Same-byte repins MUST remain rejected.
- **Evidence:** Mixed-prefix replay, retry, package-transition and unchanged activation-gate regression tests.

## Preserved boundaries

APT-01..06 and DA-08 retain operator authority, immutable history, append-only recovery, and separate installation/activation.
APT-03 gains the explicit installed-versus-execution evidence distinction.
LRI-01..07 remain accepted-future in the scenario registry. This approval does not make the policy live.
Current financial rulesets, clocks, registry bindings and seven-day grants remain unchanged.
