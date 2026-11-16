# Implementation plan

Each milestone ends with a review before the next begins.

## Milestone 0: Project foundation — done

| Deliverable | State |
|---|---|
| Repository structure, Git, `.gitignore`, `.editorconfig` | Done |
| Django backend, React + TypeScript + Vite frontend | Done |
| PostgreSQL via Docker Compose, with a non-Docker option | Done (Compose file not run in the build environment, see limitations) |
| Environment configuration and `.env.example` | Done |
| Lint and format: ruff; ESLint and Prettier | Done |
| Tests: pytest on PostgreSQL; Vitest | Done |
| CI workflow (GitHub Actions) | Written, not yet run (no remote repository) |
| Health check `/api/health/` | Done |
| README and architecture documents | Done |

## Milestone 1: Identity and workspace foundation — done, awaiting review

| Deliverable | State |
|---|---|
| Custom user model in the first migration | Done |
| Workspace, membership, roles, statuses, ownership invariants | Done |
| Device model, registration, revocation, sync gate | Done |
| Central capability policy and workspace access check | Done |
| Login, logout, current user, memberships, workspace selection | Done |
| App shell, login, workspace choice, dashboard placeholder, states | Done |
| Required tests 1 to 8 | Done |

**Acceptance criteria and evidence**

| # | Criterion | Evidence |
|---|---|---|
| 1 | Registration and authentication work | `tests/test_accounts.py` |
| 2 | An owner can access their workspace | `test_workspace_access.py::test_owner_can_access_their_workspace` |
| 3 | No access without membership | `…::test_user_without_membership_gets_404` |
| 4 | No access by changing a URL identifier | `…::test_owner_of_one_workspace_cannot_read_another_by_changing_the_url`, `…::test_cannot_modify_another_workspaces_member_through_own_workspace_url` |
| 5 | Roles are enforced | `…::test_role_matrix`, `test_memberships.py::test_services_recheck_the_actors_authority` |
| 6 | Inactive memberships are rejected | `…::test_inactive_membership_is_rejected_everywhere` |
| 7 | A revoked device cannot synchronise | `test_devices.py::test_revoked_device_cannot_synchronise` |
| 8 | Authentication and CSRF protections | `tests/test_csrf.py` |

### Known limitations

- No sign-up, invitation, password-reset or member-creation API (D-010, O-003, O-007).
- Ownership transfer exists as a tested service with no endpoint; it should
  require password confirmation when exposed.
- Revoking a device does not end that browser's session (D-009, O-006).
- No concurrency stress tests yet. The invariants rest on database
  constraints, which are tested; contention tests start with the first
  financial operations.
- Login rate limiting is per server process (D-016).
- No service worker, IndexedDB or sync queue (D-014).
- No production deployment configuration (web server, TLS, static files).
- UI is English only (O-019).

## Milestone 2: Catalogue and people (proposed)

Products (name, SKU, description, reference, cost and minimum prices, status,
inventory flag), with cost price and margin hidden from affiliates. Member
onboarding API once O-001 and O-003 are decided. Customers with duplicate-phone
warning.

*Acceptance:* affiliates never receive cost price in any response; SKU unique
per workspace; all records workspace-scoped with isolation tests.

## Milestone 3: Orders, attribution and pricing approval

Multi-line orders with product and price snapshots, attribution locked on
submission, below-minimum approval bound to an order version.

## Milestone 4: Sales, payments and commissions

Sale completion, partial payments with separate confirmation, reversals,
versioned commission policies, eligibility after full confirmed payment,
payouts. Concurrency tests on PostgreSQL. Needs O-010 to O-012.

## Milestone 5: Basic inventory

Stock movements as the audit trail, balance as a projection, deduction on
sale completion, negative stock blocked.

## Milestone 6: Offline foundation

Service worker, IndexedDB, persistent operation queue with idempotent
operation identifiers, explicit conflicts. Needs O-015.

## Milestone 7: Excel import and export, reporting

Needs O-013 and O-017.
