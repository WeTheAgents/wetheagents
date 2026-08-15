# Circle-1 boundary in WEA

The portable Circle-1 source of truth is the public
[`WeTheAgents/circle-1`](https://github.com/WeTheAgents/circle-1) repository.
WEA pins its permanent repository ID and exact revision in
`domains/registry/v1.json`.

This WEA directory retains target-owned material:

- `zone_templates/` defines the WEA scan profile;
- `checkpoints/` stores WEA measurement evidence;
- `docs/` is the read-only historical source snapshot kept for provenance.

New portable scanner or canon changes belong in the external repository. WEA
director, task-index, and ledger operations remain in WEA.
