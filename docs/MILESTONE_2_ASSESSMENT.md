# Milestone 2 — Repository assessment and engineering plan

Assessed commit: `1ba96e6` on `main` (identical to `origin/main`). Date: 2026-11-16.
No application code, migrations, dependencies or commits were changed for
this assessment.

## Evidence base

| Evidence | Result |
|---|---|
| Source read | All backend apps, settings, URLs, migrations, frontend `src/` and `e2e/`, CI workflow, docs |
| Existing backend suite (pytest, PostgreSQL 16) | 213 passed, 4 skipped |
| Existing CI on GitHub for `1ba96e6` | backend, frontend and e2e jobs passed |
| New assessment probes (18) | 16 confirmed a suspected weakness; 2 disproved one (noted below). Kept outside the repository |
| Production-mode configuration checks | `manage.py check` and `check --deploy` with `DJANGO_DEBUG=false` |

A finding is **Confirmed** only if a probe or an existing test demonstrated
it against the real code and database. Anything else is labelled **Risk** or
**Unverified**.

Two suspected weaknesses were disproved and are not reported:

- *Sessions survive a password change.* False: Django deletes the session row
  the next time it is presented with a stale password hash (probe S18).
- *Unlimited installations per user.* Only partly true: installation creation
  is limited by the login throttle (10 per minute per address). See F-13.

---

## 1. Executive summary

The Milestone 1 foundation is sound and well tested where it exists:
tenant isolation is structural and enforced on every workspace route;
sessions are bound to browser installations; revocation works; ownership
changes are serialised under real concurrency. No authentication bypass and
no cross-workspace data access was found.

Milestone 2 is, however, mostly **new surface**: there is no registration,
password change, password reset, workspace creation, invitation, session
management or member-management API or screen for end users. Of the 12
required user journeys, 3 are complete, 4 partial and 5 missing.

Security weaknesses that remain open from the Milestone 1 review are
confirmed in the current code:

- **Login rate limiting is defective** (F-01, F-02): bypassed by a forged
  `X-Forwarded-For` header, no per-account limit, and it throttles correct
  logins from a shared address.
- **The Django admin is a high-value, unthrottled target** that can also
  silently strip a workspace of its owner (F-03).
- **Membership and device lifecycles do not meet the Milestone 2 rules**:
  removing a member leaves their devices authorised and reinstatement
  restores them (F-05); a manager can permanently lock the owner's browser
  out of the workspace (F-04).

The largest planning risk is not in the code: **making an unverified phone
number the login identifier and the invitation target** creates account
squatting and invitation-hijack risks (R-01) that need a product decision
before the data model is changed.

**Recommendation: GO for M2.1 (security hardening) now; GO for M2.2 onward
once the product decisions in section 11, questions Q1 to Q6, are made.**

---

## 2. Actual repository architecture

Modular monolith, one origin (Vite proxy in development), PostgreSQL only.

```
backend/
  config/settings.py        single env-driven settings module
  config/urls.py            /api/health/, /api/v1/…, /admin/, /api/docs/ (debug only)
  apps/common/              UUIDModel, TimestampedModel, domain errors (exceptions.py),
                            HTTP error mapping (api_errors.py), health check
  apps/accounts/            User, DeviceInstallation, UserSession, session_store.py,
                            installations.py (bind/revoke), authentication.py, auth views
  apps/workspaces/          Workspace, WorkspaceMembership, WorkspaceDevice,
                            policies.py (capabilities), access.py (guard), checks.py,
                            services.py, device_services.py, selectors.py, context.py,
                            management commands create_workspace, add_member
  apps/devices/             no models; device list/revoke and sync handshake views
  apps/audit/               AuditEvent, record_event()
  scripts/e2e_seed.py       throwaway database for browser tests
  tests/                    14 modules incl. isolation contract and concurrency tests
frontend/src/
  api/                      client.ts (CSRF, errors), endpoints.ts, types.ts
  session/                  SessionProvider, SessionContext
  components/               AppShell, WorkspaceRoute, States
  pages/                    LoginPage, WorkspaceSelectPage, DashboardPage
frontend/e2e/               Playwright: auth, workspaces, devices, phone
.github/workflows/ci.yml    backend, frontend, e2e jobs (PostgreSQL service)
```

Dependency direction: `common` ← `audit` ← `accounts` ← `workspaces` ←
`devices`. Domain modules may not import DRF; enforced by
`tests/test_architecture.py::test_domain_modules_do_not_import_the_http_layer`.

### Request path for a workspace endpoint

1. `accounts.authentication.SessionAuthentication.authenticate`
   (`apps/accounts/authentication.py:20`) — session must be bound to an
   active `DeviceInstallation`, which becomes `request.auth`; else 401.
2. `WorkspaceAPIView.get_permissions` (`apps/workspaces/access.py`) always
   runs `IsAuthenticated` then `WorkspaceAccess`:
   active membership (404 if none) → active workspace (403) →
   `ensure_workspace_device` (`access.py:45`; 403 `device_not_authorized`) →
   capability for the method (403).
3. Handler queries via `self.workspace_queryset(Model)`.
4. Writes go through services that call `authorize_actor`
   (`apps/workspaces/services.py:50`), re-reading and locking the actor's
   membership.

### Existing API (complete list)

| Method | Path | View | Auth |
|---|---|---|---|
| GET | `/api/health/` | `HealthCheckView` | public |
| GET | `/api/v1/auth/csrf/` | `CsrfView` | public |
| POST | `/api/v1/auth/login/` | `LoginView` (email + password) | public, CSRF, throttled |
| POST | `/api/v1/auth/logout/` | `LogoutView` | session |
| GET | `/api/v1/auth/me/` | `MeView` | session |
| GET | `/api/v1/auth/installations/` | `InstallationListView` | session |
| POST | `/api/v1/auth/installations/{id}/revoke/` | `InstallationRevokeView` | session |
| GET | `/api/v1/workspaces/` | `MyWorkspacesView` | session |
| PUT | `/api/v1/workspaces/current/` | `CurrentWorkspaceView` (last-used hint) | session |
| GET | `/api/v1/workspaces/{ws}/` | `WorkspaceDetailView` | `workspace.view` |
| GET | `/api/v1/workspaces/{ws}/members/` | `MemberListView` | `members.view` |
| PATCH | `/api/v1/workspaces/{ws}/members/{id}/` | `MemberDetailView` (role, status) | `members.manage` |
| GET | `/api/v1/workspaces/{ws}/devices/` | `DeviceListView` | `devices.use` |
| POST | `/api/v1/workspaces/{ws}/devices/{id}/revoke/` | `DeviceRevokeView` | `devices.use` + service check |
| POST | `/api/v1/workspaces/{ws}/sync/handshake/` | `SyncHandshakeView` | `devices.use` |
| GET | `/api/schema/`, `/api/docs/` | drf-spectacular | only when `API_DOCS_ENABLED` (default = `DEBUG`) |
| — | `/admin/` | Django admin | staff; always routed |

Out-of-band operations: `manage.py create_workspace`, `manage.py add_member`,
`manage.py changepassword`.

---

## 3. Existing functionality assessment

**Strong and should be preserved**

- The workspace guard: mandatory permission classes, import-time refusal to
  override guard methods, system checks `workspaces.E001` to `E003`, and the
  isolation registry `tests/isolation.py` run by `tests/test_isolation.py`.
  Every new workspace endpoint in Milestone 2 must be added to that registry.
- `authorize_actor` re-reads and locks the actor (`tests/test_actor_authorization.py`).
- Installation-bound sessions (`UserSession` with `user` and `installation`
  columns; `apps/accounts/session_store.py`) and revocation that deletes
  sessions in the same transaction.
- Concurrency tests on PostgreSQL (`tests/test_concurrency.py`).
- Uniform error format and domain/HTTP separation.

**Weak or absent**

- Identity is email-based; `User.phone` is a free-text, non-unique field
  (`apps/accounts/models.py:52`, `USERNAME_FIELD = "email"` at line 59).
- Capabilities are coarse: five (`workspace.view`, `members.view`,
  `members.manage`, `devices.use`, `devices.manage`) against nine targeted.
- All onboarding is operator-only (management commands).
- Frontend has three screens: login, workspace chooser, placeholder dashboard.

---

## 4. Requirement-by-requirement status

Status is measured against the **Milestone 2 target**, not against what
Milestone 1 promised.

### A. Authentication

| Requirement | Status | Evidence |
|---|---|---|
| User registration | PARTIAL | `accounts.services.register_user` (validates password policy) and `manage.py create_workspace`; no API or screen |
| Phone normalisation and uniqueness | MISSING | `User.phone` free text, not unique (probe S10) |
| Phone as primary login identifier | MISSING | `USERNAME_FIELD = "email"`; `LoginSerializer` takes `email` |
| Login and logout | COMPLETE (email) | `tests/test_accounts.py::test_login_then_me_then_logout`, `e2e/auth.spec.ts` |
| Password hashing | COMPLETE | Django default PBKDF2; validators incl. `min_length=10` (`settings.py:86`); `test_register_user_normalises_email_and_hashes_password` |
| Password change | MISSING | no endpoint; only `manage.py changepassword`. Sessions do end on change (probe S18) |
| Password reset | MISSING | no endpoint, no delivery channel |
| CSRF protection | COMPLETE | `tests/test_csrf.py` (CSRF checks on), login protected with `csrf_protect` |
| Session expiration | PARTIAL | absolute 14 days only (`settings.py:102`); no idle timeout (probe S9) |
| Session invalidation | PARTIAL | logout, installation revocation, password change, user deactivation; no "sign out other sessions"; expired rows never purged |
| Account suspension | PARTIAL | `User.is_active=False` refuses existing sessions (`test_deactivated_user_loses_existing_session`, probe S17); no API, not audited, can orphan a workspace (F-11) |
| Login rate limiting | DEFECTIVE | F-01, F-02 |
| Error-message security | COMPLETE | `test_failed_logins_are_indistinguishable` |
| Login timing equality | UNVERIFIED | Django's `ModelBackend` hashes a dummy password for unknown users; not measured |
| Authentication abuse prevention | DEFECTIVE | F-01, F-02, F-03 (admin) |

### B. Workspace onboarding

| Requirement | Status | Evidence |
|---|---|---|
| Workspace creation | PARTIAL | `services.create_workspace` (`services.py:37`) and command; no API or screen |
| Atomic workspace + owner membership | COMPLETE | `@transaction.atomic`; `test_create_workspace_creates_exactly_one_active_owner`, `test_create_workspace_refuses_blank_name_and_inactive_owner` |
| Workspace listing | COMPLETE | `MyWorkspacesView`; `test_my_workspaces_lists_only_my_active_memberships` |
| Workspace selection | COMPLETE | URL-based (`/w/<id>`); `e2e/workspaces.spec.ts` |
| Multiple workspace membership | COMPLETE | `test_user_with_several_workspaces_has_a_role_in_each`, `test_one_installation_serves_several_workspaces` |
| Workspace-aware frontend routing | COMPLETE | `App.tsx`, `WorkspaceRoute.tsx`; two-tab and history browser tests |
| Cross-workspace isolation | COMPLETE for existing endpoints | isolation contract over all 6 workspace routes |

### C. Membership and invitations

| Requirement | Status | Evidence |
|---|---|---|
| Invitation creation, expiry, revocation, acceptance | MISSING | no model, service or endpoint |
| Intended-user verification | MISSING | and see risk R-01 |
| `Invited` membership state | MISSING | `MembershipStatus` = active, suspended, removed |
| Membership suspension | PARTIAL | `set_member_status` + `PATCH members/{id}`; owner only; devices untouched |
| Membership removal | PARTIAL | status `removed`; devices stay authorised (F-05) |
| Membership reinstatement | DEFECTIVE (vs target) | silently restores the old device authorisation (probe S5) |
| Last-owner protection | PARTIAL | DB: single owner, owner always active; services refuse; bypassable via admin (F-03) and account deactivation (F-11) |
| Concurrent ownership changes | COMPLETE | `test_concurrent_ownership_transfers_leave_exactly_one_owner`, `test_action_waiting_on_a_transfer_is_refused_once_the_transfer_commits` |

### D. Roles and permissions

| Requirement | Status | Evidence |
|---|---|---|
| Role model (owner, manager, attendant, affiliate) | COMPLETE | `MembershipRole`, DB check constraint |
| Capability-based permissions | PARTIAL | mechanism complete (`policies.py`); vocabulary too coarse for Milestone 2 |
| Backend enforcement | COMPLETE | structural guard + system checks + isolation contract |
| Manager restrictions | PARTIAL | cannot change members (probe S16); **can revoke the owner's device** (F-04) |
| Affiliate restrictions | COMPLETE for current endpoints | `test_role_matrix`, own-devices-only listing |
| Consistency across endpoints | COMPLETE | `test_every_workspace_route_is_in_the_isolation_contract` |
| Privilege escalation (role) | COMPLETE | `owner_role_reserved`; `test_add_member_cannot_create_a_second_owner`; admin path open (F-03) |

### E. Sessions and devices

| Requirement | Status | Evidence |
|---|---|---|
| Device installation creation | COMPLETE | `bind_session_to_installation` (`installations.py:46`) |
| Device/session binding | COMPLETE | `test_first_login_registers_the_browser_and_binds_the_session` |
| Session revocation | PARTIAL | only by revoking the whole installation |
| Device (installation) revocation | COMPLETE | `test_revoking_an_installation_ends_its_sessions_and_only_those` |
| Workspace-specific device authorisation | COMPLETE | `test_revoked_workspace_device_closes_that_workspace_only` |
| Global vs workspace revocation | COMPLETE | D-017/D-020; tests above |
| Session listing | PARTIAL | installations listed; individual sessions and their activity are not |
| Logout from other sessions | MISSING | probe S15 |
| Idle and absolute expiration | PARTIAL | absolute only |
| Re-authentication for sensitive operations | MISSING | F-09 |

### F. Production security

| Requirement | Status | Evidence |
|---|---|---|
| DEBUG | COMPLETE | default `False`; placeholder secret refused when not debug (`settings.py:19-22`) |
| ALLOWED_HOSTS | COMPLETE | env-driven, default empty (deny all) |
| HTTPS enforcement | PARTIAL | `SECURE_SSL_REDIRECT`, HSTS and proxy SSL header are opt-in (`settings.py:115-121`); HSTS 0 by default |
| Secure cookies | PARTIAL | default secure when not debug, but overridable; `.env.example` sets `false`; starts without warning (F-08) |
| CSRF trusted origins | COMPLETE | env-driven |
| Proxy trust configuration | DEFECTIVE | `NUM_PROXIES` unset, so the throttle trusts `X-Forwarded-For` (F-01) |
| Secret management | COMPLETE | `.env` ignored; only `.env.example` and a documented test-only e2e password are committed |
| Database credentials | COMPLETE | `DATABASE_URL`; Compose has dev-only defaults |
| Django admin exposure | DEFECTIVE | F-03 |
| Audit-event integrity | DEFECTIVE | F-07 |
| Sensitive information in logs | COMPLETE (code level) | only `HealthCheckView` logs; no request-body logging. Production log shipping UNVERIFIED |
| Production startup safeguards | PARTIAL | secret key only; insecure cookies, missing HSTS and proxy settings are not blocked; no `--deploy` check in CI |

---

## 5. Security findings, ranked

No Critical findings: no authentication bypass, no cross-workspace data
access, no role escalation through the API was found.

### Confirmed findings

| ID | Severity | Summary |
|---|---|---|
| F-01 | High | Login throttle bypassed with a forged `X-Forwarded-For` |
| F-02 | High | No per-account limit; throttle counts successes; per-process memory |
| F-03 | High | Django admin: unthrottled login, can demote the owner without audit |
| F-04 | Medium | A manager can permanently lock the owner's browser out of the workspace |
| F-05 | Medium | Removing a member leaves devices authorised; reinstatement restores them |
| F-06 | Medium | Production can start with insecure cookies and no HSTS |
| F-07 | Medium | Audit events can be rewritten and deleted through querysets |
| F-08 | Medium | Sessions: absolute 14-day lifetime only, no idle timeout, no sign-out-others |
| F-09 | Medium | Sensitive account operations need no re-authentication |
| F-10 | Medium | No database guarantee that a workspace keeps its owner |
| F-11 | Medium | Deactivating the owner's account orphans the workspace |
| F-12 | Low | A GET request creates a workspace device authorisation |
| F-13 | Low | Installations per user are unbounded over time |
| F-14 | Low | `User.phone` is unvalidated and not unique |

#### F-01 Login throttle bypassed with a forged header — High, Confirmed
- **Where:** `apps/accounts/views.py:37-38` (`ScopedRateThrottle`, scope `login`);
  `config/settings.py:134` (`DEFAULT_THROTTLE_RATES`, no `NUM_PROXIES`).
- **What:** with `NUM_PROXIES` unset, DRF identifies the client by the
  `X-Forwarded-For` header whenever it is present. Any client can send a
  different value per request.
- **Harm:** probe S1 made 50 password guesses against one account, each with a
  different header value; none was throttled, and the 51st (correct)
  password succeeded. An attacker can guess passwords of an owner who
  controls payouts at network speed.
- **Fix:** set `NUM_PROXIES` to the real proxy count (0 in development);
  have the reverse proxy overwrite, not append, `X-Forwarded-For`; derive
  the client address in one helper used by the throttle and audit.
- **Test:** forged header values share one budget (429 after the limit);
  with `NUM_PROXIES=1` the right-most proxy-appended address is used.

#### F-02 Throttle design: no per-account limit, counts successes, per process — High, Confirmed
- **Where:** same as F-01; default `LocMemCache` (no `CACHES` setting).
- **What:** one bucket per address, counting every request including correct
  logins and validation errors; nothing per account; counters live in each
  process's memory and reset on restart.
- **Harm:** probe S3: 30 wrong guesses from 30 distinct real addresses
  against one account, none limited (distributed guessing). Probe S2: the
  11th *correct* login from one address in a minute gets 429, so staff
  behind one shop router or one mobile-carrier gateway lock each other out.
- **Fix:** count only failed attempts; separate buckets per normalised
  identifier (phone) and per address, with escalating delay; shared store
  (Django `DatabaseCache` — no new dependency — or Redis); record failures
  as audit events. Keep the generic error message.
- **Test:** failures from many addresses against one account are limited;
  successes do not consume budget; a successful login does not reset another
  address's lock unfairly; limits hold across two processes (shared cache).

#### F-03 Django admin is unthrottled and can strip ownership silently — High, Confirmed
- **Where:** `config/urls.py:16` (always routed, also in production);
  `apps/workspaces/admin.py:26-30` (`WorkspaceMembershipAdmin`, role and
  status editable).
- **What:** (1) probe S7: 40 wrong passwords against a superuser at
  `/admin/login/`, never limited, then success. (2) probe S6: a staff user
  changed the owner membership to `attendant` through the admin form; the
  workspace was left with no owner and no audit event.
- **Mitigation already present:** a session created by the admin login is
  not bound to an installation, so it cannot call the API
  (`test_session_without_an_installation_is_not_accepted_by_the_api`).
- **Harm:** a guessed superuser password gives full database control; an
  honest operator edit can orphan a shop.
- **Fix:** make membership `role`/`status` read-only in the admin (changes
  only through services); throttle admin login with the same mechanism as
  F-02; serve the admin only on an internal hostname or disable it in
  production (`ADMIN_ENABLED`); separate cookie path or name.
- **Test:** admin change form cannot alter role/status; admin login limited;
  `/admin/` not routed when disabled.

#### F-04 A manager can lock the owner out — Medium, Confirmed
- **Where:** `apps/workspaces/device_services.py:64-65`
  (`revoke_workspace_device` allows any device for `devices.manage`);
  `policies.py` grants `devices.manage` to managers.
- **What:** probe S4: a manager revoked the owner's workspace device; the
  owner's browser then receives 403 `device_not_authorized` for that
  workspace. No API restores a revoked workspace device, by design.
- **Harm:** a disgruntled manager can deny the owner access from every
  browser the owner currently uses. The owner recovers only with a new
  installation (another browser or cleared cookies), which most shop owners
  will not know to do.
- **Fix:** an actor may revoke devices only of members whose role ranks below
  their own (owner > manager > attendant/affiliate); the owner's devices only
  by the owner. Add an owner-only re-authorisation action.
- **Test:** manager revoking owner's or another manager's device → 404 and
  unchanged; owner revoking manager's device → 200.

#### F-05 Membership removal does not revoke devices; reinstatement restores them — Medium, Confirmed
- **Where:** `apps/workspaces/services.py:140` (`set_member_status`) does not
  touch `WorkspaceDevice`.
- **What:** probe S5: after removal the member's workspace device stays
  `active`; after reinstatement the same browser regains access silently.
- **Harm:** contradicts the Milestone 2 rules. A browser that was handed in
  or lost during the dispute that led to removal is trusted again on
  reinstatement.
- **Fix:** in the same transaction as removal (and, per decision Q8,
  suspension), revoke the member's workspace devices with reason
  `membership_removed`. Reinstatement leaves them revoked; see Q8 for how a
  reinstated member's browser regains access.
- **Test:** removal revokes all of that member's devices in that workspace
  only; reinstatement leaves them revoked; audit records both.

#### F-06 Production can start with insecure transport settings — Medium, Confirmed
- **Where:** `config/settings.py:96-121`; `backend/.env.example`
  (`DJANGO_SECURE_COOKIES=false`); `.github/workflows/ci.yml` (no `--deploy`).
- **What:** with `DJANGO_DEBUG=false` and `DJANGO_SECURE_COOKIES=false`,
  `manage.py check` reports no issues; `check --deploy` reports W004 (no
  HSTS), W008 (no SSL redirect), W012 and W016 (insecure session and CSRF
  cookies). No Content-Security-Policy is sent.
- **Harm:** copying `.env.example` to a server sends session cookies over
  plain HTTP if any HTTP path exists (hotel and café Wi-Fi are common in the
  target market).
- **Fix:** refuse to start when not debug and cookies are not secure; enable
  HSTS and SSL redirect by default when not debug; CSP at the proxy or in
  middleware; CI job running `check --deploy --fail-level WARNING` with
  production-like variables.
- **Test:** settings import raises for each unsafe combination; CI step fails
  on deploy warnings.

#### F-07 Audit events are mutable — Medium, Confirmed
- **Where:** `apps/audit/models.py:41-47` (protection only on `save()`/`delete()`
  of an instance).
- **What:** probe S8: `AuditEvent.objects.update(...)` rewrote every row and
  `AuditEvent.objects.all().delete()` removed them.
- **Harm:** any code path (or a compromised operator shell) can erase the
  record of a role change or device revocation — and later of payouts.
- **Fix:** PostgreSQL trigger rejecting `UPDATE`/`DELETE` on the audit table
  (reversible `RunSQL` migration), or revoke those privileges from the
  application role. Add login success/failure, logout, password and admin
  events; add client address and request id.
- **Test:** queryset update and delete raise; raw SQL from the application
  role fails; login events are written.

#### F-08 Session lifetime and control — Medium, Confirmed
- **Where:** `config/settings.py:102` (`SESSION_COOKIE_AGE` 14 days);
  `SESSION_SAVE_EVERY_REQUEST` and `SESSION_EXPIRE_AT_BROWSER_CLOSE` both
  `False` (probe S9); no `clearsessions` schedule.
- **What:** a session lasts 14 days from login regardless of inactivity;
  users cannot see or end individual sessions or "sign out everywhere else"
  (probe S15); expired rows accumulate.
- **Harm:** affiliates often share phones; a session left on a borrowed phone
  stays usable for two weeks.
- **Fix:** add `created_at` and `last_activity_at` to `UserSession`; enforce
  idle and absolute limits in `SessionAuthentication`; endpoints to list and
  end sessions and to end all others; scheduled purge.
- **Test:** idle and absolute expiry with frozen time; listing shows only own
  sessions; "end others" keeps the current one.

#### F-09 No re-authentication for sensitive operations — Medium, Confirmed
- **Where:** `apps/accounts/views.py:88-98` (`InstallationRevokeView`);
  future password change, ownership transfer, role changes.
- **What:** probe S12: a second session (for example one stolen from an
  unlocked phone) revoked the legitimate user's other browser, signing the
  real user out while the attacker stayed signed in.
- **Harm:** account takeover persistence; the victim is evicted first.
- **Fix:** a recent-authentication window stored in the session
  (`reauthenticated_at`), required for password change, revoking other
  installations or sessions, ownership transfer and role changes; a
  `POST /auth/reauthenticate/` endpoint.
- **Test:** each sensitive endpoint returns 403 `reauthentication_required`
  outside the window and succeeds inside it.

#### F-10 No database guarantee that a workspace keeps an owner — Medium, Confirmed
- **Where:** `apps/workspaces/models.py` constraints
  `membership_single_owner_per_workspace`, `membership_owner_must_be_active`
  (at most one, never "at least one").
- **What:** the owner row can be demoted or deleted outside the services
  (probe S6 through the admin).
- **Fix:** close the admin path (F-03); a deferred constraint trigger checking
  that each active workspace has exactly one active owner at commit.
  Revisit if co-owners are approved (Q5).
- **Test:** demoting or deleting the owner row directly fails at commit;
  transfer still succeeds.

#### F-11 Deactivating the owner's account orphans the workspace — Medium, Confirmed
- **Where:** `User.is_active` is independent of ownership; no service guards it.
- **What:** probe S11: owner deactivated; membership remains `owner/active`;
  nobody can manage members.
- **Fix:** an account-suspension service that refuses (or requires transfer)
  when the user owns an active workspace; audit it.
- **Test:** suspending a sole owner is refused with a clear error.

#### F-12 GET creates a device authorisation — Low, Confirmed
- **Where:** `apps/workspaces/access.py:45` → `ensure_workspace_device`.
- **What:** probe S13: the first GET to a workspace creates a
  `WorkspaceDevice` row and an audit event.
- **Harm:** a state change on a safe method; a cross-site top-level link can
  trigger it (only for the victim's own browser and own membership, so no
  privilege is gained). Mainly audit noise.
- **Fix:** acceptable to keep; document it, or create authorisations only on
  workspace selection (a POST).
- **Test:** if changed: GET without a prior authorisation returns 403 with a
  code the SPA turns into a selection POST.

#### F-13 Installations per user unbounded over time — Low, Confirmed
- **Where:** `bind_session_to_installation` (`installations.py:46`).
- **What:** each login without a recognised cookie creates a row; probe S14
  showed the login throttle caps this at 10 per minute per address (and
  F-01 lifts that cap).
- **Fix:** cap active installations per user (oldest revoked or refused),
  periodic cleanup of unused ones (O-022).

#### F-14 `User.phone` unvalidated and not unique — Low now, blocker for Milestone 2
- **Where:** `apps/accounts/models.py:52`.
- **What:** probe S10: `"677 12 34 56"` stored as typed; two users can hold
  the same number.
- **Fix:** see section 7 (E.164 normalisation, unique constraint).

### Risks requiring a decision or further verification

| ID | Risk | Status |
|---|---|---|
| R-01 | **Unverified phone as identifier and invitation target.** If phone numbers are unique but unverified, anyone can register someone else's number first (squatting, blocking the real person), and an invitation "for" a phone number would be accepted by whoever registered that number. "Only the intended account can accept" is not achievable with an unverified phone alone | Design risk; needs Q1 |
| R-02 | Password reset without a verified channel is either impossible or an account-takeover vector | Design risk; needs Q2 |
| R-03 | Login timing differences between unknown and known accounts | Unverified; Django mitigates, not measured |
| R-04 | Behaviour behind the real production proxy (address and TLS headers) | Unverified; no deployment exists |
| R-05 | `ensure_workspace_device` runs on every request: one extra query per request | Not a security issue; measure under load |

---

## 6. API and frontend journey assessment

| # | Journey | Backend | Frontend | Status | Missing |
|---|---|---|---|---|---|
| 1 | Owner registration | `register_user` service; CLI only | none | MISSING | `POST /auth/register/`, registration screen |
| 2 | Login | `POST /auth/login/` (email) | `LoginPage` | COMPLETE (email) | switch to phone, throttle fixes |
| 3 | Logout | `POST /auth/logout/` | shell and chooser | COMPLETE | — |
| 4 | Password reset | none | none | MISSING | request/confirm endpoints, channel (Q2), screens |
| 5 | Workspace creation | `create_workspace` service; CLI only | none | MISSING | `POST /workspaces/`, screen |
| 6 | Workspace selection | `GET /workspaces/`, `PUT /workspaces/current/` | `WorkspaceSelectPage`, `/w/<id>` | COMPLETE | — |
| 7 | Invitation creation | none | none | MISSING | model, service, endpoints, screen |
| 8 | Invitation acceptance | none | none | MISSING | token flow, register-or-login then accept, screen |
| 9 | Member management | list + PATCH status | none | PARTIAL | screen; manager rights; device revocation on removal |
| 10 | Role assignment | PATCH role (owner only) | none | PARTIAL | screen; re-authentication |
| 11 | Session management | installations list/revoke | none | PARTIAL | session list, end session, end others, screen |
| 12 | Device management | workspace devices list/revoke | none | PARTIAL | hierarchy rule (F-04), re-authorise, screen |

### Missing API operations (proposed; none exist today)

| Method | Path | Capability or rule |
|---|---|---|
| POST | `/api/v1/auth/register/` | public, throttled |
| POST | `/api/v1/auth/password/change/` | session + re-auth |
| POST | `/api/v1/auth/password/reset/` and `/reset/confirm/` | public, throttled; channel per Q2 |
| POST | `/api/v1/auth/reauthenticate/` | session |
| GET | `/api/v1/auth/sessions/` | session (own only) |
| POST | `/api/v1/auth/sessions/{id}/end/` | session + re-auth for non-current |
| POST | `/api/v1/auth/sessions/end-others/` | session + re-auth |
| POST | `/api/v1/workspaces/` | session; policy per Q4 |
| PATCH | `/api/v1/workspaces/{ws}/` | `workspace.update` |
| GET, POST | `/api/v1/workspaces/{ws}/invitations/` | `members.invite` |
| POST | `/api/v1/workspaces/{ws}/invitations/{id}/revoke/` | `members.invite` |
| GET | `/api/v1/invitations/{token}/` | public preview, throttled, minimal data |
| POST | `/api/v1/invitations/{token}/accept/` | session; intended-user rule (Q1) |
| POST | `/api/v1/workspaces/{ws}/members/{id}/suspend/`, `/remove/`, `/reinstate/` | `members.suspend`, `members.remove` |
| POST | `/api/v1/workspaces/{ws}/members/{id}/role/` | `members.change_role` + re-auth |
| POST | `/api/v1/workspaces/{ws}/devices/{id}/reauthorize/` | owner (Q8) |
| GET | `/api/v1/workspaces/{ws}/audit/` | `audit.view` |

Splitting the current `PATCH members/{id}` into explicit actions lets each
action carry its own capability; the existing PATCH would be removed in the
same phase (it has no frontend consumer today).

### Missing frontend screens

Registration; password change; password reset (request and confirm);
re-authentication prompt; create workspace; members list with
suspend/remove/reinstate/role; invite member and pending invitations;
accept invitation (signed-out and signed-in paths); my sessions and
browsers; workspace devices; workspace settings; audit log (if Q-scope).

---

## 7. Required data-model changes

Existing models serve most target entities; only `WorkspaceInvitation` is new.

| Entity | Exists | Change |
|---|---|---|
| `User` (`accounts`) | yes | `phone` → E.164-normalised, unique, `USERNAME_FIELD`; `email` optional (nullable, unique when present, per Q3); `phone_verified_at` nullable (never set without real verification); keep UUID key |
| `Workspace` | yes | none required; `workspace.update` edits name only |
| `WorkspaceMembership` | yes | keep statuses active/suspended/removed; record `status_changed_at`/`by` or rely on audit. **Recommend not** adding an `invited` membership row (an invitee may have no account, and membership requires a user); represent "Invited" by a pending `WorkspaceInvitation` — see Q7 |
| `WorkspaceInvitation` | **new** (`workspaces`) | `workspace` FK, `phone` (E.164), `role` (check: not owner), `token_hash` (store a hash, never the token), `invited_by` FK, `status` (pending/accepted/revoked/expired), `expires_at`, `accepted_by`/`accepted_at`, `revoked_by`/`revoked_at`; partial unique: one pending invitation per workspace and phone; check constraints for status/timestamp consistency |
| `DeviceInstallation` | yes | optional cap (F-13) |
| `WorkspaceDevice` | yes | add `revocation_reason` (manual / membership_removed / membership_suspended) so reinstatement and audit can tell them apart |
| `UserSession` | yes | add `created_at`, `last_activity_at` (idle/absolute expiry, listing); optional coarse `ip_prefix` for display (privacy decision) |
| `AuditEvent` | yes | DB trigger against UPDATE/DELETE; add `ip`, `request_id`; new actions for auth events |
| Throttle state | n/a | Django `DatabaseCache` table (`createcachetable`) — no new dependency |

### Relationships and lifecycle rules

- `User` 1—N `WorkspaceMembership` N—1 `Workspace`; exactly one owner
  membership per active workspace (or "at least one" if Q5 allows co-owners).
- `User` 1—N `DeviceInstallation` 1—N `UserSession`;
  `DeviceInstallation` 1—N `WorkspaceDevice` N—1 `Workspace`.
- `WorkspaceInvitation` N—1 `Workspace`; on acceptance creates (or, for a
  removed member, reactivates per Q8) one `WorkspaceMembership` in the same
  transaction, locked against concurrent acceptance and revocation.
- Membership `active → suspended → active`, `active|suspended → removed`,
  `removed → active` only via a new invitation or explicit reinstatement
  (Q8). Removal revokes workspace devices; reinstatement does not restore them.
- A device identifier is a server-issued browser identifier, **not**
  cryptographic proof of a physical device, and documentation must keep
  saying so.

### Migration notes

- Phone as identifier is the riskiest migration: existing users have no phone
  (the dev database and seed data are email-based). Plan: add nullable
  normalised `phone`, backfill or require on next login, then make it
  required and the login field. Reversible in steps.
- `UserSession` new columns are nullable; existing rows expire normally.
- Audit trigger: `RunSQL` with reverse.
- Throttle cache table: `createcachetable` in deploy steps and CI.

---

## 8. Prioritised Milestone 2 roadmap

Sequence kept as proposed, with one change: **phone-identity data model work
moves to the start of M2.2** because registration, reset and invitations all
depend on it, and it needs Q1 to Q3 answered.

### M2.0 Repository assessment and threat model
- **Objective:** this document; threat model per journey.
- **Deliverable:** approved findings, decisions Q1–Q12 answered.
- **Acceptance:** engineering and product sign-off.

### M2.1 Login abuse protection and production hardening
- **Objective:** close F-01, F-02, F-03, F-06, F-07.
- **Files:** `config/settings.py`, `apps/accounts/views.py` (`LoginView`),
  new `apps/accounts/throttling.py` (failure-based, per-identifier and per-address),
  `apps/common/` client-address helper, `apps/workspaces/admin.py`,
  `config/urls.py`, `apps/audit/` (trigger migration, auth event receivers),
  `.env.example`, `ci.yml`.
- **Migrations:** audit trigger (`RunSQL`, reversible); cache table.
- **Tests:** forged-header bucket sharing; distributed guessing per account;
  successes not counted; shared store across two clients; admin form
  read-only fields; admin login limit; settings refusal per unsafe combo;
  audit update/delete refused; login events recorded.
- **Browser:** login lock message after N failures, then recovery after the window.
- **Acceptance:** all above pass; `check --deploy --fail-level WARNING` clean in CI.
- **Risks:** locking out a whole shop behind one address → per-identifier
  limits must be the primary control, per-address secondary and generous.

### M2.2 Identity: phone login, registration, passwords, session lifecycle
- **Depends on:** M2.1, Q1–Q3.
- **Objective:** phone-based accounts; registration; password change and
  reset; idle/absolute expiry; session listing and ending; re-authentication.
- **Files:** `apps/accounts/models.py`, `services.py`, `serializers.py`,
  `views.py`, `urls.py`, `authentication.py` (expiry checks),
  `session_store.py` (activity columns), new `apps/accounts/phone.py`
  (normalisation), `create_workspace`/`add_member` commands, `e2e_seed.py`,
  `frontend/src/pages/LoginPage.tsx`, new registration/password/sessions pages.
- **New:** reset token mechanism (Django `PasswordResetTokenGenerator` is
  suitable once a delivery channel exists).
- **Migrations:** phone fields (staged, reversible), session columns.
- **Tests:** normalisation table (local, +237, spaces, invalid); uniqueness
  after normalisation; registration abuse throttled; password change ends
  other sessions and requires re-auth; reset token single-use and expiring;
  idle/absolute expiry with frozen time; list/end/end-others own sessions only.
- **Browser:** register → land in chooser; change password; end another session.
- **Risks:** R-01, R-02; data migration for existing email users.

### M2.3 Workspace creation and settings
- **Depends on:** M2.2.
- **Objective:** self-service workspace creation (policy Q4); rename.
- **Files:** `apps/workspaces/views.py`, `serializers.py`, `urls.py`,
  `policies.py` (`workspace.update`), `tests/isolation.py` (new route),
  frontend create-workspace screen.
- **Migrations:** none expected.
- **Tests:** atomicity under failure injection; creator is sole owner;
  creation throttle; rename requires `workspace.update`; isolation contract entry.
- **Browser:** register → create workspace → land in `/w/<id>`.

### M2.4 Invitations and membership lifecycle
- **Depends on:** M2.2 (phone identity), M2.3, Q1, Q6–Q8.
- **Objective:** invite by phone, expiry, revocation, acceptance; suspend,
  remove, reinstate with device revocation (F-05); last-owner protection
  (F-10, F-11).
- **Files:** `apps/workspaces/models.py` (`WorkspaceInvitation`),
  new `apps/workspaces/invitations.py` (services), `services.py`
  (`set_member_status` split into suspend/remove/reinstate),
  `device_services.py`, views/urls/serializers, `tests/isolation.py`.
- **Migrations:** invitation table; `WorkspaceDevice.revocation_reason`;
  owner-presence trigger.
- **Tests:** token stored hashed; expired/revoked/accepted tokens refused;
  wrong account refused; concurrent accept vs revoke (one wins);
  concurrent double-accept; cannot invite to owner; managers limited per Q6;
  removal revokes devices in that workspace only; reinstatement keeps them
  revoked; sole-owner suspension refused; isolation contract for every new route.
- **Browser:** owner invites; invitee registers and accepts; owner removes;
  removed member's browser refused; reinstated member flow per Q8.
- **Risks:** R-01; token leakage through link sharing (short expiry, single use).

### M2.5 Capability vocabulary and device lifecycle
- **Depends on:** M2.4.
- **Objective:** move to `workspace.view`, `workspace.update`,
  `members.invite`, `members.suspend`, `members.remove`,
  `members.change_role`, `devices.view`, `devices.revoke`, `audit.view`;
  role-rank rule for acting on other members and their devices (F-04);
  owner re-authorisation of devices; audit view.
- **Files:** `apps/workspaces/policies.py`, every view's
  `required_capability`, `device_services.py`, `tests/test_workspace_access.py`
  role matrix, frontend capability-driven UI.
- **Migrations:** none (capabilities are code).
- **Tests:** full role × capability × target-rank matrix; manager cannot
  touch owner or managers; affiliate sees only own devices; `test_every_role_has_a_policy...` updated.
- **Note:** M2.4 can introduce `members.invite/suspend/remove` early; M2.5
  completes the set. Ordering M2.5 after M2.4 matches the brief but the
  capability names should be fixed in M2.4 to avoid renaming twice.

### M2.6 Frontend journeys and integration tests
- **Objective:** screens for journeys 1, 4, 5, 7–12; capability-aware
  navigation (UX only); error states for 403/409/429/re-auth.
- **Files:** `frontend/src/pages/*`, `api/endpoints.ts`, `api/types.ts`,
  `components/AppShell.tsx`, `e2e/*`.
- **Tests:** Vitest per screen (validation, error mapping); Playwright for
  every journey including negative paths.

### M2.7 Security review and release verification
- **Objective:** independent review; re-run probes S1–S17 as regression
  tests; `check --deploy` clean; dependency audit (`pip-audit`, `npm audit`);
  staging deployment behind the real proxy (resolves R-04).
- **Acceptance:** no open High findings; release blockers below closed.

### Mandatory release blockers vs deferrable

| Blocker for Milestone 2 release | Can wait |
|---|---|
| F-01, F-02 login abuse | F-12 GET side effect |
| F-03 admin exposure | F-13 installation cap |
| F-04 manager vs owner devices | Audit-log screen (if Q scope says later) |
| F-05 device revocation on removal | IP display in session list |
| F-06 production startup safeguards | Load testing of per-request device check |
| F-07 audit integrity | |
| F-08 idle/absolute expiry and sign-out-others | |
| F-09 re-authentication | |
| F-10, F-11 owner integrity | |
| Phone identity with Q1 decided (R-01) | |
| Invitation flow with intended-user rule | |
| Password reset with Q2 decided (R-02) | |

---

## 9. Testing strategy

Keep the existing layers; extend them rather than adding frameworks.

| Layer | Tool | Rule for Milestone 2 |
|---|---|---|
| Domain services | pytest on PostgreSQL | every service: success, each refusal, stale-actor, audit event written |
| Isolation | `tests/isolation.py` registry + `test_isolation.py` | every new workspace route added; contract runs automatically |
| Structure | `test_architecture.py`, system checks | new service modules added to `DOMAIN_MODULES`; public routes list changes reviewed |
| Concurrency | `test_concurrency.py` (`transaction=True`, threads) | invitation accept vs revoke, double accept, concurrent removal of last owner, concurrent role change |
| Security regression | new `tests/test_security_regressions.py` | one test per finding F-01…F-11, named after the finding |
| Migrations | `test_migrations.py` pattern | phone migration forward and back; audit trigger forward and back |
| Settings | new tests importing settings with env overrides | production refusal rules |
| Frontend unit | Vitest + Testing Library | forms, error-code mapping (403, 409, 429, `reauthentication_required`) |
| Browser | Playwright against real stack, seeded `_e2e` database | every journey in section 6 including a negative path |
| CI | GitHub Actions | add `check --deploy` job, `createcachetable`, `pip-audit`/`npm audit` (non-blocking first) |

Tests must assert the boundary (status code **and** unchanged database
state **and** audit record), not only a 200.

---

## 10. Release blockers (Milestone 2)

1. F-01 and F-02: login throttling fixed and shared across processes.
2. F-03: admin cannot change membership role/status; admin login throttled
   and not publicly exposed in production.
3. F-04: role-rank rule for revoking devices.
4. F-05: removal revokes workspace devices; reinstatement does not restore.
5. F-06: unsafe production settings refused; `check --deploy` clean in CI.
6. F-07: audit rows immutable at the database level; auth events recorded.
7. F-08 and F-09: idle and absolute expiry; sign-out-others; re-auth.
8. F-10 and F-11: ownership cannot be lost by any path.
9. Phone identity implemented according to Q1, with R-01 explicitly accepted
   or mitigated.
10. Invitation acceptance restricted to the intended account per Q1.
11. Password reset per Q2 (or explicitly descoped with an operator procedure).
12. All required journeys have backend tests and a browser test.

---

## 11. Questions requiring product-owner decisions

| # | Question | Why it matters | Proposed safe default |
|---|---|---|---|
| Q1 | Will phone numbers be verified (SMS/WhatsApp one-time code) in Milestone 2? | Without verification, unique phones allow squatting and invitation hijack (R-01) | Invitations carry a single-use secret link sent by the owner over WhatsApp; acceptance requires the link **and** a phone match. Treat phone as unverified everywhere; plan verification as a separate feature |
| Q2 | How do users reset a forgotten password? | Needs a verified channel (R-02) | Owner-assisted or operator-assisted reset with a one-time reset link, audited, until phone verification exists |
| Q3 | Is email kept, optional, or dropped? | Login field, reset channel, data migration | Optional and unique when present; not a login identifier |
| Q4 | Can anyone register and create workspaces, or only approved merchants? | Abuse, support load | Anyone may register; creating a workspace is open but throttled; operator can suspend workspaces |
| Q5 | Exactly one owner, or co-owners allowed? | Target text says "last active owner"; current DB enforces exactly one | Keep exactly one owner in Milestone 2 (simpler integrity); revisit later |
| Q6 | What may managers do: invite, suspend, remove — which roles? | Privilege boundaries | Managers invite, suspend, remove and change roles only of attendants and affiliates; never managers or the owner |
| Q7 | Is "Invited" a membership state, or an invitation state? | Membership needs a user; invitees may not have an account | Invitation state only; membership row created on acceptance |
| Q8 | How does a reinstated member's browser regain access, given revoked devices must not be silently restored? | Today a revoked workspace device is final for that installation | Owner explicitly re-authorises a device (new action), or the member signs in on a fresh installation; audited either way |
| Q9 | Suspension: should it also revoke devices, or only block access? | Suspension is meant to be temporary | Block access only; devices revoked on removal |
| Q10 | Session limits | Shared phones vs convenience | Idle 3 days, absolute 14 days; re-auth window 10 minutes |
| Q11 | Should the Django admin be available in production? | Highest-privilege surface | Disabled by default; enabled only on an internal host |
| Q12 | Is there any real user data yet? | Determines how careful the phone migration must be | Assume none (pilot not started); confirm |

---

## 12. Final recommendation

**GO**, phased:

- **M2.1 can start immediately.** It fixes confirmed High findings and does
  not depend on any open product decision.
- **M2.2 to M2.6 start once Q1 to Q6 are answered** (Q7 to Q12 can be
  answered during M2.2). Q1 and Q2 decide the shape of the user model and the
  invitation design; building them before the decisions risks a second
  identity migration.
- No Milestone 2 feature should be released while any item in section 10
  remains open.

### Probe file

The 18 assessment probes are in
`/tmp/claude-0/-home-user-merchantflow/550de802-49bd-5b40-8fd2-3ecf53545345/scratchpad/m2probe/test_m2_probes.py`
(outside the repository, not committed). In M2.1 and later phases each
confirmed probe becomes a regression test asserting the corrected behaviour.

---

## Status after M2.1 (security hardening)

Appended after implementation; the assessment above is unchanged.

| Finding | Status | Regression tests |
|---|---|---|
| F-01 Forged `X-Forwarded-For` bypass | **Resolved** | `test_login_protection.py::test_forged_forwarded_header_does_not_buy_more_attempts`, `::test_client_ip_trusts_only_the_configured_proxies`, `::test_behind_one_trusted_proxy_the_appended_address_is_limited` |
| F-02 Per-account limit, successes counted, per-process store | **Resolved** | `::test_distributed_guessing_against_one_account_is_limited`, `::test_correct_logins_never_consume_the_allowance`, `::test_people_sharing_a_shop_network_do_not_block_each_other`, `::test_concurrent_guesses_cannot_exceed_the_limit`, `::test_the_limit_is_shared_between_separate_processes`; `e2e/auth.spec.ts` lock-out |
| F-03 Admin exposure and membership edits | **Resolved** | `test_admin.py` (16 tests) |
| F-04 Manager can lock out the owner | **Resolved** | `test_device_lifecycle.py::test_manager_cannot_revoke_the_owners_device` and rank tests |
| F-05 Removal and reinstatement vs devices | **Resolved** | `test_device_lifecycle.py::test_removal_revokes_*`, `::test_reinstatement_does_not_restore_device_access`, `::test_first_entry_cannot_slip_in_while_the_member_is_being_removed` |
| F-06 Unsafe production settings | **Resolved** | `test_production_settings.py` (23 tests, incl. real start-up in a separate process); CI deploy-check step |
| F-07 Mutable audit records | **Resolved** (against every application code path; against the table owner only with the role split in DEPLOYMENT.md) | `test_audit_integrity.py` |
| F-08 Session lifetime and control | **Planned for M2.2** | — |
| F-09 Re-authentication | **Planned for M2.2** | — |
| F-10 No database guarantee of an owner | **Resolved** | `test_owner_integrity.py` |
| F-11 Owner deactivation orphans workspace | **Resolved** | `test_owner_integrity.py`, `test_admin.py::test_admin_refuses_to_deactivate_a_workspace_owner` |
| F-12, F-13, F-14 | Out of M2.1 scope, unchanged | — |
