# Exact protected installation remains separate

This candidate is not installed or activated. Do not post a test/template source
or dispatch live Tide from this document alone. Its source SHA is deliberately
not prefilled: parallel reviewed changes alter the final full-package identity.

The operator transition source and workflow input below are a new extension
implemented by this candidate. They are not available through the old initial
installation protocol. Existing protected code deployment, Access package update
when applicable, and guarded/manual canonical merge remain their own procedures.

After independent review and separately authorized protected code installation:

1. Read actual canonical main and replay its ledger. Keep the original active
   Hello World anchor. Validate the applicable Access package separately; changes
   within its manifest require its existing exact operator package update too.
2. With the final merged code, compute `package_transition.git_manifest(root, base)`
   and require equality to `hello_world.package_files()`. Never normalize a
   mismatched installed package or substitute a known expected hash in the guard.
   Read the previous hash with `package_transition.current_hash(engine)` and the
   previous transition from `engine.hello_world_package`. For the first transition,
   verify the old Git manifest at the original checkpoint predecessor against the
   original installation hash. Later transitions bind the prior canonical record.
3. Obtain a separate actual unedited numeric-operator comment on permanent Issue1.
   Its first line is `<!-- wea:hello-world-package-transition -->` followed by a
   JSON object with exactly these fields:

   - `schema`: `wea-hello-world-package-transition-1`
   - `anchor_sha256`: canonical digest of the unchanged original anchor
   - `previous_package_sha256`: current canonical operational-package hash
   - `package_sha256`: digest of the full new manifest
   - `previous_transition_sha256`: digest of the prior canonical transition, or null
   - `previous_tide_hash`: current engine.last_hash
   - `predecessor` and `code_sha`: the same actual full current-main commit SHA

   The source must be later than the previous canonical cutoff. Issue1 must retain
   its original accepted open body. Record actual body hash, numeric comment ID
   and GitHub created revision; placeholders and test sources are never authority.
4. Dispatch ordinary **Tide** on that exact main with only the new
   `hello_world_package_revision` input set to the actual created revision.
   Leave initial Tide activation and Hello World installation inputs empty.
   If main advanced, regenerate exact evidence; do not reuse stale authorization.
5. Independently validate the resulting candidate through the existing trusted
   guard, including live recapture. Inspect all ordinary event effects as well as
   the zero-effect package transition. Canonically merge only through the existing
   authorized guarded/manual process, then read back the same original anchor,
   new package chain, original history, balances and idempotency.

Until the canonical merge, the new source or workflow input alone changes no
authority. A same-source retry after acceptance creates no second transition.
A different future package requires another exact separately approved source.
Recovery is a forward transition; never edit old anchor, batches or consumed keys.
