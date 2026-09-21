# Agent Switching Protocol

The operator replaced the identity-specific worktree recipe on 2026-09-21.
Use [persistent workplaces](WORKPLACES.md) for the current allocation, role,
publication and handoff procedure. Earlier examples remain in Git history.

## Assign a session

1. Retain the existing registered Agent ID and read its canonical genome.
   Admission, identity and authority are separate from local workplace selection.
2. Assign one free neutral WEA slot, work/slot-1 through work/slot-3. Registered
   Codex and Claude identities may use the same slot sequentially. Agent0 uses
   its separate coordinator place and work/agent0 after the documented transition.
3. Reconcile the prior occupant's session, owned processes, Git state and PR.
   An unfinished task or unknown writer blocks reuse; do not reset or auto-stash.
4. Record the assignment locally in workplaces.json. Match its Agent ID, cwd,
   branch, prompt and role selector before launch. Set session WEA_AGENT and
   effective Git identity; verify the authenticated account binding separately.
5. Launch in that existing place with its own role/genome reads and bounded scope.
   Retain the native session, process receipt, result and next checkpoint outside
   the checkout. Release occupancy only after the old writer has stopped and its
   delivery has been reconciled or an explicit suspension decision retained.

Parallel work still needs coordination: separate Git worktrees do not allocate
identities, stop old sessions, serialize registry updates or grant WEA powers.
Do not create extra task branches or use the main checkout as an Agent0 workplace.
The registry is manual local coordination, not an atomic lock or canonical state.

## New identities

Use [Tide participant admission](TIDE.md#add-participants) and the
[CLI genome initialization procedure](CLI.md) when an identity does not yet exist.
Use an assigned existing slot for explicitly authorized onboarding maintenance;
do not create a permanent branch per new Agent ID. A checked-out genome, local
selector or environment variable does not register or authenticate an agent.
The exact task contract still governs Access, Plan, funding, Work and acceptance.
