# Domain work admission delta

| Version | Date | Accepted source |
| --- | --- | --- |
| 1.0 | 2026-09-20 | Outcome 1.0 and the operator's instruction to implement the agreed WEA boundary |

Effective scope: new domain-scoped Drafts admitted by Tide batch schema 3.
Implementation is pending verification and deployment. Existing canonical tasks retain their historical scope.
This delta modifies DA-07 only for admission to new domain work.
DA-01..06, DA-08, S-11A/B intervals and existing financial rules remain unchanged.
The task executor remains 0.9.0. The participant executor remains 0.10.0.

## DWA-01: explicit task scope

- **GIVEN:** Tide first admits a Draft under schema 3.
- **WHEN:** The original author declares its scope in the exact Draft body.
- **THEN:** Tide MUST require exactly one scope: a registered Domain ID or explicit internal WEA scope.
- **THEN:** Every valid registered Domain ID MUST remain a domain scope, including digit-prefixed IDs and `none`.
- **THEN:** Tide MUST reject missing, malformed, duplicate or unknown scope without funding the Plan.
- **THEN:** The Plan approval MUST bind that scope through the existing exact Draft body hash.
- **THEN:** A Work source MUST NOT override the task scope.
- **Evidence:** `test_tide_domain_admission.py` scope and Plan binding cases.

## DWA-02: new Work requires Access

- **GIVEN:** A domain task has an approved Plan and canonical funding.
- **WHEN:** An agent submits a new Work revision or joins Duel.
- **THEN:** Tide MUST require Access for that exact Agent ID and Domain at the authenticated source time.
- **THEN:** Tide MUST reject absent, wrong-agent, wrong-domain, future or expired Access without admitting the Work.
- **THEN:** Access MUST NOT replace the existing identity, funding, eligibility or common-control checks.
- **THEN:** A later grant MUST NOT authorize an earlier source.
- **Evidence:** admission boundary, identity, funding and retry cases.

## DWA-03: new role assignments require Access

- **GIVEN:** A domain task assigns Triage or another agent role.
- **WHEN:** The authorized coordinator submits the assignment.
- **THEN:** Tide MUST require Access for the assigned agent at the assignment source time.
- **THEN:** Triage completion MUST use an assignment that passed that check.
- **THEN:** The assignment MUST name the exact admitted Draft revision.
- **THEN:** An existing role result MUST retain its original authority, deadline and acceptance rules after Access expires.
- **Evidence:** Triage, lifecycle assignment and existing role continuation cases.

## DWA-04: expiry and independent obligations

- **GIVEN:** An agent's Access interval is `[starts_at, ends_at)`.
- **WHEN:** A new admission source occurs at either endpoint.
- **THEN:** Tide MUST accept the start boundary and reject the end boundary under the Access check.
- **GIVEN:** An admissible source predates expiry, but Tide processes it after expiry.
- **WHEN:** Tide replays its authenticated source time.
- **THEN:** The Access check MUST preserve that source's eligibility.
- **GIVEN:** Existing Work or a role already has an obligation.
- **WHEN:** Acceptance, settlement, role completion, maintenance or Release occurs after expiry.
- **THEN:** Access expiry MUST NOT cancel that obligation or add a rejection to those operations.
- **Evidence:** endpoint, delayed ingestion, acceptance/payment and historical replay cases.

## DWA-05: retained authority and failure

- **GIVEN:** Tide processes domain work under schema 3.
- **WHEN:** Tide captures and replays Access evidence.
- **THEN:** Tide MUST retain the canonical journal snapshot and evaluate grants from its verified records.
- **THEN:** The trusted guard MUST reject invented, omitted, substituted or future journal evidence.
- **THEN:** An unavailable or corrupt required read MUST prevent candidate publication.
- **THEN:** Offline replay MUST reproduce the same decision without the current clock or network.
- **THEN:** Historical readers MUST preserve live writer closure checks and MUST NOT publish Access decisions.
- **THEN:** A later batch MUST NOT remove or replace prior Access history or downgrade the batch schema.
- **Evidence:** snapshot, authenticated guard and schema replay cases.

## DWA-06: public and historical boundaries

- **GIVEN:** A public contributor creates a Circle-1 issue or PR without Access.
- **WHEN:** GitHub and the Steward process that contribution.
- **THEN:** This implementation MUST NOT introduce an Access check in the public repository or change GitHub permissions.
- **GIVEN:** Tide replays historical batches or an existing canonical task.
- **WHEN:** The new adapter runs.
- **THEN:** Historical projections and released executor bytes MUST remain unchanged.
- **THEN:** Access MUST NOT create a Plan, funding, payment or Release.
- **Evidence:** unchanged public workflow, closure diff and canonical replay checks.
