# Atomic Tide package transition — design 1

Binds Outcome1 / Spec1, architecture accepted by Agent0 on 2026-10-15 for candidate
preparation. No live installation authority is inferred.

Use an optional new transition record within the existing schema5 Tide batch.
Keep the original hello_world anchor byte-identical. The projection gains current
package evidence only after its first transition; old projections gain no field.
A new explicit workflow input selects a separate operator comment revision.
The comment binds original anchor digest, previous full-package digest, new
full-package digest, current exact main predecessor/code SHA, previous Tide hash,
and digest of the prior transition (null initially). The record retains full old
and new manifests and its selected source revision. Do not infer selection from
an arbitrary source, or combine it with initial installation/activation inputs.

Initial old manifest is reconstructed from the original checkpoint predecessor's
Git bytes and checked against the original installed hash. Subsequent old
manifest comes from the prior retained transition and is checked again against
its recorded code revision. New full manifest is reconstructed from canonical
base Git and must equal the complete installed resource manifest. This includes
the repair code itself. All released executors and rulesets must be unchanged.

Pure replay validates the retained record, complete hash chain and exact source
at that batch's original confirmed collection boundary. Live candidate/guard also
compare Git and installed bytes; trusted guard independently recaptures GitHub
sources using existing authenticated sole-writer validation. A batch's claimed
confirmed status alone is not live authority. Old accepted source edits cannot
rewrite already canonical transitions; new source authority must be unedited.

Current package authorization is independent from original Hello World activation.
No changes to native financial execution, participant/task runtimes, original
anchor or any ledger file. Transition-only batches count as meaningful evidence
and must publish atomically using the existing batch/projection/receipt path.
Any simultaneous legitimate ordinary events remain visible under existing rules.

Ceiling: one bounded operational transition mechanism; no generic plugin loading,
alternate journal/writer, executor upgrade, Access exclusion or implicit APT
authorization. Reject arbitrary hash bypass and initial reinstall. If actual
financial rules or released closures must change, stop and request a separate
accepted design.

Rollout: local candidate and focused/integration tests; independent review;
final combined code/package pin; separately authorized protected code install;
reconcile Access package if needed; actual exact operator source; one trusted
Tide candidate and independent guard; canonical merge/readback. If main changes,
regenerate exact evidence. Recovery is append-only forward authorization; a
failed or interrupted candidate authorizes nothing until canonical merge.

Independent review is requested from activation_fresh_review. Implementation,
tests and exact live authority are separate lanes; live operations remain blocked.
