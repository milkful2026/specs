# Implementation Plan — MA-1: User Registration (Mobile OTP, Social Login, Address and Wallet Setup)

## 1. Overview

**Story:** [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) — User Registration (Flutter)
**Date:** 2026-07-29
**Author:** SDD Agent (implementation-plan skill)

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Flutter Registration Onboarding | `mobile-app` | — |
| Identity & Auth — Registration APIs | `services` | MA-92 |
| User Service — Registration API | `services` | MA-93 |
| Inventory — Serviceability Check API | `services` | MA-95 |
| Wallet — Auto-Provision on Registration | `services` | MA-100 |

**What this delivers:** the full first-run registration journey — mobile + OTP entry (with
optional Google/Apple social link), name, address capture with serviceability validation,
delivery slot selection, legal consent, and an auto-provisioned wallet — ending in an
authenticated session on the Flutter app.

**Path note:** MA-1 spans two areas (`mobile-app` and `services`), which the
`implementation-plan` skill's `{area}`-scoped path template doesn't directly account for (it
assumes one area per story). This plan is written to `MA-1/impl-plan/` at the specs repo root —
the same neutral, area-agnostic location already used for MA-1's Step 1–5 workflow scratch files
— rather than nesting it under either `mobile-app/` or `services/` alone.

**Jira status note:** MA-1 never went through a live Jira SDD run — its specs were drafted and
merged directly to `main` in this repo's initial import, with no Jira Tasks or PR ever created
for it. This plan treats the merged spec files as the approval gate (equivalent in substance to
`SDD: Approved`), since that's what the skill's status check is actually a proxy for.

## 2. Prerequisites

All four target repos (`milkful-app`, `services`, `portal-ui`) are scaffold-only — confirmed by
listing each: `milkful-app` has only docs/scripts (no `lib/`, no `pubspec.yaml`); `services` has
only `README.md` (no service directories); `portal-ui` has only `README.md`. Nothing below is
"already satisfied" — everything is a fresh build.

| Prerequisite | Status |
|---------------|--------|
| Flutter project scaffold (`pubspec.yaml`, `lib/`) in `milkful-app` | Not done |
| `services/identity-auth/`, `services/user/`, `services/inventory/`, `services/wallet/` directories | Not done |
| Cognito User Pool (phone username attribute) | Not done — infra |
| DynamoDB `otp_requests` table | Not done — infra |
| Aurora `users`, `inventory`, `wallet` clusters/schemas | Not done — infra |
| ElastiCache Redis (OTP rate limiting, serviceability cache) | Not done — infra |
| EventBridge bus + `UserRegistered`, `WalletCreated` rules and consumer SQS queues | Not done — infra |
| Google Maps SDK / Places API keys in Secrets Manager | Not done — infra, needs a human to provision the API key itself before implementation can wire it in |

**New-service gate:** per `services/README.md` §"Human approval gate — new service", creating a
new top-level microservice needs explicit architect approval before scaffolding. Identity & Auth,
User, Inventory, and Wallet are all already named in that same README's **Service Inventory**
table (§"Service inventory") as part of the documented target architecture — this plan treats
that table as the standing approval to scaffold exactly these four, and no others. If that
reading is wrong, stop before Step 3.1 below and get explicit sign-off first.

## 3. Implementation Order

1. **Identity & Auth — Registration APIs (MA-92)** — foundational; nothing else in this story depends on it existing first, but User Service's registration call needs a valid `cognito_sub` from it, so it must exist before User Service can be integration-tested end-to-end.
2. **Inventory — Serviceability Check API (MA-95)** — independent of the other three specs; can be built in parallel with #1, ordered here only because User Service (#3) calls it synchronously during registration.
3. **User Service — Registration API (MA-93)** — depends on #1 (Cognito `sub` from a verified OTP session) and #2 (serviceability re-check before commit); this is the saga's orchestration point.
4. **Wallet — Auto-Provision on Registration (MA-100)** — depends on #3's `UserRegistered` event; cannot be integration-tested until User Service actually publishes that event.
5. **Flutter Registration Onboarding** — depends on all four backend specs being deployed to a reachable environment (staging) for real integration testing; screen-level UI work can start in parallel against mocked responses, but the plan sequences it last since its acceptance check requires the real APIs.

## 4. Per-Spec Implementation Steps

### MA-92: Identity & Auth — Registration APIs

**Files to create** (under `services/identity-auth/`, per the target module layout in `services/README.md` §4):

- `services/identity-auth/src/handlers/otp_send_handler.*` — `POST /auth/otp/send` entrypoint; thin — validates request shape, calls domain, maps exceptions to HTTP
- `services/identity-auth/src/handlers/otp_verify_handler.*` — `POST /auth/otp/verify` entrypoint
- `services/identity-auth/src/handlers/social_auth_handler.*` — `POST /auth/social` entrypoint
- `services/identity-auth/src/handlers/token_refresh_handler.*` — `POST /auth/token/refresh` entrypoint (standard Cognito refresh flow passthrough)
- `services/identity-auth/src/domain/otp_service.*` — OTP generation, bcrypt hashing, expiry/attempt rules, rate-limit check (business rules only, no AWS SDK imports per §3.4/§3.7)
- `services/identity-auth/src/domain/social_link_service.*` — idToken validation policy, existing-mobile-vs-social-only branching (FR-3, flagged G1)
- `services/identity-auth/src/domain/exceptions.*` — typed exceptions: `OtpExpiredError`, `OtpAttemptsExceededError`, `UserExistsError`, `RateLimitExceededError`, `InvalidSocialTokenError`
- `services/identity-auth/src/adapters/cognito_adapter.*` — wraps `AdminCreateUser`, `AdminConfirmSignUp`, `InitiateAuth`; only place allowed to import the Cognito SDK (§3.7)
- `services/identity-auth/src/adapters/otp_store_adapter.*` — DynamoDB `otp_requests` read/write
- `services/identity-auth/src/adapters/rate_limit_adapter.*` — Redis counter, key `register:otp:{mobile}` (matches the naming convention MA-21's login spec later relies on to avoid counter collision)
- `services/identity-auth/src/adapters/social_jwks_adapter.*` — Google/Apple JWKS validation
- `services/identity-auth/src/adapters/notification_publisher.*` — publishes `OtpRequested` domain event to EventBridge (envelope shape per `services/README.md` §5, `eventType: "identity.otp.requested"`)
- `services/identity-auth/src/config/env.*` — env var validation at startup only (Cognito pool ID, DynamoDB table name, Redis endpoint — no hardcoded values)
- `services/identity-auth/migrations/` — not applicable (DynamoDB table is IaC-managed, not SQL migration); note table creation belongs in the IaC step below, not here
- `services/identity-auth/Dockerfile` — not applicable if deployed as Lambda per spec §6; omit unless the team's Lambda packaging convention requires one
- `services/identity-auth/README.md` — service README per module layout template

**Infrastructure (IaC, outside the service module layout — coordinate with whoever owns `services/infrastructure/`):**

- Cognito User Pool with phone as username attribute
- DynamoDB table `otp_requests` (PK `requestId`, GSI on `mobile`, TTL on `ttl`)
- EventBridge rule for `OtpRequested` → Notification Service's SQS queue
- API Gateway routes: `/auth/otp/send`, `/auth/otp/verify`, `/auth/social`, `/auth/token/refresh` — no Cognito authorizer (pre-auth, per spec §6)

**Implementation steps:**

1. Scaffold `services/identity-auth/` per the module layout in `services/README.md` §4.
2. Implement `otp_service.*`: OTP generation (6-digit, per spec — see MA-21's Identity Auth spec §6 for why this must stay 6-digit, not the 5-digit shown in an unrelated later mockup), bcrypt hash, 5-min expiry, max-3-attempt lockout.
3. Implement `cognito_adapter.*` against a Cognito test pool (LocalStack or a real dev pool per team convention).
4. Implement `otp_send_handler` → `otp_service` → `otp_store_adapter` + `rate_limit_adapter`; wire the `409 USER_EXISTS` branch (existing, verified user) per FR-1.
5. Implement `otp_verify_handler` → on success, call `cognito_adapter` to create/confirm the Cognito user and issue tokens; return `isNewUser`.
6. Implement `social_auth_handler` + `social_link_service` + `social_jwks_adapter`; wire the `requiresMobileVerification` partial-token branch (FR-3, flagged G1 — mobile-not-verified-yet path).
7. Implement `token_refresh_handler` as a thin passthrough to Cognito's refresh flow.
8. Wire `notification_publisher` to emit `OtpRequested` on every send.

**Tests to write:**

- Unit: OTP generation/hash/expiry rules, rate-limit key logic, social JWKS validation, every typed exception's trigger condition
- Integration: Cognito test pool round trip (send → verify → tokens), mocked SNS/EventBridge publish
- Negative: expired OTP, 3-attempt lockout, invalid social token, existing-user send returns 409

**Acceptance check:** integration test suite for `services/identity-auth/` passes; a manual `curl` round trip against a deployed dev stack (send → verify) returns valid Cognito tokens for a test mobile number.

---

### MA-95: Inventory — Serviceability Check API

**Files to create** (under `services/inventory/`):

- `services/inventory/src/handlers/serviceability_check_handler.*` — public `GET /serviceability/check`
- `services/inventory/src/handlers/internal_serviceability_check_handler.*` — `GET /internal/serviceability/check`, IAM/mTLS-authenticated for User Service only
- `services/inventory/src/domain/serviceability_service.*` — match rules: active zone AND (pincode prefix OR point-in-polygon); prefers polygon over pincode when lat/lng provided
- `services/inventory/src/domain/exceptions.*` — `InvalidPincodeError`
- `services/inventory/src/adapters/zone_repository.*` — Aurora `serviceability_zones` reads (fail-closed on DB error per NFR)
- `services/inventory/src/adapters/zone_cache_adapter.*` — Redis, key `svc:{pincode}`, TTL 15 min
- `services/inventory/src/adapters/zone_update_consumer.*` — SQS consumer for `ZoneUpdated` → cache bust (FR-3)
- `services/inventory/migrations/0001_serviceability_zones.sql` — `serviceability_zones` table (id, name, active, slot_config jsonb, created_at) + pincode/polygon index structures
- `services/inventory/Dockerfile` — Fargate, per spec §6
- `services/inventory/README.md`

**Implementation steps:**

1. Scaffold `services/inventory/` per the module layout.
2. Write migration `0001_serviceability_zones.sql`; get it reviewed (production migrations require human approval per `services/README.md` §3.6 — this is a **new table**, not a repair/undo, but still route through the normal migration review, not an ad hoc script).
3. Implement `zone_repository` (Aurora reads) and `zone_cache_adapter` (Redis, cache-aside).
4. Implement `serviceability_service` match logic; unit-test pincode-prefix and point-in-polygon paths independently before wiring together.
5. Implement both handlers (public + internal variants share the domain service, differ only in auth and response shaping if any).
6. Implement `zone_update_consumer` for cache invalidation.
7. Seed at least one serviceable test zone (e.g. Bangalore Central) for integration tests and for manual Flutter testing later.

**Tests to write:**

- Unit: pincode-prefix match, point-in-polygon match, polygon-over-pincode precedence
- Integration: seeded zones, cache hit vs. miss, `ZoneUpdated` invalidation
- Negative: malformed pincode (400), inactive zone (not serviceable), DB unreachable (503, fail-closed)

**Acceptance check:** integration suite passes; manual `GET /serviceability/check?pincode=560001` against the seeded test zone returns `serviceable: true` with the expected slot list.

---

### MA-93: User Service — Registration API

**Files to create** (under `services/user/`):

- `services/user/src/handlers/register_handler.*` — `POST /users/register`, Cognito-JWT-authorized, `sub` must match registering user (per spec §5b of `services/README.md` — never trust client-supplied IDs; the registering user's identity comes from the verified JWT claim, not a request body field)
- `services/user/src/handlers/delivery_slots_handler.*` — `GET /delivery/slots?zoneId=`
- `services/user/src/domain/registration_service.*` — validation (name length, ≥1 address, mandatory TERMS/PRIVACY consents), transaction orchestration, idempotent-on-duplicate-`cognito_sub` behavior
- `services/user/src/domain/exceptions.*` — `NotServiceableError`, `ValidationError`, `DuplicateRegistrationError` (handled as idempotent 200, not a hard error — see spec §8)
- `services/user/src/adapters/user_repository.*` — Aurora `users`/`addresses`/`user_consents` writes, single DB transaction across all three (per NFR "Consistency")
- `services/user/src/adapters/inventory_client_adapter.*` — calls Inventory's internal serviceability endpoint (re-validation before commit, spec §8) — this is the *only* place allowed to make that outbound call, per the adapter pattern
- `services/user/src/adapters/cognito_attribute_adapter.*` — `AdminUpdateUserAttributes` for `name`, `custom:default_pincode`
- `services/user/src/adapters/outbox_publisher.*` — transactional outbox table + a separate publisher Lambda/consumer that reads the outbox and emits `UserRegistered` to EventBridge (spec §6 "Outbox")
- `services/user/migrations/0001_users_addresses_consents.sql` — `users`, `addresses`, `user_consents`, `outbox_events` tables per spec §6 schema
- `services/user/Dockerfile` or Lambda packaging, per team convention (spec says Lambda)
- `services/user/README.md`

**Implementation steps:**

1. Scaffold `services/user/`.
2. Write and get reviewed migration `0001_users_addresses_consents.sql` (new tables — human approval per `services/README.md` §3.6).
3. Implement `user_repository` with a single transaction spanning `users` insert/upsert, `addresses` insert, `user_consents` insert.
4. Implement the outbox pattern: `outbox_events` write inside the same transaction as step 3, plus a separate publisher process that polls/streams the outbox to EventBridge — do not publish directly from inside the request-handling transaction (this is what makes the "event publish fails but user still created" edge case in spec §9 safe).
5. Implement `inventory_client_adapter` calling Inventory's `/internal/serviceability/check` (depends on MA-95 being deployed first, per Implementation Order).
6. Implement `registration_service`: validation rules, then orchestrate repository + inventory re-check + Cognito attribute sync, in that order (fail fast on validation before any writes).
7. Implement `register_handler` (JWT `sub` extraction, DTO mapping, calls `registration_service`) and `delivery_slots_handler` (reads zone/slot config — confirm at implementation time whether this is a local replica or a live call to Inventory; the spec leaves this as "cached from Inventory or local replica" — resolve with whoever owns Inventory before hardcoding one approach).
8. Wire idempotency: duplicate `POST /users/register` for the same `cognito_sub` returns the existing `userId` with `200`, not a `409` or duplicate row.

**Tests to write:**

- Unit: validation rules (name length, address count, mandatory consents), idempotency-key logic
- Integration: Aurora test DB, mocked Inventory client, full registration transaction, outbox → mocked EventBridge publish
- Negative: non-serviceable address (422), partial DB failure rolls back cleanly, duplicate register returns existing `userId`

**Acceptance check:** integration suite passes; a manual registration call against a deployed dev stack (with valid JWT, serviceable address) returns `201` with a `userId`, and a row appears in `outbox_events` ready for publishing.

---

### MA-100: Wallet — Auto-Provision on Registration

**Files to create** (under `services/wallet/`):

- `services/wallet/src/handlers/user_registered_consumer.*` — SQS consumer for `wallet-user-registered` queue
- `services/wallet/src/handlers/wallet_status_handler.*` — `GET /wallet/me/status`, JWT-authorized
- `services/wallet/src/handlers/wallet_retry_handler.*` — `POST /wallet/me/retry` (internal replay by userId, per spec FR-3)
- `services/wallet/src/domain/wallet_provisioning_service.*` — idempotent-create logic keyed by `idempotencyKey` (= userId), opening ledger entry creation
- `services/wallet/src/domain/exceptions.*` — `WalletAlreadyExistsError` (used internally to short-circuit to idempotent no-op, not surfaced as a client error)
- `services/wallet/src/adapters/wallet_repository.*` — Aurora `wallets`/`ledger_entries` writes
- `services/wallet/src/adapters/wallet_event_publisher.*` — publishes `WalletCreated` to EventBridge
- `services/wallet/migrations/0001_wallets_ledger.sql` — `wallets` (id, user_id UNIQUE, balance, currency, status, created_at), `ledger_entries` (id, wallet_id, type, amount, ref, created_at)
- `services/wallet/Dockerfile` — Fargate consumer + a Lambda for the status/retry API (per spec §6, this spec spans two compute types — keep the consumer and the API as separate deployables, not one artifact, per "one service → one deployable artifact" *per component*, matching how Identity Auth already separates Lambda handlers from its adapters)
- `services/wallet/README.md`

**Implementation steps:**

1. Scaffold `services/wallet/`.
2. Write and get reviewed migration `0001_wallets_ledger.sql`.
3. Implement `wallet_repository` and the opening-ledger-entry logic (type `OPENING`, amount 0) as part of the same insert as the wallet row.
4. Implement `wallet_provisioning_service` with idempotency on `idempotencyKey` — a duplicate `UserRegistered` event must no-op, not create a second wallet or throw an error the consumer would retry forever.
5. Implement `user_registered_consumer`: subscribe to the EventBridge rule → SQS queue `wallet-user-registered` (depends on MA-93's `UserRegistered` event actually being published — cannot be integration-tested end-to-end until MA-93 is deployed, per Implementation Order); configure the DLQ `wallet-user-registered-dlq` with a CloudWatch alarm (spec §6).
6. Implement `wallet_status_handler`: `CREATING` while unprocessed (<30s normal), `ACTIVE` once created, `FAILED` after retries exhausted.
7. Implement `wallet_retry_handler` for manual replay by userId (used by the mobile app's retry banner, and by support).

**Tests to write:**

- Unit: idempotency-key no-op path, opening ledger entry shape
- Integration: publish a `UserRegistered` event → assert a wallet row and opening ledger entry exist
- Chaos/negative: forced DB insert failure → DLQ → status `FAILED` → manual retry restores `ACTIVE`; duplicate event delivery → no second wallet

**Acceptance check:** integration suite passes; publishing a test `UserRegistered` event against a deployed dev stack results in `GET /wallet/me/status` returning `ACTIVE` within 5s.

---

### Flutter Registration Onboarding

**Files to create** (under `milkful-app/lib/`, exact structure to be confirmed against whatever Flutter project scaffold is chosen in Step 5.1 below — paths here follow a conventional `lib/features/registration/` layout consistent with the spec's screen list):

- `lib/features/registration/presentation/signup_screen.dart` — `/signup`, mobile entry (FR-1)
- `lib/features/registration/presentation/otp_screen.dart` — `/otp` (FR-2)
- `lib/features/registration/presentation/profile_screen.dart` — `/profile`, name entry (FR-4)
- `lib/features/registration/presentation/address_screen.dart` — `/address`, map/search/manual (FR-5)
- `lib/features/registration/presentation/serviceability_widget.dart` — inline result UI used by `address_screen.dart` (FR-6)
- `lib/features/registration/presentation/slot_screen.dart` — `/slot` (FR-7)
- `lib/features/registration/presentation/consent_screen.dart` — `/consent` (FR-8)
- `lib/features/registration/presentation/success_screen.dart` — `/success` (FR-9), including the wallet-pending/failed retry banner
- `lib/features/registration/bloc/registration_bloc.dart` — `RegistrationBloc` (spec §6)
- `lib/features/auth/bloc/auth_bloc.dart` — `AuthBloc` (spec §6) — **this is the base MA-21's login spec extends**, so its event/state shape should anticipate login-specific events even though only registration events are implemented in this story (don't hardcode registration-only assumptions into its core state shape)
- `lib/features/registration/data/registration_draft.dart` — `RegistrationDraft` model (spec §7)
- `lib/features/registration/data/registration_api_client.dart` — `dio`-based client for all 6 endpoints in spec §8
- `lib/core/storage/secure_token_storage.dart` — `flutter_secure_storage` wrapper, shared with `AuthBloc`
- `lib/core/storage/onboarding_draft_storage.dart` — `shared_preferences`/Hive persistence (FR-10)
- `lib/core/routing/app_router.dart` — `go_router` config with the onboarding route guard chain

**Implementation steps:**

1. Confirm/establish the Flutter project scaffold (`flutter create`, `pubspec.yaml` with `flutter_bloc` or `riverpod`, `go_router`, `dio`, `pinput`, `intl_phone_field`, `google_maps_flutter`, `webview_flutter`, `flutter_secure_storage` — pick state management library before writing `RegistrationBloc`/`AuthBloc`, since the spec allows either `flutter_bloc` or `riverpod` and this plan doesn't decide that for you).
2. Implement `AuthBloc` and `secure_token_storage` first — every other screen in this flow depends on having somewhere to put the tokens returned by OTP verify.
3. Implement `signup_screen` + `registration_api_client`'s OTP-send call; wire the `USER_EXISTS` → "Already registered? Log in" inline link (this is the exact hook MA-21 attaches to later — get its route/state contract right here even though `/login` doesn't exist until MA-21 is implemented).
4. Implement `otp_screen`, including the resend countdown and lockout states (FR-2).
5. Implement social auth entry points (`social_auth_handler` calls) with the `requiresMobileVerification` branch honored.
6. Implement `profile_screen`, `address_screen` (map + search + manual, with the location-permission-denied → manual fallback), `serviceability_widget`.
7. Implement `slot_screen`, `consent_screen` (including the WebView legal doc links).
8. Implement `success_screen` with the wallet-status poll (every 2s up to 15s) and retry banner.
9. Implement `onboarding_draft_storage` and wire save-on-Continue / resume-on-relaunch (FR-10).
10. Wire `app_router` guards so an authenticated session skips straight past onboarding on relaunch.

**Tests to write:**

- Widget: phone validation, OTP resend timer, consent gating on submit button (per spec §10)
- Integration test: the full happy-path scenario in spec §10 ("Given: Fresh install... Outcome: User authenticated; wallet confirmation shown"), plus the three negative scenarios listed there
- All selectors as specified: `find.text(...)`, `find.bySemanticsLabel('Mobile number')`, `find.byKey(Key('otp-input'))`

**Acceptance check:** `flutter test` passes for all widget tests; the integration test scenario from spec §10 passes against a deployed dev backend (all four services above must be reachable).

## 5. Cross-Cutting Steps

- Update `services/README.md` §2's repository structure is already the target — no changes needed there, but each new service's own `README.md` (created per spec above) must be added, not skipped.
- Confirm the EventBridge producer/consumer map in `docs/design/milkful-messaging.drawio` reflects `OtpRequested`, `UserRegistered`, `WalletCreated`, `ZoneUpdated` once these are real — this is a documentation update, not code, but is listed in `services/README.md` §5 as the reference map and should stay accurate.
- After all four services are deployed to a shared dev/staging environment, run the Flutter integration test scenario end-to-end — this is the first point at which the full saga (OTP → register → wallet event → status poll) can be verified together.
- Root-level lint/test run across whichever services were touched (see `services/README.md` §8 CI/CD Guardrails — lint → unit → integration per service before merge).

## 6. Test Strategy

| Level | Scope |
|-------|-------|
| Unit | Per-service domain logic (see each spec section above) — no AWS SDK, no DB, no network |
| Integration | Per-service, against a test DB / LocalStack / Cognito test pool |
| Contract | Event payload shapes (`OtpRequested`, `UserRegistered`, `WalletCreated`) match what each consumer expects — verify against the envelope format in `services/README.md` §5 |
| E2E | The single Flutter integration test scenario in the mobile spec, run against a real deployed dev stack of all four services |

**How to run (per service, once scaffolded):** `{unit/integration test command per the language/framework chosen at implementation time — not yet fixed, since no service code exists to inherit a convention from}`. For Flutter: `flutter test` (widget + unit), `flutter test integration_test/` (integration).

**Coverage threshold:** not yet established for this greenfield codebase — `services/README.md` §6 requires "all tests pass" (zero failures) as the gate, not a numeric coverage threshold; don't invent one.

**Lint:** run per the tooling chosen at implementation time (not yet fixed for either the Flutter or the backend codebases).

## 7. Commit Strategy

One commit per spec (5 commits total for this story), each scoped to that spec's files only — mirrors the "one file per spec" discipline already used in the specs repo itself. Suggested order matches Implementation Order (§3):

1. `feat(identity-auth): OTP send/verify, social auth, token refresh (MA-92)`
2. `feat(inventory): serviceability check API (MA-95)`
3. `feat(user): registration API, delivery slots (MA-93)`
4. `feat(wallet): auto-provision on UserRegistered (MA-100)`
5. `feat(mobile): registration onboarding flow (MA-1)`

Each commit message should reference the Jira story (`MA-1`) and, once Jira Tasks exist for this
story's specs, the relevant Task key.

## 8. Risks and Blockers

- **New-service approval reading (§2 above)** is this plan's biggest assumption — if the architect disagrees that the Service Inventory table constitutes pre-approval, all four backend specs are blocked at Step 3.1 until that's resolved explicitly.
- **Google Maps/Places API key provisioning** is an external, human-gated dependency (spec §6) — not something an implementation agent can self-serve; flag early so it isn't discovered as a blocker mid-sprint.
- **Wallet failure UX (spec's flagged concern, `wallet-auto-provision.md` §12 Q1)** was resolved as "async, non-blocking" during SDD — if product revisits this, it changes both the User Service response contract (`walletStatus`) and the Flutter success-screen retry banner; a change here has a two-spec blast radius.
- **State management library choice** (`flutter_bloc` vs. `riverpod`) is left open by the spec — pick before Step 4's Flutter implementation starts, since `AuthBloc`/`RegistrationBloc` naming assumes `flutter_bloc`-style blocs; a `riverpod` choice would need equivalent-but-differently-named providers, not a literal `Bloc` class.
- **`GET /delivery/slots` data source** (spec's own open question — "cached from Inventory or local replica") is unresolved; implementing it either way is straightforward, but implementing it inconsistently with how Inventory actually manages zone/slot config would create a second source of truth — resolve with the Inventory owner before Step 4.7.
- **Outbox publisher is a second deployable** inside User Service (the transactional-outbox pattern requires a poller/streamer separate from the request-handling Lambda) — make sure this doesn't get skipped as "just a detail" during scaffolding; without it, `UserRegistered` never actually reaches Wallet.
