# Circle-1 compatibility snapshot

Portable Circle-1 scanner development now belongs in the public
[`WeTheAgents/circle-1`](https://github.com/WeTheAgents/circle-1) repository.
The modules in this directory are a read-only compatibility snapshot retained
for WEA history and existing callers.

WEA-specific orchestration stays outside this directory, including
`scripts/circle1_director_sweep.py`, task-index reconciliation, and ledger
operations.
