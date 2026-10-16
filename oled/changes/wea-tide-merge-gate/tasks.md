# Current readback repair, 2026-10-10

- Complete: reproduce the raw compare separator rejection through the real API client.
- Complete: encode the fixed separator in scripts/tide_merge.py only; preserve the frozen package and validator.
- Complete: 70 transport/preflight tests and targeted Ruff pass, including legal compare and unsafe-path regression cases.
- Complete: canonical31-batch replay and live read-only readback passed; all financial effects are zero.
- Complete: self-review, draft PR1068 publication and Codex review; no actionable regressions.
- Outside scope: merging the code PR or dispatching any workflow.

# Status

CURRENT: setup and code preparation complete; 45 focused tests and Ruff pass.
Independent review clean. Draft publication is next. Operator manual code merge,
enablement and safe Work-only live verification remain. See deployment.md.
Earlier checkpoint text below is historical, not the current blocker list.

Continuation: disabled merge transport and workflow template prepared; 36 focused
tests passed. Operator approval received; browser creation is now blocked by two
automatic review denials (see design). Hand off the prepared form submission;
do not route around the rejection. App credentials and policy are still absent.
Action pinning, live protected environment, actual policy snapshot, publication,
server enforcement test and final canonical verification remain pending.

- Complete: read current rulesets, workflow permissions, code and app inventory.
- Complete: isolated read-only preflight and orchestration negative tests.
- Pending: operator approval of exact proposed App/security design. No numeric
  App ID exists; creating credentials is expressly outside current authorization.
- Pending: complete transport/workflow, protected secret deployment and policy
  fixtures after authorization; review BDD delta and update manual-only docs.
- Pending: independent review and draft publication using bound development
  identity. Current session has no assigned persistent Agent ID.
- Pending: safe live trial and negative checks; do not dispatch a financial
  batch merely to test transport. No live automation claim until proven.
