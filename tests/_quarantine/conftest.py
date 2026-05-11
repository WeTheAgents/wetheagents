"""Skip quarantined tests during normal pytest runs.

Tests in this directory exercise checkers that have been moved to
`scripts/_quarantine/`. They are kept on disk for reference and for
the day a checker is reinstated, but they do not run by default.

Re-enable a quarantined test by removing it from `_quarantine/` and
deleting the matching entry from `collect_ignore` below.
"""

from __future__ import annotations

import os

collect_ignore_glob = ["test_*.py"]
collect_ignore = [
    "test_check_history_reconciliation.py",
    "test_check_gauntlet_evaluator_consistency.py",
]

# Allow `pytest tests/_quarantine/` to still discover these files when
# the operator explicitly opts in by setting WEA_RUN_QUARANTINED_TESTS=1.
if os.environ.get("WEA_RUN_QUARANTINED_TESTS") == "1":
    collect_ignore_glob = []
    collect_ignore = []
