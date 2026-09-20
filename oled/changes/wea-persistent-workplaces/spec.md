# Workplace operating contract

Version 1, 2026-09-20. Source: operator adoption request; outcome v1. Applies to local WEA sessions, including sessions in domains. This is an operating procedure, not executable enforcement.

- PW-1: A new task reuses the identity's free repository workplace and gets a fresh unique branch from fetched origin/main. Resuming an unfinished task retains its branch. Given two completed sequential tasks, the path and environment remain the same.
- PW-2: A dirty or occupied place is not switched, reset, cleaned or reassigned. Given an old session, running owned process, unexplained files or unresolved handoff, preserve the place until reconciled. Concurrent writers use distinct identities/places; explicit additional concurrency needs a separate place.
- PW-3: Completion retains commits, untracked/ignored evidence and session references before releasing the place. Given required evidence only in an old checkout, remote branch backup alone is insufficient for deletion.
- PW-4: A domain checkout records repository identity and actual task base separately from the immutable Domain record revision. Given any local place, no Access, Work, funding, acceptance, release or GitHub authority follows from its existence.
- PW-5: The next session checks local occupancy, actual Git state and authenticated binding before writing. Given a stale chat, its remembered path/branch is not sufficient to resume. Manual discipline supplies this check; no lock service is claimed.

Existing Domain/Access and Tide scenarios remain unchanged. No new wea command or canonical state transition is introduced.
