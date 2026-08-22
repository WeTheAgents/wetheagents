# Design: WEA vNext Block 9 single-laptop cutover

Decision status: `proposed for operator review; not accepted; not implemented; not live`

Current design revision: `1.0`

Date: `2026-08-18`

Implements outcome version: `1.0`, exact SHA-256
`e9cbdcc924c8e01cae3240885e272fc75a7595bae1dcab4ee4034e6d439d1f67`

Implements spec version: `1.0`, exact SHA-256
`25c65e999bb158d773fa7d46c5e566cd36f5a7eb4b8b8aff272274d8efe59dfa`

Acceptance source:
`../wea-vnext-s13c-financial-correction/WEA_vNext_BLOCK9_ACCEPTANCE.txt`.
The frozen Outcome and Spec stay unchanged.

## Revision history

| Revision | Implements spec | Status | Material decision |
| --- | --- | --- | --- |
| 1.0 | Block 9 Spec 1.0, S-71 through S-79 | proposed | Use a manual stop-the-world cutover, one laptop, one Agent0 writer, a shared local lock, signed approvals, and one Git compare-and-swap transaction. |

## Operator premises

The operator supplied these premises on 2026-08-18:

1. The project is frozen. Agents start manually.
2. Every participant is controlled from this laptop.
3. Any amount of downtime is acceptable.
4. The ledger runtime and Agent0 run only on this laptop now and for the
   foreseeable future.

These premises remove the need for a rolling migration, distributed consensus,
automatic failover, or a dual-write period. They do not weaken the accepted
money, authority, replay, tamper, or recovery rules.

Operator and Agent0 remain separate logical roles. They use separate approval
keys even though both keys live in the same controlled laptop trust domain.
This is procedural and cryptographic separation. It is not two-person custody.

## Repository context

### Current state

- v1 remains authoritative and is under an operator pause.
- Direct v1 CLI and maintenance writers still exist.
- `scripts/tide.py` writes several ledger files separately and appends history.
  A process crash can therefore leave a partial local file set.
- The CLI halt guard reads `ledger/tide.json`, but it is not a shared epoch
  guard and does not protect every direct writer.
- `label-paid.yml` uses the GitHub `ledger-writes` concurrency name. Other
  direct writers do not share one technical lock.
- `src/wea_vnext/` contains verified inactive behavior and replay code. It has
  no live adapter or canonical `ledger/vnext/` namespace.
- The accepted S13C implementation is an in-memory control plane. It is not a
  durable authenticated ledger transaction.

The current writer list in the parent decision delta is a starting inventory,
not completeness evidence. Source inspection also finds direct ledger writes
in CLI commands, Tide, pending-payment processing, gauntlet scripts,
reconciliation scripts, and write-enabled workflows.

### Platform and dependency constraints

- Python 3.10 or newer remains the implementation language.
- The transaction and validation code uses the Python standard library.
- Git is the atomic publication substrate. The canonical repository identity
  and target ref are fixed in each cutover bundle.
- Windows OpenSSH is present on the target laptop and provides detached
  Ed25519 signatures through `ssh-keygen -Y sign` and `ssh-keygen -Y verify`.
- The target is Windows 10 Home build 19045, so Windows Sandbox is unavailable.
  Shadow uses a pre-provisioned non-admin local account, restricted token,
  Job Object, NTFS isolation, and a whole-laptop offline network boundary.
- A dedicated ledger GitHub App installation is the only remote principal
  allowed to update the canonical ref. A second projection App can mutate
  Issues and labels but has no Contents permission. Both private keys remain
  on the laptop under the dedicated Agent0 Windows account.
- GitHub stores and publishes Git history. It is not a second ledger writer or
  a second runtime host.
- No server, database, queue, distributed lock, or new Python dependency is
  introduced.
- No separate narrow reference runtime is introduced. Shadow and recovery use
  the complete manifest-pinned candidate runtime.

## Design summary

The first cutover is an offline release, not a live migration:

1. Install all vNext code, guards, schemas, and tests while vNext stays off.
2. Stop every agent, writer, workflow trigger, and maintenance process.
3. Freeze one exact Git and GitHub input boundary.
4. Build the mutation, reconciliation, genesis, and shadow evidence from that
   boundary.
5. Have the operator and Agent0 sign the same canonical cutover core.
6. Let `agent0@system` publish one signed, fast-forward Git commit.
7. Treat vNext as active only when the canonical remote ref contains that
   commit.
8. Run the vNext writer manually, one cycle at a time.

The activation commit contains the epoch, genesis, first vNext transaction,
derived state, enabled adapter selection, retired-writer guards, and initial
projection intents. Git makes those repository effects visible together.

## Material decisions

### D-B9-01. Stop the world instead of coordinating live writers

- The cutover has no rolling, blue-green, or dual-write phase.
- The operator stops all manual agents before the frozen snapshot.
- Write-enabled GitHub workflows are disabled or converted to read-only before
  the snapshot.
- Local process inspection and the GitHub Actions queue must both show no
  running or pending writer.
- v1 stays closed until the attempt either fails before publication or vNext
  becomes authoritative.
- If a failed attempt reopens v1, the next attempt requires a new snapshot,
  evidence set, manifest, and both approvals.

Rejected alternative: a live rolling migration adds leases, handover states,
and concurrency failure modes without product value under the accepted
unlimited-downtime premise.

### D-B9-02. Derive the mutation universe in two independent ways

The implementation produces two immutable source artifacts.

`static-writer-universe.json` comes from repository analysis at the exact
predecessor tree. It scans all file types for:

- writes or appends under `ledger/` and protocol-state paths;
- Git commits, ref updates, pushes, and GitHub mutation calls;
- CLI mutation handlers and indirect transaction-helper callers;
- workflow triggers, permissions, schedules, concurrency groups, and secrets;
- process launchers, maintenance scripts, dynamic imports, and shell commands;
- documented manual mutation paths.

`operational-writer-universe.json` comes from a separate operator inventory. It
enumerates:

- every manually launchable Agent0 and agent command;
- Windows processes, startup entries, and Task Scheduler jobs;
- GitHub Actions jobs that can run on the self-hosted laptop;
- configured repository credentials and their allowed mutation targets;
- active worktrees, runbooks, aliases, wrappers, and emergency procedures.

The canonical union is split into three explicit inventories:

1. `protocol-writer-inventory.json` contains anything that can change ledger,
   epoch, authority, idempotency, lifecycle, or other protocol state.
2. `canonical-ref-competitor-inventory.json` contains any process or credential
   that can update, delete, or force the canonical Git ref during the freeze.
3. `projection-writer-inventory.json` contains non-Git GitHub mutations, such
   as comments and labels, that can only project already committed protocol
   state. Tracked Issue forms, workflow guards, CLI help, and root documents
   are canonical-ref files, not projections.

Each row contains:

- stable writer ID and exact source path or external source ID;
- trigger and process owner;
- credential binding;
- possible mutation targets;
- shared-lock and epoch-guard call site;
- inventory class and target/ref/path evidence;
- decision: `replace`, `disable`, or `historical-read-only` for protocol
  writers; `fenced` for canonical-ref competitors; or a named idempotent state
  machine for projection writers;
- pre-cutover shutdown proof and post-cutover rejection proof.

Every difference between the two universes needs an explicit resolved row. An
unknown, ambiguous, omitted, late-added, or dynamic mutation path blocks
cutover.
The static universe runs again against the exact predecessor immediately
before activation. A different hash invalidates the manifest and approvals.

Ordinary feature-branch pushes and non-protocol discussion comments receive an
explicit `out-of-protocol` classification. That classification must prove the
exact target ref or GitHub object and prove that repository rules prevent the
operation from changing the canonical ref or ledger paths. These operations do
not use the ledger transaction helper.

Gauntlet mint, `award`, `revoke`, `transform`, `pending.json`, `label-paid.yml`,
legacy Tide, and direct maintenance writers cannot remain active vNext paths.
Historical readers can read v1 bytes but cannot call a write helper.

### D-B9-03. Use one shared lock and one epoch guard

All v1 and vNext mutation entrypoints use one transaction helper before
activation is possible.

The helper creates an exclusive lock file below the common Git directory, not
inside one worktree. This makes the lock common to every local worktree. The
file is created with exclusive-create semantics and contains a run ID, process
ID, writer ID, target repository/ref, expected predecessor, and start time.

The lock has no automatic timeout and is never stolen. After a crash, Agent0
must inspect the recorded process and canonical ref before removing a stale
lock. Failing closed is acceptable because downtime is unlimited.

While holding the lock, the helper:

1. resolves the canonical repository and ref from immutable configuration;
2. reads the current remote ref;
3. reads and hashes both active remote rulesets and the allowed ledger GitHub
   App principal;
4. requires the exact expected predecessor and remote authority snapshot;
5. reads the epoch from that exact remote tree;
6. rejects a v1 writer when a valid vNext bootstrap exists;
7. rejects a vNext writer when the bootstrap is absent or invalid;
8. rebuilds the candidate state and checks all invariants;
9. performs an ordinary fast-forward Git push through the pinned App token;
10. reads the remote ref and authority state again and classifies the result.

A stale process cannot rely on an early guard result. It repeats the epoch and
predecessor checks immediately before publication. An old process based on the
predecessor loses the remote ref compare-and-swap after cutover.

Rejected alternatives:

- The current `ledger/tide.json` halt flag does not cover every writer.
- A lock inside one worktree does not serialize other worktrees.
- GitHub workflow concurrency does not serialize local CLI scripts.
- A time-based lease can create two writers after a pause or clock error.

### D-B9-04. Make a Git commit the authoritative transaction

The canonical target is the exact GitHub repository node ID and ref recorded in
the cutover core. For the first cutover, the intended ref is
`refs/heads/main` in the canonical WEA repository.

The writer builds a complete candidate in an isolated worktree rooted at the
approved predecessor. Temporary files live under
`.wea_runs/vnext-transaction/<run-id>/` and are not ledger records.

Each file is written through a same-directory temporary file, flushed, and
replaced. The writer then builds and verifies the complete Git tree. It creates
one Agent0-signed commit whose single parent is the approved predecessor.

The commit uses the non-circular evidence graph in D-B9-05. A final tree
manifest covers every activation path except itself. The Git tree and signed
commit bind that manifest. Validation rejects any missing, extra, changed, or
non-deterministically derived path.

The writer uses a normal fast-forward push. It never uses force, force-with-
lease, merge, or rebase for a ledger transaction. The server-side ref update is
the compare-and-swap boundary.

The local commit is not authoritative before the remote ref accepts it. If the
push response is lost, the writer reads the remote ref:

- candidate commit: the transaction succeeded;
- approved predecessor: the transaction did not occur and can retry exactly;
- any other commit: the result is ambiguous and all writers remain blocked.

This preserves GitHub as the publication surface while keeping the only
executing ledger writer on the operator laptop.

### D-B9-05. Store an append-only event chain and derived projections

The activation transaction creates this canonical namespace:

```text
ledger/vnext/
  bootstrap.json
  genesis.json
  events/0000000000000000.json
  state/
  projection-status.json
```

Evidence for one attempt is stored at:

```text
evidence/vnext/cutover/<attempt-id>/
  static-writer-universe.json
  operational-writer-universe.json
  protocol-writer-inventory.json
  canonical-ref-competitor-inventory.json
  projection-writer-inventory.json
  reconciliation.json
  github-boundary.json
  shadow-report.json
  cutover-core.json
  approvals/operator.json
  approvals/operator.sig
  approvals/agent0.json
  approvals/agent0.sig
  final-tree-manifest.json
```

`bootstrap.json` is the exact signable bootstrap payload. It contains no
signature bytes. This avoids a circular hash in which a signature must sign
itself.

`cutover-core.json` is built before approval. It contains every deterministic
transition input and expected effect, including exact bootstrap, genesis, and
sequence-zero payload hashes. It contains the required approval roles and
binding identities, but no approval envelope, signature, or final-tree hash.

The builder next creates one canonical approval JSON for each role. Each file
contains the same exact `cutover-core.json` SHA-256, role, binding, approval
time, and stable source path. Each role signs the exact bytes of its own
approval JSON under the cutover signature namespace. The approval JSON files
do not contain their own hash or signature. Thus the authenticated envelope
binds both the common core and its role-specific authority evidence without a
cycle.

After both signatures exist, the builder deterministically creates
`events/0000000000000000.json`. It combines the exact pre-approved event payload
with each approval JSON hash, signature hash, Git blob ID, and binding result.

The builder then creates `final-tree-manifest.json`. It records the path, byte
length, SHA-256, and Git blob ID of every activation file except itself. The
actual Git tree binds the final manifest. No file recursively hashes itself.

The validator proves one unique realization in this order:

1. rebuild and hash the cutover core;
2. verify each detached signature over the exact approval JSON bytes and
   require both approval JSON core hashes to equal the rebuilt core hash;
3. rebuild sequence zero from the core and exact approvals;
4. rebuild every derived state and activation file from sequence zero;
5. rebuild the final tree manifest from the actual path set;
6. require the Git-tree diff from the approved predecessor to contain only
   those exact activation files.

`events/0000000000000000.json` is the first vNext ledger transaction. It binds
the bootstrap, genesis, exact approval source revisions, epoch, expected v1
predecessor, resulting state hash, and initial projection intents.

Each later transaction receives the next fixed-width sequence number and
contains:

- predecessor transaction and Git commit hashes;
- exact input boundary and runtime triple;
- accepted event group and idempotency results;
- financial rows when money changes;
- projection intents;
- pre-state and post-state hashes;
- transaction implementation version and hash.

Bootstrap, genesis, event, approval, and evidence files use canonical UTF-8
JSON with no BOM, duplicate keys, floating values, or trailing newline. Hashes
cover exact bytes.

Event files, bootstrap, and genesis are immutable. `state/` and
`projection-status.json` are derived projections. Deleting them and replaying
genesis plus every event must recreate identical bytes.

One successful Git commit contains one authoritative ledger transaction. A
later cycle never edits an earlier event, even when it corrects its meaning.

### D-B9-06. Separate approval, commit, and Git transport authority

Before activation, an accepted implementation revision installs a versioned
authority registry in the approved predecessor. The registry contains public
keys and public GitHub principal identifiers only. It binds:

- authority kind and exact source identity;
- public-key fingerprint;
- binding ID and positive version;
- half-open effective interval;
- allowed signature namespaces;
- for Agent0, exact Agent ID `agent0@system`, canonical repository, ref, commit
  signing permission, and separate Git transport permission.

Private keys stay outside the repository. Dormant setup replaces the current
same-user worker model with three explicit Windows identities:

- the trusted operator account holds the passphrase-protected operator key;
- a dedicated standard account, `wea-vnext-agent0`, holds the Agent0 approval,
  commit-signing, ledger-App, and projection-App keys and runs only the manual
  Agent0 writer/projector;
- a separate standard account, `wea-vnext-worker`, runs agent work in feature
  worktrees and has no read access to either key directory or the Agent0 common
  Git directory.

`wea-vnext-shadow` remains a fourth, more restricted account for D-B9-09.
Untrusted agent code never runs under the operator or Agent0 access token.
Exact NTFS ACLs deny worker and shadow identities; the trusted operator can
still recover the machine and is inside the declared trust ceiling. Current
same-user dispatch must be replaced and proven before activation.

The two roles sign the exact bytes of their separate canonical approval JSON
files with OpenSSH Ed25519 signatures. Cutover uses namespace
`wea-vnext-cutover`. Correction and repair use separate namespaces.

Each approval JSON binds:

- the same exact `cutover-core.json` SHA-256;
- authority kind and source identity;
- key fingerprint and binding ID/version/hash/interval;
- approval time;
- canonical repository node ID and ref;
- stable source path. Sequence zero and the final tree manifest bind the exact
  approval JSON and signature revisions and hashes.

The verifier rebuilds an `allowed_signers` view from the pinned registry. It
verifies exact bytes, signature namespace, key fingerprint, role, binding
version, and active interval. The operator and Agent0 fingerprints must differ.
A role string supplied by the caller gives no authority.

The Agent0 approval key also signs the activation commit. This proves commit
authorship, but it does not authorize the remote ref update.

A dedicated ledger GitHub App is the sole Git transport principal. It is
installed only on the canonical repository with Metadata read and Contents
write, and with no Issues permission. Agent0 creates a short-lived installation
token locally and uses that token for one HTTP Git push. No hosted App service
is required.

Two enforced GitHub branch rulesets target the exact canonical ref:

1. the safety ruleset blocks deletion and force pushes and has no bypass actor;
2. the writer-admission ruleset restricts updates and grants `always` bypass
   only to the dedicated ledger App.

The ledger App can therefore publish an ordinary fast-forward update but
cannot bypass the separate deletion and force-push rules. No user,
administrator role, team, deploy key, workflow `GITHUB_TOKEN`, legacy PAT, or
projection App is in either relevant bypass list.

A second dedicated projection GitHub App has Metadata read and Issues write,
but no Contents, Workflows, Administration, or other write permission. Its
short-lived installation token is used only after a committed transaction to
reconcile comments and labels. The projection App cannot update the canonical
ref and is a separately versioned projection-writer binding, not a ledger
writer.

Before the frozen predecessor, implementation must:

- remove `contents: write` from legacy workflows or disable those workflows;
- remove or rotate `ADMIN_TOKEN` and every legacy credential that can update
  the canonical ref;
- prove that feature-branch credentials cannot update the canonical ref;
- record both App IDs, installation IDs, repository ID, exact permissions,
  both ruleset IDs, target patterns, enforcement states, bypass actors, and
  canonical API hashes;
- prove with the ledger App token that a normal fast-forward succeeds while
  force-push and deletion fail, and prove that the projection App token cannot
  update the canonical ref.

The cutover core binds that complete remote authority snapshot. Immediately
before push, Agent0 reads it again through the GitHub API and requires exact
equality. After push, it reads both rulesets and the ref again. If the
repository plan or permissions cannot enforce App-only ordinary updates plus
no-bypass deletion and force-push protection, activation is blocked.

The ledger-App binding, projection-App binding, commit-signing binding, and
Agent0 approval binding are four separate versioned records. Rotation of any
one invalidates an older unconsumed bundle.

The trust ceiling is explicit: separate keys prove two separate role acts, but
the same operator controls the laptop and both roles. A second human or device
is not claimed.

### D-B9-07. Keep conversion approval in the existing Agent identity boundary

An Agent approves a conversion through a new exact GitHub comment revision
published by the GitHub account in that Agent's active account binding. This
keeps the approval connected to the current GitHub-native identity model.

The frozen GitHub boundary stores the permanent account, Issue, comment, and
content-edit revision IDs, exact bytes, SHA-256, created/effective time, and
complete confirmed read evidence. A caller-generated hash or copied role label
is not approval.

Before cutover, the reconciliation process closes the v1 task and escrow. It
then creates only a non-financial immutable conversion intent. The intent
contains every field required by R-B9-02, including the complete Plan, Plan
bank, Triage revision, author-payer, authority interval, expiry, and one-shot
idempotency key.

Genesis preserves a pending intent but creates no debit, program escrow, Plan,
Task, or child Contract.

After cutover, a manual vNext cycle can activate one pending intent. One event
group atomically:

1. revalidates the exact Agent account binding and approval interval;
2. checks the intent state, expiry, and idempotency key;
3. checks the current author-payer balance;
4. debits the complete Plan bank once;
5. creates one program escrow;
6. creates the approved Plan and Task;
7. creates the first child Contract under the accepted Plan contract;
8. marks the intent consumed.

Any failure creates none of these effects. Insufficient funds appends one
terminal cancellation and does not revive after a later balance increase.
Direct Contract creation and simultaneous v1/vNext escrow are impossible.

If the frozen project has no approved conversions, genesis contains an exact
empty intent array. The mechanism remains covered because the accepted Spec
permits future conversion within this cutover.

### D-B9-08. Build reconciliation and genesis entirely offline

After the stop, one read phase captures:

- canonical Git tree and ledger files;
- all Issues, comments, edits, labels, and pull requests in the canonical
  repository;
- task index, escrow, pending payments, history, idempotency keys, aliases,
  genomes, Identity evidence, and Hello World keys;
- configured authorities, runtime manifests, rulesets, and writer evidence.

The phase writes an immutable input bundle. Later reconciliation, genesis, and
shadow runs use only that bundle. A network response cannot change one replay.

The GitHub side of the reconciliation universe contains every non-PR Issue in
the canonical repository, open or closed. One fully paginated query records its
query variables, total count, cursors, page counts, node IDs, update times, and
complete content-edit revisions. `hasNextPage` must be false on every required
connection. Pull requests are captured separately as possible deliverables.

The local side is the union of every Issue reference reachable from task
indexes, escrow, pending payments, history, idempotency keys, comments,
settlements, aliases, and documented exception records.

Every GitHub Issue receives either a proved `not-v1-obligation`
classification or a v1 obligation classification. Any task/lifecycle marker or
local reference forces the obligation path. Every local reference must resolve
back to exactly one captured Issue. A member reachable from only one side, an
unresolved inverse link, or an incomplete page blocks the attempt.

Reconciliation gives every unfinished v1 obligation exactly one outcome:
`settle-v1`, `stop/refund`, `convert-with-fresh-approval`, or
`historical-close`. It cross-links every system row to one basis and proves for
each funded obligation that deposits equal payments plus refunds.

`historical-close` requires zero money and zero remaining obligation. Any
active escrow, pending payment, unlinked row, unexplained amount, missing
outcome, or duplicate outcome blocks the attempt.

Genesis deterministically preserves:

- exact Agent IDs, balances, genome snapshots, and identity bindings;
- used and retired Hello World keys;
- immutable v1 history references and hashes;
- pending conversion intents as non-financial records;
- opening supply calculated from the same frozen balance and escrow state.

Historical gauntlet mint is audit metadata. It is never added to opening supply
again. Achievement, `award`, `revoke`, and `transform` history stays readable
but cannot alter genome, Release, eligibility, authority, or money.

Two independent genesis builds from the same input must produce the same exact
bytes. Replay of genesis alone must produce the recorded opening state hash.

### D-B9-09. Run shadow under an isolated non-admin Windows account

Shadow uses the complete manifest-pinned candidate runtime and the immutable
input bundle. It does not query mutable GitHub state during replay.

Dormant setup creates one dedicated local account, `wea-vnext-shadow`. It is a
standard user with no administrator, remote-logon, repository, GitHub,
credential-store, Task Scheduler, service-control, or network-configuration
authority. Account creation happens during accepted setup, never during a
shadow run.

The host copies the exact Windows Python runtime, candidate source, immutable
input bundle, and manifests into a new directory. NTFS ACLs grant the shadow
account read and execute only. One empty output directory is its only writable
task path. The live repository, `.git` common directory, user profiles,
credential directories, and Agent0 worktrees explicitly deny that account.

The host launches the process with a restricted token inside a Windows Job
Object. The token has no administrative privileges. The Job Object limits the
process tree and rejects unapproved child processes.

Before launch, the operator disables every non-loopback network adapter on the
laptop. A pre-run check records all adapter IDs and requires state `Down`; an
external connectivity probe must fail. The non-admin shadow account cannot
enable an adapter. Network is restored only after the process exits and the
post-run checks finish.

Inside the isolated process, the shadow adapter also rejects every ledger,
GitHub, credential, permission, Git, and protocol-state write. OS account and
ACL isolation protect the live repository if code bypasses that adapter.

Before and after each run, the host records hashes of the live ledger,
canonical Git refs, authority registries, repository status, account/ACL/Job
configuration, and adapter state. Any unexplained difference fails the run.

The report binds the input boundary, all three mutation inventories,
reconciliation, ruleset, runtime, output bytes, accepted/rejected counts,
balances, supply, lifecycle state, authority results, and retired-command
results.

The harness runs twice from fresh copied inputs and empty output directories.
The report bytes and state bytes must match exactly. Tests attempt direct file,
subprocess, socket, Git, environment, and GitHub bypasses. A mismatch, write
attempt, stale input, incomplete page, enabled adapter, available external
network, or ACL escape blocks activation.

### D-B9-10. Publish one activation commit

Implementation and rehearsal happen before the activation attempt. The
predecessor already contains dormant vNext code, shared guards, the authority
registry, tests, and the disabled-by-default adapter. The activation commit
contains no new unreviewed runtime logic.

The offline preparation sequence is:

1. disable every writer trigger and stop every local writer process;
2. verify zero running or pending local and GitHub writer jobs;
3. freeze the canonical Git ref and complete GitHub input boundary;
4. rebuild both mutation universes and all three inventories;
5. finish v1 settlement and freeze reconciliation;
6. build genesis and replay it twice;
7. run shadow twice and prove no live mutation;
8. build the exact non-circular cutover core and deterministic event payload;
9. build the operator approval JSON for the core and obtain its detached
   signature;
10. build the Agent0 approval JSON for the same core and obtain its detached
    signature;
11. derive sequence zero and every activation file from the core and approvals;
12. build the final tree manifest and stage the exact tree in an isolated
    worktree.

The cutover core binds every S-75 field, including:

- canonical repository node ID, ref, and expected predecessor;
- frozen v1 and GitHub boundaries;
- both mutation-universe hashes and all three inventory hashes;
- reconciliation and shadow hashes;
- exact genesis and bootstrap bytes/hashes;
- target epoch and expected resulting state hash;
- ruleset, Tide interface, executor, Python, and dependency identities;
- exact `agent0@system` approval, commit-signing, ledger-App transport, and
  projection-App bindings;
- exact pair of GitHub branch rulesets and canonical-ref authority snapshot;
- transaction, durable correction, and `replay_repair` versions/hashes;
- the exact deterministic activation blueprint and closed path set.

Agent0 then acquires the shared lock and repeats every freshness, authority,
remote-ruleset-pair, replay, invariant, stage-set, and remote-predecessor check. It
creates the signed commit, obtains a short-lived token for the pinned GitHub
App installation, and performs one fast-forward push.

The remote ref update makes these effects active together:

- vNext epoch and bootstrap;
- genesis and transaction sequence zero;
- derived opening state;
- v1 writer rejection;
- exact vNext adapter selection;
- initial idempotent projection intents;
- current root operational status and CLI help;
- every tracked Issue form and workflow guard required by R-B9-09.

All tracked public surfaces are therefore present in the one activation tree
or are already epoch-aware dormant files whose exact activated behavior is
bound by that tree. They never wait for a post-transaction projection.

No v1 and vNext writer are active together. Root files and adapter code read
the epoch from the committed bootstrap; a local environment flag cannot enable
vNext.

### D-B9-11. Run one manual Tide cycle at a time

After activation, the operator starts `scripts/tide_vnext.py --once` manually.
The first version has no schedule, resident daemon, or automatic worker launch.

One cycle:

1. acquires the shared lock;
2. reads and verifies the canonical remote chain;
3. reconstructs state from genesis and all events;
4. reads one complete confirmed GitHub boundary;
5. resolves the exact runtime triple for each event;
6. computes one immutable transaction and all projection intents;
7. checks replay, authority, idempotency, and financial invariants;
8. signs, commits, and fast-forward pushes one transaction through the pinned
   GitHub App;
9. confirms the remote ref and releases the ledger lock;
10. acquires the separate shared projection lock and reconciles external
    projections.

Untrusted agent code never runs in this process. Agent work stays in separate
processes and worktrees.

Projection intents are authoritative transaction data. Each intent has a
target-specific state machine: `pending`, `observed`, `applied`, `confirmed`,
or `unknown`. Until every intent is confirmed, the derived operational status
is `projection_degraded` and lists the exact pending or unknown targets.

Comment projection includes a deterministic hidden marker containing the
projection ID and desired-content hash. Before creation, the worker reads every
comment page and searches for the marker. After creation, it reads back the
exact immutable comment ID, revision, marker, and content hash.

If comment creation returns an uncertain result, the state becomes `unknown`.
Automatic retry cannot create another comment. It first performs a complete
read reconciliation. An exact existing marker becomes `observed`; multiple or
conflicting markers block for operator review. A new create is allowed only
after the operator records evidence that no prior comment exists.

Labels and other non-Git mutable targets use desired-state upsert and exact
read-back instead of create-on-retry. Tracked Issue forms are activation-tree
files under D-B9-10. The projection lock has no timeout or automatic steal, so
two projectors cannot race.

The projector obtains a short-lived token only for the exact pinned projection
App binding. It rechecks App identity, installation, repository, permissions,
and absence of Contents permission before every batch. Missing or expanded
permissions, binding rotation, or any ability to update the canonical ref
blocks projection and leaves the visible status `projection_degraded`.

A projection receipt is non-financial evidence appended by a later ledger
transaction only after exact read-back. Projection retry never replays a ledger
transition or money effect.

### D-B9-12. Use the same durable append kernel for recovery

The transaction helper is shared by normal Tide cycles, cutover, financial
correction, and `replay_repair`. There is no emergency side door.

#### Before sequence zero is published

- Temporary directories and local candidate commits are not authoritative.
- If the canonical ref still equals the predecessor, the exact commit can
  retry.
- If v1 or the GitHub boundary changed, the attempt is cancelled and rebuilt.
- No recovery action creates a vNext epoch.

#### After sequence zero is published

- Every restart reads the canonical ref, verifies hashes and signatures, and
  reconstructs state from genesis plus the full event chain.
- A missing or mismatched derived state is regenerated before new work.
- v1 never reactivates automatically.
- A structurally valid chain with wrong financial meaning receives a financial
  correction. A structurally valid chain with wrong non-financial replay
  meaning receives `replay_repair`.
- A missing Git object, hash mismatch, invalid signature, malformed event, or
  broken predecessor chain is cryptographic or structural corruption. It does
  not enter the append path. Agent0 restores the exact content-addressed bytes
  from the canonical remote or a verified clone and reruns validation.
- If exact original bytes are unavailable, all writes remain blocked. This
  Design does not invent new history or fall back to v1.

#### Durable financial correction

The durable adapter loads exact signed operator and Agent0 approval sources,
then invokes the accepted S13C 1.1 semantic validator. The new transaction
contains the proposal, approvals, complete correction group, immutable rows,
pre/post state hashes, supply result, idempotency result, and implementation
hash.

The remote Git transaction supplies crash atomicity. A retry with the same key
and payload returns the existing group. Conflicting reuse rejects.

The S13C snapshot limit of 64 groups remains. The transaction containing group
64 also emits a deterministic correction checkpoint that binds the complete
ledger head, positions, total minted, authority registry, and prior segment
hash. The next segment uses that published checkpoint as its externally pinned
opening. Full ledger replay still verifies every earlier segment.

#### Durable `replay_repair`

`replay_repair` accepts only the closed operation set already defined by the
parent Design: `executor_override`, `void_event`, `supersede_record`, and
`cursor_reset`.

It requires separate operator and Agent0 signatures over the same exact repair
payload. It binds the affected IDs, violated Spec rule, implementation hashes,
effective transaction, and pre/post state hashes.

The validator compares the complete financial projection before and after.
Any changed balance, escrow, supply, minted total, or financial row rejects the
repair and routes the request to financial correction.

Original event bytes never change. Replaying the chain applies the repair at
its recorded position and produces the recorded post-state hash.

## Protected boundaries

- **Money:** every transaction verifies `balances + active escrow = signed
  supply`; no boolean, negative, partial, or unexplained amount is accepted.
- **Authority:** exact active versioned bindings and verified source bytes are
  required. Role labels and public-field hashes have no authority.
- **Single writer:** only `agent0@system` with the pinned approval,
  commit-signing, and ledger-App transport bindings can publish a vNext ledger
  commit. Layered remote rulesets reject every other principal and reject
  deletion or force-push even from the ledger App. The projection App has no
  Contents permission.
- **Immutability:** v1 history, genesis, bootstrap, events, approvals, and
  evidence remain append-only or immutable.
- **Atomicity:** the canonical remote ref either contains the complete signed
  transaction commit or its predecessor.
- **Replay:** derived state is disposable and must reproduce exact bytes.
- **Shadow isolation:** the complete Windows runtime executes under a
  restricted non-admin account with read-only inputs, no live-repository ACL,
  a bounded Job Object, and all non-loopback network adapters down.
- **Secrets:** no private key, PAT, environment file, or decrypted credential
  enters Git, logs, evidence, or projection output. Worker and shadow Windows
  identities cannot read operator or Agent0 key directories.
- **Staging:** uncommitted or unpushed files never count as ledger state.
- **Retirement:** gauntlet mint and achievement writes have no vNext adapter.
- **Failure:** uncertainty blocks the writer. It never guesses whether a push,
  approval, or financial transition succeeded.
- **Projection:** uncertain create responses cannot trigger another create
  until exact remote reconciliation resolves the prior attempt.
- **Trust:** this Design trusts the operator-controlled Windows laptop and its
  OS account. It does not claim resistance to laptop or key compromise.

## Ceiling and observable revisit trigger

### Ceiling

- one controlled Windows laptop;
- one manually started Agent0 writer process;
- one canonical Git repository and branch;
- all agents and participants controlled by the operator;
- unlimited acceptable downtime;
- no untrusted Python in the writer process;
- no automatic schedule or failover;
- standard-library runtime plus Git and Windows OpenSSH;
- separate pre-provisioned non-admin Windows accounts for Agent0, workers, and
  shadow, with verified NTFS/token/Job isolation appropriate to each role;
- one dedicated ledger GitHub App, one no-Contents projection GitHub App, and
  layered no-bypass safety plus App-only writer-admission rulesets;
- full replay without general ledger checkpoints.

The accepted parent performance trigger remains: return to Design at 50,000
vNext events or when full replay exceeds five seconds on the Agent0 laptop.
S13C correction segments use their accepted 64-group checkpoint boundary.

### Revisit when

Return to Outcome, Spec, and Design before any of these changes:

- an uncontrolled or external participant joins;
- an agent or writer runs on another machine;
- an automated schedule or always-on service is required;
- two writers, high availability, or bounded downtime is required;
- the canonical ledger moves away from the pinned Git ref;
- GitHub can no longer enforce the pinned layered canonical-ref rulesets;
- the target cannot provide the accepted account, ACL, Job Object, or offline
  network isolation;
- untrusted code must run inside the writer;
- private keys need independent human or hardware custody;
- replay crosses the event-count or time trigger;
- a new active gauntlet, achievement, or ikigai mechanism is proposed.

## Migration and recovery

### Migration and rollout

Use three separately accepted deliveries:

1. **Dormant implementation:** add guards, storage, schemas, signing,
   reconciliation, genesis, shadow, recovery, adapter, and tests. Keep the
   adapter disabled and create no `ledger/vnext/` namespace.
2. **Rehearsal and exact bundle:** run crash tests and a complete read-only
   rehearsal. Build the final bundle from a newly frozen boundary.
3. **Activation:** after separate operator and Agent0 signatures, publish the
   single activation commit.

Design acceptance authorizes only the next Tasks revision. It does not
authorize any of these three deliveries by itself.

### Replay and idempotence

- Every event, transaction, intent, approval, projection, correction, and
  repair has one deterministic ID and request hash.
- Exact retry returns the already published result.
- Same ID or key with different bytes fails closed.
- Git predecessor, transaction predecessor, and state predecessor all form one
  continuous chain.
- Full reconstruction validates exact types, fields, hashes, ordering,
  authority intervals, and financial invariants.

### Chosen recovery mechanism

- Before the canonical sequence-zero commit: discard or retry the candidate.
- After it: reconstruct and move forward with an append-only correction or
  `replay_repair`.
- Never rewrite history or automatically return to v1.

### Recovery-mode selection evidence

The canonical remote ref is the decisive evidence:

- it does not contain sequence zero: pre-cutover recovery;
- it contains a valid sequence zero: vNext reconstruction and forward repair;
- it contains an unknown or invalid state: stop and investigate without write.

### Partial-failure and data-preservation rule

Local staging debris is quarantined by run ID. It is not deleted until the
remote outcome is known. Every accepted Git object, v1 byte, approval, event,
and projection intent remains available for audit.

## Verification hooks

| Contract | Planned proving surface | Required proof |
| --- | --- | --- |
| S-71 | `tests/vnext/test_block9_writer_gate.py` | Independent universes, three complete inventories, out-of-protocol target proof, unknown/late writer rejection, shared guard, layered rulesets, ledger-App fast-forward, App force/delete rejection, projection-App ref rejection, stale process, wrong credential, and remote CAS loss. |
| S-72 | `tests/vnext/test_block9_reconciliation.py` | Four outcomes, complete money equality, signed conversion intent, refund-before-activation, full Plan activation, expiry, rotation, insufficient-funds cancellation, and no dual escrow. |
| S-73 | `tests/vnext/test_block9_genesis.py` | Canonical bytes, exact identities and balances, opening supply, pending intents only, historical mint handling, stale input rejection, and rebuild equality. |
| S-74 | `tests/vnext/test_block9_shadow.py` | Two identical full-runtime restricted-account runs, all adapters down, absent credentials, read-only inputs, denied live paths, Job Object limits, adapter and direct bypass attempts, before/after live hashes, complete input, and deterministic report. |
| S-75 | `tests/vnext/test_block9_cutover.py` | Non-circular core/signed-envelope/tree graph, two distinct OpenSSH signatures, separate Agent0 ledger-App transport binding, exact layered remote rulesets, tracked public surfaces in the activation tree, unique deterministic tree, single-parent commit, crash points, lost push response, epoch switch, and no dual writer. |
| S-76, S-77 | `tests/vnext/test_block9_legacy_retirement.py` | Historical readability, no double mint, no achievement effect, and hard rejection of retired writes. |
| S-78 | `tests/vnext/test_block9_recovery_prerequisites.py` and `tests/vnext/test_block9_recovery.py` | Durable S13C semantics, segment checkpoint, repair money exclusion, fsync/commit/push crash matrix, restart replay, tamper rejection, and no v1 fallback. |
| S-79 | `tests/vnext/test_block9_public_contract.py` | Tracked Issue-form/workflow activation, pinned no-Contents projection App, pending/unknown projection status, hidden-marker comment reconciliation, lost response, exact read-back, projection locking, desired-state upsert, eventual convergence, and no repeated ledger or money transition. |

Repository integration also requires:

- a disposable local bare Git remote for deterministic commit and crash tests;
- temporary OpenSSH keys for signature and rotation tests;
- a disposable GitHub repository that proves the exact layered rulesets,
  ledger-App fast-forward, ledger-App force/delete rejection, projection-App
  ref rejection, legacy-token rejection, and remote-state reread;
- a restricted-account run that proves ACL, process, network, and
  host-credential isolation;
- a clean-checkout static writer scan over every tracked file type;
- a no-network replay from the frozen GitHub input bundle;
- existing full vNext, invariant, schema, idempotency, history, document-sync,
  Ruff, Pyright, and compile gates;
- one complete no-write rehearsal against the frozen project before the final
  activation bundle exists.

These are hooks for later Tasks and Verify. This Design does not claim that the
tests or implementation already exist.

## Requirement-to-decision trace

| Requirement | Governing decisions |
| --- | --- |
| R-B9-01 / S-71 | D-B9-02, D-B9-03, D-B9-04 |
| R-B9-02 / S-72 | D-B9-06, D-B9-07, D-B9-08 |
| R-B9-03 / S-73 | D-B9-05, D-B9-08 |
| R-B9-04 / S-74 | D-B9-08, D-B9-09 |
| R-B9-05 / S-75 | D-B9-03, D-B9-04, D-B9-05, D-B9-06, D-B9-10 |
| R-B9-06 / S-76 | D-B9-02, D-B9-08, D-B9-10 |
| R-B9-07 / S-77 | D-B9-02, D-B9-08, D-B9-10 |
| R-B9-08 / S-78 | D-B9-04, D-B9-05, D-B9-06, D-B9-12 |
| R-B9-09 / S-79 | D-B9-05, D-B9-10, D-B9-11 |

## Downstream state

- **Tasks:** current Block 9 Tasks point to this missing Design. After exact
  Design acceptance, create a new Tasks revision bound to Design 1.0. Do not
  edit implementation groups during this Design gate.
- **Implementation/tests:** absent and blocked. Existing vNext code remains
  inactive. No writer, ledger namespace, credential, or workflow changed.
- **Verification/readiness:** not ready. S-71 through S-79 remain
  accepted-future until implementation and fresh verification prove them.
- **Activation:** separately blocked after implementation. It requires a final
  frozen bundle and two exact signatures under D-B9-10.

## Unknowns and blockers

There is no unresolved technical choice that blocks review of Design 1.0.

The following operator acts are intentionally deferred:

1. Accept or reject this exact Design revision.
2. During the later dormant implementation stage, confirm the operator and
   Agent0 public-key fingerprints. No private key enters the repository.
3. Create and install the separate ledger and projection GitHub Apps, approve
   their minimal non-overlapping permissions, and approve the two layered
   canonical-ref rulesets.
4. Approve creation of the separate non-admin Agent0, worker, and shadow
   accounts and their required NTFS/token/Job isolation during dormant setup.
5. Before activation, keep the project frozen and provide the operator
   signature for the exact final cutover core.
6. Start the manual Agent0 activation only after the independent rehearsal and
   verification report is clean.

Next authorized action: operator review of this Design. Implementation remains
blocked until exact acceptance.
