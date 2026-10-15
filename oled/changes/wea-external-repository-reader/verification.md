# External repository observation: Verification 1.0

Decision: Not ready for protected installation or private Domain bootstrap. Implementation and local verification are complete; final independent/native review and publication/installation gates remain with the coordinator. Bound to Outcome/Spec/Design/Tasks 1.0.

## Fresh evidence, 2026-10-15

- Nine-file Access/initiative/reader regression: **295 passed, 2 failed** in 530 seconds. The two exact activation/committed-package tests correctly rejected CRLF working bytes against Git-normalized LF bytes. Task files were normalized to the repository LF contract without weakening package verification or changing Python behavior.
- Final targeted command: `python -B -m pytest -q -p no:cacheprovider tests/vnext/test_repository_reader.py tests/vnext/test_runtime_boundary.py tests/vnext/test_scenario_registry.py tests/vnext/test_access_runtime.py::test_exact_activation_with_committed_protocol_and_response_loss`: **141 passed** in 13.58 seconds, including both prior failures and all 64 executable workflow input combinations. This is a targeted rerun, not a claim of a new full-suite run.
- Scoped Ruff lint and format checks, documentation sync, staged/unstaged whitespace checks: pass.
- Offline replay of retained canonical Access journal `c781edb6cb72361a5a14261171cff18dee90a19f`: baseline and candidate both preserve 13 records, 4 grants and active policy `wea-long-lived-initiatives:1`. Exact state hash: `69cfb4e9ca08555e68d9b612573b69fdf349aef8e36eceeecadc058f5288fe01`. No network or journal write.
- Canonical transport, pure initiative/Access/protocol modules and all released executor paths are byte-unchanged in Git.

Independent source review found the Bash errexit AND-list gap. Three independent required-field checks replaced that list. The initial shell tests also discovered the Windows WSL stub instead of installed Git Bash; discovery now derives Git's installation path and proves `BASH_READY` before any negative assertion. The final truth table therefore cannot count a broken interpreter as successful rejection. Earlier failures remain in coordinator evidence. Initial oversized pytest parameter IDs were shortened to avoid Windows path limits; the oversized-response assertion remains intact.

Evidence files retained by the coordinator: `external-reader-regression.txt`, `external-reader-focused-final.txt`, `external-reader-extra-results.json`, both `external-reader-history-*.json`, and independent review records. No live visibility, source publication, credential, grant, workflow dispatch or package installation is claimed.

## Contract and protected lean cut

ER-01..04 use real reader HTTP-opener tests, process capture/private-failure/retry cases and retained LRI alias/preflight regressions. ER-05 uses the same reader, no-writer spies, strict CLI mode rejection and the actual workflow's 64-case Bash guard truth table. ER-06 has explicit reader/writer token separation and credential-source/redaction tests. ER-07 has exact-byte activation, APT/history/regression checks and unchanged protected paths.

One bounded standard-library reader is shared with isolated preflight; one process injection seam and optional composition-root credential selection. No general API client, new dependency, second writer or safe validation removed. Self-review found no further necessary cut. Intended changes are the reader, adapter/workflow wiring, relevant tests and six durable records. Ignored .venv, bytecode, Ruff and pytest caches are local generated test artifacts; the sandbox cannot inspect the elevated-run pytest-cache directory, and it is not staged.

Private visibility requires the pending exact credential operation and successful actual preflight. Protected installation requires APT and the independently diagnosed Hello World installed-package reconciliation. Reader checks do not establish ordinary Tide health. Final deployment approval and native review remain separate gates.
