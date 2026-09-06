# Spec: operator metadata correction

| Version | Date | Authority |
| --- | --- | --- |
| 1.0 | 2026-09-06 | Accepted operator answer; Outcome 1.0 |

This delta supplements Block 9 Spec 1.1, requirements R-B9-01/R-B9-05 and scenarios S-71/S-75.
All other requirements remain unchanged. It becomes effective with the code merge.

## MODIFIED: R-OM-01 command source authority

The source author MUST equal `peachgabba22`. The workflow actor MUST equal the source author.
The source MUST bind the exact command and body hashes.
The system MUST retain nonempty `author_association` metadata without using its value to authorize the command.
Different association values across authenticated GitHub reads MUST NOT reject an otherwise identical source.
The system MUST reject a changed author, body, command, source URL, Issue, or workflow evidence.

### S-71/S-75 metadata cases

- GIVEN an otherwise valid operator command with `MEMBER`, `OWNER`, `COLLABORATOR`, `CONTRIBUTOR`, or `NONE` metadata.
- WHEN the candidate builder reads the source.
- THEN it MUST accept the source and retain its association value.
- GIVEN that command and different association metadata on a later authenticated read.
- WHEN the trusted guard reads the source again.
- THEN it MUST accept unchanged authority and immutable source evidence.
- GIVEN a different author, actor, command hash, body hash, source URL, Issue, or completed workflow evidence.
- WHEN the builder or guard reads the source.
- THEN it MUST reject the candidate before publication or merge.

Evidence: `tests/vnext/test_block9_github_native.py`, including metadata parameters,
source substitution, workflow evidence, and exact operator rejection cases.
Previous `COLLABORATOR` rejection evidence is obsolete for this delta.
Live S-71/S-75 proof remains missing until a successful GitHub run and trusted guard.
