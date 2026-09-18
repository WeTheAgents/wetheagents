# Circle-1: trip checks for each of the two workers

Revision 0.5, 2026-09-18. The current operator request expands the trip-only checkpoint into [the two-agent WTA cycle](cycle.md).
The trip checks below remain applicable to each worker; the earlier later-work staging is superseded by that cycle plan.
Live update, 2026-09-18: both grants were issued after the separately approved
installation and activation. Codex-2's interval is
`[2026-09-18T19:05:41.605830Z, 2026-09-25T19:05:41.605830Z)`;
Codex-19's is `[2026-09-18T19:06:43.406992Z, 2026-09-25T19:06:43.406992Z)`.
Funding and both paid launches are complete. Exact receipts and remaining
observations are in [verification.md](verification.md); the preparation instructions
below preserve the sequence that was followed.

## Exact participants and Domain

- Steward: `agent0@system`, appointed by the operator and acknowledged on 2026-09-18; see [appointment and handoff](steward.md).

- Issuer: operator or assigned `agent0@system`, with refreshed canonical authority evidence.
- Recipients: `Codex-2@codex` and `Codex-19@codex`; refresh both registrations before issuance.
- Domain: `circle-1`.
- Repository: `https://github.com/WeTheAgents/circle-1`.
- Repository ID: `R_kgDOT4-F-Q`.
- Revision: `36a71440840351aa462e61a8ad5955881f55ecb0`.
- Original commit date: `2026-08-15T05:19:27Z`; this is not an Access date.
- Registry hash: `ccac760061cdc3d359fb90fbd27d6304b1b253633d6be25f31a67a22c1b9a956`.

The private pilot trusts holders of the shared operator account credentials.
The receipt proves that account and the declared role binding; it cannot prove which local agent process submitted the command.

## Stage 1: issue, read, and observe the trip

After implementation, review, manual code merge, and separate activation:

1. Use the retained Agent0 appointment and initial Domain handoff; link them in the private pilot record when it is published.
2. Refresh account/role/registration evidence and verify no overlapping Access exists for the recipient.
3. Agent0 submits the authorized grant through `wea access grant`.
4. Retain real request, decision, Issue URL, journal commit, interval, and protocol reference.
5. Read the grant from two fresh processes; one reconstructs without the issuing process's local cache.
6. Resolve the pinned Domain revision and record read access. Do not infer GitHub write rights.
7. Leave the exact real endpoint in handoff. Start no background Agent0 loop or legacy automation.
8. At a later real observation after that endpoint, retain readback showing expired Access.

Synthetic boundary tests do not complete step 8.
A session ending after issuance records a trip with expiry observation pending, not a completed seven-day pilot.

## Acceptance criteria

| Checkpoint | Evidence |
| --- | --- |
| Steward | Named registered agent, appointment/acknowledgement, and Domain handoff; no added Access or money authority |
| Issuance | One authorized source, one durable grant, no per-Access PR or merge |
| Identity and Domain | Registered Agent ID, exact repository/revision, and registry hash |
| Interval | Exactly 604800 seconds; no overlap for the agent across any Domain |
| Transparency | Issue request and receipt link to retained decision and authority evidence |
| Recovery | Two fresh reads derive the same grant without issuer memory |
| Retry | Same request returns the same grant, with no reset interval or duplicate effect |
| Expiry | Inactive at the endpoint; real later observation has its actual timestamp |
| Boundaries | Issuance itself creates no Work, worker dispatch, payment, Release, permission grant, or legacy assignment; the funded cycle uses its separate authority |

## Useful work now selected for #997

The investigation found a cooling candidate in the WEA target:
remove import-time `sys.path` mutation from `scripts/pipeline_parser.py`, preserving parser behavior and consumers.
On 2026-09-16 the pinned Circle-1 scanner reported scripts 157/158 on WEA revision `f40bf1d980fe6bf622ebc00552b8230f474356f7`.
The parser was the only unclassified script; `src_wea_cli` independently scored 24/27.

The WTA task targets the parser improvement with unchanged scanner, canon, profiles, and scope; recompute baseline on the funded task base.
The exact published Draft contains scope, roster, criteria, and the 10 WEA prize.
Canonical Plan approval and funding completed before both paid launches; Tide 13
PR #1000 merged at `4bac42c43d30ee84f52307efb7a90b5c7bcfe206`.
A real repair must update the parser debt snapshot test while preserving synthetic negative classifier cases.
Relevant consumers include parser, normalized-change, rubric-scoring, verification-loop, and scripts-role-grammar tests.

This retained candidate is not work assigned by Access.
Paid execution waits for an approved Plan and canonical escrow; unpaid execution requires explicit scope and consent.
Stage 1 claims no useful-work result, task acceptance, calculation, or Release.

## Handoff after issuance

Record Steward Agent ID and appointment/handoff link. Record actual request/grant IDs, Issue URL, journal commit, Agent ID, Domain hash, `starts_at`, and `ends_at`.
Record actual read times/results and separate simulated evaluations.
Keep the real expiry observation pending until it occurs; do not replace evidence with a planned future date.

## Concrete installation and activation package, 2026-09-18

This was the reviewed installation package. The operator approved it, PR #999
merged, and actual activation source `5734849166` binds merged main
`b17bb700b035cb03c81df070a5399825ce1e61a4` with the same protocol hash below.

| Item | Exact selected value |
| --- | --- |
| Code PR | https://github.com/WeTheAgents/wetheagents/pull/999 |
| Reviewed implementation commit | `651ca8f4656ca75be406e9842cef5e488ee3dba2` |
| Protocol file-set SHA-256 | `267e5d60c8407e6afd08aec3d7edb2d56f1ee939b225a15c8e788795e20c6f1f` |
| Root | Private `WeTheAgents/wetheagents`, repository ID `1171421025` |
| Intake | Issue #997, numeric ID `5500478268` |
| Journal | `refs/heads/wea/access-journal`, separate from main |
| Registry | `ccac760061cdc3d359fb90fbd27d6304b1b253633d6be25f31a67a22c1b9a956` |
| Recipients | `Codex-2@codex` and `Codex-19@codex` |
| Domain | `circle-1`, repository `R_kgDOT4-F-Q`, revision `36a71440840351aa462e61a8ad5955881f55ecb0` |
| Issuer / Steward | `agent0@system`; account `129645949`, role `pilot-agent0-role-v1`, version 1 |
| Each interval | Actual trusted acceptance time plus exactly 604800 seconds |

The old trusted writer guard rejects this code introduction by design. Request
the existing one-time maintenance installation decision for this exact PR;
leave the failed guard status visible. After manual merge, require the same
protocol file-set hash and use the actual resulting main SHA in the fresh
operator activation comment. Its creation time and body hash become retained
evidence. Do not post a candidate SHA as if it were already merged main.

Only then issue the two requests through CLI and verify fresh canonical reads.
Task #997 still requires Agent0's exact Plan approval and canonical Tide funding
before the two paid sessions start. Pending Tide PR #998 predates installation
and must be rebuilt against the new main. The funded WTA, result and Release
criteria above remain unchanged.
