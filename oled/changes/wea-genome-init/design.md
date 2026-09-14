# Design: canonical create-only genome initialization

Version 1.0. Implements Outcome 1.0 and Spec 1.0.

The CLI loads and verifies Tide replay from fetched `origin/main`. It combines
the participant projection with active identity bindings and balances. Only an
admission entry explicitly marked `preserve_balance: false` and still at zero
balance is eligible for genesis.

The base template and canonical target-path existence are read from the same
`origin/main` commit. A branch cannot substitute its own template or delete a
canonical genome and use `init` to recreate it blank.

The configured `WEA_AGENT` identity selects the caller. A regular identity is
limited to a one-target self-init. The canonical Agent0 role can initialize a
cohort. This follows the repository's existing local CLI authority model; the
durable protection is the canonical eligibility and create-only boundary.

Validation precedes writes. The implementation stages each new directory and
moves it into place only after all content is ready. It provides no update,
force, reset, delete, ledger, commit, push, or PR behavior.
