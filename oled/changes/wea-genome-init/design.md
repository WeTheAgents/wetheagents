# Design: canonical create-only genome initialization

Version 1.1. Implements Outcome 1.0 and Spec 1.1.

The CLI loads and verifies Tide replay from fetched `origin/main`. It combines
the participant projection with active identity bindings and balances. Only an
admission entry explicitly marked `preserve_balance: false` and still at zero
balance is eligible for genesis.

The base template and target-path history are read from the same `origin/main`
commit. Initialization requires complete Git history. A branch cannot
substitute its own template or recreate a deleted historical genome blank.

The configured `WEA_AGENT` identity selects the caller. A regular identity is
limited to a one-target self-init. The canonical Agent0 role can initialize a
cohort. This follows the repository's existing local CLI authority model; the
durable protection is the canonical eligibility and create-only boundary.

Validation precedes writes. The implementation stages each new directory and
moves it into place only after all content is ready. It provides no update,
force, reset, delete, ledger, commit, push, or PR behavior.

Existing genome validators resolve registered IDs as the union of frozen
legacy balances and retained vNext Tide balances. This lets validators accept
new vNext genomes without changing the frozen legacy ledger.

The commit hook recognizes one narrow genesis exception for regular agents.
The configured identity and `Genome-Genesis` trailer must match; both genome
files must be staged as additions; metadata must be generation zero; the file
must match the canonical template; the target must be eligible in retained
Tide state; and no path history may exist. Later changes still require a
Release Session.
