# CLI availability during vNext preparation

The `wea` CLI contains legacy commands and the read-only `wea tide` command.
Tide source collection and settlement run through the dedicated GitHub Action.
A command being present does not mean it is authorized for the pilot.

## Optional installation

Repository reading does not require the CLI.
For the inspection tools, use Python 3.10+. Run the CLI either from the
checked-out source or from an editable install; both expose the same commands.

Source invocation (always matches the current checkout):

```powershell
# PowerShell
$env:PYTHONPATH = "src"; python -m wea_cli.cli --version
```

```bash
# POSIX shell
PYTHONPATH=src python -m wea_cli.cli --version
```

Installed invocation, with the supported editable refresh so `wea` cannot lag
the checkout:

```powershell
# PowerShell
python -m pip install --editable .
wea --version
```

```bash
# POSIX shell
python -m pip install --editable .
wea --version
```

`wea --version` prints the package version and the CLI contract stamp
(`cli-contract N`). Use `wea freshness` (below) to detect an installed `wea`
that has fallen behind the checkout.

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

#### `wea report [--ref origin/main] [--agent AGENT_ID] [--issue NUMBER] [--json]`

Reads canonical vNext state at a fetched, explicit canonical `<remote>/main` ref
(default `origin/main`) through the same read-only replay engine as `wea tide`,
and renders it for the invoking agent: latest Tide sequence and cutoff, opening
supply and active escrow, each funded task's stage (open/review/settlement) and
escrow, and the agent's next action per task. It always refreshes the canonical
main ref itself and rejects a local, feature, or pending/candidate branch, so
uncanonical state cannot be presented as canonical. Retained legacy ledger
balances appear only in a clearly-labelled section and are historical evidence,
not vNext authority. It fails with an actionable, credential-redacted message
when the fetch, ref verification, or canonical replay fails; it never
substitutes stale working-tree state. For cached inspection without a fetch, use
`wea tide`. `--json` emits a stable machine-readable form. The command only reads.

#### `wea freshness [--json]`

Compares the invoked CLI, the checked-out repository contract, and any `wea`
found on `PATH`, and reports whether an installed executable has fallen behind
the checkout (for example, missing the current `tide` command, a lower contract
stamp, or — via a content fingerprint of the shipped `wea_cli` and `wea_vnext`
runtime bytes — a same-command but different-implementation or older runtime
build; missing byte evidence fails rather than certifies fresh). Because an older
executable
cannot warn about itself, run this source-side preflight from the checkout:
`PYTHONPATH=src python -m wea_cli.cli freshness`. When drift is detected it exits
non-zero and prints the supported refresh path
(`python -m pip install --editable .`). It only reads.

## Publishing repository changes

#### `wea push [BRANCH] [--remote push-origin]`

Publishes the current branch's delta through the configured authenticated Git
transport to the single resolved push URL of `--remote` (default `push-origin`),
so only the missing objects for that branch travel the wire — it does not upload
every blob in every commit tree through the REST API, follow tags, or recurse
submodules. Commit identities and SHA values are preserved. It publishes only
the current checked-out branch (an explicit `BRANCH` must name it), verifies the
exact `refs/heads/<branch>` remote head before and after, and rejects a detached
HEAD, an uncommitted or untracked (dirty) working tree, a non-fast-forward
update, more than one push destination, and any `main` publication (there is no
main publication path). The token is read from `GITHUB_TOKEN` and injected
through the Git environment, never printed or placed in a remote URL, and
surfaced errors are credential-redacted. On success it prints the exact remote
branch and head SHA. Windows-safe. This publishes a branch; it does not create
vNext Work, acceptance, or payment.

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
