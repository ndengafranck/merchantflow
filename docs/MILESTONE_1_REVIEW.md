# Milestone 1 architecture review

Reviewed commit: `67f8586` (Milestones 0 and 1). Review date: 2026-11-16.
No application code was changed during this review.

## Verdict

**GO for Milestone 2, conditional on five small corrections (R1 to R5 below).**

- No Critical findings. No cross-workspace data leak or authentication bypass
  was found, by inspection or by test.
- Two High findings. Neither blocks Milestone 2; both block a pilot with real
  users (H-01 also blocks any synchronisation work).
- Four findings block Milestone 2. All are guardrails that are cheap now and
  expensive after Milestone 2 has copied the current patterns into many more
  endpoints and screens.

**Independence caveat.** This review was performed by the same engineer who
wrote the code. The probes below were written to try to break the stated
properties, but a second reviewer would still add value before a pilot.

## Method

1. Read every backend module, the frontend source, configuration and tests.
2. Re-ran the existing suites.
3. Wrote 21 additional probes for properties the existing tests do not cover,
   including three real-concurrency probes with committed transactions on
   PostgreSQL. They are preserved in `docs/review/` and are not collected by
   the normal test run.
4. Probed the production build in Chromium for manifest validity,
   installability and offline behaviour.

### Results of what was run

| Run | Result |
|---|---|
| `backend`: `pytest` (PostgreSQL 16.15) | 97 passed (76 test functions, parametrised) |
| `backend`: `ruff check` | Clean |
| `frontend`: `npm test` | 16 passed |
| `frontend`: lint, typecheck, production build | Clean |
| Review probes `docs/review/milestone_1_probes.py` | 21 passed; each asserts the behaviour observed, including the defects |
| PWA probe `docs/review/pwa_probe.cjs` | See section 6 |

To re-run the probes:

```bash
cd backend && DJANGO_SETTINGS_MODULE=config.settings .venv/bin/python -m pytest -c pyproject.toml --rootdir ../docs/review -o testpaths= -p no:cacheprovider -q ../docs/review/milestone_1_probes.py
```

### Not verified

- Real Android, iOS, macOS or Windows devices. Only desktop Chromium, headless.
- Docker Compose (no daemon in the build environment) and the CI workflow
  (no remote repository). Both remain unexecuted.
- Behaviour behind a real reverse proxy with TLS.
- Timing side channels on login, load behaviour, and dependency vulnerabilities.
- The browser end-to-end run from the milestone build was not repeated; its
  script was never added to the repository (see T-01).

## Properties verified

"Verified" here means inspected and exercised by a test or probe.

| Property | Evidence |
|---|---|
| All 10 non-public API routes answer 401 to anonymous GET, POST, PUT, PATCH and DELETE | Probe P10 |
| All 6 routes under `/workspaces/<id>/` use `WorkspaceAPIView`, `WorkspaceAccess` and declare a capability | Probe P10 |
| Non-member gets 404, identical to an unknown workspace | `test_workspace_access.py` |
| Changing the workspace id in the URL, or pairing an own workspace id with a foreign record id, finds nothing | `test_workspace_access.py`, `test_devices.py` |
| Suspended and removed memberships are refused on every endpoint; suspended workspace is closed | `test_workspace_access.py` |
| An endpoint with no declared capability raises instead of serving | `test_workspace_view_without_declared_capability_fails_closed` |
| A Django superuser has no implicit workspace access through the API | Probe P09 |
| Login and authenticated writes are refused without a valid CSRF token; cross-origin writes are refused | `test_csrf.py` (CSRF checks on) |
| A session identifier planted before login is discarded at login; logout deletes the server session; a replayed cookie is refused | Probe P08 |
| A password change ends the user's other sessions; deactivating a user ends theirs | Probe P07, `test_accounts.py` |
| Three concurrent ownership transfers leave exactly one owner, in 5 of 5 rounds | Probe P17 |
| Six concurrent revocations of one device produce one audit event | Probe P19 |
| Malformed JSON, wrong content type and wrong body shape give 400 or 415, not 500 | Probe P13 |

---

## Findings

Severity scale: Critical (exploitable data exposure or integrity loss now),
High (serious weakness in a stated security property), Medium (should be
fixed before real users or before the pattern spreads), Low (hygiene).

### 1. Multi-tenancy and authorization

No IDOR or cross-workspace leak found. The findings are about how the
protection is kept in place as the codebase grows.

#### A-01 The workspace guard is enforced by convention, not by structure
- **Severity:** Medium. **Blocks Milestone 2: yes.**
- **Location:** `backend/apps/workspaces/access.py:62-71`;
  `backend/apps/devices/views.py:57`; every handler in
  `backend/apps/workspaces/views.py` and `backend/apps/devices/views.py`.
- **Problem:** Three things rely on each developer remembering them.
  (1) A subclass that sets `permission_classes` replaces the list, as
  `SyncHandshakeView` already does; omitting `WorkspaceAccess` would silently
  remove tenant checks. (2) A view under `/workspaces/<id>/` could extend plain
  `APIView`. (3) Every query is scoped by hand with
  `filter(workspace=request.workspace)`.
- **Why it matters:** Milestone 2 adds many endpoints, one of which carries a
  field affiliates must never see (cost price). One forgotten filter is a
  cross-tenant leak, and nothing would fail.
- **Correction:** Resolve membership and capability in
  `WorkspaceAPIView.initial()` (or make `get_permissions()` prepend the two
  mandatory classes) so subclasses can only add checks. Add probe P10 to the
  suite as a permanent test that walks the URL configuration. Give
  workspace-owned models a common abstract base with a required
  `for_workspace()` queryset method, and add a shared test helper that every
  new endpoint must pass (non-member 404, foreign record id 404).

#### A-02 Services authorise from a caller-supplied, possibly stale membership
- **Severity:** Medium. **Blocks Milestone 2: yes.**
- **Location:** `backend/apps/workspaces/services.py:43-45`, `:56`;
  `backend/apps/devices/services.py:14-16`, `:33-41`;
  `backend/apps/workspaces/policies.py:10`, `:41-43`;
  `backend/apps/workspaces/context.py:10`, `:31`.
- **Problem:** `require_capability(actor, …)` trusts the role on the Python
  object passed in. Probe P16 shows a membership object loaded before an
  ownership transfer still performs owner-only operations afterwards. Over
  HTTP the window is one request, but offline replay and imports will hold
  actors for longer. Separately, the policy and context modules raise and
  catch Django REST Framework exceptions, so the business layer depends on
  the HTTP layer.
- **Why it matters:** Every Milestone 2 to 4 service will copy this pattern,
  including the financial ones.
- **Correction:** Inside each service transaction, re-read the actor's
  membership (`select_for_update(of=("self",))` or `FOR SHARE`) and check
  status and capability on the fresh row. Raise a domain
  `NotPermittedError` from `apps.common.exceptions` and map it to 403 in the
  exception handler.

#### A-03 Minor scoping and disclosure issues
- **Severity:** Low. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/workspaces/views.py:91`;
  `backend/apps/devices/views.py:45` with `devices/services.py:33-45`;
  `backend/apps/workspaces/access.py:50-59`.
- **Problem:** (1) The final re-read in `MemberDetailView` is by primary key
  only; it is safe today because line 78 scoped it, but it is the habit A-01
  warns about. (2) Revoking a device answers 404 for an unknown id and 403 for
  another member's device, so a member can confirm a device id exists in
  their workspace. Ids are random UUIDs, so this is not practically
  exploitable. (3) A `required_capability` mapping that omits a method raises
  a 500; the mapping form is unused and untested.
- **Correction:** Scope the re-read; return 404 in both revoke cases for
  non-managers; return 405 for unmapped methods and add a test.

#### A-04 The SPA does not carry the workspace in its URL
- **Severity:** Medium. **Blocks Milestone 2: yes.**
- **Location:** `frontend/src/App.tsx:45-68`;
  `frontend/src/session/SessionProvider.tsx:21-25`, `:70-77`;
  `backend/apps/workspaces/context.py:18-33`.
- **Problem:** The selected workspace lives in the server session, which all
  tabs of a browser share. Choosing workspace B in one tab changes what
  another tab shows after a reload. Screens cannot be bookmarked or shared,
  and the browser's back button does not cross a workspace switch.
- **Why it matters:** A person who owns one shop and is an affiliate of
  another is an approved use case. Once Milestone 2 has forms, the wrong-tab
  case means records entered into the wrong shop. API calls are correctly
  scoped, so this is a data-entry risk, not a leak.
- **Correction:** Route as `/w/<workspace-id>/…` and derive the active
  workspace from the URL. Keep the session value only as "last used" for the
  post-login redirect.

### 2. Authentication

Session creation, rotation, logout and CSRF behave as designed (see table
above). The weaknesses are around rate limiting, lifetime and deployment.

#### H-02 Login rate limiting is bypassable and mis-keyed
- **Severity:** High. **Blocks Milestone 2: no. Blocks a pilot: yes.**
- **Location:** `backend/apps/accounts/views.py:36-37`;
  `backend/config/settings.py:129` (no `NUM_PROXIES`, no `CACHES`).
- **Problem:**
  1. *Bypass.* The throttle identifies clients by the `X-Forwarded-For`
     header when present. Probe P01 sent 40 failed logins, each with a
     different header value, and none was limited.
  2. *Wrong key.* The limit is per IP address and counts successful logins.
     Probe P02: the eleventh correct login from one address in a minute gets
     429. Mobile carriers commonly put many subscribers behind one address,
     so legitimate users can lock each other out while an attacker rotating
     addresses is unaffected.
  3. *No per-account limit.* Nothing slows guessing against one account from
     many addresses.
  4. *Per process.* Counters are in each process's memory and reset on restart.
- **Why it matters:** Password guessing is the main realistic attack on a
  password-only system, and accounts will control commission payouts.
- **Correction:** Set `NUM_PROXIES` to match the deployment and have the
  proxy overwrite `X-Forwarded-For`. Count failed attempts only, keyed by
  account and by address separately, with increasing delay. Use a shared cache
  (database or Redis). Record failed logins (see D-03).

#### S-01 The Django admin is exposed on the application origin
- **Severity:** Medium. **Blocks Milestone 2: no. Blocks a pilot: yes.**
- **Location:** `backend/config/urls.py:16`;
  `backend/apps/workspaces/admin.py:26-30`.
- **Problem:** (1) `/admin/login/` has no rate limit: probe P11 made 40 wrong
  guesses against a superuser and then logged in. (2) The admin shares the
  SPA's session cookie, so any script-injection flaw in the SPA would act
  with a logged-in operator's superuser rights. (3) Membership rows are
  editable in the admin, bypassing the services and the audit trail; probe
  P03c used it to demote an owner, leaving a workspace with no owner and no
  audit event.
- **Correction:** Serve the admin on a separate hostname or behind network
  restrictions, with its own cookie name, rate limiting and a second factor.
  Make membership `role` and `status` read-only in the admin.

#### S-02 Session lifetime and revocation
- **Severity:** Medium. **Blocks Milestone 2: no.**
- **Location:** `backend/config/settings.py:101`.
- **Problem:** Sessions last a fixed 14 days with no idle timeout. Sessions
  are opaque rows, so there is no way to list a user's sessions, sign them
  out everywhere, or end the sessions of a removed member (their access is
  correctly refused per request, but the login persists). Expired rows are
  never purged because `clearsessions` is not scheduled. There is no
  re-authentication step for sensitive actions.
- **Correction:** Replace the session model with one that records user and
  device (Django's `AbstractBaseSession`), which also resolves H-01. Add an
  idle timeout, "sign out everywhere", a scheduled purge, and password
  confirmation for payouts and ownership transfer when those exist.
  Cheapest before a pilot, because changing the session backend signs
  everyone out. Related open decision: O-005.

#### S-03 Insecure cookie settings can be deployed without warning
- **Severity:** Medium. **Blocks Milestone 2: no. Blocks deployment: yes.**
- **Location:** `backend/config/settings.py:96-105`, `:114-116`.
- **Problem:** With `DJANGO_DEBUG=false` and `DJANGO_SECURE_COOKIES=false`
  (the value in `.env.example`) the application starts normally; only
  `manage.py check --deploy` warns. HSTS is set only when
  `DJANGO_BEHIND_TLS_PROXY` is on. No Content-Security-Policy is sent. Cookie
  names do not use the `__Host-` prefix.
- **Correction:** Refuse to start when debug is off and cookies are not
  secure. Run `check --deploy --fail-level WARNING` in CI with production-like
  variables. Add a CSP at the proxy or with middleware.

#### S-04 Account model details
- **Severity:** Low. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/accounts/models.py:49-51`, `:21`;
  `backend/apps/accounts/services.py`; `backend/apps/workspaces/services.py:55-66`.
- **Problem:** `phone` has no format validation. The password policy is
  applied by `register_user` but not by `User.objects.create_user`.
  `add_member` accepts a deactivated user. There is no password reset (O-007).
- **Correction:** Validate phone format when O-001 is decided; apply password
  validation in the manager or forbid direct use; reject inactive users.

#### Implications of users with several workspaces

Verified: capabilities are computed per membership, so being an owner in one
workspace grants nothing in another (`test_user_with_several_workspaces_has_a_role_in_each`).
Consequences the design must keep respecting:

1. **Accounts are global, memberships are local.** A workspace owner must
   never be able to edit, deactivate or reset the password of a user account,
   only their membership. The onboarding API in Milestone 2 must hold to this.
2. **Adding a member by email reveals whether an account exists** on the
   platform. The invitation flow should answer identically either way.
3. **One session covers all of a user's workspaces.** A stolen session
   exposes all of them, and session policy cannot differ per workspace
   without the session model change in S-02.
4. **Wrong-workspace data entry** in the UI: finding A-04.
5. **Customers must stay per workspace.** A person referred in two shops is
   two records; affiliates who work for both must not become a bridge
   (open decision O-018).

### 3. Device management

#### H-01 Revoking a device does not stop whoever holds it
- **Severity:** High. **Blocks Milestone 2: no. Blocks synchronisation work
  and a pilot: yes.**
- **Location:** `backend/apps/devices/services.py:33-55`;
  `backend/apps/devices/views.py:28-35`;
  `backend/apps/devices/permissions.py:19-45`.
- **Problem:** Probe P05 reproduces the lost-phone scenario. The owner revokes
  an affiliate's device. The browser on that phone is still logged in, so it
  registers a new device with one ordinary request that nobody has to
  approve, and passes the sync gate again. Revocation currently only retires an identifier.
- **Why it matters:** Revocation is the control an owner will reach for when
  a phone is lost or a seller leaves on bad terms. It gives a false sense of
  safety.
- **Answer to "should revocation invalidate sessions?": yes.** Revoking a
  device should end every session bound to that device, and registering a new
  device should not be possible from a session that was bound to a revoked
  one. Removing or suspending a membership should also revoke that member's
  devices in the workspace (see V-02).
- **Correction:** Bind each session to a device at login (session model from
  S-02). `revoke_device` deletes the bound sessions in the same transaction.
  Decide whether new-device registration needs owner approval for affiliates
  (new open decision; record it in `OPEN_DECISIONS.md`).

#### V-01 Device identity can be claimed by any session of the same user
- **Severity:** Medium. **Blocks Milestone 2: no. Must be settled in the
  synchronisation design.**
- **Location:** `backend/apps/devices/permissions.py:19-45`;
  `backend/apps/devices/views.py:22-26`.
- **Problem:** Probe P06: a second browser logged in as the same user lists
  the user's devices and presents another device's id successfully. Nothing
  ties a device id to the browser that registered it.
- **Why it matters:** Offline operations will be attributed to devices and
  deduplicated by operation identifiers per device. If attribution can be
  chosen freely, conflict handling and audit lose their meaning. This is
  self-impersonation, not privilege escalation.
- **Correction:** With session-to-device binding the header becomes
  unnecessary: the server takes the device from the session. If a header is
  kept, require it to equal the session's device.

#### V-02 Device lifecycle gaps
- **Severity:** Medium. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/workspaces/services.py:104-127`;
  `backend/apps/devices/views.py:28-35`; `backend/apps/devices/models.py:13-59`.
- **Problem:** (1) Removing a member leaves their devices active; on
  reactivation the old devices work again (probe P12). (2) Registration is
  unlimited and unthrottled: probe P14 created 60 devices in a loop.
  (3) Devices reference user and workspace separately instead of the
  membership, so nothing in the schema says the user is still a member.
- **Correction:** Revoke devices when a membership leaves `active`. Cap
  active devices per member and throttle registration. Consider a foreign
  key to the membership.

### 4. Database integrity

Constraints present and tested: case-insensitive unique email; one membership
per user per workspace; at most one owner per workspace; owner always active;
valid role and status values; device revocation fields consistent. Foreign
keys use `PROTECT` throughout. Indexes match the current query patterns.

#### D-01 "Every workspace has an owner" is not enforced by the database
- **Severity:** Medium. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/workspaces/models.py:73-83`.
- **Problem:** The constraints guarantee at most one owner, not at least one.
  Probes P03 and P03b removed the owner with one ORM statement each; P03c did
  it through the admin. Separately, deactivating the owner's user account
  leaves a workspace whose only owner cannot log in (probe P15).
- **Correction:** Close the admin path (S-01). Add a deferred constraint
  trigger on membership update and delete if the invariant must hold against
  all writers. Block deactivation of a user who owns a workspace. Expose
  ownership transfer.

#### D-02 Races that surface as server errors
- **Severity:** Low. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/workspaces/services.py:21-26`, `:63-66`.
- **Problem:** `add_member` and `_unique_slug` check then insert. Under
  concurrency the unique constraint correctly prevents duplicates, but the
  loser gets a raw `IntegrityError` (observed in probe P18), which would be a
  500 over HTTP. Data stays correct.
- **Correction:** Catch `IntegrityError` and raise `ConflictError`, or retry
  for the slug. Adopt this as the rule for every create in Milestone 2.

#### D-03 The audit trail is incomplete and not tamper-resistant
- **Severity:** Medium. **Blocks Milestone 2: no. Must be fixed before
  financial records (Milestone 4).**
- **Location:** `backend/apps/audit/models.py:41-47`;
  `backend/apps/accounts/views.py:45-65`; `docs/ARCHITECTURE.md` (database
  design principles).
- **Problem:** (1) Immutability is implemented only on model instances.
  Probe P04 rewrote and then deleted every audit row through a queryset.
  (2) Logins, failed logins and logouts are not recorded, and events carry no
  IP address or request identifier. (3) Admin edits and workspace status
  changes are not audited. (4) The architecture document says every
  security-relevant change writes an audit event, which is not true today.
- **Correction:** Revoke UPDATE and DELETE on the audit table from the
  application's database role, or add a trigger. Record authentication events
  via Django's login signals. Add request context. Correct the document.

#### D-04 Smaller schema points
- **Severity:** Low. **Blocks Milestone 2: no.**
- **Location:** `backend/apps/workspaces/models.py:17-22`;
  `backend/config/settings.py:74-77`; `backend/.env.example`.
- **Problem:** `Workspace.currency` and `name` have no database checks.
  The development database role owns the schema and can create databases;
  production needs a least-privilege role. No connection reuse or timeouts
  are configured. `ATOMIC_REQUESTS` is off, which is fine only while every
  write goes through a transactional service; that rule is not written down.
- **Correction:** Add the checks with the next migration; document the
  production role and the "all writes through services" rule.

### 5. Testing

The existing tests are meaningful: they assert status codes, response bodies
and database state, use real CSRF checking where it matters, and include
negative cases for each role. Gaps:

#### T-01 Evidence that cannot be reproduced
- **Severity:** Medium. **Blocks Milestone 2: yes (the CI part).**
- **Location:** `.github/workflows/ci.yml`; `docker-compose.yml`; no
  end-to-end directory exists.
- **Problem:** The CI workflow and the Compose file have never been executed.
  The browser run reported at the end of Milestone 1 used a script that was
  not committed, so it cannot be repeated.
- **Correction:** Push to a remote and get one green CI run. Start the
  database once with Compose. Commit the browser script as a Playwright
  suite with its own CI job.

#### T-02 Missing test categories
- **Severity:** Medium. **Blocks Milestone 2: no, except the first row.**

| Gap | Recommendation |
|---|---|
| No test that every route is guarded (blocks M2, part of A-01) | Promote probe P10 |
| No concurrency tests in the suite | Promote P17 to P19; make a concurrency test mandatory for every financial operation |
| Throttle tests cover only the simple case | Add proxy-header and shared-address cases once H-02 is fixed |
| Session lifecycle untested | Promote P07 and P08; add expiry |
| Management commands untested, yet they are the only onboarding path | Add command tests |
| Admin behaviour untested | Add tests once S-01 is fixed |
| No tests under production-like settings | Assert `Secure` cookies and startup refusals |
| Frontend: no test for workspace-switch data reset, mobile navigation or selection failure | Add with A-04 |
| No dependency audit; actions pinned by tag; no hash-pinned Python requirements | Add `pip-audit` and `npm audit` jobs |

### 6. PWA

Three different things, with their actual state:

| Capability | State | Evidence |
|---|---|---|
| **Responsive UI** | Implemented | Layout collapses below 720px; checked by emulation only during the build, not on physical devices |
| **Installability** | Partial | Manifest parses with no errors and desktop Chromium reports no installability errors (PWA probe). Not tested on any phone. Icon set is insufficient for Android and iOS (below) |
| **Offline functionality** | None | 0 service workers registered; reloading the built app while offline fails with `ERR_INTERNET_DISCONNECTED` (PWA probe). No IndexedDB, no queue |

The application is a responsive website with a manifest. It should not be
described as a PWA or as offline-capable to users yet.

#### P-01 Manifest and installation metadata are incomplete
- **Severity:** Medium. **Blocks Milestone 2: no.**
- **Location:** `frontend/public/manifest.webmanifest`;
  `frontend/index.html:5-8`; `frontend/public/` (one SVG file).
- **Problem and requirements per platform** (browser behaviour stated from
  documentation knowledge, not device testing; confirm on devices):

| Platform | Missing |
|---|---|
| **All** | HTTPS in production. PNG icons at 192 and 512 pixels; the only icon is an SVG. Manifest `id` and `scope`. A service worker with a versioned cache and an update prompt before any offline claim |
| **Android (Chrome)** | A maskable 512-pixel icon, otherwise the launcher icon is shrunk onto a white plate. Screenshots for the richer install sheet. A request for persistent storage before queuing offline orders |
| **iOS and iPadOS (Safari)** | `apple-touch-icon` at 180 pixels; `apple-mobile-web-app-title`; `viewport-fit=cover` with safe-area padding. There is no install prompt, so the app must show "Share, then Add to Home Screen" instructions. No Background Sync: the queue must flush when the app is opened or comes online. Storage of a site that is not installed can be evicted after about a week without use, so unsynced orders are at risk unless the app is installed. The installed app has its own cookies and requires a fresh login |
| **macOS** | Works through Chrome or Edge install and Safari's "Add to Dock" once PNG icons exist. Nothing platform-specific beyond the common items |
| **Windows** | Works through Edge or Chrome install once PNG icons exist. Screenshots improve the install dialog. Desktop-only Excel import and export fits this platform |

- **Design inputs for the offline milestone:** never cache authenticated
  `/api` responses in the service worker; clear local data on logout because
  phones are shared; a session can expire (14 days) while operations are
  queued, so the queue must survive re-login and be bound to user and
  workspace; a stale cached application must not be able to send operations
  the server no longer understands (send a client version).

### 7. Operations

#### O-01 There is no production deployment path
- **Severity:** Medium. **Blocks Milestone 2: no. Blocks a pilot: yes.**
- **Location:** `backend/requirements.txt` (no application server);
  repository root (no proxy or static-file configuration).
- **Problem:** No WSGI server, static file handling, TLS termination, backup
  or log configuration exists. Logging has no request identifiers.
- **Correction:** Add a minimal documented deployment (gunicorn, a reverse
  proxy serving the built SPA on the same origin, TLS, database backups)
  before the pilot, and run it through `check --deploy`.

#### O-02 Frontend robustness
- **Severity:** Low. **Blocks Milestone 2: no.**
- **Location:** `frontend/src/pages/WorkspaceSelectPage.tsx:72`;
  `frontend/src/session/SessionProvider.tsx`; `frontend/src/main.tsx`.
- **Problem:** A failed sign-out on the workspace screen is swallowed.
  Memberships and capabilities are loaded once and go stale until reload
  (the server still enforces). There is no error boundary, so a rendering
  error blanks the page.
- **Correction:** Surface the error; refresh memberships on 403 or 404 from a
  workspace call; add a top-level error boundary.

---

## Closing assessment

### 1. Overall architecture assessment

The foundation is sound. The modular structure, the service layer, the
capability policy, the session and CSRF design, and the database constraints
are appropriate for the product and were confirmed by test, including under
real concurrency for the ownership invariant. Tenant isolation holds on every
existing endpoint.

The weaknesses are of two kinds. First, several protections depend on
developers following a convention (A-01, A-02), which is acceptable for six
endpoints and not for sixty. Second, the device concept does not yet deliver
the security property its name implies (H-01, V-01), and the controls around
login (H-02, S-01, S-02) are not ready for the public internet.

### 2. Critical and high-priority findings

- **Critical:** none.
- **H-01:** revoking a device does not stop the person holding it; they
  re-register and continue.
- **H-02:** login rate limiting is bypassed by a forged header, locks out
  users who share an address, and has no per-account limit.

### 3. Required corrections before Milestone 2

| # | Correction | Finding |
|---|---|---|
| R1 | Make the workspace guard structural; add the route-walking test; add the workspace-scoped model base and endpoint test helper | A-01, T-02 |
| R2 | Services re-read and lock the actor's membership; domain permission error instead of framework exceptions | A-02 |
| R3 | Put the workspace in the SPA's URL | A-04 |
| R4 | One green CI run on a remote; Compose started once; browser suite committed | T-01 |
| R5 | Decide the session-to-device binding (H-01, S-02) and record it in `DECISIONS.md`, even if built later, because it changes the session backend | H-01, S-02 |

R1 to R4 are roughly a day of work. R5 is a decision, not code.

### 4. Recommended improvements that can wait

- **Before a pilot with real users:** H-01 and H-02 implemented; S-01, S-02,
  S-03; D-01; V-01, V-02; O-01; P-01 icons and iOS metadata.
- **Before financial records (Milestone 4):** D-03, and concurrency tests as
  a rule (T-02).
- **Any time:** A-03, S-04, D-02, D-04, O-02, the remaining rows of T-02.

### 5. Recommendation

**GO for Milestone 2 once R1 to R5 are done.** Do not start Milestone 2
feature code before them. **NO-GO for a pilot with real users or real
customer data** until the "before a pilot" list is complete.

---

## Status after the Milestone 1 corrections

Added after the review. The text above is unchanged and describes commit
`67f8586`. This table records what the corrections (R1 to R5) did to each
finding. "Open" findings were outside R1 to R5 and are unchanged.

| Finding | Status | Regression test or note |
|---|---|---|
| A-01 Guard by convention | **Fixed** (R1) | `test_architecture.py`, `test_isolation.py` |
| A-02 Stale actor; domain depends on HTTP | **Fixed** (R2) | `test_actor_authorization.py`, `test_architecture.py::test_domain_modules_do_not_import_the_http_layer` |
| A-03 Unscoped re-read; 403 versus 404 on revoke; 500 for unmapped method | **Fixed** | `test_devices.py::test_member_cannot_revoke_or_detect_someone_elses_device`, `test_architecture.py::test_capability_mapping_answers_405_for_unlisted_methods` |
| A-04 Workspace not in the SPA URL | **Fixed** (R3) | `App.test.tsx`, `e2e/workspaces.spec.ts` |
| H-01 Revocation does not stop the holder | **Fixed for a browser held without the password** (R5). A person who knows the password can still sign in on a new installation: DECISIONS D-019, OPEN_DECISIONS O-020 | `test_devices.py::test_revoked_browser_cannot_obtain_a_replacement_device`, `test_installations.py`, `e2e/devices.spec.ts` |
| H-02 Login rate limiting | **Open** | Blocks a pilot |
| S-01 Admin on the application origin | **Partly mitigated**: a session created by the admin login can no longer call the API. Unthrottled admin login and editable memberships remain | `test_installations.py::test_session_without_an_installation_is_not_accepted_by_the_api` |
| S-02 Session lifetime and revocation | **Partly fixed** (R5): sessions record user and device and can be ended per device. Idle timeout, "sign out everywhere", scheduled purge and re-authentication remain | `test_installations.py` |
| S-03 Insecure cookie settings deployable | **Open** | |
| S-04 Account model details | **Open** | |
| V-01 Device id can be claimed | **Fixed** (R5): the device comes from the session | `test_devices.py::test_client_cannot_choose_which_device_it_is` |
| V-02 Device lifecycle gaps | **Partly fixed**: unlimited registration is gone (one device per installation per workspace). Devices are still not revoked when a membership ends (O-021); installations per user are uncapped (O-022) | `test_devices.py::test_first_entry_authorises_the_installation_once` |
| D-01 "At least one owner" not enforced by the database | **Open** | |
| D-02 Races surfacing as server errors | **Fixed for `add_member`** (the actor lock serialises it). `_unique_slug` unchanged | `test_concurrency.py::test_concurrent_add_member_never_surfaces_a_database_error` |
| D-03 Audit trail incomplete and mutable | **Open** | Before Milestone 4 |
| D-04 Smaller schema points | **Open** | |
| T-01 Evidence not reproducible | **Fixed** (R4): browser suite committed, Compose verified, all three CI jobs pass on GitHub | `frontend/e2e/`, [CI run 43927496492](https://github.com/ndengafranck/merchantflow/actions/runs/43927496492) |
| T-02 Missing test categories | **Mostly fixed**: route coverage, concurrency, session lifecycle and isolation contract are in the suite. Management commands, admin and production-settings tests remain | |
| P-01 PWA metadata | **Open** | |
| O-01 No deployment path | **Open** | Blocks a pilot |
| O-02 Frontend robustness | **Partly fixed**: sign-out errors are shown. Error boundary and membership refresh remain | |
