# Verification - inactive schema-5 financial implementation

This is a reviewable pending implementation, not installation or activation.
Same Codex-2 native session 01a0fd5e-c86b-7a43-ab0a-361eba0862d9 on work/slot-1;
HEAD fee147a968224e9ead3075e62771e82cff1452d2 and index remain unchanged.
No independent native review or CI has occurred. Agent0 performs them separately.

## Current checks

Commands use this checkout's .venv/Scripts/python.exe and current dependencies.
Evidence is under D:/AgentRuns/wea/agent0/20261002-readiness-implementation/.
All test API/source/merge IDs and times are explicitly synthetic fixtures; they
are never operator receipts or evidence of a real GitHub activation/mint.

| Check | Actual result | Evidence |
| --- | --- | --- |
| Financial adapter plus explicit native candidate suites | 54 passed in 268.98s in the retained focused run | financial-final-focused.txt |
| Reconnect task-label and wheel-resource/isolation suites | exit 0; 21 passed in 19.72s, both task-label parameters included | financial-reconnect-repairs.txt/result.json |
| Fresh stabilized full tests/vnext | exit 0; 974 passed, 18 skipped, 1 deselected in 1058.99s | financial-reconnect-full-vnext.txt/result.json |
| Unchanged Windows owned-process check | separate trusted executor, exit 0; 1 passed in 0.89s | trusted-owned-process-check.json |
| Required vNext/tests and changed-CLI Ruff | exit 0; all checks passed | financial-reconnect-lint.txt |
| Canonical invariant | exit 0; balances plus escrow = 19025, Tide 25 | financial-reconnect-invariant.txt/result.json |
| Ledger schema | exit 0 | financial-reconnect-schema.txt/result.json |
| Protected original files and canonical replay | all 265 byte-identical; all 25 batches replay exactly | financial-reconnect-protected-files.json |
| Accepted historical validator and uncovered-record inventory | 3 consumed, 1 retired, 19025 = 19025, zero new money | financial-reconnect-historical.json |
| Fresh offline wheel and full source comparison | exit 0; all 188 packaged Python/JSON files match | financial-final-wheel.txt/result.json, financial-final-package-receipt.json |
| JSON Schema structure and diff whitespace | passed | source schemas; git diff --check |

Full pytest uses an explicit fresh writable basetemp and offline existing pip
cache. Only the exact Windows process-tree case is deselected, as directed,
because its unchanged code/test already passed through the authorized trusted
executor. No Access code/test or assertion is weakened. Agent0 repeats that exact
case after this worker stops; that later readback is not claimed here.

## Retained failures and superseded limits

The original stage-1 broad run was 942 passed, 18 skipped, 3 failed. Its log
hello-world-vnext-tests-fixed.txt remains. Missing pip/wheel prerequisites were
repaired locally without new dependency declarations. The baseline access_snapshot
mock failure reproduced on unchanged main and was repaired. The financial writer
also supplies hello_world; the mock now declares that keyword and asserts the
ordinary path receives None. Both label parameters and packaging pass again.
The Windows limitation is resolved by the separately retained trusted pass.

The former financial-full-vnext.txt stopped at 43% after exec-server disconnect.
It has NO exit verdict and is not a passed suite. financial-reconnect-before.json
retains Agent0's process-absence and account-binding readback. No concurrent old
worker/test process remained when the fresh run started. Neither failed nor
interrupted logs were erased.

A broad CLI lint probe found 129 errors in unchanged legacy CLI files. Those
files are outside this maintenance scope. Required vNext/test and changed-CLI
lint passes; the broad probe is not mislabeled green.

## BDD and financial proofs

- R-09/S-09: accepted pinned Block-2 witness and validator restore the three
  consumed opportunities without money. Tombstones stay retired; all original
  legacy per-Agent keys, opening balances and ledger bytes remain unchanged.
  Uncovered historical mint records/keys block activation pending explicit mapping.
- S-09B: tests invoke the real build_candidate adapter, serialize all three
  journal/state/receipt files, validate with trusted offline code, and reload
  complete history. One valid accepted greeting credits exactly 42 to the immutable
  base Agent. Retry/no-op, alias, duplicate/rejection and competing order add none.
  Current supply increases by 42; opening supply and task/role escrow remain fixed.
- P-01..08: later participant approval alone creates no mint or admission authority.
  A committed fixture participant batch and its explicit synthetic canonical
  merge time feed the real registry_at path. Pre-admission Work remains invalid; fresh Work after admission can
  mint without replacing activation. Base Agent mappings remain immutable.
- S-09C: native evidence selects permanent Issue/body and separate installation
  and activation sources. The system Contract stays active with zero bank and
  review fee. New malformed/wrong-owner/role/runtime/stale/edited/foreign evidence
  cannot mint; retained payments are not reversed after later edits. Unresolved
  Hello World boundaries preserve prior state and unrelated task processing.
- Schema-4 binding policy transitions to schema 5 without losing Access/initiative
  authority. Binding and financial schema downgrades fail closed. Schemas 1..4 and
  their recorded task 0.9/participant 0.10 runtimes continue identical replay.

## Self-review and proven fixes

Reviewed three specific risks: aggregate intents paid on every replay; future
admission retroactively validating old Work; and new source failures erasing
paid state or blocking unrelated tasks. Retained opportunities and delta-only
financial application fix the first. Temporal registry_at plus retained invalid
revision dispositions fix the second. Frozen paid records and unresolved boundary
dispositions fix the third. Serialized reload and later-admission tests exercise
these paths through the financial adapter, not only a preview calculation.

Two edge cases verified: concurrent aliases choose one deterministic account
mint, and an unpaid edited snapshot fails while a later edit never reverses an
already paid record. Cross-batch Work/acceptance, consumed legacy owners and the
retired tombstone also have financial tests. Raw imports/runtime globals remain
fail closed, and the six copied native dependencies are byte-identical to 0.9.

## Exact pending packet and relay

pending-packet.json and financial-final-package-receipt.json name current runtime,
complete source-package identity, built wheel and source archive. Proposed source
schema, utf8-exact-1 comparison, exact body and installation/activation templates
remain pending exact operator decisions. All actual source IDs/times remain null.
The new workflow input defaults empty; no live runtime was repinned or activated.
Its protected candidate integration is review-only and remains subject to the
separate installation/activation and CI gates.

No native commit is asserted. No fetch/stage/commit is required from restricted
shared Git storage. Codex-2 consents to Agent0 relaying these exact reviewed bytes
with real Codex-2 author identity and Agent0's actual committer/signoff. Do not
invent a native commit, session or Codex signoff. Agent0 separately publishes the
draft and performs review/CI; installation, activation, Issue mutation, financial
publication and real mint remain separate gates.


## Proposal schema constant correction (same-session continuation)

Agent0 found two stale runtime constants in source-schema.json and
installation-source-schema.json. Both now name the existing verified 0.11
runtime. Only those constants changed; comparison, body and authority semantics
are unchanged. The schemas, templates and pending packet agree. Real approvals,
source IDs and times remain null. Synthetic complete-checkpoint activation and
installation commands validate with the current runtime; both reject the obsolete
runtime, incomplete checkpoints and invalid dates. Specimens are TEST ONLY, not
operator sources or authorization. Evidence: financial-packet-fix-check.json.

All 264 files in financial-tested-tree.json match before and after this correction,
including production, ruleset/manifest, workflow, tests and pyproject bytes. All
188 packaged source files, the source package, wheel and source archive remain
unchanged. No broad pytest rerun was needed: the completed full result remains
974 passed, 18 skipped, 1 deselected, exit 0; the unchanged Windows test has its
separate trusted 1 passed in 0.89s result. Original failures and the interrupted
43% log remain historical evidence without a successful exit verdict.

The corrected 37-file review diff and manifest are financial-packet-fix-deliverable.patch
and financial-packet-fix-deliverable-receipt.json; earlier seals are preserved.
Codex-2@codex consents to honest Agent0 relay of these actual bytes with
Codex-2 author identity and Agent0's actual committer/signoff. No native commit
or Codex signoff is invented. Independent native review/CI, installation,
activation, Issue1 mutation and real mint remain pending separate gates.
