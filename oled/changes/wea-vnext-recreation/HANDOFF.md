# Agent0 handoff: WEA vNext current state

Status: `Block 9 Spec 1.1 and Design 1.3 select a real canonical private pilot;
active Tasks 2.2 has no hash gate; GitHub-native writer implementation is next`.

## Current truth

- v1 remains authoritative and under an operator pause. Direct legacy writers
  still exist. Do not call them.
- Domain/Access and S13C are merged inactive control planes.
- The scenario registry has 70 current, 9 accepted-future, and zero
  proposed-future Block 9 scenarios.
- The operator rejected a narrow successor reference runtime.
- The operator accepted the SDD evidence reconciliation on 2026-08-16.
- The first cutover does not carry gauntlet mint into vNext.
- Achievement, award, revoke, and transform records remain readable history.
  They create no active vNext effect.
- A future identity-discovery mechanism for ikigai is important. It requires a
  separate future Outcome and Spec.
- The canonical root ledger repository is `WeTheAgents/wetheagents`.
  `WeTheAgents/circle-1` is one separate Domain repository for agent travel.
- The private pilot uses the real canonical ledger. GitHub Actions and pull
  requests replace local Apps, local locks, and local epoch guards as authority.

## Current authority

- Accepted Block 9 Outcome/Spec 1.0:
  `../wea-vnext-block9-cutover/`.
- Exact accepted Block 9 Design 1.1 and Tasks 2.1 manifests:
  `../wea-vnext-block9-cutover/WEA_vNext_BLOCK9_DESIGN_1_1_ACCEPTANCE.txt`
  and `../wea-vnext-block9-cutover/WEA_vNext_BLOCK9_TASKS_2_1_ACCEPTANCE.txt`.
- Current Group 2 review:
  `../wea-vnext-block9-cutover/WEA_vNext_BLOCK9_GROUP2_REVIEW.html`.
- Current Spec, Design, and runbook:
  `../wea-vnext-block9-cutover/spec-1.1.md`,
  `../wea-vnext-block9-cutover/design-1.3.md`, and
  `../wea-vnext-block9-cutover/tasks-2.2.md`.
- Operator review artifact:
  `../wea-vnext-s13c-financial-correction/WEA_vNext_SDD_REVIEW.html`.
- Permanent engineering boundary: `../../../docs/VNEXT_BOUNDARY.md`.

## Exact next step

Implement the GitHub-hosted Agent0 candidate workflow and trusted data-only
pull-request guard. Then retire local and legacy canonical writer authority.

Do not merge the activation pull request, edit canonical ledger history, change
visibility, or open external participation. The activation merge and later
public exposure remain the two operator stop points.

## Historical provenance

- Domain/Access: PR `#942`, merge `bb114e7`.
- S13C: PR `#943`, merge `942998d`.
- S13C verification: PR `#944`, merge `0ea6513`.
