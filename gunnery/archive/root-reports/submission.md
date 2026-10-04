## Task
Closes #386

## Deliverable
Implemented 8 adversarial test cases for `scripts/check_incident_correlator.py` in `tests/test_incident_correlator_redteam.py`. 

### Attack Surface Summary
- **Tested Vectors:** 
  1. All checks failing simultaneously (catastrophic failure).
  2. Leaf checks failing while upstream parent passes.
  3. Commands returning OS error statuses (STATUS_ERROR) vs standard script failures.
  4. Unimplemented check skipping (`STATUS_SKIP`).
  5. Extraneous/Unknown injected check results.
  6. Empty results.
  7. Disconnected component failure.
  8. Simulated circular dependency loop graph traversing.
- **Findings (Gaps Fixed):** 
  - *Catastrophic Misattribution:* When ALL checks failed, the previous BFS logic incorrectly attributed the root cause to the leaves (e.g. `idem_consistency`), failing to recognize `invariant` as the true root cause for catastrophic failure. I implemented a fix in `check_incident_correlator.py` to identify `len(known_failed) == len(_CHECK_REGISTRY)` and explicitly assign `invariant` as the root cause.
- **Already Handled Vectors:**
  - ERROR and SKIP statuses were already correctly accounted for by the `correlate_failures` filtering logic.
  - Unknown check name results were safely handled because `DEPENDENCY_GRAPH.get()` gracefully returned `[]`, meaning unknown checks were treated as independent root causes instead of crashing.
  - Leaf failing with parent passing natively resolved correctly as an independent root cause without needing an explicit patch.
  - Circular dependency graphs were naturally resilient in topological sorts without crashing due to the seen cache in the BFS implementation.

## Self-Roast
**Logic:**
The adversarial approach methodically probes edge cases in the BFS graph traversal and the `correlate_failures` logic.
- *Gap 1:* I initially overlooked that the topological sort (`_topological_order`) could enter an infinite loop if the `DEPENDENCY_GRAPH` contained cycles.
- *Fix 1:* After reviewing the BFS logic, I verified that the `seen` cache prevents infinite loops. But if `root_causes` array returned empty due to cyclic failing upstream, BFS could skip nodes. I created a mock cycle test to confirm it still handles it by appending disconnected/cyclic failed nodes at the end safely.
- *Gap 2:* My initial test for the "All checks fail" case wrongly checked against `len(failed) >= 6`, but if unknown checks exist, it could falsely trigger.
- *Fix 2:* I refined the fix to measure `len(known_failed) == len(_CHECK_REGISTRY)` to strictly limit the catastrophic invariant attribution to cases where *all known* registry checks legitimately fail.

## Agent
gemini-4@google