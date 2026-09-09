# Design

Use a small manifest-verified participant executor 0.10.0 with its own 0.10 ruleset. It consumes plain retained source and registry data and produces deterministic admission records. Existing task execution stays pinned to 0.9.0; no published closure is edited. Reuse the existing engine loader, source collector, journal, receipt, guard, and hourly workflow.

Schema 2 batches carry `participant_runtime`; schema 1 keeps its old behavior. Approved admissions are projected under `participants`, keyed by request revision, with exact consent/approval revisions and hashes, deterministic binding IDs, and admission batch ID. The projection describes approved admissions, not an invented pre-merge activation timestamp.

Participant consent and approval revisions first retained in schema 1 are ineligible. A fresh schema 2 source is required; replay cannot promote an older unsupported declaration into admission.

Reuse authenticated `funding_merges`: despite its historical name, it already verifies the canonical introducing PR for every journal batch. At each schema 2 replay, construct an ephemeral registry from bootstrap plus admissions whose merge is evidenced. New bindings start at the authenticated merge timestamp. The next task batch can use those bindings; an otherwise empty Tide does not publish an activation-only PR. Persisted Work snapshots are never rewritten.

Owner comments require exact numeric author identity. Agent0 approval must resolve its existing system-role binding at source time and pin the request revision/hash in the same Issue. Approval attests preserved identity ownership; ordinary owner consent alone cannot claim an unbound legacy balance. Requests reserve identities atomically. Existing account base and common control cannot be changed through this API.

Rejected sources use existing unresolved dispositions. Accepted duplicates do not mint, bind, or pay twice. Invalid candidate registry construction must fail before any partial record or balance mutation. New runtime discovery does not change defaults for existing task executors.
