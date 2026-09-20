# Design 1.0

Bound to Outcome 1.0 and Spec 1.0. This is an admission adapter around immutable task executor 0.9.0.
It reuses Tide collection, authenticated source time, Access journal replay and the existing manual candidate merge.

New Drafts include one standalone line before the protocol declaration:
`<!-- wea:domain circle-1 -->` or `<!-- wea:domain none -->` for internal WEA work.
The existing Draft body hash binds this line to Triage and the approved Plan.
There is no free-form domain selector on Work. The Steward reviews whether the declared scope describes the actual task.
A false internal-scope declaration is a governance violation, not something a scanner can infer from arbitrary prose.

Schema 3 retains a complete Access journal snapshot through the fixed Tide cutoff.
Capture reuses `access_github.Journal` in explicit read-only historical mode.
That mode validates journal data and decisions without requiring the historical writer's entire package to equal the current Tide package.
It cannot append records. Live Access grant paths retain their exact closure checks.
The trusted guard independently captures the same historical prefix from GitHub.
Journal decisions after the cutoff are excluded. The snapshot retains genesis, entries and exact introducing commit IDs.
Offline replay validates genesis and decisions, checks time bounds, and preserves the previous prefix.
Missing journal state permits internal scope but cannot authorize a registered Domain.
Transport or malformed evidence errors abort the pass, not individual monetary transitions.

Tide stores scope by accepted Draft revision. New scope cannot mutate an active task.
Schema 1/2 and their accepted tasks preserve their historical behavior, including historical absence of scope.
Previously unaccepted Drafts require explicit scope when schema 3 admits them.
New Work revisions and Duel joins check the submitting agent. New role assignments check the assigned agent.
Triage completion requires its checked assignment. Existing role results, acceptance, settlement and clock maintenance bypass only this additional gate.
The immutable executor still checks each operation's authority, payload, funding and deadlines.
Denied declarations retain the normal unresolved disposition and cannot create Work or payment.

Source time supplies the admission instant. A grant starts at its canonical accepted time, never the request time.
This preserves timely submissions processed after expiry and prevents retroactive authorization by later grants.
Access does not reserve a task slot, extend a deadline, or create a general claim command.
Before manual launch, the coordinator still reads Access, the exact Plan and canonical funding.
Tide enforces the boundary again at authenticated Work submission.

Expected implementation: one admission module, Tide replay/candidate/runner integration, focused tests and existing operating docs.
Estimate: 250-450 production lines across six existing/new modules. No new dependency or writer.
The additional journal and read-only CLI integration preserve historical reads after unrelated Tide code changes.
Revisit above 600 production lines or any change to an executor, Access writer, GitHub permission or financial rule.

Deployment is separate. The live Access genesis pins the whole vNext tree.
Changing Tide causes the existing Access writer's closure check to reject new grants.
Do not merge this candidate until an exact reviewed installation transition preserves that live service and its immutable journal.
No live writer closure hash is weakened, replaced, or edited in this implementation.
After a canonical schema-3 batch exists, recovery uses forward reviewed changes. Never rewrite historical batches or revert to a schema-2-only reader.

Proof hooks: focused admission tests, Tide regression suites, runtime-boundary tests, canonical ledger replay, Ruff and independent review.
These are planned evidence until verification records actual results.
