# Task #980 — Logic model: reliable `wea report`, `wea push`, `wea freshness`

A code-free description of how the three commands behave and why. It documents
observable behaviour and decision points, not implementation lines.

## Scope and boundary

- Only `wea report`, `wea push`, `wea freshness` and their wiring, focused tests,
  docs, and this report change. BDD, immutable executors, rulesets/manifests,
  Tide settlement semantics, authority, identity bindings, balances, task states,
  and historical evidence are untouched.
- The vNext read path lives in `src/wea_cli/tide.py`, which the runtime-boundary
  guard already permits to read `wea_vnext`. The new `freshness` and `push`
  modules deliberately carry no `wea_vnext` reference, so they stay outside the
  guarded writer surface and add no new members to that allowlist.

## `wea report` — canonical vNext snapshot

Purpose: show the real vNext/Tide state from a fetched canonical ref, read-only.

1. Resolve the configured ref (default `origin/main`) to an exact commit.
   - If the ref cannot be resolved → fail with an actionable message ("fetch
     origin first"). There is no fallback to stale local data.
2. Confirm canonical Tide is active at that commit (the bootstrap file exists).
   - If not → fail actionably (the checkout predates Tide initialization).
3. Replay the retained journal through the existing read-only ledger API
   (the same `Replay` engine `wea tide` uses).
   - If replay/verification fails → fail actionably; again, no stale fallback.
4. From the replayed state, present:
   - resolved commit, latest sequence, and cutoff;
   - opening supply, total balances, and active escrow;
   - each funded task with a lifecycle label derived only from the projection's
     `plan_status`/stage `phase`: **funded → open → review → settlement**
     (open = intake/join/moves, review = decision, settlement = closed);
   - the invoking agent's balance and, per task, the next action produced by the
     runtime's own `next_action` — lifecycle guidance is read from the runtime,
     never invented here.
5. Explicitly separate retained legacy history: the frozen `ledger/*.json`
   predecessor files are listed and labelled as historical, not vNext authority.
6. Output: a concise human view and a stable `--json` object with the same data.

## `wea push` — authenticated git transport

Purpose: publish exactly one branch's delta, preserving commit identity.

- Uses native `git push` over the configured push remote (default `push-origin`
  if present, else `origin`; overridable with `--remote`). This replaces the old
  per-blob GitHub REST reconstruction, which re-uploaded every tree/blob.
- Preserves original commit identities and SHAs (native git transfers the delta),
  and returns the exact remote branch and head SHA, verified by re-reading the
  remote ref after the push.
- Update modes: new branch (create), fast-forward (update), and idempotent
  (already up to date). `--delete BRANCH` removes a remote branch.
- Refusals (each an actionable error, nothing published):
  - detached HEAD with no explicit branch;
  - dirty working tree when publishing the checked-out branch (ambiguous state);
  - non-fast-forward update (remote is not an ancestor of local);
  - `main`/`master` publication — this task adds no protected main path.
- Authentication uses `GITHUB_TOKEN`/`GH_TOKEN` injected as a one-shot
  `http.extraheader` for HTTPS remotes, so the token never appears in a remote
  URL, an argv-visible refspec, or any error text (secrets are redacted).
- Windows-safe: all git calls use argument lists (no shell), run with the repo as
  cwd, and surface a clear message when `git` is absent.

## `wea freshness` — stale/missing install detection

Purpose: tell an operator whether the installed `wea` matches this checkout.

- The running process computes a CLI *contract*: a monotonic epoch, the packaged
  version, and the sorted command surface. Run from the checkout
  (`python -m wea_cli.cli freshness`), that contract is the checkout contract.
- It then probes the installed `wea` console script on PATH as a subprocess
  (`wea freshness --emit-contract`), with `PYTHONPATH` stripped so the probe
  reflects the actually-installed package rather than the invoking source tree.
- Comparison outcomes:
  - **fresh** — installed contract matches the checkout;
  - **stale** — installed epoch is behind, or a command is missing, **or** the
    installed CLI is too old to answer the probe at all (a legacy executable
    cannot warn about itself retroactively; the failed probe is the signal);
  - **source_behind** — the installed CLI is ahead of the checkout;
  - **not_installed** — no `wea` on PATH (the source CLI still works via `-m`).
- On any non-fresh outcome it prints the supported refresh path,
  `python -m pip install --editable .` (identical on PowerShell and POSIX), and
  the source-preflight invocation. It never installs or writes anything.

## Why these choices

- Reusing the existing read-only ledger API keeps `report` consistent with `wea
  tide` and avoids duplicating protocol rules or touching executors.
- Native git push is the bounded, credential-safe transport the Plan asks for and
  removes the fragile full-blob REST path.
- A contract-epoch + command-surface comparison is the minimal signal that
  detects both "missing command" and "older than source", including the
  retroactive-staleness case an old executable cannot self-report.
