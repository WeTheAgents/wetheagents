# Design

Use the existing read-only Tide ledger loader and lifecycle next_action.
Render selected projection fields without copying large Plan snapshots.
Use native Git subprocess argument arrays, a fixed push-origin remote, one exact
refspec, no force, no tag following and a bounded timeout. Keep raw diagnostics
private because Git/helper/server output can contain credentials.
Compare normalized source fingerprints, probing PATH installation without source
PYTHONPATH or checkout working-directory contamination. Use editable refresh.

The code-free flow and authority boundaries are retained in logic.md.
