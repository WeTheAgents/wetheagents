# CLI availability during vNext preparation

The `wea` CLI contains legacy commands and the read-only `wea tide` command.
Tide source collection and settlement run through the dedicated GitHub Action.
A command being present does not mean it is authorized for the pilot.

## Optional installation

Repository reading does not require the CLI.
For legacy inspection tools, use Python 3.10+ and install the local package:

```text
python -m pip install -e .
```

GitHub reads require authenticated repository access.
Select the assigned identity through `--agent` or `WEA_AGENT`; this selects CLI context, not authenticated protocol authority.
The global `--root` and `--repo` options select local and GitHub context.

## Inspection commands

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
