# Exact operational-package continuation

Spec version 1; Outcome version 1. Accepted for candidate preparation on
2026-10-15 through the delegated operator instruction and Agent0 architecture
checkpoint. This does not activate the extension on the live system.
The Hello World42 specification remains unchanged except the explicitly
authorized operational-package continuation below.

- PT-01: An active contract MAY continue under another complete operational
  package only with a separately authenticated, unedited operator comment on
  permanent Issue1 binding original anchor, exact current canonical code/predecessor,
  previous Tide hash, prior transition, and old/new complete package identities.
  Missing, foreign, edited, late, stale, reordered, duplicate, ambiguous or
  unauthenticated evidence MUST fail without a candidate.
- PT-02: The original installation, activation, anchor, opening identities and
  native executor/ruleset bytes MUST remain unchanged. Prior ledger projections
  MUST replay identically. Initial activation and package transition MUST NOT be
  combined. A transition requires an already canonically active contract.
- PT-03: The entire installed package MUST equal the authorized manifest and
  exact canonical Git bytes; arbitrary changes, exclusions, renamed/missing/new
  files and candidate-supplied code MUST NOT bypass verification. The independent
  trusted guard MUST recapture source authority and reconstruct the same result.
- PT-04: Accepted transitions MUST form an append-only chain in atomic Tide
  batches; subsequent ordinary batches reuse the authorized package without new
  approval. Replays/retries cannot duplicate a transition or financial effect.
  No-op transitions and stale predecessors MUST fail. Forward recovery needs
  a new exact authorization; rollback does not erase prior authorization.
- PT-05: The transition MUST create no balance/supply/escrow/Work/permission
  effects. Existing independently eligible events retain their original rules;
  historical mint keys and rejected Work cannot become eligible through update.

## Observable scenarios

| Scenario | Given / when / then | Proof |
|---|---|---|
| Exact continuation | Active original anchor; exact new operator source and full manifests; transition is retained, original anchor and balances unchanged | package transition integration test |
| Authority negatives | Source with wrong actor/author/repository/Issue/type, edited revision/history, bad body hash, duplicate fields, missing/ambiguous source, wrong time or wrong binding; no transition | parametrized authority tests |
| Chain negatives | Wrong previous package/Tide/transition/code/anchor, same package, replayed source, transition before activation or mixed initial flag; reject | chain and CLI tests |
| Byte boundary | Authorized source but changed installed or Git bytes, omitted/added file or modified released executor/ruleset; reject | manifest and candidate/guard tests |
| History/retry | Retained old prefix and accepted transition replay; prefix unchanged, exact next package persists; repeated transition rejected and mint unchanged | replay/financial regression |
| Trusted recapture | Candidate claims confirmed source but authenticated recapture differs; guard rejects | trusted guard regression/integration |
| Financial continuation | Transition only has no monetary delta; ordinary new eligible greeting uses existing42 rule once and alias/retry does not remint | financial integration |

Tests are planned evidence until verification.md records actual outcomes.
