# Private Domain Access pilot

Access gives one registered Agent ID a seven-day trip to one registered Domain.
The interval is exactly 604800 seconds. Trips for the same agent cannot overlap,
even across domains. A new trip can start at the exact previous endpoint.

Access does not create Work, funding, a payment obligation, Release, or GitHub
permissions. The task Plan and canonical Tide escrow remain separate.
There is no early revoke, extension, or transfer command.

The accepted [domain work admission delta](../oled/changes/wea-domain-work-admission/spec.md)
adds an Access prerequisite to new WEA domain work through Tide schema 3.
Its deployment is pending. The [Tide instructions](TIDE.md#domain-admission-schema-3-candidate) describe the new scope and checks.
Public issues and PRs remain open under ordinary GitHub permissions and Steward review.
Existing obligations keep their acceptance, settlement and Release paths after Access expiry.

## Operator deployment checkpoint

The operator accepted the Access 0.5 Outcome/Spec/Design on 2026-09-18.
Implementation approval is not activation. Review and manually merge the code
first. Keep WEA private. Do not launch another Agent0 loop or scheduled worker.
The old trusted-main writer guard rejects the newly introduced workflow. This
requires a one-time operator installation decision for the exact reviewed PR,
following the existing Tide maintenance procedure. Keep that failure visible;
do not override its status or waive subsequent financial checks.

Use the merged source CLI with `PYTHONPATH=src`, or an installed package with
exactly the activated protocol bytes. An incompatible package fails closed.
The fixed closure includes the Access adapter, vNext imports and the workflow;
genesis retains its file hashes and reviewed code commit. This pilot has one
format and no automatic migration to another implementation.

Prepare one fresh operator comment in the selected private Issue (the pilot
can use #997), with this literal first line:

```text
<!-- wea-access-activate -->
```

The JSON below it contains exactly `schema` (`wea-access-1`), `code_sha` (full
merged main SHA), `protocol_hash` (`digest(protocol(root, code_sha))` from
`wea_vnext.access_github`), `registry_hash`, `issue_number`, and `journal_ref`
(`refs/heads/wea/access-journal`). Review these exact values before publication.
The operator's numeric account is 129645949. An unedited source must match the
exact supplied body SHA-256. The source creation time becomes the cutoff;
earlier comments never acquire effects.

Dispatch **Domain Access** on main with `issue`, `activation_comment_id`, and
`activation_sha256`. The handler verifies the actual workflow run, current
main checkout, private repository, Issue identity, source and code closure.
It creates a parentless genesis commit on `wea/access-journal`. An ordinary run
with no genesis returns `disabled`. Repeating the exact activation returns the
original genesis; another activation is rejected.

Keep this data branch separate from main. It contains only genesis and one
immutable decision file per source. No Access operation needs a PR or merge.
The repository administrator remains trusted; Git cannot prevent an
administrator from deleting or replacing the entire history.

## Request and read a trip

Agent0's private pilot role selector defaults to `pilot-agent0-role-v1`, version 1:

```text
wea access grant --agent Codex-19@codex --domain circle-1
wea access show --agent Codex-19@codex
wea access show --request-id <retained-UUID>
```

The operator can select `--issuer operator`. Another Agent0 binding requires
explicit `--binding-id` and `--binding-version` values. `WEA_AGENT` alone does
not establish authority. GitHub authenticates the account; the agent identity
is declared against its canonical binding. Sessions sharing the operator's
credentials are trusted and are not independently distinguished.

The CLI saves and flushes the UUID, account and exact payload under
`.wea_runs/access-requests/` before posting. It prints that recovery location.
A queued Issue comment is `pending`, not a grant. The CLI waits briefly and
then returns the current state. Resume with the same command and
`--request-id <UUID>`; do not manufacture a new UUID after a lost response.
An identical retry returns the original decision and interval. A conflicting
payload is rejected, including when the original local request file is absent.

The handler checks authority at declaration and acceptance and registration at
acceptance. Sources edited before capture receive a rejection. Captured source
bytes survive subsequent edits or deletion. `show` rebuilds the journal before
reporting decisions and retains Issue URLs, authority evidence, exact interval,
journal commits and actual evaluation time. A read failure is `unavailable`.
Read output distinguishes observed decisions from still-pending requests;
inspect each decision's `status` rather than treating process completion as a grant.

## Recovery and bounds

Every eligible Issue-comment event reconciles the configured Issue. Events are
wake-up hints, not a durable FIFO queue. Manual dispatch with empty inputs runs
the same reconciliation and repairs missing or corrupted workflow receipts.
It does not start a recurring automation.

Publication uses a non-forced Git ref update. A competing append requires a
fresh read and revalidation. A lost response requires readback before another
attempt. Receipt failure does not undo or reissue a committed grant.
Git ancestry and append-only tree checks retain ordering without a second hash
chain. A replay/integrity error stops issuance and is reported explicitly.
Recovery proceeds by readback and new appends; never rewrite accepted intervals.

The reader fetches immutable journal objects through native Git into a temporary
bare repository and validates them locally. Within one reconciliation, it reuses
the validated state while the head is unchanged. A competing append invalidates
that snapshot. Git credentials are passed through the process environment;
the temporary object store is removed when the process closes.

The bounded pilot supports at most 500 grants and 2000 intake comments per
bounded capture. Rejections and duplicate requests do not consume grant capacity;
they remain retained in the journal. Grant-capacity exhaustion stops new issuance
while existing history remains readable. Extending these bounds or changing the pinned implementation
requires a separately reviewed change; do not force-push around the check.
The 2000-comment bound includes receipts. An over-limit capture fails before
processing requests. At capacity, CLI submission retains its local request and
receipt repair reports pending without changing a committed Access interval.

Expiry is evaluated from `[starts_at, ends_at)`. It needs no timer, Issue edit,
PR or financial event. Disabling the Actions workflow stops new issuance but
does not revoke existing grants. Unit tests use synthetic time. Record a real
post-endpoint read, with its actual observation time, before claiming a lived
seven-day trip.

The full two-agent WTA sequence and its separate funding/Release checkpoints
are in [the pilot cycle](../oled/changes/wea-domain-access-private-pilot/cycle.md).
