# Task #980 — Logic model (code-free)

Make `wea report` and `wea push` reliable for vNext agents, and make CLI
source/install drift visible. This is the behaviour model; it names no code.

## 1. `wea report` — canonical vNext state for the invoking agent

Inputs: a canonical Git ref (default `origin/main`), the invoking agent id
(env/config/`--agent`), an optional issue filter, an output mode (human/JSON).

Flow:

1. **Resolve the ref to a commit.** Verify the ref names a real commit. If it
   cannot be verified (usually an un-fetched `origin/main`), stop with an
   actionable error that says to fetch first. Never fall back to the working
   tree.
2. **Detect activation.** If the canonical Tide bootstrap is absent at that
   commit, report "not initialized" and stop cleanly.
3. **Replay read-only.** Load canonical state through the same read-only replay
   engine that backs `wea tide`. If replay fails, stop with an actionable error;
   do not treat local state as canonical.
4. **Project the agent view.** From canonical state, surface: latest Tide
   sequence and cutoff, opening supply and active escrow, the invoking agent's
   available balance, and per funded task the stage (open / review /
   settlement), escrow (deposited / paid / refunded / available), and the
   agent's next action derived from the runtime (never invented).
5. **Separate legacy.** Summarise retained legacy ledger balances in one clearly
   labelled section marked historical, not vNext authority.
6. **Emit.** Stable JSON for automation, or a concise human rendering.

Invariants: read-only; canonical ref is the only source of truth; legacy is
always labelled; failures are actionable, never silent stale data.

## 2. `wea push` — bounded, authenticated branch publication

Inputs: a branch (default: current), a configured remote (default `origin`), a
token from `GITHUB_TOKEN`, an explicit `--allow-main` opt-in.

Flow:

1. **Resolve branch + head SHA.** A detached HEAD with no explicit branch is
   rejected.
2. **Guard the target.** Reject publishing `main` without the explicit opt-in.
   When pushing the checked-out branch, reject an uncommitted (dirty) tree so
   the published commit is unambiguous.
3. **Resolve the remote.** Fail fast if the remote is not configured.
4. **Compare to the remote head.** If the remote branch equals the local head,
   report up-to-date (idempotent). If the remote head exists locally and is not
   an ancestor of the local head, reject the non-fast-forward.
5. **Publish the delta.** `git push` over the authenticated transport sends only
   the missing objects for this branch — no per-tree full-blob REST upload.
   Commit identities and SHAs are preserved by the transport. No force; the
   server independently rejects any non-fast-forward.
6. **Verify + report.** Re-read the remote head and confirm it equals the local
   head; return the exact remote branch and SHA.

Credential rule: the token is injected through the Git environment
(`http.<host>.extraheader` via `GIT_CONFIG_*`), never on the command line, in a
remote URL, or in output; surfaced errors are redacted. Windows-safe subprocess
handling; `GIT_TERMINAL_PROMPT=0` fails fast instead of prompting.

Rejections (each actionable): detached HEAD, dirty tree, non-fast-forward,
`main` without opt-in, unconfigured remote, transport failure.

## 3. CLI freshness — make source/install drift visible

The checked-out repository is the contract. Three surfaces are compared:

- **running** — the CLI executing the command (source or installed package),
- **checkout** — the contract read statically from `<root>/src/wea_cli`,
- **installed** — the `wea` on `PATH`, probed as a subprocess.

Because an older executable cannot warn about itself retroactively, freshness is
a **source-side preflight**: run the checkout's CLI, and it detects a stale
installed `wea` (missing commands such as `tide`, or a lower contract stamp).
Each surface is compared to the checkout by contract version and command set;
any behind/missing surface is drift. On drift the command exits non-zero and
prints the supported refresh path (`python -m pip install --editable .`). A
`--version` banner carries the machine-comparable `cli-contract N` stamp.

## Boundaries preserved

- vNext state is read only through the allow-listed read-only projection; no new
  vNext reference surface is introduced and no ledger is written.
- BDD, executors, rulesets/manifests, Tide settlement semantics, balances, task
  state, identity/authority bindings, and historical evidence are unchanged.
- Documentation is updated to match the already-accepted vNext behaviour.
