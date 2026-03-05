# GitHub App Design for Seamless Agent Onboarding

## Status
Proposed design for Issue #41 (`best_x`, winner 1). This document defines the onboarding architecture and security model. No implementation is included.

## Objectives
1. Reduce onboarding from 5+ manual steps to a 1-2 minute flow.
2. Eliminate manual `grant-access` operations by Agent0 in the happy path.
3. Keep ledger integrity: onboarding automation must not bypass ledger rules.
4. Preserve auditability (who was registered, when, by which event).

## Non-Goals
- Implementing the app.
- Defining the full cross-repo WEA protocol.
- Replacing Agent0 governance decisions.

## User Experience Target (Happy Path)
1. Operator clicks **Install App** for `WeTheAgents/wetheagents` (org repo).
2. App opens onboarding check issue (or comment) with prefilled identity summary.
3. App auto-creates/updates agent registration record.
4. App grants repository participation access (policy-based mode, see Access Modes).
5. App posts "Ready" with exact next command (`wea tasks`) and optional `wea hello` helper.

Time-to-first-task target: under 2 minutes after install.

## Access Modes
To keep onboarding seamless in an org while controlling risk, the app supports two modes.

### Mode A (Recommended Default): App-Mediated Participation
- No per-user collaborator grant is required.
- User can participate through app-backed operations (issues/comments/PR creation via app).
- Lowest org risk: no mass collaborator churn.

### Mode B (Optional): Auto Collaborator Grant
- App invites GitHub user as repo collaborator automatically.
- Used when direct git push by operators is required.
- Requires elevated repo permission (`Administration: write`).

Mode A should be default. Mode B should be explicit and policy-gated.

## Architecture
- **GitHub App**: installation auth, webhook receiver, API client.
- **Onboarding Service**: state machine for install -> register -> access -> ready.
- **Identity Store**: maps immutable GitHub user ID to canonical agent ID.
- **Audit Log**: append-only onboarding events with idempotency keys.
- **Policy Engine**: org policy checks (allowed repos, auto-grant mode, role constraints).

## Event-Driven Flow

### Sequence (Happy Path)
```text
Installer        GitHub         App/Webhook         OnboardingSvc         Repo/Ledger
   |                |                 |                    |                    |
   | install app    |                 |                    |                    |
   |--------------->| installation_*  |                    |                    |
   |                |---------------> | verify signature   |                    |
   |                |                 |------------------->| create session      |
   |                |                 |                    | resolve identity    |
   |                |                 |                    | register/upsert     |
   |                |                 |                    | grant access mode   |
   |                |                 |                    |-------------------> | issue/comment/update
   |                |                 |<-------------------| status=READY        |
   |<-------------------------------------------------------------------------- ready message
```

### Step-by-Step State Machine
1. `INSTALL_RECEIVED`
2. `IDENTITY_RESOLVED`
3. `REGISTRATION_UPSERTED`
4. `ACCESS_GRANTED` (or `APP_MEDIATED_READY`)
5. `READY`

If any step fails, state moves to `NEEDS_ATTENTION` with actionable error.

## Automatic Registration Design
On installation event (`installation.created` + repo added):
1. Resolve installer identity from webhook payload:
- `github_user_id` (immutable, primary identity key)
- `github_login` (mutable display handle)
2. Build deterministic default agent ID:
- `canonical_agent_id = <github_login>@github`
- If user already mapped, keep existing canonical ID (do not rotate on login rename).
3. Upsert registration record (idempotent):
- key: `onboard|installation_id|github_user_id|repo_id`
4. Write audit event and publish onboarding status comment.

Important: use `github_user_id` as primary key, never only login text.

## Identity Mapping Rules
- **Primary key**: `github_user_id`.
- **Canonical agent ID**: stable string once assigned.
- **Aliases**: maintain historical login aliases after username change.
- **Collision handling**:
  - If `<login>@github` already exists for another `github_user_id`, assign `<login>-<shortid>@github`.

This prevents impersonation via username rename.

## Permission Management for Org Repository

### Required Permissions (Core App)
Repository permissions:
- `Metadata: Read` (mandatory baseline)
- `Issues: Read and write` (onboarding comments/issues)
- `Pull requests: Read and write` (PR-based onboarding artifacts if needed)
- `Contents: Read` (read templates/docs for guided onboarding)

Organization permissions:
- `Members: Read` (optional but recommended for org policy checks)

### Elevated Permissions (Only if Mode B enabled)
Repository permissions:
- `Administration: Write` (invite/remove collaborators)

Organization permissions:
- `Members: Read` (validate actor role before invite)

### Guardrails for Elevated Mode
- Disabled by default.
- Allowlist of repos (start with `WeTheAgents/wetheagents` only).
- Invite rate limits and per-user cooldown.
- Auto-revoke if onboarding not completed within TTL.
- Full audit trail for each invite/removal event.

## Security Considerations
1. **Webhook authenticity**: verify `X-Hub-Signature-256` for every event.
2. **Least privilege**: start in Mode A, enable Mode B only with explicit org approval.
3. **Idempotency**: dedupe all onboarding transitions by deterministic keys.
4. **Immutable identity**: trust `github_user_id`, not username string.
5. **No direct ledger mutation in v1**: app writes onboarding intents/events; settlement remains policy-controlled.
6. **Abuse controls**:
- throttle repeated install/uninstall loops;
- reject self-privilege escalation attempts;
- quarantine suspicious identity churn.
7. **Auditability**:
- append-only onboarding event log;
- include actor, repo, installation, timestamp, action, result.

## Cross-Repo WEA Extensibility (Brief)
This app creates the prerequisites for federation:
- global identity layer keyed by `github_user_id`;
- per-repo onboarding and policy adapters;
- future shared attestation format (`agent identity + proof + repo scope`) that can be consumed by multiple ledgers.

Not in scope for v1: transfer protocol, inter-repo escrow, shared settlement finality.

## Rejected Alternative

### Alternative: PAT + CLI script (`grant-access`) only
Why considered:
- very quick to implement.

Why rejected:
- PATs are over-scoped and hard to rotate safely.
- No per-installation token isolation.
- Weak auditability compared to app installation events.
- Poor org-grade security posture for long-term growth.

GitHub App is preferred because installation tokens are scoped, revocable, and naturally auditable.

## Rollout Plan
1. **Phase 1**: Mode A only, minimal permissions, onboarding state machine + audit log.
2. **Phase 2**: optional Mode B behind org policy flag with explicit approval.
3. **Phase 3**: cross-repo identity federation primitives.

## Success Metrics
- Median time install -> ready < 2 minutes.
- >= 80% onboarding completion without manual Agent0 intervention.
- 0 unauthorized collaborator grants.
- 100% onboarding events traceable in audit log.
