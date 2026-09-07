# Tasks: source-to-settlement integration

Status: investigation complete for the first source boundary; implementation not started.
Bindings: accepted Outcome 1.1 and Spec 1.0; Design remains in progress in this directory.

- [x] Trace the current public facade, intake, lifecycle, settlement, and GitHub guard.
- [x] Run current activation, approval, Flat PoD, authority, pause, and progression tests.
- [x] Reproduce raw declaration versus normalized source mismatch without ledger writes.
- [x] Record operator choice: pilot Issues remain in the canonical root.
- [x] Obtain the operator decision on the source-boundary and task-derived payment clarification.
- [x] Record both accepted pilot ownership arrangements and common operator control.
- [x] Select existing funded identities and prepare manual role prompts and inspection checkpoints.
- [ ] Capture authenticated account IDs and construct the exact versioned pilot identity registry from accepted evidence.
- [ ] Complete source schema, declaration mapping, runtime compatibility, and identity-history design.
- [ ] Implement a raw-source-to-executor slice with faithful evidence and disk replay.
- [ ] Integrate task-derived financial deltas with the existing candidate builder and guard.
- [ ] Prove invalid sources, invalid author decisions, incomplete reads, stale candidates, and cross-Plan money isolation.
- [ ] Prove retry and crash/restart with exact task and financial replay.
- [ ] Run independent review and the affected BDD regression suite.
- [ ] Publish code separately from activation and rebuild activation inputs from merged main.

The remaining source schema and identity-bootstrap design blocks runtime commitment, not independent source-normalization work once its design is complete.
The original operator-metadata fix and Agent0 instruction remain separate completed local work.
