# Circle-1 scripts observability inventory logic

## Review model

The harness exists to make script observability reviewable before anyone argues
about policy. Agent0 runs it against a checkout, then reads the inventory as a
map of where scripts emit human output, diagnostics, artifacts, subprocesses,
GitHub activity, ledger/protocol writes, network calls, or unresolved side
effects.

Each detection is evidence, not judgment. A noisy script is not automatically
wrong, and a quiet script is not automatically safe. The useful question is:
which observable surfaces should a reviewer inspect before changing or accepting
that script?

## Invariants

The harness only reads Python source text and parses AST. It must not import
scanned files, execute scanned code, launch discovered subprocesses, call GitHub,
or mutate ledger data.

The denominator must stay visible. Recursive files under the scripts tree remain
in scope, default exclusions are reported, unreadable files and parse errors stay
in the output, and a missing scripts directory is a CLI error instead of an empty
successful scan.

Ledger/protocol classification is target-path based. Text written into a normal
artifact can mention ledger paths without becoming a ledger write candidate.
History-like filenames outside the ledger tree are not ledger evidence by
themselves.

Import aliases are bookkeeping, not dataflow proof. Direct aliases for common
modules and imported subprocess/logging/sys names should resolve to their
canonical channel families, while wrappers and runtime-selected targets remain
limitations or ambiguous side effects.

Unresolved writes should not inflate two buckets. If the scanner cannot identify
the receiver of a write call, the honest classification is ambiguous unless the
write target is otherwise statically visible.

Visible gh subprocess commands are GitHub side-effect candidates. The scanner
does not try to prove whether a gh command posts a comment, edits metadata, or
only reads state; it surfaces the command for human review.

## Failure paths

Parse errors and read errors are reported as ambiguous evidence for that file so
checkpoint consumers can distinguish broken input from a clean script.

Dynamic calls, dynamic file targets, and helper abstractions are allowed to fall
back to ambiguous evidence when the AST does not provide a stable channel target.

Evidence snippets should preserve enough of a multi-line call for review while
remaining short enough for JSON checkpoint diffs.

## Accepted examples

A default human print is stdout evidence.

A print aimed at the system error stream is stderr evidence, including when the
system module was imported through a simple alias.

A subprocess call imported directly from the subprocess module is process-launch
evidence, and it is also GitHub-candidate evidence when its visible command starts
with gh.

A path write whose target resolves under the ledger tree is both artifact-write
and ledger/protocol-write evidence.

A normal report write whose payload merely mentions a ledger path is only
artifact-write evidence.

An unresolved object write is ambiguous evidence, not a separate artifact-write
claim.

## Rejected outcomes

A prose-only policy does not satisfy this logic because it cannot inventory the
current tree.

A CI gate or settlement rule does not satisfy this logic because the task asks
for measurement, not enforcement.

Silently skipping nested scripts or returning a successful zero-file report for a
missing scripts directory does not satisfy this logic because it hides denominator
movement.
