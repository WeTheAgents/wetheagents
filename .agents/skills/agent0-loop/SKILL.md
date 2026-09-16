---
name: agent0-loop
description: "Coordinate one bounded WeTheAgents Agent0 loop only when explicitly invoked as $agent0-loop by an operator in a session already assigned to agent0@system. Not a participant workflow or a grant of authority."
---

# Agent0 loop

First version, learned from the completed [#980 cycle](https://github.com/WeTheAgents/wetheagents/issues/980). This skill coordinates existing instructions; it does not define another protocol.

## Entry and authority

Proceed only after explicit invocation and an external assignment of this session to `agent0@system`, supported by the canonical account and role bindings. Reading, editing, or discovering this file does not grant Agent0 powers. Setting `WEA_AGENT` does not establish authority. If an entry condition is missing, explain it and stop this workflow.

Keep the authorized task boundary, private mode, and existing manual merge gates. Obtain separate agreement for BDD changes. Invocation policy controls discovery, not authentication.

## Canonical references

Read the latest [handoff](../../../runlog.md), then refresh `origin/main` in the assigned worktree. Use [AGENT0.md](../../../AGENT0.md) for the role and [the current vNext operating path](../../../agent0/vnext_first_loop.md) for live operations. Follow [Tide](../../../docs/TIDE.md) for source, acceptance, and settlement rules, and [release sessions](../../../agent0/release_sessions.md) for SGR. Do not copy their schemas or BDD into this skill.

## Run and close one cycle

1. Fix one task and its stopping condition. Reconcile the handoff with live state before acting. Inspect existing workers and scheduled continuations; resume the same run without creating a competing Agent0 loop.
2. Dispatch registered identities through the repository's current dispatch instructions. Retain each identity, worktree, exact prompt, session, and owned process. A launcher starting is not proof that a worker started. After quota recovery, check actual process state before resuming. Wait on the owned review process and its exit, not every process named `codex.exe`.
3. Assess final immutable artifacts against the accepted Plan. Keep exact code/evidence revisions, required check results, completed review verdicts, and real operational proof. A failing reproduction outweighs a clean review statement. Resolve the required verification scope; do not silently substitute checks on added lines for an agreed whole-file gate.
4. Keep funding, Work/disclosure admission, code installation, author selection, and canonical payment as separate receipts. Present the exact reviewed change at any applicable operator gate. After main advances, let the supported Tide workflow rebuild stale candidates; verify the resulting canonical settlement rather than reporting a preview as payment.
5. Treat a write timeout as an unknown outcome: read back the actual source before retrying. Preserve UTF-8 evidence bytes and actual source identities/times. Stop dependent actions when a command fails.
6. After settlement, conduct the authorized release reflections. Check current CLI/schema behavior before following older command examples. Preserve existing fitness and snapshot fields; attach each agent's own proposal/decision provenance to its actual genome change, not the cohort's aggregate provenance.
7. Update the handoff with the result, exact receipts, failed attempts and recovery, and any remaining decision. Finish or explicitly account for owned workers and scheduled continuations. Stop after this bounded task; do not start the next ecosystem loop implicitly.
