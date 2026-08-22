# Handoff: WEA vNext Block 9 Cutover

Status: `Outcome/BDD 1.0, Design 1.0, and Tasks 2.0 accepted; dormant code Groups 1, 3, 4, and 5 are authorized`.

The operator accepted the gauntlet, achievement, ikigai, and Design-direction
decisions on 2026-08-16, then requested the Block 9 BDD. Outcome and Spec 1.0
were drafted afterward and accepted without changes on 2026-08-17. The accepted decisions remove
gauntlet mint, retain achievement history without active effect, and keep the
future identity mechanism in a separate contract.

The accepted Outcome, Spec, Design, and Tasks files remain byte-for-byte frozen
at their preparation-time content. Their external acceptance manifests pin the
exact bytes and record the later operator acts. Current parent status is
composite Outcome and decision overlays 1.2.

## Current boundary

- S-71 through S-79 are accepted-future scenarios awaiting implementation.
- The proposed-future scenario set is empty.
- The 70 current scenarios and inactive control planes remain unchanged.
- Groups 1, 3, 4, and 5 are the only authorized implementation scope.
- Group 2 host and GitHub setup, Group 6 v1 resolution, Group 7 rehearsal, and
  Group 8 activation remain blocked.
- No live writer, cutover, genesis publication, credential change, or ledger
  mutation is authorized.

## Exact next action

Implement and verify dormant code Groups 1, 3, 4, and 5 from Tasks 2.0. Keep
the adapter disabled and do not mutate the host, GitHub settings, credentials,
the v1 ledger, or the canonical ref. Stop after a clean implementation report.
