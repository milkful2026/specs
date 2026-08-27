# Implementation Plan — MA-96: Cart Service (Lambda + DynamoDB)

## 1. Overview

**Story:** [MA-96](https://milkfuldairyindia.atlassian.net/browse/MA-96) — Cart Service
**Date:** 2026-08-21
**Author:** Claude Code (session), implementing the merged MA-121 spec

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Cart Service (Lambda + DynamoDB) (MA-121) | `services/cart` | — |

**What this delivers:** `GET /cart`, `POST /cart/items`, `PUT /cart`, `DELETE /cart/items/{id}` per
MA-121's merged spec (including its own PR #8 review fixes: `cartVersion`/`ifVersion` optimistic
concurrency, the `offerCode` field synced from MA-101/MA-122's own review, Idempotency-Key storage,
and the wallet-gate scoping fix) — built against `services/user`, `services/catalog`, and
`services/inventory`, which are real; stubbed against Pricing & Offer Service (MA-101) and Wallet
Service (MA-100), which are not.

**Path note:** single-area story (`services` only, one new service directory `services/cart/`) —
this plan lives at `services/tasks/MA/MA-96/impl-plan/`, alongside the spec it implements, mirroring
MA-23's own impl plan (`mobile-app/tasks/MA/MA-23/impl-plan/`).

## 1a. Status Update (2026-08-27) — code review findings, resolved vs. still open

This repo's own PR #11 (2026-08-21) review found six issues in this plan/its early
implementation. Re-checked against the real code today, not just this document:

| Finding | Status |
|---|---|
| §4A's internal endpoint would ship public and unauthenticated ("network isolation" doesn't exist for a Lambda + HttpApi service, unlike Inventory's Fargate-behind-private-ALB setup this plan borrowed the reasoning from) | **Fixed.** The route now uses `HttpIamAuthorizer` (AWS_IAM/SigV4) in `user_stack.py`, verified via `cdk synth` — the route synthesizes with `AuthorizationType: AWS_IAM`, not `JWT`, not unauthenticated. `internal_caller_role_arns` (defaults to empty — nobody granted yet) is where Cart Service's own execution role ARN gets added once its CDK stack exists; the route's `execute-api` ARN is exported via `CfnOutput` for that stack to import. §4A below is updated to match — do not reintroduce the old "network isolation" framing. |
| §4A claimed no `UserProfile` field/repository change was needed for `default_address_state`, but at the time neither the field nor the repository population existed | **Fixed** (as a side effect of unrelated work, `services/user` PR #10's first commit) — `default_address_state` is now genuinely on `UserProfile`, populated in `user_repository.py`, and serialized on `GET /users/me`. §4A's original claim is accurate now, not just asserted. |
| §4A didn't mention that `get_my_profile` raises `UserNotFoundError` rather than returning `None`, so the handler would 500 instead of returning `{"defaultAddressState": null}` | **Fixed** — the actual handler (`internal_address_state_handler.py`) catches `UserServiceError` broadly and maps it to the correct HTTP status (404 for `UserNotFoundError`), covered by its own test suite. |
| §6 of the merged MA-121 spec explicitly says "a small, additive consumer of an existing capability, not a new endpoint on `user`'s side," but this plan adds a new endpoint anyway, without reconciling the contradiction | **Still open.** This plan still adds a new endpoint (§4A) — that's the correct call given `get_my_profile`'s actual signature (it needs `cognito_sub`, which `user`'s existing public routes resolve from the caller's own JWT, not an arbitrary target user), but MA-121 §8 itself hasn't been revised to match. Whoever owns MA-121 should reconcile the spec text with what's actually being built, not this plan silently overriding the spec. |
| MA-121 §6/§11's Redis read-through cache (flagged as needing Platform/Architecture sign-off before implementation) is absent from this plan with no acknowledgment | **Still open.** `grep -i redis` over this entire plan still returns nothing. Not implemented, not deferred-with-a-note, not sign-off-requested — just silently absent, same as PR #11 found it. If Redis is out of scope for this pass, that should be a stated decision here, not silence. |
| §4D's DynamoDB schema gives `ITEM#`/`IDEMPOTENCY#` rows a TTL but the `META` row (holding `cartVersion`) has none, so `cartVersion` could persist at a stale non-zero value after every item has expired | **Still open.** §4D below is unchanged — `META`'s `cartVersion` still has no TTL or reset policy. FR-1's "no cart and empty cart are the same state" implies `cartVersion` should read `0` once items expire; nothing here makes that true. |

**Net: the one finding that actually blocked shipping (the auth gap) is fixed and verified. Of the
other five, two are genuinely resolved (the `UserProfile` field, the missing-user handling); three
— the MA-121 §8 contradiction, the silently-dropped Redis cache, and the `cartVersion` TTL gap —
are still exactly where the review left them and need real decisions, not just
re-acknowledgment.**

## 2. Prerequisites

Confirmed by reading each target service directly — **three of MA-121's own dependency assumptions
don't match the real code**, beyond the two already-known missing services:

| Dependency | MA-121's assumption | Actual state |
|---|---|---|
| Pricing & Offer Service (MA-101) | Spec'd, PR #9 reviewed | **Does not exist** — no `services/pricing-offer` directory |
| Wallet Service (MA-100) | "already shipped" (FR-6) | **Does not exist at all** — not even spec'd (already flagged in MA-23's own impl plan §2) |
| Inventory Service — stock quantity | MA-121 §8: "assumes a per-product quantity lookup exists or is added as a small Inventory-side addition" | **Inventory Service has no stock-quantity concept whatsoever** — its domain model (`services/inventory/src/domain/models.py`) is `Zone`/`Slot`/`ServiceabilityResult` only; its only two endpoints are both `serviceability/check`. Stock quantity is Catalog Service's data, not Inventory's — see next row. |
| Catalog Service — `availableQuantity` | MA-120 §7 (mobile spec, same drafting pass) already resolved this: Catalog Service gains `available_quantity` on `Product`, populated from `StockChanged`, serialized on `GET /products/{id}`. | **Still not implemented** — confirmed by reading `services/catalog/src/domain/models.py`'s `Product` dataclass (no such field) and `handlers/dto.py`'s `serialize_product` (doesn't emit it). This is the real prerequisite for Cart's own stock re-validation (FR-2/FR-3) — not an Inventory-side addition. |

**This is a genuine, previously-unflagged inconsistency between the two specs drafted in the same
pass**: MA-120 §7 correctly identifies Catalog Service as the owner of per-product stock quantity
and resolves the gap there; MA-121 §8 independently assumed Inventory Service owns it (or would gain
it) without cross-checking against MA-120's own resolution. Cart Service's stock re-validation (FR-2/
FR-3) must call **Catalog Service**, not Inventory — flagged here rather than silently building
against the wrong service.

**Real, working precedent found for every cross-service call pattern this story needs:**
- `services/user/src/adapters/inventory_client_adapter.py` — the established HTTP-client-with-retry
  pattern (services/README.md §3.7) for one service calling another's `/v1/internal/...` endpoint.
  Cart Service's own client adapters (Catalog, User, Pricing, Wallet) all follow this exact shape.
- `services/identity-auth/src/adapters/otp_store_adapter.py` — the DynamoDB adapter pattern (boto3
  resource, typed exceptions, correlation-ID logging) Cart's own `cart_repository.py` follows.
- `services/user/src/adapters/outbox_event_publisher.py` + `run_local_outbox_publisher.py` — the
  transactional-outbox pattern MA-121 FR-5 calls for. Postgres does this via a same-transaction
  outbox-table insert; DynamoDB's equivalent is `transact_write_items` (see §4D below) — same
  guarantee (event write never lands without the domain write), different primitive.
- `services/identity-auth/infra/identity_auth/identity_auth_stack.py` — the CDK (Python) pattern for
  a Lambda + DynamoDB service; Cart's own `infra/cart/cart_stack.py` follows this shape.
- `services/local-dev/bootstrap.py`'s `bootstrap_dynamodb()` — the moto-backed local DynamoDB table
  creation pattern (`otp_requests`); Cart's `cart` table is added here the same way.

**New prerequisites this story surfaces (small, additive — same category as this SDD chain's other
flagged contract additions):**
1. **Catalog Service** needs MA-120 §7's `available_quantity` addition actually implemented (it's
   spec'd, just not built) — a genuine blocker shared with MA-23, not something this plan can route
   around by calling a different service.
2. **User Service** needs a new internal endpoint for Cart to resolve a caller's delivery-address
   state without re-authenticating as that user — `GET /users/me`'s domain method
   (`get_profile_by_sub(cognito_sub)`) already does exactly this lookup; it just needs a second,
   internal-facing handler wired to it (`GET /v1/internal/users/{cognitoSub}/address-state` or
   similar), matching Inventory's own public-vs-internal endpoint split
   (`serviceability_check_handler.py` vs `internal_serviceability_check_handler.py`). Cart calls it
   with the `sub` claim already present on its own inbound JWT — no new identifier concept needed.
3. **Catalog Service** needs an equivalent internal stock-check endpoint for Cart's FR-2/FR-3 (or
   Cart reuses the existing public `GET /products/{id}` once it carries `availableQuantity` — a
   judgment call for whoever picks up Catalog's own `available_quantity` work; flagged, not decided
   here).

## 3. Implementation Order

1. **Confirm/flag prerequisite #1 above** (Catalog's `available_quantity`) — not built here (out of
   this story's own directory), but nothing in §4 that depends on it can be integration-tested until
   it lands. Domain/unit-level work proceeds against a fake regardless.
2. **`services/user`: internal address-state endpoint** — small, independent, unblocks Cart's own
   delivery-state resolution for its internal `POST /pricing/quote` calls (FR-1).
3. **`services/cart` scaffold** — `src/{handlers,domain,adapters,config}/`, `infra/`, `migrations/`
   (N/A for DynamoDB — table def lives in `infra/`), `tests/`, matching `services/README.md` §4's
   target layout and identity-auth's actual realized structure.
4. **Domain models + `cart_repository.py`** (DynamoDB, single-table: line items + version +
   idempotency records, per MA-121 §7 as merged).
5. **Client adapters**: `catalog_client_adapter.py` (stock check), `user_client_adapter.py`
   (delivery-address state), `pricing_client_adapter.py` (quote — written correctly against MA-101's
   contract, not integration-testable until that service exists), `wallet_client_adapter.py` (balance
   check — same treatment, MA-100 doesn't exist at all).
6. **Domain service** (`cart_service.py`): FR-1–FR-6's business rules.
7. **Handlers** (`get_cart_handler.py`, `add_item_handler.py`, `put_cart_handler.py`,
   `delete_item_handler.py`) + **outbox publisher handler** + `run_local_outbox_publisher.py`.
8. **`local-dev` integration**: `bootstrap.py`'s `cart` table, `run_local.py` shim, README update.
9. **CDK stack** (`infra/cart/cart_stack.py`) — Lambda functions + DynamoDB table definition,
   mirroring `identity_auth_stack.py`.

## 4. Per-File Implementation Steps

### §4A: `services/user` — internal address-state endpoint

**Status: implemented and fixed** — see §1a. This section is updated to describe what's actually
built, not the original (unauthenticated) design.

**Files created:**
- `services/user/src/handlers/internal_address_state_handler.py` —
  `GET /v1/internal/users/address-state?cognitoSub=` (query parameter — matches Inventory's own
  internal-endpoint convention, `?pincode=&lat=&lng=`, not a path parameter as originally drafted
  here). **Not** JWT-authenticated the way `/users/me` is — but also **not** relying on "network
  isolation" as originally planned, since that reasoning doesn't hold for a Lambda + HttpApi service
  (see §1a). Calls the existing `RegistrationService.get_my_profile(cognito_sub)` domain method
  unchanged, and catches `UserServiceError` broadly so a missing user maps to 404 rather than 500.
- Response: `{"defaultAddressState": "Karnataka" | null}` — deliberately narrower than
  `GET /users/me`'s full profile (§11 of MA-93's own spec already establishes "keep this minimal");
  Cart Service has no legitimate need for the caller's name/mobile/accountType.

**Real auth mechanism (`user_stack.py`):**
1. The route is registered with `apigwv2_authorizers.HttpIamAuthorizer()` — AWS_IAM/SigV4
   authorization, the same category of protection the JWT authorizer gives every public route here,
   just for a service-to-service caller instead of an end user. Verified via `cdk synth`: the route
   synthesizes with `AuthorizationType: AWS_IAM`.
2. `UserStack` takes a new `internal_caller_role_arns: tuple[str, ...] = ()` constructor argument.
   For each ARN, the stack imports that role (`iam.Role.from_role_arn(..., mutable=True)`) and
   attaches an `execute-api:Invoke` policy scoped to this route's exact ARN. Defaults to empty —
   **nobody is granted access until a real caller's role ARN is added.**
3. The route's `execute-api` ARN is also exported via `CfnOutput` (`InternalAddressStateRouteArn`),
   so a caller's own stack can instead grant itself directly once it exists, without `user_stack.py`
   needing to know about it in advance.
4. **Cart Service's own execution role doesn't exist yet** (MA-96 itself isn't built) — so today,
   `internal_caller_role_arns` has nothing real to reference. This route is deployed but
   unreachable by design until that changes. Whoever builds Cart's own CDK stack (§4H) must either
   pass its execution role's ARN into `UserStack`, or use the exported output to grant itself —
   this plan's own §4H doesn't do that yet (Cart's stack isn't built), so it's a real follow-up, not
   assumed-done here.
5. Local dev: `services/local-dev/_lambda_local_server.py` doesn't emulate IAM/SigV4 at all (same
   as it doesn't verify the Cognito JWT authorizer's signature on public routes) — the route is
   reachable directly from `localhost:8002` in local dev regardless of the real IAM restriction.
   This is an accepted, documented gap in the local-dev shim generally, not specific to this route.

**Tests written:** `services/user/tests/unit/handlers/test_internal_address_state_handler.py`
(handler-level, mirroring `test_get_me_handler.py`'s shape) and 5 new tests in
`services/user/tests/infra/test_user_stack.py` asserting the route's `AuthorizationType` is
`AWS_IAM` (not JWT, not absent), that `internal_caller_role_arns` produces the expected
`execute-api:Invoke` policy on the given role, and that the default (empty) case grants nobody.

**Acceptance check:** `pytest services/user/tests/` passes — 104 tests, including the 5 new infra
tests (all passing as of 2026-08-27).

---

### §4B: `services/cart` scaffold + domain models

**Files to create:**
- `services/cart/src/domain/models.py` — `LineItem` (id, product_id, quantity, frequency, start_date,
  added_at), `Cart` (line_items, version), `Frequency` enum (`ONE_TIME`/`DAILY`/`ALTERNATE_DAYS`,
  mirrors the mobile `Frequency` enum's wire values exactly — MA-121/MA-101's shared contract).
- `services/cart/src/domain/exceptions.py` — `CartVersionMismatchError`, `StockCheckUnavailableError`,
  `DeliveryAddressRequiredError`, `AddressLookupUnavailableError`, `PricingUnavailableError`,
  `WalletCheckUnavailableError`, `WalletBalanceTooLowError`, `OutOfStockError` — one per distinct
  error code MA-121 §9 enumerates, per services/README.md §5c/§9's "typed exception per failure mode"
  rule.

**Tests to write:** none yet (pure data classes) — covered indirectly by domain-service tests below.

---

### §4C: Client adapters

**Files to create** (all follow `inventory_client_adapter.py`'s shape: retry+backoff via a new
`services/cart/src/adapters/retry.py` copy — per-service duplication, not a shared package, matching
this codebase's existing convention of one `retry.py` per service rather than a central one):

- `catalog_client_adapter.py` — `HttpCatalogClient.get_available_quantity(product_id) -> int | None`,
  calling Catalog Service (endpoint TBD per §2's flagged prerequisite — either the existing public
  `GET /products/{id}` once it carries `availableQuantity`, or a new internal endpoint; whichever
  Catalog's own eventual `available_quantity` work lands as). `None` is a valid response (field still
  absent) — the domain service (§4E) then treats stock as unbounded-but-flagged, mirroring MA-120
  §7's own mobile-side fallback-cap treatment, not a hard failure.
- `user_client_adapter.py` — `HttpUserClient.get_delivery_address_state(cognito_sub) -> str | None`,
  calling §4A's new internal endpoint.
- `pricing_client_adapter.py` — `HttpPricingClient.quote(items, delivery_state, offer_code=None) ->
  Quote`, request/response shaped exactly per MA-101/MA-122's merged contract (including its own
  PR #9 fix: `offerCode` field, tax/delivery-inclusive `monthlyEstimate`). **This adapter is written
  correctly against a service that doesn't exist** — every call will raise
  `ExternalServiceUnavailableError` until MA-101 is implemented; this is expected, not a bug, exactly
  like the mobile app's own `DioPricingRepository` in the same situation.
- `wallet_client_adapter.py` — `HttpWalletClient.get_balance(cognito_sub) -> int`. **No real contract
  exists to code against at all** (MA-100 has no spec) — same treatment as the mobile app's
  `StubWalletBalanceRepository`: this adapter always raises `WalletCheckUnavailableError` (matching
  MA-121 §9's own documented failure mode for "Wallet balance check fails mid-request"), not a real
  HTTP call to an invented endpoint shape.

**Tests to write:** unit tests per adapter (mocked `requests`, matching
`inventory_client_adapter.py`'s own likely test shape — check `services/user/tests/unit/adapters/`
for the exact pattern to mirror) — request shape, retry-on-transient-failure, typed-exception
mapping. `wallet_client_adapter`'s test simply asserts it always raises the documented exception —
there's no "happy path" to test since no real endpoint exists.

---

### §4D: `cart_repository.py` (DynamoDB)

**Schema** (single table `cart`, per MA-121 §7 as merged — PK `userId`, SK a prefixed string):

```
cart (table)
  PK: userId (S)
  SK: SK (S)                    -- "ITEM#{uuid}" | "META" | "IDEMPOTENCY#{key}"
  -- ITEM# rows:
  productId (S), quantity (N), frequency (S), startDate (S, nullable),
  addedAt (S), expiresAt (N)    -- TTL, 30 days from last write
  -- META row (one per user):
  cartVersion (N)                -- incremented on every mutation (FR-1/FR-3)
  -- IDEMPOTENCY# rows:
  responseBody (S), expiresAt (N) -- TTL, 24h
```

**Files to create:**
- `services/cart/src/adapters/cart_repository.py` — `DynamoDbCartRepository` implementing:
  - `get_cart(user_id) -> Cart` (query by PK, split `ITEM#`/`META` rows)
  - `add_item(user_id, item, idempotency_key) -> LineItem` — **DynamoDB `transact_write_items`**:
    put the new `ITEM#` row, an `IDEMPOTENCY#{key}` row (conditional: fails if it already exists —
    this IS the dedup mechanism, not an application-level check), and increment `META`'s
    `cartVersion`, all atomically. A `TransactionCanceledException` on the idempotency-key condition
    means "already processed" — the repository re-reads and returns the prior result rather than
    erroring.
  - `replace_cart(user_id, items, if_version) -> Cart` — `transact_write_items`: assert `META.cartVersion
    == if_version` (conditional check, same transaction), delete every existing `ITEM#` row not in
    the new set, put/update the rest, increment `cartVersion`. The conditional-check failure is what
    `CartVersionMismatchError` (409, FR-3) maps from.
  - `delete_item(user_id, line_item_id) -> None`.

**Outbox write, same transaction:** every `transact_write_items` call above adds one more item — an
`OUTBOX#{eventId}` row in this same table (a fourth `SK` prefix), written atomically alongside the
domain mutation. This is DynamoDB's equivalent of the Postgres "insert an outbox row in the same
transaction as the domain write" pattern `user`'s own outbox uses — same guarantee (the event can
never be missing when the write succeeded, or present when it didn't), different primitive. The
outbox publisher (§4F) drains `OUTBOX#` rows the same way `user`'s own publisher drains its outbox
table. (A separate dedicated outbox table is also a valid choice here — flagged as an
implementation-time call, not fixed by this plan.)

**Tests to write:** unit tests against DynamoDB-local/moto (matching `otp_store_adapter.py`'s own
test fixture pattern) — idempotency-key replay returns the original result without a second `ITEM#`
row; concurrent `replace_cart` with a stale `if_version` raises `CartVersionMismatchError`; TTL
attributes set correctly on every write path.

---

### §4E: `cart_service.py` (domain)

Orchestrates FR-1–FR-6 using only the adapter interfaces above (never boto3/requests directly, per
services/README.md §3.4):

- `get_cart(user_id)`: repository read → resolve delivery-address state (§4C) → call Pricing (§4C)
  for the live breakdown → assemble response. A `None` delivery-state (no default address) raises
  `DeliveryAddressRequiredError`; a `Pricing` call failure raises `PricingUnavailableError` — `GET
  /cart` fails the whole request rather than returning unpriced data (per MA-96/MA-121's own "prices
  must reflect current catalog pricing" requirement — there's no sensible partial response here).
- `add_item(...)`: stock check (Catalog, §4C) → wallet gate (§4E below) for subscription frequencies
  → repository write (idempotency-key-aware).
- `replace_cart(...)`: same stock check per line item; wallet gate scoped to changed/new subscription
  items only (MA-121's own PR #8 fix — an unchanged, already-approved subscription item in the
  replacement set is not re-gated).
- `delete_item(...)`: repository delete, `404` on a missing/foreign id (never distinguishing the two
  in the response, per FR-4's own "doesn't leak whether an ID belongs to a different caller" rule).

**Tests to write:** the bulk of this story's real test coverage — every FR/edge-case combination
against fakes of all four client adapters + the repository, matching
`services/user/tests/unit/domain/test_registration_service.py`'s density/style.

---

### §4F: Handlers + outbox

**Files to create:**
- `handlers/get_cart_handler.py`, `handlers/add_item_handler.py`, `handlers/put_cart_handler.py`,
  `handlers/delete_item_handler.py` — thin, per services/README.md §3.2, mirroring
  `otp_send_handler.py`'s `_get_deps()`-cached-dependency-wiring shape.
- `handlers/dto.py` — request/response DTOs (pydantic), matching `identity-auth`/`user`'s own
  `handlers/dto.py` shape (`success_response`/`error_response` envelope helpers).
- `handlers/outbox_publisher_handler.py` + `run_local_outbox_publisher.py` — drains the
  `OUTBOX#`-prefixed rows (or second table, per §4D's open call) to EventBridge, matching `user`'s
  own `outbox_event_publisher.py`/`run_local_outbox_publisher.py` pair exactly.

**Tests to write:** handler-level tests per services/README.md §6 (routing, auth/JWT-claims
extraction, DTO validation, exception→HTTP-status mapping) — mirror
`test_get_me_handler.py`'s shape.

**Acceptance check:** `pytest services/cart/tests/` — all pass.

---

### §4G: Local-dev integration

**Files to modify:**
- `services/local-dev/bootstrap.py` — add a `bootstrap_cart_table()` function (copy
  `bootstrap_dynamodb()`'s shape: `PAY_PER_REQUEST`, TTL on `expiresAt`, no GSI needed since every
  access pattern is PK-only or PK+SK-prefix).
- `services/local-dev/README.md` — add `cd cart && python run_local.py # :8004` to the "Running the
  services" section (port 8004, matching the mobile app's own `AppConfig.cartBaseUrl` provisional
  port from the MA-23 impl plan §4D) and a `cart && python run_local_outbox_publisher.py` line.

**Files to create:**
- `services/cart/run_local.py` — mirrors `identity-auth`/`user`'s own `run_local.py` (loads
  `.env.local`, routes table, `serve(routes, port=8004)`).

**Acceptance check:** manual round-trip — `POST /cart/items`, `GET /cart`, `PUT /cart`,
`DELETE /cart/items/{id}` against the local stack once Catalog's `availableQuantity` work (§2) has
also landed; until then, `GET /cart` fails closed with `PricingUnavailableError` (Pricing doesn't
exist) — a real, expected, and correctly-surfaced failure, not a bug in this service.

---

### §4H: CDK stack

**Files to create:**
- `services/cart/infra/app.py`, `services/cart/infra/cdk.json`, `services/cart/infra/cart/cart_stack.py`
  — mirrors `identity_auth_stack.py`'s shape: one Lambda function per handler, the `cart` DynamoDB
  table (TTL enabled), least-privilege IAM (per-function DynamoDB read/write scoped to this table
  only, per services/README.md §12's "IAM role scoped least-privilege" done-criterion).

**Not done here:** the actual EventBridge rule wiring for `CartUpdated`'s consumers — MA-121 §8
itself says "no confirmed consumer yet"; the publish side (outbox → EventBridge) is built, but no
downstream rule is created for an unconfirmed consumer.

## 5. Cross-Cutting Steps

- Regression-run `services/user`'s full test suite after §4A (a modification to an existing,
  shipped service, not just an extension).
- `ruff check`/`pytest` clean across every new/modified file, matching this repo's established CI
  gate (seen via `.ruff_cache`/`pytest.ini`-equivalent config in each existing service).

## 6. Test Strategy

Same layering as every other service here: unit (domain, adapters against mocked
`requests`/moto-backed boto3), integration (handler → domain → DynamoDB-local round-trip), contract
(the `POST /pricing/quote` request shape, shared fixture-tested against MA-101/MA-122's own eventual
test suite once that service exists — flagged as a follow-up, not buildable both-sides today).

**Coverage threshold:** same as every prior service — no numeric threshold, "all tests pass" is the
gate.

## 7. Commit Strategy

One commit per lettered step in §4, in order — mirrors the MA-23 impl plan's own convention:

1. `feat(user): internal address-state endpoint for service-to-service calls (MA-96)`
2. `feat(cart): domain models and typed exceptions (MA-96)`
3. `feat(cart): Catalog/User/Pricing/Wallet client adapters (MA-96)`
4. `feat(cart): DynamoDB cart_repository — line items, version, idempotency (MA-96)`
5. `feat(cart): cart_service domain orchestration (MA-96)`
6. `feat(cart): handlers, DTOs, outbox publisher (MA-96)`
7. `feat(cart): local-dev integration (MA-96)`
8. `feat(cart): CDK stack (MA-96)`

## 8. Risks and Blockers

- **Catalog Service's `available_quantity` (MA-120 §7) is a real, shared blocker** — spec'd twice
  (MA-120 and, transitively, here) but implemented nowhere. Cart's stock re-validation can't be
  integration-tested until it lands; unit tests proceed against a fake `catalog_client_adapter`
  regardless.
- **MA-121 §8's Inventory-Service assumption was wrong** — Inventory has no stock-quantity concept
  at all. This plan calls Catalog instead; if a future reviewer expected Inventory, this deviation
  needs sign-off (flagged here, not silently decided).
- **Pricing & Offer Service (MA-101) and Wallet Service (MA-100) don't exist** — `GET /cart` (which
  unconditionally needs a live quote) and any subscription-frequency write (which needs a wallet
  check) cannot be exercised end-to-end at all until those land. This mirrors MA-23's own impl plan
  §2 exactly — the mobile screen and this service are both "fully built, integration-blocked" for
  the same two reasons.
- **The DynamoDB outbox mechanism (§4D) has an open implementation-time choice** (fourth `SK` prefix
  in the same table vs. a second table) — either is correct; flagged for whoever picks up §4D rather
  than decided unilaterally here.
- **New internal endpoints on `services/user`** (§4A) are a small reopening of an already-shipped
  service — per services/README.md §3's "extending an existing service does not require a new-service
  gate but does require reporting what is added and why" — reported here, not requiring the
  new-service architect gate.
- ~~**§4A's internal endpoint had no real auth**~~ — **Fixed 2026-08-27**, see §1a/§4A:
  `HttpIamAuthorizer` + `internal_caller_role_arns`, verified via `cdk synth`. Still requires a
  human to wire Cart Service's real execution role ARN in once its own CDK stack (§4H) exists — the
  route is deployed but deliberately unreachable until then.
- **MA-121 §8 still says this should be "not a new endpoint on `user`'s side," contradicting §4A as
  actually built.** Not a code problem — `get_my_profile` needs a target `cognito_sub` that a
  reused public route has no way to accept safely — but the spec text itself needs a reviewer to
  reconcile it, not another plan to silently route around it.
- **Redis read-through cache (MA-121 §6/§11) is still completely absent from this plan**, with no
  implementation, no explicit deferral, and no sign-off request — exactly as PR #11's review found
  it. Needs an explicit decision (build it with sign-off, or formally defer it) before this story is
  considered complete against its own spec.
- **`cartVersion`'s `META` row still has no TTL/reset policy** (§4D) — line items and idempotency
  records expire; the version counter doesn't, so a cart that's fully expired could still report a
  stale non-zero `cartVersion`, inconsistent with FR-1's "no cart and empty cart are the same state."
  Needs a concrete fix (TTL on `META` too, or an explicit reconciliation rule), not just
  re-acknowledgment.
