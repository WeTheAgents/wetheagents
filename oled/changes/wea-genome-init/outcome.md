# Outcome: safe genome genesis

Version 1.0. Accepted by the operator on 2026-09-14.

New identities admitted by Tide need a persistent genome before their first
session. One command should create the missing generation-zero files for one
agent or an Agent0-managed cohort without creating a ledger transaction or a
PR per identity.

Success means an admitted new identity can initialize itself, Agent0 can
initialize several admitted new identities together, and `init` can never
replace, reconstruct, or reset an existing or historical genome.

This change does not alter Tide admission, balances, task authority, genome
mutation, or release semantics.
