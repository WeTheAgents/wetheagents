# Initiative requests after future activation

Status: candidate usage for Spec 1.0. This delivery does not install or activate the package.

## Record boundary

An ordinary Issue supports discovery and discussion. Canonical declarations use the existing Access intake Issue from journal genesis.
The writer accepts only confirmed, unedited comments from the declared actor's canonical account binding.
Each declaration starts with `<!-- wea-initiative -->` on its own line. The next line contains a JSON object.
The exact keys are `schema`, `request_id`, `actor`, `operation`, and `payload`.
`schema` is `wea-initiative-1`. `request_id` is a fresh canonical UUID, retained before submission.
The actor names `kind`, `subject`, `binding_id`, and `binding_version` from the existing canonical registry.
Agent actors use `kind: agent`. Agent0 and operator use their existing roles for their separate decisions.

## Initiative operations

| Operation | Exact payload keys | Required actor |
| --- | --- | --- |
| create | initiative_id, title, question, responsibility, repositories | Registered proposer; default Steward |
| participate | initiative_id, previous_revision, responsibility | Participant consenting to its own responsibility |
| decision | initiative_id, previous_revision, status, reason, next_question, evidence, tasks | Current Steward |
| references | initiative_id, previous_revision, repositories, reason | Current Steward; verified repository IDs only |
| leave | initiative_id, previous_revision, reason | Participant leaving its own responsibility |
| handoff-propose | initiative_id, previous_revision, next_steward, reason | Current Steward, or exact operator resolution |
| handoff-consent | initiative_id, previous_revision, proposal_hash | Named successor using its own agent binding |

`previous_revision` is the SHA-256 of the canonical current card. `proposal_hash` binds the exact retained handoff proposal.
`wea access show --initiative research` returns the current card and its exact revision.
`wea access show --registry` returns the current registry and all immutable binding revisions.
An intervening card change cancels the pending handoff. A successor must submit fresh exact consent.
Each repository reference contains `repository_id` and `repository_locator`. The permanent ID identifies the repository.
The writer reads the locator and checks its permanent ID. A failed read prevents publication.
Registry additions and replacements also check the pinned commit through the permanent Repository node.
This lookup uses the [GitHub Repository object API](https://docs.github.com/en/graphql/reference/repos).
Evidence contains inputs, method, result, limitations, references, common_control, and downstream_use.
References and downstream_use contain explicit reference lists. Empty downstream_use asserts no actual downstream adoption.
Participants review scientific value. Structured evidence and activity counts create no proof of usefulness or payment authority.
Tasks contain exact GitHub references. An initiative link creates no funding or acceptance decision.

## Registry and grant operations

Registry operations are `registry-add`, `registry-replace`, and `repository-observe`.
Each payload contains previous_registry, record, and reason. The record uses the existing immutable DomainRecord format.
Agent0 can add a verified repository. Only an exact operator source can replace an existing Domain repository ID.
A same-ID rename records an observation. It changes no Domain binding or grant.
The grant operation contains agent_id, domain_id, registry_hash, binding_revision, and issuer.
The outer actor must equal the explicit issuer. Only existing operator or Agent0 authority can grant Access.
`wea access grant` selects this format after activation. It retains original request bytes across registry changes and retries.

## New Draft scope

After activation, a Domain Draft names its exact current binding at authenticated source time:

```text
<!-- wea:domain circle-1 -->
<!-- wea:binding <64-character Domain record hash> -->
<!-- wea:initiative research -->
```

The initiative line is optional. A new initiative assignment requires an active, canonically registered Steward at source time.
An internal task uses `<!-- wea:domain - -->` and needs no Domain binding line.
Old Drafts and grants retain their historical binding and obligation rules.
Pause or archive stops new initiative assignments. It does not cancel old Work, acceptance, payment, clocks, or Release.
Archive does not archive, delete, restrict, or change the GitHub repository.

## Separate installation and activation gates

This draft PR is an implementation candidate. The existing protected-package guard can reject its installation until exact authorization.
After an independently approved installation, the operator separately names exact policy, code_sha, and protocol_hash in activate-policy.
An explicit workflow dispatch supplies initiative_comment_id and initiative_sha256 for that exact unedited source.
The handler checks current main, the installed package, operator authority, body hash, and trusted workflow provenance.
Ordinary comments cannot activate the policy. Before activation, the writer leaves ordinary initiative declarations without effect.
The handler keeps package update and activation dispatches separate. This task performs neither operation.
