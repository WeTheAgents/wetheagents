# Verification: Block 9 GitHub-native private pilot

Current status: `implementation verified locally. Activation not run`

Verified contract:

- Outcome `1.0`
- Spec `1.1`
- Design `1.3`
- Tasks `2.2`

## Outcome result

The code now has one proposed path for canonical vNext ledger changes:

1. An owner writes one exact command in a GitHub Issue comment.
2. The owner starts one GitHub-hosted Action.
3. The Action creates a candidate branch.
4. A trusted base workflow checks the candidate as data.
5. The operator opens and merges the pull request.

The operator laptop is not part of this authority path. No custom App, local
lock, local epoch guard, or self-hosted guard is required.

This verification does not claim activation. The canonical ledger and GitHub
settings are unchanged.

## Requirement results

| Requirement | Result | Evidence |
| --- | --- | --- |
| S-71, one writer boundary | PASS for local code | `.github/workflows/agent0-ledger-candidate.yml`, `.github/workflows/guard-vnext-ledger.yml`, and `tests/vnext/test_block9_github_native.py` |
| S-72, one outcome per v1 obligation | PASS for the model | `tests/vnext/test_block9_reconciliation.py` |
| S-73, canonical genesis and replay | PASS for the model | `tests/vnext/test_block9_genesis.py` |
| S-74, repeatable shadow | PASS for the model | `tests/vnext/test_block9_shadow.py` |
| S-75, atomic cutover | PARTIAL | Candidate and guard checks pass. The exact canonical package does not exist yet. |
| S-76, gauntlet is historical | PASS for local code | The mint workflow is absent. The CLI rejects mint after `ledger/vnext/bootstrap.json` exists. |
| S-77, achievements are historical | PASS for local code | Award, revoke, and transform reject after vNext activation. A future identity mechanism is separate work. |
| S-78, forward recovery | PASS for the model | Recovery stages a complete GitHub candidate. It does not publish through a local kernel. |
| S-79, private state and projections | PARTIAL | Public projections are explicitly `deferred`. Private ruleset proof is `DEFERRED`. |
| S-80, two private E2E tasks | NOT RUN | Activation must occur first. |
| S-81, public transition | NOT RUN | The private E2E pilot and exposure audit must occur first. |

## Trust boundary results

The candidate workflow uses `GITHUB_TOKEN`. It runs on `ubuntu-latest`. It
does not merge the pull request.

The guard uses `pull_request_target`. It checks out one base commit. It fetches
candidate Git objects without a checkout. It does not import or run candidate
code.

The guard checks these facts:

- repository ID and `main` target.
- owner command bytes and source comment.
- exact package commit and manifest.
- exact predecessor and next sequence.
- idempotency key.
- semantic replay from explicit balanced postings, money, supply, and schema.
- exactly one new event plus derived state and idempotency files for later
  transactions. Earlier events, bootstrap, and genesis are immutable.
- exact workflow run and workflow path.
- no mixed code and ledger change.
- no legacy `ledger/**` write.
- no change to the trusted writer boundary.

The old direct-write workflows are absent. The BTC workflow is manual and
read-only. Existing repository guards now run on GitHub-hosted runners without
`ADMIN_TOKEN`.

## Commands run

```text
python -m pytest -q tests/vnext
```

Result: `608 passed, 18 skipped`.

```text
python -m pytest -q tests/vnext/test_block9_github_native.py
```

Result after the final trust-boundary changes: `30 passed`.

```text
python -m pytest -q tests/test_claim_removed.py \
  tests/test_cli_comment.py tests/test_cli_gates_redteam.py \
  tests/test_cli_gh_errors.py tests/test_cli_issue_edit.py \
  tests/test_cli_pr_flow.py tests/test_gauntlet_mint_pipeline.py
```

Result: `38 passed`.

```text
python scripts/check_invariant.py --root .
python scripts/check_ledger_schema.py --root .
```

Result: both checks passed. The invariant was `19025 = 10000 + 9025`.

```text
python -m ruff check <Block 9 changed Python files and tests>
```

Result: passed.

```text
pyright src/wea_vnext/block9
```

Result: `0 errors, 0 warnings` for Block 9. A repository-wide run still reports
9 existing errors outside Block 9. The disabled manual protocol workflow already
records that wider drift as separate work.

All 15 tracked workflow files parsed as YAML.

## Findings

### Resolved

- The local epoch guard created a second authority path. It is removed.
- The local transaction kernel created and pushed canonical commits. It is
  removed.
- The projection App, projection lock, and dedicated Windows accounts added a
  runtime that the private pilot does not need. They are removed.
- Three legacy direct-write workflows created a second write path. They are
  removed.
- Repository guards depended on the laptop and `ADMIN_TOKEN`. They now use
  GitHub-hosted runners and read-only checkout credentials.
- A state hash could previously agree with an event without proving the money
  transition. The guard now derives balances and escrow from explicit balanced
  postings and compares the exact result.
- A package could previously name an old event as a target. Later transactions
  now add only the next event and update only the two derived indexes.
- A changed legacy writer could previously keep its old filename and redirect
  authority to vNext. Writer-capable pilot files are immutable until deleted.
- The v1 pending-payment queue is not copied into vNext. Escrow release and
  payment are one atomic Git transaction, so no second queue protocol is needed.
- Live Actions API evidence confirmed that `run.path` is the workflow path
  without a ref suffix. The guard now checks that exact GitHub response shape.
- GitHub API reads are limited to `api.github.com` and the two canonical
  comment/run evidence endpoints.
- Ordinary source and documentation deletions pass the PR guard. A ledger or
  transaction-evidence deletion still rejects, and deleting a legacy writer is
  the only permitted way to retire that writer-capable file during the pilot.
- Writer discovery includes extensionless and hidden scripts under executable
  source roots.
- Final-tree validation requires one candidate commit whose only parent is the
  approved predecessor.
- Windows shadow principals are compared by resolved SID, not by a reusable
  account label.

### Open before the activation package

- The implementation must merge without `ledger/vnext/**` data.
- The exact predecessor is the resulting canonical `main` commit.
- GitHub Issue `#1` is still open and is the only open task in the current
  read-only snapshot. The activation package must give it one explicit
  historical-close outcome, or the operator must close it before the snapshot.
- The exact frozen input, genesis, sequence zero, state, package manifest, and
  command do not exist yet.

### Deferred

- Private ruleset proof remains `DEFERRED`.
- Comment and label projections remain `DEFERRED`.
- Public exposure checks remain `NOT RUN`.

## Next stop

Merge the code-only implementation after review. Then read canonical `main`
again and build one exact activation package.

Stop before the Agent0 workflow starts. Show the exact bytes and hashes to the
operator. This stop protects the first canonical vNext ledger write.
