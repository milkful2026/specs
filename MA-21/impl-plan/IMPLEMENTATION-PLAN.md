# Implementation Plan — MA-21: User Login (Authentication)

## 1. Overview

**Story:** [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) — User Login (Flutter)
**Date:** 2026-07-29
**Author:** SDD Agent (implementation-plan skill)

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Flutter Login Flow | `mobile-app` | — |
| Identity & Auth — Login APIs | `services` | MA-92 |
| User Service — Account Type & Profile Lookup | `services` | MA-93 |

**What this delivers:** the returning-customer login journey — mobile + 6-digit OTP verify,
persistent session ("remember me"), role-aware landing (B2C/B2B), and secure per-device logout —
reached from the "Already registered? Log in" link MA-1's registration flow already built.

**Path note:** same as MA-1 — this plan lives at `MA-21/impl-plan/` at the specs repo root rather
than nested under a single `{area}`, since the story spans `mobile-app` and `services`.

**Hard dependency on MA-1:** every spec in this story extends something MA-1 builds — the shared
Cognito user pool and `otp_requests` table (Identity Auth), the `users` table (User Service), and
the entry screen + `AuthBloc` base (Flutter). **MA-1's implementation plan must be executed
first** — this is not just a sequencing preference, several files below are edits to files MA-1's
plan creates, not new files.

## 2. Prerequisites

Same scaffold-only starting state as MA-1 (confirmed via the same repo listing — see MA-1's plan
§2). Additionally, everything below assumes **MA-1 is already implemented**:

| Prerequisite | Status |
|---------------|--------|
| `services/identity-auth/` scaffolded, Cognito pool + `otp_requests` table live (MA-1 Step 4.1) | Not done — blocked on MA-1 |
| `services/user/` scaffolded, `users` table live (MA-1 Step 4.3) | Not done — blocked on MA-1 |
| `lib/features/auth/bloc/auth_bloc.dart` and `lib/core/storage/secure_token_storage.dart` exist (MA-1 Step 4's Flutter work) | Not done — blocked on MA-1 |
| MA-1's `/signup` screen's `USER_EXISTS` → "Log in" link exists and is routable | Not done — blocked on MA-1 |

No new infrastructure beyond MA-1's is required for MA-21 — this story only adds new API routes,
a new DB column, and new Flutter screens on top of what MA-1 provisions.

## 3. Implementation Order

1. **Identity & Auth — Login APIs (MA-92)** — extends the Identity Auth service MA-1 already scaffolds; no dependency on this story's other two specs.
2. **User Service — Account Type & Profile Lookup (MA-93)** — extends the User service MA-1 already scaffolds; independent of #1, can be done in parallel.
3. **Flutter Login Flow** — depends on both #1 and #2 being deployed (calls `POST /auth/login/otp/send`, `POST /auth/login/otp/verify`, `GET /users/me`, `POST /auth/logout`), and on MA-1's Flutter work already being merged (extends `AuthBloc`, reuses the entry screen's routing hook).

## 4. Per-Spec Implementation Steps

### MA-92: Identity & Auth — Login APIs

**Files to create** (new files alongside MA-1's `services/identity-auth/` module):

- `services/identity-auth/src/handlers/login_otp_send_handler.*` — `POST /auth/login/otp/send`
- `services/identity-auth/src/handlers/login_otp_verify_handler.*` — `POST /auth/login/otp/verify`
- `services/identity-auth/src/handlers/logout_handler.*` — `POST /auth/logout`, Cognito-JWT-authorized (the one login-related endpoint that isn't pre-auth)
- `services/identity-auth/src/domain/login_service.*` — existing-verified-user lookup, `404 USER_NOT_FOUND` branch, delegates OTP generation/hashing/expiry to the *same* `otp_service` MA-1 already built (do not duplicate that logic — see Files to modify below)

**Files to modify** (existing files from MA-1's Identity Auth work):

- `services/identity-auth/src/domain/otp_service.*` — add a `purpose` parameter (`"REGISTER" | "LOGIN"`) threaded through to the store adapter; this is additive, must not change registration's existing call sites' behavior
- `services/identity-auth/src/adapters/otp_store_adapter.*` — add `purpose` attribute to the DynamoDB write/read; absence on old rows defaults to `"REGISTER"` per spec §7 (no backfill migration needed)
- `services/identity-auth/src/adapters/rate_limit_adapter.*` — add a `login:otp:{mobile}` key path, distinct from MA-1's existing `register:otp:{mobile}` (MA-1's plan already named this convention specifically so this story wouldn't collide with it)
- `services/identity-auth/src/adapters/cognito_adapter.*` — add an `InitiateAuth`-for-existing-user method and a `revokeToken(refreshToken)` method (per-device only — **must not** call `AdminUserGlobalSignOut**, per spec §6 risk note)

**Implementation steps:**

1. Add the `purpose` field to `otp_service` and `otp_store_adapter` first — this is the one shared-code change every other step in this spec depends on, and it must not break MA-1's existing registration tests when done.
2. Add the `login:otp:{mobile}` rate-limit key path to `rate_limit_adapter`.
3. Implement `login_service`: look up Cognito user by phone, branch on `phone_number_verified` (found+verified → proceed, else → `404 USER_NOT_FOUND` with `redirect: "signup"`).
4. Implement `login_otp_send_handler` → `login_service` → (reused) `otp_service` with `purpose: "LOGIN"`.
5. Implement `login_otp_verify_handler` → on success, call the new `InitiateAuth` method on `cognito_adapter` (not `AdminCreateUser`/`AdminConfirmSignUp` — those are registration-only).
6. Implement `cognito_adapter.revokeToken` and `logout_handler`; verify manually that it revokes only the supplied refresh token, not the whole account (this is the single most important thing to get right in this spec — a mistake here silently breaks the "concurrent sessions allowed" product decision from MA-21's Step 1 analysis).

**Tests to write:**

- Unit: `purpose` branching in `otp_service` (both registration and login paths still pass), rate-limit key isolation (a login attempt and a registration attempt on the same mobile don't share a counter), `revokeToken` called with single-token scope only
- Integration: Cognito test pool with a pre-seeded verified user (login path) and an unverified/absent user (404 path); regression-run MA-1's existing Identity Auth integration tests to confirm nothing broke
- Negative: login OTP against unregistered number, logout with an already-expired/revoked token (must still return `204`), logout with a malformed/missing token (`400`)

**Acceptance check:** integration suite passes (including MA-1's pre-existing Identity Auth tests, run as a regression check); manual round trip against a deployed dev stack: login-OTP-send → verify → tokens → logout → confirm the same refresh token now fails a subsequent refresh call.

---

### MA-93: User Service — Account Type & Profile Lookup

**Files to create** (new files alongside MA-1's `services/user/` module):

- `services/user/src/handlers/get_me_handler.*` — `GET /users/me`, Cognito-JWT-authorized, resolves the user via the `sub` claim only (never a client-supplied ID, per `services/README.md` §5b)
- `services/user/migrations/0002_add_account_type.sql` — `ALTER TABLE users ADD COLUMN account_type VARCHAR NOT NULL DEFAULT 'B2C' CHECK (account_type IN ('B2C', 'B2B'))`

**Files to modify:**

- `services/user/src/domain/exceptions.*` — add `UserNotFoundError` if MA-1's registration domain doesn't already have an equivalent (check first — spec explicitly calls out this must be a clean `404`, not a `500`, per its Edge Cases section)
- `services/user/src/adapters/user_repository.*` — add a narrow read method for `GET /users/me` (userId, name, mobile, accountType, defaultAddressId only — per spec §7, deliberately not the full registration payload)

**Implementation steps:**

1. Write migration `0002_add_account_type.sql` — additive, `NOT NULL DEFAULT`, no backfill script needed (get it reviewed same as any production migration, per `services/README.md` §3.6).
2. Add the narrow read method to `user_repository` — resist the temptation to reuse whatever broader read method MA-1's registration flow uses internally; this spec's §11 explicitly calls out keeping this endpoint minimal.
3. Implement `get_me_handler`: JWT `sub` → repository lookup → `404` if no matching row, else the narrow response shape from spec §4 FR-2.

**Tests to write:**

- Unit: `GET /users/me` response shape, 404-on-missing-user branch, confirms the handler never accepts a client-supplied user ID
- Integration: Aurora test DB with the migration applied — assert existing MA-1-seeded rows read back `accountType: "B2C"` with no manual backfill step
- Migration test: apply `0002_add_account_type.sql` against a DB already seeded by MA-1's `0001_users_addresses_consents.sql` + test data; assert no errors and all rows satisfy the `CHECK` constraint

**Acceptance check:** integration suite passes; manual `GET /users/me` against a deployed dev stack (valid JWT for an MA-1-registered test user) returns `200` with `accountType: "B2C"`.

---

### Flutter Login Flow

**Files to create** (under `lib/features/login/`, alongside MA-1's `lib/features/registration/` and `lib/features/auth/`):

- `lib/features/login/presentation/login_entry_screen.dart` — `/login`, standalone mobile-number entry (FR-1) — only rendered on standalone re-entry, not when arriving via MA-1's carried-forward-number redirect
- `lib/features/login/presentation/login_otp_screen.dart` — `/login/otp` (FR-2)
- `lib/features/login/bloc/login_events.dart` / additions to `auth_bloc.dart` — `LoginOtpRequested`, `LoginOtpVerified`, `SessionRefreshed`, `LoggedOut` events (spec §6 — these were anticipated in MA-1's `AuthBloc` design per that plan's Step 4 note, so this should be extending existing state handling, not bolting on a parallel bloc)
- `lib/features/login/data/login_api_client.dart` — `dio` client for the 3 login endpoints + reuses MA-1's existing token-refresh call
- `lib/core/session/session_state.dart` — `SessionState` model (spec §7), adds `accountType` on top of whatever token fields MA-1's `AuthBloc` already tracks

**Files to modify:**

- `lib/core/routing/app_router.dart` (created by MA-1) — add `/login` and `/login/otp` routes; update the "no valid session" redirect logic to route to `/login` (not `/signup`) when a last-known-mobile-number hint exists (e.g. post-logout), per spec §6
- `lib/features/registration/presentation/signup_screen.dart` (created by MA-1) — confirm its existing "Log in" link (built in MA-1 for the `USER_EXISTS` response) actually navigates to the new `/login/otp` route with the mobile number carried in route state — this may already work as MA-1 built it, or may need a small update once `/login/otp` actually exists to receive it; verify, don't assume
- `lib/features/auth/bloc/auth_bloc.dart` (created by MA-1) — add the login-specific event handlers; add silent-refresh-on-app-start logic (FR-3) if MA-1 didn't already implement it generically enough to cover login-issued tokens too (it should — both are just Cognito refresh tokens — but verify)

**Implementation steps:**

1. Confirm MA-1's `signup_screen`'s existing "Log in" link contract (what route/state does it currently navigate to?) before building `/login/otp` — this determines whether `login_otp_screen` needs to accept a route parameter for the carried-forward number or whether that wiring needs a small MA-1-side fix first.
2. Implement `login_entry_screen` (standalone re-entry path only) and `login_api_client`'s send call.
3. Implement `login_otp_screen`: 6-digit `pinput` (per the resolved product decision — build 6 digit cells, not the 5 shown in the attached mockup, which is flagged as a stale design asset in the spec), resend countdown, lockout state.
4. Wire OTP verify → token storage (reuse MA-1's `secure_token_storage`) → call `GET /users/me` → store `accountType` in `SessionState`.
5. Implement role-aware landing: read `SessionState.accountType`, render the B2C/B2B indicator on Home (no B2B-specific screens — just the indicator, per spec §4 FR-4's deliberately narrow scope).
6. Implement the silent-refresh-on-app-start path if not already generic in MA-1's `AuthBloc`.
7. Implement the logout action (placement is provisional per the spec's own open question — put it wherever the current nav shell has room; don't block this story on a real Account screen existing) → confirmation dialog → `POST /auth/logout` → clear storage regardless of API result (spec §9) → route to entry screen.

**Tests to write:**

- Widget: phone validation on standalone `/login` entry, OTP resend/lockout timer, logout confirmation dialog cancel vs. confirm
- Integration test scenario 1 (spec §10): login via MA-1's redirect link, full happy path to role-aware Home
- Integration test scenario 2 (spec §10): logout → standalone re-login round trip
- Negative: unregistered number on standalone `/login`, invalid/expired/lockout OTP states, refresh failure on app start routes cleanly to entry screen with no error dialog

**Acceptance check:** `flutter test` passes; both integration scenarios from the spec's §10 pass against a deployed dev stack with the two Login API services above already running.

## 5. Cross-Cutting Steps

- Regression-run MA-1's full test suite (all four services + Flutter) after this story's changes — several files are shared/modified, not just extended in isolation (see each spec's "Files to modify" above).
- Update `docs/design/milkful-messaging.drawio` if the optional `UserLoggedIn` analytics event (mentioned as a maybe in Step 2 context, not committed to in any spec above) is added later — not part of this plan since no spec commits to building it.
- Confirm the new `account_type` column doesn't require any change to MA-1's existing registration write path — it shouldn't, since the column has a `DEFAULT` and registration never sets it — but verify this explicitly rather than assuming, since it's an easy thing for a reviewer to miss.

## 6. Test Strategy

Same per-service/Flutter split as MA-1's plan §6. The one addition: every test suite touched by
this story's "Files to modify" list must be re-run as a **regression check against MA-1's
existing tests**, not just this story's new tests — this story edits shared files, so a passing
new-test-suite alone doesn't prove MA-1 still works.

**Coverage threshold:** same as MA-1 — no numeric threshold, "all tests pass" is the gate.

## 7. Commit Strategy

One commit per spec (3 commits), in Implementation Order:

1. `feat(identity-auth): login OTP send/verify, per-device logout (MA-21, MA-92)`
2. `feat(user): account type field, GET /users/me (MA-21, MA-93)`
3. `feat(mobile): login flow, role-aware landing (MA-21)`

Each references `MA-21` and, once Jira Tasks exist matching this plan's specs (MA-105, MA-106,
MA-107 — already created during the SDD phase), the relevant Task key.

## 8. Risks and Blockers

- **Hard sequencing on MA-1** (§1 above) is this plan's single biggest constraint — nothing here can be meaningfully started, let alone tested, before MA-1's four backend specs and Flutter work exist. Don't let "MA-21 looks smaller" create pressure to parallelize past this.
- **`RevokeToken` correctness** (Identity Auth step 6) is the one piece of this story where a subtle implementation mistake (accidentally calling a global-sign-out variant) would silently violate the "concurrent sessions allowed" product decision without any test necessarily catching it unless the test suite explicitly asserts *other* sessions remain valid after one logout — make sure that specific assertion exists, not just "the logged-out token now fails."
- **Design-asset mismatch** (6-digit implementation vs. the 5-digit mockup) is a known, already-flagged inconsistency — implement to the spec (6-digit), not the image; don't silently "fix" this by matching the mockup instead.
- **Logout UI placement** is genuinely undecided (spec's own open question) — implement the mechanism now, treat the exact button/menu location as a small follow-up change once a real Account screen exists, not as a blocker for this story.
