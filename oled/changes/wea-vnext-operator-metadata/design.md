# Design: operator metadata correction

Revision 1.0 implements Outcome 1.0 and Spec 1.0 in this directory.
The parent mechanism remains Block 9 Design 1.3.

Use the existing shared source validator. Keep a nonempty text check for association metadata.
Remove association equality from both authorization and remote source comparison.
Retain exact login, workflow actor, URL, Issue, body, command, and workflow checks.
No dependency, fallback identity, App, or alternate writer is needed.

Run 33231456987 failed before candidate construction with the organization-member error.
The owner API reports MEMBER; the Actions response did not satisfy that equality.
Its alternate value is unknown. Do not invent that value.

The current ledger is inactive. Code rollback uses an ordinary revert before activation.
A code merge changes the predecessor and invalidates the old activation command.
Rebuild the package against merged main before any activation attempt.
After activation, the parent append-only recovery policy applies.

Ceiling: one fixed operator. Multiple operators require a new accepted authority design.
Local regression tests prove metadata handling. Only a real Actions run proves token-context integration.
