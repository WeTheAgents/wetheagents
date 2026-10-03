# Review-correction verification: inactive HelloWorld42 candidate

Authority clarification by Agent0: this file retains the stopped Code2 snapshot
below. Final code at b3675d3b663451c84658fa0f36b6183b77a36443 was independently
reviewed in a separate technical session under the same operator: no actionable
defects; 31 read-only-compatible tests passed. Agent0's full run passed 984 tests
with 18 skipped and 1 deselected; the separate Windows case passed. Final CI
passed validate, boundary, semgrep and Workers Builds, but trusted-ledger-check
and tide/replay failed on the existing protected writer boundary. This does not
authorize merge, installation, the proposed source isolation or activation.
Earlier pending statements below describe the worker's historical checkpoint.

Same Codex-2@codex native session 01a0fd5e-c86b-7a43-ab0a-361eba0862d9,
work/slot-1, current unchanged HEAD aee48d69c40c76da47c91daeee5835ab25f407f3, canonical task base fee147a968224e9ead3075e62771e82cff1452d2.
The three actual PR1035 review failures are corrected and verified by the current
focused native checks plus the completed trusted local Agent0 full run.
The original technical review session 01a0fe58-25ab-7e50-b00a-11823651d2cb
reported these three actionable findings; same operator, not independent ownership.
Fresh review/CI and live gates remain pending; no review-clean/CI-green claim.

| Check | Actual current result | Evidence |
| --- | --- | --- |
| Red regressions on original code | 4 failed, 6 deselected: authority, both lone surrogates, global precheck | review-correction-red.txt/result.json |
| Initial corrected regressions | 10 passed in 107.26s; original receipt elapsed 108.47s | review-correction-regressions.txt/result.json |
| Reconnect affected suites | 117 passed, 1 packaging failure from denied pip user-cache write; includes extended authenticated-conflict test | review-correction-reconnect-focused.txt/result.json |
| Unchanged packaging test after cache repair | 1 passed in 12.10s, exit 0; no dependency/assertion change | review-correction-reconnect-packaging-fixed.txt/result.json |
| Completed trusted local full vNext run | 984 passed, 18 skipped, 1 deselected, 1 warning; exit 0 (authorized trusted local Agent0 validation, not native Code2); 1322.77s elapsed, pytest 1321.24s | review-correction-resilient-full.txt/result.json |
| Interrupted native full vNext run | stopped at 57%, no exit verdict; not successful | review-correction-full.txt; old running receipts preserved |
| Invariant / ledger schema | Both exit 0; 19025 WEA, zero escrow, Tide 25 | review-correction-reconnect-invariant/schema.txt and separate result.json files |
| Required Ruff | exit 0 | review-correction-reconnect-lint.txt/result.json |
| Historical bytes / replay | 265 files match canonical fee147a9; 25 batches replay byte-identically | review-correction-reconnect-protected-files.json |
| Accepted witness / inventory | validator passed; 3 consumed accounts, retired tombstone, no new money | review-correction-reconnect-historical.json |
| Offline wheel / resource bytes | exit 0; all 188 packaged Python/JSON files match current source | review-correction-reconnect-wheel-fixed.txt/result.json, wheel-comparison.json |
| Source schemas | structurally valid; synthetic current-runtime complete checkpoints pass, previous runtime and incomplete checkpoint fail | review-correction-reconnect-source-schema-check.json |
| Exact Windows owned-process case | excluded as directed; production/test bytes unchanged; final trusted repeat pending Agent0 after STOP | prior actual published-tree trusted pass retained |


## Corrected behavior and pending semantic approval

1. Authenticate source ownership/operator identity and exact activation fields,
   runtime, checkpoint, Issue revision/body, attestation and chronology before
   counting authority. Foreign, malformed and invalid declarations get unresolved
   dispositions and cannot disqualify the sole valid decision. Two valid operator
   activations still fail closed initially; after activation they preserve prior
   state, block new HW mints and record an unresolved boundary.
2. Validate greeting UTF-8 encodability before retaining Work. Escaped lone high
   and low surrogates get explicit unresolved dispositions; they never enter
   decoded Work/state. The exact captured ASCII-escaped snapshot remains evidence.
   No replacement, normalization or Unicode equivalence is introduced. A fresh
   valid greeting can qualify later while an unrelated valid task continues.
3. Resolve the canonical active system path before the global unresolved-source
   precheck, with the narrowly bound exception described below.


Before: ledger.candidate rejected every unconfirmed source before loading the
canonical active anchor. Activated HelloWorld therefore never reached its isolated
boundary handler, and unrelated valid task transactions were blocked.

After: load the canonical predecessor first. Only a retained active HelloWorld
anchor plus retained HelloWorld state, canonical repository, permanent Issue
4015417565/number 1 and Issue/comment kind can isolate that evidence. The existing
native boundary still reports it unresolved, preserves paid records/balances/supply
and produces no new HW mint. Unrelated valid tasks continue; the regression funds
an actual 100-WEA escrow through serialized candidate, offline guard and reload.
Initial activation, caller-only anchors, ordinary required task sources and
foreign-repository unresolved sources remain strict. No general permissive
exception or alternate writer is introduced.


Accepted R-09/S-09/S-09B/S-09C and P-01..08 remain unchanged. The retained
candidate spec claims unrelated-task isolation, but is not itself new authority.
R-09 requires confirmed events and gives invalid Work no mint; S-09C excludes the
ordinary task activation chain and keeps the system active after invalid Work.
The accepted spec does not separately prescribe global precheck ordering.
The earlier claim of explicit operator approval was unsupported: item 3 belongs
to Agent0's locally authored review-correction-prompt.txt, not a direct user
approval of this behavior. The active-path isolation is implemented and tested
proposal code, pending explicit operator agreement before merge or installation.
Tests and a clean technical review demonstrate behavior, not policy acceptance.
No accepted BDD text or code is changed by this authority clarification.

## Package identity

Runtime: `["c3520362f9cc7354777201d4657739886db30c457c0ebabc2ca5bcead734a536", "0.11", "300c135ef8d26c2f3669c68c168e98111c52cd50fd48d7f44dc642e7f2cb1bcb"]`

- Code/test fingerprint: `4eb77a8c00e4d1b5aff38f11b6a1b85f16cf2d978c0dcf30df9312aed40bc32c` (265 tested source/test files).
- Source-package SHA256: `6d19a6c6828f8a88c168907b6a30f640cdb61a918dbc05caf797e72ffff26031`.
- Wheel SHA256: `e9cb5a6726c31ce1fb9cc6b930f74e8c6be6d4019068a5ad1d0de4e1a19ec6fa`.
- Source archive SHA256: `9249e1dae9710b0b3d136bdd034a22f9910666067d3176a2a1d81e2b737be1da`.
- Proposed exact body SHA256: `f278640dcced89db53191e09f7dfaa6d6e419d7c6e8e17d9321d68a7b8d1c6e5`; body bytes unchanged.


## Retained history and pending gates

Earlier full 974/18/1 evidence applies to the original published aee tree,
not these modified sources. Original 942-pass/3-failure logs and the older 43%
interrupted full log remain preserved. The first correction focused log contains
five dots with no exit receipt; it is interrupted, not passed. The stale original
running process receipt and reconnect process-absence/account-binding readback
are preserved. No duplicate former process was started. Reconnect wheel/focused
cache-denial failures remain alongside the successful process-local writable-cache
repair. A local sealing helper first used the wrong state filename; it was
corrected to the production STATE constant, and its full actual check exited 0.
No production workaround, dependency declaration, arbitrary skip or assertion
weakening was used for these local tooling repairs.
The second native transport disconnect left review-correction-full.txt at 57%
without an exit verdict; it remains interrupted, not passed. Agent0 verified the
former native PID25300 and owned pytest absent, then obtained the real resilient
full result through an authorized bounded trusted local executor outside the
native tool lifecycle. Its actual stdout/receipt remain unchanged and explicitly
attributed to Agent0, not Code2. No native full success receipt is manufactured.


All installation/activation approvals, actual source IDs and times remain
null/pending. Exact body, utf8-exact-1/source proposals, code review, protected
installation, activation, Issue1 mutation and real mint are separate gates.
The candidate is inactive. No fetch/stage/commit/push, PR/comment mutation, live
Tide, installation, activation, mint, deployment or payment occurred here.

Original aee48d69 CI reportedly passed boundary/validate/semgrep/Workers Builds;
trusted-ledger-check and tide/replay failed with the exact protected source gate
`existing writer boundary source changed: .github/workflows/tide.yml`. That gate
is expected and remains untouched. It is not bypassed or claimed green. Fresh
native technical review (same operator; not independent ownership) and actual CI
of this correction remain Agent0's next review steps after STOP. The unchanged
Windows case's published-tree trusted pass (1 passed, 0.87s per Agent0) is prior
evidence; Agent0 repeats it for this final tree after STOP.

Separate Access installation consequence: Agent0's unchanged historical reader
with verify_closure=False validated 9 records at journal head
459b333b74bf27246e45947baf5d12503fd45589, authorized code
37949899b5b074384275fe08e3bbdb94bc5f3511. The candidate changes pinned
engine.py, tide/__main__.py, ledger.py and replay.py. Ordinary live Access would
reject this changed package until a separate exact operator append-only Access
package transition. No grants, journal records or intervals changed. This readback
and consequence are in hello-world-access-installation-impact.json; historical
read mode is not installation authority or permission to update Access.
