# Proposed design: task evidence through the existing writer

Status: design in progress; source-boundary delta accepted.
Bindings: local accepted Outcome 1.0 and Spec 1.0; parent Block 9 Design 1.3.

## Chosen direction

Reuse the existing GitHub Actions candidate and trusted data-only guard.
Read pilot sources from the canonical root with the existing GitHub-hosted execution plane.
Keep raw authenticated GitHub snapshots separate from normalized executor input.
Derive internal identifiers and event fields from evidence and prior task state.
Rebuild through verified executor calls; never deserialize a caller's supposedly verified in-memory object.

The journal records sufficient inputs to replay intake, identity authority, lifecycle, and settlement.
Task projections are derived data. Adding a separate task-state file is not assumed necessary.
The writer derives financial deltas from the executor result against current global balances and escrow.
The guard repeats the derivation using trusted base code and candidate data.
It also checks that unrelated Plans cannot spend the same funds or alter each other's state.

## Runtime compatibility

Preserve every released executor directory and manifest.
If separating source evidence changes the executor boundary, release a new executor closure and pin its exact runtime triple.
Do not relabel a normalized body as the original GitHub body to keep 0.8.0 tests green.
Map raw declarations to existing authority decisions. Do not introduce a new approval role through normalization.

The source-boundary change requires a new executor closure.
In 0.8.0, `LifecycleEvent.__post_init__` requires `source_snapshot` to contain the normalized event JSON.
Then `_apply_lifecycle_event_core` requires the accepted GitHub body to equal that same snapshot.
Both checks must remain unchanged for historical 0.8.0 replay.
An external wrapper that substitutes synthetic GitHub bodies would bypass the accepted raw-source boundary.
The new closure must distinguish the raw source reference from the canonical derived-event snapshot.
Its exact version and manifest follow the repository release procedure; no new runtime is registered by this design record.

### Retained source and derivation records

Reuse the existing accepted GitHub event representation for exact source bytes and source metadata.
Reference sources by repository, object kind, object ID, and revision ID, with the exact content hash.
Do not introduce a second source format that loses the accepted event's ordering or payload evidence.
The source collection also retains its read-boundary evidence; a body hash alone proves neither authenticity nor completeness.

The task journal binds each derived operation to its source references, pinned runtime triple, and predecessor task state.
Computed actor authority, internal IDs, stage, eligibility, and settlement remain outputs of replay.
A stored derived event is a comparison value, not an independently authorized instruction.
The writer and guard reconstruct the event from retained raw sources and the same predecessor.
Neither path accepts a serialized verification marker as proof.

This model applies to intake sources as well as Work declarations.
Draft body, Triage assignment and completion, assessment, Plan proposal, and author decision remain distinct source roles.
The new runtime must retain their existing exact-source and canonical-order checks.
System events require their own evidenced provenance; they must not inherit the comment-source assumption.

The proving hooks are raw-source activation and Work acceptance, altered derived-event rejection,
and replay from journal files in a fresh process with no retained in-memory state.
These hooks remain unimplemented; the existing 31 passing executor tests do not prove them.

## Recovery and source collection

Retain accepted raw evidence and replay versions in canonical history.
After merge, replay uses retained evidence rather than mutable live comments.
Before merge, the trusted capture must establish complete, current source evidence.
Define stable creation/edit revision IDs, pagination completeness, and ordering before implementing the collector.
Use the accepted new-comment fallback when stable edit identity is unavailable.
Do not create fictional deadline or body-restoration comments to satisfy the executor.
Define their source provenance explicitly when mapping existing Tide events.

## Rejected shortcuts

- Raw balanced postings do not prove task authorization or acceptance.
- Posting internal lifecycle JSON exposes protocol-derived fields and does not implement the public declaration contract.
- A local daemon or second writer duplicates an already accepted GitHub authority path.
- Rebuilding money rules in an adapter duplicates the executor.
- Saving Python objects with private verification markers bypasses replay checks.

## Remaining design work

Specify the input record schema and each supported declaration mapping before coding.
Bind immutable source capture, identity history, task ordering, and global financial reconciliation.
Scope implementation evidence by supported BDD paths; unsupported paths must not appear live.
Verify the source-boundary change with an independent review before publication.

### Runtime identity bootstrap

The package retains v1 usernames and operator labels, not a complete task-runtime registry with binding intervals and control groups.
Initialize that registry only from explicitly approved identity evidence.
Keep conversion approval bindings separate from runtime identity bindings.
An empty conversion list is not proof that agent authority is missing from every historical source.
Historical v1 balances are money evidence, not automatic permission to act under an Agent ID.
The pilot payer, Triage reviewer, participant identities, and Agent0 role need exact account bindings.
Common-control Work still requires the accepted disclosure evidence before selection or settlement.
