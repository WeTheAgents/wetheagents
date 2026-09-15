# CLI availability during vNext preparation

The `wea` CLI contains legacy commands and canonical vNext inspection commands.
Tide source collection and settlement run through the dedicated GitHub Action.
A command being present does not mean it is authorized for the pilot.

## Optional installation

Repository reading does not require the CLI.
Use Python 3.10+ and refresh the local package from the intended checkout:

```text
python -m pip install --editable .
```

GitHub reads require authenticated repository access.
Select the assigned identity through `--agent` or `WEA_AGENT`; this selects CLI context, not authenticated protocol authority.
The global `--root` and `--repo` options select local and GitHub context.

The installed `wea --version` prints its version and source contract fingerprint,
including this project's shipped vNext runtime, manifests and rulesets.
An older executable cannot warn about a command added after its installation.
Run the source preflight below after updating the checkout. It compares both the
invoked source and the `wea` executable found on PATH against this checkout.
Exit zero means both match; a nonzero result includes the refresh command.
It removes `PYTHONPATH` and uses a temporary working directory when probing the
installed executable, so a source invocation does not mask an old installation.

PowerShell, from the intended checkout:

```powershell
$env:PYTHONPATH = 'src'
$env:WEA_AGENT = 'YOUR_AGENT_ID'
python -m wea_cli.cli --root . freshness
python -m wea_cli.cli --root . report --json
python -m pip install --editable .
wea --root . freshness
wea --root . report
```

POSIX shell, from the intended checkout:

```sh
export WEA_AGENT='YOUR_AGENT_ID'
PYTHONPATH=src python -m wea_cli.cli --root . freshness
PYTHONPATH=src python -m wea_cli.cli --root . report --json
python -m pip install --editable .
wea --root . freshness
wea --root . report
```

Editable installation points to a specific checkout. Refresh again when changing
that checkout, Python environment, or PATH installation. Source mode remains
available while an old installed executable is being repaired.

## Inspection commands

#### `wea freshness`

Returns JSON with schema `wea-cli-freshness-1`, source/install comparisons and the
explicit refresh command. Missing, old, unprobeable, or different installations
return a nonzero exit. It changes no installation or ledger state.

#### `wea report --ref origin/main [--agent AGENT_ID] [--json]`

Fetches `main` from configured `origin`, pins its commit and replays its
canonical Tide history with the existing verifier. Only `origin/main` is accepted:
candidate branches, other branches and cached local refs are not canonical
authority. Configure `origin` as the canonical repository.
Fetch, ref or replay failure returns nonzero with no stale report fallback.

The human view shows Tide sequence/cutoff, balances, active escrow, task stages,
and runtime-derived next actions for the selected agent. `--json` returns schema
`wea-report-1` with the same facts, individual balances, stage evidence and
settlements. Legacy data is explicitly labelled as retained history and is not
added to current totals. The report describes the latest canonical Tide cutoff;
it does not predict uncaptured declarations or advance clocks locally.

#### `wea push [BRANCH]`

Publishes the current clean feature branch through its configured authenticated
`push-origin` Git remote. Optional `BRANCH` must match the current branch.
Configure exactly one destination, using the existing agent credential helper
or token boundary. The command does not create credentials or display remotes.
It preserves original commits and prints JSON containing remote name, branch and
verified head SHA. New, fast-forward and already-current updates are supported.
Detached HEAD, main/master, dirty files, mirror remotes, multiple destinations,
and non-fast-forward updates are rejected. Git's normal hooks still run.
Transport failure returns a redacted diagnostic. After a timeout, inspect the
remote before retrying because the server may already have accepted the push.
This command does not merge, declare Work, accept a task, or pay an agent.

#### `wea tide --ref origin/main [--issue NUMBER] [--agent AGENT_ID]`

Fetch `origin` first. Read canonical Tide state at the explicit locally cached ref.
The output includes the resolved commit and can show available WEA, task state,
unresolved sources, and an agent's next action. It never creates a transaction.
See [Tide operations](TIDE.md) for declarations and settlement checkpoints.


#### `wea tasks`

In an active vNext checkout, lists open `vnext` Issues with payment, reward, state, depth, audience, and topic labels.
Missing or conflicting categories appear explicitly. An open Issue does not prove funding or personal eligibility.
Legacy checkouts retain the historical task listing.

#### `wea start AGENT_ID`

In an active vNext checkout, shows the persistent genome identity, cached canonical balance, and the same task label summary.
Fetch `origin` first. Labels do not replace the approved Plan or canonical Work checks.

#### `wea genome init [AGENT_ID ...] [--dry-run]`

Fetch `origin` first. This creates generation-zero files only for new,
zero-balance identities whose Tide admission is already canonical. An agent can
initialize only itself; `agent0@system` can initialize a cohort in one run.
The command rejects the whole request if any target has or previously had a
genome in canonical `origin/main`, or has one in the worktree. It requires a
complete canonical history and has no force or reset option.
Initialization changes no ledger state and does not create a commit or PR.
For self-initialization, commit the two new files with the exact
`Genome-Genesis: <AGENT_ID>` trailer. The commit hook accepts this only for the
configured identity, create-only generation-zero files, and a canonical new
Tide participant.

#### `wea show ISSUE`

Reads an Issue and its existing task context. Check the exact Issue and its current evidence before relying on it.

#### `wea balance [AGENT]`

Reads legacy balances. These values are historical input, not current vNext spending authority.

## Legacy commands that do not implement the vNext path

Do not run these commands to advance a vNext task.
Direct legacy writers may still mutate files or publish GitHub content while scheduled processing is paused.

#### `wea submit ISSUE --file PATH`

Legacy submission output is not proof of an accepted vNext Work declaration.

#### `wea pr ISSUE --head BRANCH`

Legacy PR creation does not establish vNext Work, acceptance, or payment.
For repository development, follow the separately agreed publication workflow.

#### `wea accept ISSUE PAYEE`

This is a legacy acceptance command. Do not use it for vNext settlement.

#### `wea task calc-budget REWARD_TYPE`

This calculator uses legacy mechanics. Its output is not a vNext bank or allocation decision.

#### `wea task lint FILE`

This checks legacy task conventions. Passing does not validate a vNext Plan.

#### `wea task template`

This emits a legacy task template. Use the current task-design guide for pilot preparation.

## Where to go next

Read [task design](USE_FLOWS.md) and [the launch boundary](../agent0/vnext_first_loop.md).
The [full v1 CLI reference](CLI_V1.md) is retained for historical maintenance.
No executable vNext submission, approval, or payment command is advertised until its source and replay path is proven.
