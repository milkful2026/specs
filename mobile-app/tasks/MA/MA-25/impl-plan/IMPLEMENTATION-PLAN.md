# Implementation Plan — MA-25: Subscription Module (Start / Stop / Pause)

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-25](https://milkfuldairyindia.atlassian.net/browse/MA-25) — Subscription Module (Start / Stop / Pause) (Flutter) |
| **Date** | 2026-09-21 |
| **Specs implemented** | [MA-130](https://milkfuldairyindia.atlassian.net/browse/MA-130) — Wallet Service: Debit Capability (`services`, extends MA-127) · [MA-131](https://milkfuldairyindia.atlassian.net/browse/MA-131) — Subscription Service: Lifecycle & Daily Run (`services`, new) · [MA-132](https://milkfuldairyindia.atlassian.net/browse/MA-132) — Order Service: Subscription Order Materialization (`services`, new) · [MA-133](https://milkfuldairyindia.atlassian.net/browse/MA-133) — Flutter My Subscriptions & Lifecycle Screens (`mobile-app`) |
| **Spec branch** | `main` (PR #19 merged, merge `e680e4f`, incl. the review-fix revisions `fa92641`) |
| **Repos touched** | `milkful2026/services` (MA-130, MA-131, MA-132, plus a small `services/user` companion change — see Step 6), `milkful2026/milkful-app` (MA-133) |

**What this delivers:** the Schedule tab from the MA-25 mock — a My Subscriptions list, a Vacation Mode toggle, and full per-subscription pause(date-range)/resume/stop/skip-a-day/edit control — backed by two brand-new AWS microservices (**Subscription Service**: lifecycle + a daily scheduled run that decides what's due; **Order Service**: turns a due subscription into a real, paid Order) and one extension to an already-shipped service (**Wallet Service** gains a debit capability, `LedgerType.ORDER_DEBIT`, alongside its existing MA-127 credit side). A subscription created once runs itself — auto-generating a correctly-timed, auto-paid order every due day, honoring pauses/skips/edits, until the customer stops it.

**Codebase reality found during analysis:**
- `services` has **no `order/` and no `subscription/` directory** — both are created from scratch here, mirroring `services/wallet/`'s Fargate/FastAPI layout (single deployable, `main.py` running HTTP + a background thread), **not** `services/cart/`'s Lambda layout. `services/README.md`'s canonical inventory designates Order as Fargate (matches) but Subscription as Lambda — MA-131.md itself already flags and accepts this deviation (§1: "this spec builds a single FastAPI deployable instead... matching every other backend service actually built in this codebase so far, none of which use real Lambda packaging"). Both directories are already placeholders in `services/README.md`'s "Repository Structure (target)" tree (lines 76-77), so their existence isn't a surprise to the architecture doc, just not yet built.
- `services/README.md` §"Human approval gate — new service" requires explicit architect approval before scaffolding a **new** top-level service, with the approval evidenced by documenting why no existing service can own the capability, proposing name/datastore/compute/API, and getting a sign-off. For Subscription and Order, that case is made across MA-131.md §2/§6 and MA-132.md §2 respectively, and the gate is satisfied by the same mechanism MA-126/MA-127 (also new services) went through: an SDD-reviewed spec PR, merged (`e680e4f`) after review-fix (`fa92641`). Noted here per the README's own rule, not re-litigated.
- **`services/shared/`** now holds `adapters/retry.py`, `adapters/outbox_event_publisher.py`, `errors.py`, `handlers/auth.py`, `handlers/health.py` — consolidated during MA-24's own PR #19 review-fix pass (commit `811a11f`, services repo). Unlike `services/wallet/`'s original scaffold (which started with local copies of all four and only got consolidated after review), **Subscription and Order Service should import from `shared/` directly from day one** — no local `adapters/retry.py`, `handlers/auth.py`, or `adapters/outbox_event_publisher.py` files at all. Each service still keeps its own tiny `handlers/health.py` (2 lines: `from shared.handlers.health import ConsumerHealth; consumer_health = ConsumerHealth()`) since that's per-process state, not shared code. Both `payment/Dockerfile` and `wallet/Dockerfile` already build from the `services/` root (`context: ..`) and `COPY shared/ ./shared/` for exactly this reason — the new services' Dockerfiles must do the same from the start, not repeat the bug that required a follow-up fix last time.
- Confirmed by reading `services/payment/src/adapters/wallet_limits_client.py` directly (corrected path — a review pass on this plan mis-cited it as `services/adapters/wallet_limits_client.py`): **most internal service-to-service calls in this codebase are plain unauthenticated HTTP** (`requests` + `shared.adapters.retry.call_with_retry`), not real SigV4/mTLS, despite MA-130 §5's NFR table describing "Internal-only network exposure ... security-group-restricted." **One confirmed exception: `cart/src/adapters/user_client_adapter.py`'s call to `GET /v1/internal/users/address-state`** — that file's own docstring states this specific route *is* SigV4-signed and protected by API Gateway's `HttpIamAuthorizer` (AWS_IAM), and it implements real `botocore`/`boto3` SigV4 signing before every call; an unsigned `requests.get()` against it gets a 403 before User's handler ever runs. Order Service's new `user_client_adapter.py` calls this exact same endpoint (§4 Step 4) and **must sign it the same way** — this is not a "swap in a signer later" adapter like Pricing/Wallet's internal calls, it needs SigV4 from day one. `pricing_client_adapter.py` and `wallet_client_adapter.py` (Order → Pricing, Order → Wallet) do follow the plain-unauthenticated pattern, consistent with `wallet_limits_client.py`'s own doc comment. **Unlike `wallet_limits_client.py`, none of this plan's new adapters use its "cache + fall back to a safe default on failure" behavior** — MA-132.md is explicit that a User/Pricing/Wallet call failure must fail the order materialization closed (message left unacked), never guess a state, a price, or a debit outcome.
- `services/local-dev/docker-compose.yml` **still has no `cart`, `payment`, or `wallet` service entries** — `bootstrap.py` already prepares their `.env.local` files and queues (confirmed reading both), but the compose file itself was never extended past `identity-auth`/`user`/`inventory`/`catalog`. This is a carried-over gap from MA-24, not something this plan introduced; Step 5 below closes it for all six services at once (the three pre-existing plus the two new ones plus `cart`) rather than letting `subscription`/`order` become a seventh and eighth service nobody can actually `docker compose up`.
- Neither `payment/` nor `wallet/` has an `infra/` CDK stack yet either (no `payment_stack.py`/`wallet_stack.py` exist) — confirmed via `find`. The only real Fargate CDK precedent in this repo is `services/inventory/infra/inventory/inventory_stack.py` (`ecs.FargateService` + `ecs.ContainerImage.from_ecr_repository`, **not** `from_asset` — that file's own module docstring explains why). Subscription's and Order's `infra/` stacks in this plan mirror `inventory_stack.py`, not `cart_stack.py` (Lambda) or a nonexistent `wallet_stack.py`.
- `milkful-app` already has `lib/features/wallet/` as the established `Screen → _View → Bloc → Repository(+Fake)` pattern (MA-125/MA-24) to mirror for `lib/features/subscriptions/`. `home_screen.dart`'s `_HomeBottomNav` (index 1, Schedule) and `wallet_screen.dart`'s `_WalletBottomNav` (index 1) are both confirmed still-unwired stubs (`onTap` only handles indices 0/2 in each).
- `ProductConfigBloc` (MA-120/MA-23) already resolves `deliveryState` via `ProfileRepository.getMe().defaultAddressState` for Pricing quotes, but has **no delivery-slot UI at all** — confirmed reading `product_config_state.dart` (no `slotId` field) and `product_config_bloc.dart`. Registration's own one-time `preferredSlotId` is confirmed **not even sent** to the backend anymore (`registration_repository.dart`: "slot preference is now chosen later, from Home's own calendar picker"). MA-133.md's FR-6 fix (PR #19 review) names `RegistrationBloc` (app-wide singleton, provided in `main.dart`) → `RegistrationRepository.getDeliverySlots(zoneId)`, keyed by `state.draft.zoneId`, as "the exact mechanism `home_screen.dart`'s `_DeliverySlotPicker` already uses." **A review pass on this plan found that mechanism doesn't actually work for the common case**: `RegistrationBloc.state.draft.zoneId` is populated only during an active registration session and is discarded (`_draftStorage.clear()`) once registration succeeds — for any returning user opening a new app session, it's `null`. `home_screen.dart`'s own picker degrades gracefully when that happens (`_DeliverySlotPicker` just hides); `ProductConfigScreen`'s slot picker cannot degrade the same way, because `canConfirm` requires a `slotId` for subscriptions — so following FR-6's named mechanism literally would leave Subscribe Now permanently disabled outside the one session where registration just completed. Fixed here by resolving `zoneId` the same way `deliveryState` already is — from the user's profile, not the ephemeral registration draft — via a new `defaultAddressZoneId` field on `GET /users/me`, mirroring the precedent MA-23's own implementation plan §4A/§2.1 already set for `defaultAddressState`. See the new backend companion step at the top of Step 6.

---

## 2. Prerequisites

### `milkful-app` (MA-133)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `--dart-define=SUBSCRIPTION_BASE_URL` / `ORDER_BASE_URL` | **Not done** | New `AppConfig` fields, local-dev defaults `http://localhost:8008` / `http://localhost:8009` (ports 8000-8007 are already taken — confirmed reading `app_config.dart`). |
| `bloc_test`, `mocktail`, `shared_preferences` (dev/runtime) | **Already satisfied** | Same versions `WalletBloc`/`WalletScreen` already use — no new packages needed for this feature. |
| `defaultAddressZoneId` on `GET /users/me` | **Not done** (review-found gap) | `RegistrationBloc.state.draft.zoneId` — MA-133 FR-6's named slot-fetch source — is `null` for any returning user; a small `services/user` companion change (mirrors MA-23's `defaultAddressState` addition) is required so the slot picker has a real `zoneId` outside an active registration session. See Step 6's backend companion sub-step. |

### `services` (MA-130, MA-131, MA-132)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `services/subscription/` directory tree | **Not done** | Create, mirroring `services/wallet/`'s Fargate/FastAPI layout — importing `shared/adapters/retry.py`, `shared/handlers/auth.py`, `shared/adapters/outbox_event_publisher.py` directly, no local copies. |
| `services/order/` directory tree | **Not done** | Same. |
| `services/wallet/` debit extension | **Not done** | No new directory — extends the existing, already-shipped MA-127 service. |
| `services/shared/events/` new schemas | **Not done** | `SubscriptionOrderDue.schema.json`, `OrderPaymentFailed.schema.json`, `WalletDebited.schema.json`, `WalletLowBalance.schema.json` alongside the existing three from MA-24. |
| Aurora databases `milkful_subscription`, `milkful_order` | **Not done** | Add `CREATE DATABASE` lines to `services/local-dev/init-databases.sql` (currently creates `milkful_user`, `milkful_inventory`, `milkful_catalog`, `milkful_wallet`, `milkful_payment`). |
| `order-events-q` + DLQ | **Not done** | Created by Order Service's own `infra/` (CDK) and by local-dev `bootstrap.py`; does not exist yet (no Order Service). |
| `WALLET_LOW_BALANCE_THRESHOLD_PAISE` config | **Not done** | New `WalletSettings` field, default `10000` (₹100), MA-130 §7. |
| `docker-compose.yml` entries for `cart`/`payment`/`wallet` | **Not done (pre-existing gap)** | Carried from MA-24 — closed in Step 5 alongside the two new services, since leaving it open would make `subscription`/`order` the third and fourth services with no working local-dev container. |
| `infra/` CDK stacks for `subscription`/`order` | **Not done** | Mirror `services/inventory/infra/inventory/inventory_stack.py`'s Fargate pattern (`ecs.FargateService`, `ContainerImage.from_ecr_repository`) — the only real Fargate CDK precedent in this repo; `wallet`/`payment` have none yet to copy from either. |
| EventBridge rule `subscription-order-due` (`SubscriptionOrderDue` → `order-events-q`) | **Not done** | CDK in `subscription/infra` (MA-131 §6); local-dev `bootstrap.py` adds the moto equivalent. |
| EventBridge-Scheduler-equivalent for the Daily Run | **Not done, no real local emulation** | MA-131 §6/§11 already flags this as a documented fidelity gap (same shape as Inventory's SQLite-for-Aurora gap) — local-dev uses a cron-like invocation script hitting `POST /internal/run-daily`, not real Scheduler behavior. |

---

## 3. Implementation Order

1. **Shared event schemas** (`services/shared/events/*.schema.json`) — `SubscriptionOrderDue` (Subscription → Order), `OrderPaymentFailed` (Order, new consumer TBD), `WalletDebited`/`WalletLowBalance` (Wallet → future consumers). Written first so every service's contract tests share one source of truth, same rationale as MA-24 Step 1.
2. **MA-130 Wallet Service — debit capability** — extends the already-shipped `services/wallet/` with `debit_for_order`, `POST /wallet/internal/debit`, `GET /wallet/internal/balance`. *Reason:* Order Service (step 4) calls this synchronously on the order-creation critical path; must exist first.
3. **MA-131 Subscription Service** — full new-service scaffold: lifecycle (create/pause/resume/stop/skip/edit), cut-off enforcement, the Daily Run, read APIs. *Reason:* produces `SubscriptionOrderDue`, the event Order Service (step 4) consumes; has no dependency on Order or Wallet's debit extension, so it can build in parallel with step 2 if useful, but is sequenced after it here since step 5's local-dev wiring needs both queues stood up together.
4. **MA-132 Order Service** — full new-service scaffold: the `order-events-q` consumer, User Service (delivery-state) + Pricing Service (quote) + Wallet Service (debit) integration, read APIs. *Reason:* depends on steps 2 and 3 both existing (calls Wallet's new debit endpoint, consumes Subscription's new event) and on Pricing/User Service (already shipped, MA-101/MA-22/MA-96-adjacent).
5. **local-dev wiring** — `subscription` (:8008) and `order` (:8009) added to `docker-compose.yml`, **plus** finally adding the still-missing `cart`/`payment`/`wallet` entries (pre-existing gap, closed here rather than compounding it); `bootstrap.py` creates `order-events-q` + DLQ + the `SubscriptionOrderDue` rule; `apply_migrations.py`/`init-databases.sql` cover the two new databases. *Reason:* enables the end-to-end acceptance run across all four new/extended pieces.
6. **`services/user`: `defaultAddressZoneId`** (review-found gap, not in the original decomposition) — small, additive, independent of steps 1–5; unblocks the slot picker's real `zoneId` source. Can happen in parallel with anything above.
7. **MA-133 Flutter My Subscriptions & Lifecycle Screens** — **may start in parallel with step 1** against `FakeSubscriptionRepository`, same precedent as MA-125 relative to MA-126/MA-127; the real `DioSubscriptionRepository` is validated against the live services once steps 2–5 are done. The slot picker itself depends on step 6 (`defaultAddressZoneId`) landing first. No feature flag (unlike MA-125's `WALLET_ENABLED`) — ships live once merged, per MA-133 §4 FR-1's own decision.

> Steps 2–4 are three separate services/extensions with a linear dependency chain; commit them separately (§7).

---

## 4. Per-Spec Implementation Steps

### Step 1 — Shared event schemas (`services/shared/events/`)

**Files to create:**
- `services/shared/events/SubscriptionOrderDue.schema.json` — per MA-131 §4 FR-8: `subscriptionId, userId, productId, quantity (integer), deliveryDate (date), slotId, correlationId`. Required: all.
- `services/shared/events/OrderPaymentFailed.schema.json` — per MA-132 §6: `eventId, occurredAt, correlationId, orderId, userId, subscriptionId, amountPaise (integer), reason (enum: INSUFFICIENT_BALANCE | WALLET_NOT_ACTIVE | PRODUCT_UNAVAILABLE | DELIVERY_ADDRESS_UNKNOWN)`. Required: all except none (every field always populated at the point this is enqueued). `reason`'s enum is widened beyond MA-132.md's own JSON sample (which only lists `INSUFFICIENT_BALANCE | WALLET_NOT_ACTIVE`) to also cover the `PRODUCT_UNAVAILABLE`/`DELIVERY_ADDRESS_UNKNOWN` cases MA-132.md's own edge-case table (§9, review-fixed) requires — the sample JSON in §6 was written before those two rows were added and was never updated to match; this plan's schema follows the edge-case table, the more complete and more recently reviewed source.
- `services/shared/events/WalletDebited.schema.json` — per MA-130 §6: `eventId, occurredAt, correlationId, userId, walletId, orderId, amountPaise (integer), balanceAfterPaise (integer)`. Required: all.
- `services/shared/events/WalletLowBalance.schema.json` — per MA-130 §6: `eventId, occurredAt, userId, walletId, balancePaise (integer), thresholdPaise (integer), reason (enum: LOW_AFTER_DEBIT | DEBIT_REFUSED)`. Required: all.
- Update `services/shared/events/README.md` — extend the one-paragraph description to cover these four new contracts alongside the existing three.

**Implementation steps:**
1. Draft the four schemas as JSON Schema 2020-12, `additionalProperties: false`, matching `PaymentConfirmed.schema.json`'s existing style exactly.
2. No change needed to `shared/events/__init__.py`'s `load_schema(name)` helper — it already works by filename convention.

**Tests to write:**
- None here directly — exercised by MA-130/131/132's own contract tests (steps 2-4).

**Acceptance check:**
- `python -c "import json; [json.load(open(f)) for f in ['services/shared/events/SubscriptionOrderDue.schema.json', 'services/shared/events/OrderPaymentFailed.schema.json', 'services/shared/events/WalletDebited.schema.json', 'services/shared/events/WalletLowBalance.schema.json']]"` runs clean.

---

### Step 2 — MA-130 Wallet Service: debit capability (extends `services/wallet/`)

**Files to modify:**
- `services/wallet/src/domain/exceptions.py` — add `OrderUserMismatchError(WalletError)` (`error_code="ORDER_USER_MISMATCH"`, `http_status=400`), `InvalidAmountError(WalletError)` (`error_code="INVALID_AMOUNT"`, `http_status=400`), and **`WalletProvisioningPendingError(WalletError)`** (`error_code="WALLET_PROVISIONING_PENDING"`, `http_status=503`, review-added). **`WALLET_NOT_ACTIVE` is deliberately not a new exception class** — per MA-130.md §4 FR-1 (review-fixed), it's a normal 200 response value on `DebitOutcome`, not an HTTP error, so it never goes through the existing `@app.exception_handler(WalletError)` path. `WalletProvisioningPendingError` *is* an exception (503), and is deliberately **not** folded into `WALLET_NOT_ACTIVE` — see the repository step 2 split below; conflating "no wallet row yet" (a provisioning race) with "wallet exists but genuinely inactive" would silently drop the retry semantics the sibling `credit_recharge` consumer already gives the identical race (`RetryableConsumerError`).
- `services/wallet/src/domain/models.py` — no change; `LedgerType.ORDER_DEBIT` already exists (confirmed reading this file — MA-130.md §2's whole problem statement is that this enum value was already anticipated but unused).
- `services/wallet/src/domain/wallet_service.py` — add:
  - `DebitResult(StrEnum)`: `DEBITED`, `INSUFFICIENT_BALANCE`, `WALLET_NOT_ACTIVE` (per MA-130.md §6, review-fixed to include the third value the original enum omitted).
  - `DebitOutcome(dataclass)`: `result: DebitResult`, `balance_paise: int | None` (set for `DEBITED`/`INSUFFICIENT_BALANCE`, `None` for `WALLET_NOT_ACTIVE`), `required_paise: int | None` (set only for `INSUFFICIENT_BALANCE`).
  - `debit_for_order(*, user_id, order_id, amount_paise, correlation_id) -> DebitOutcome` — validates `amount_paise > 0` else raises `InvalidAmountError`; delegates the lock-check-write sequence to `repository.debit_for_order(...)` in one transaction (mirrors `credit_recharge`'s shape exactly, per MA-130.md §6's own instruction: "hold the lock across the whole check-then-write, never release-then-write"); after a `DEBITED` or `INSUFFICIENT_BALANCE` result, computes the post-attempt balance vs. `WALLET_LOW_BALANCE_THRESHOLD_PAISE` and enqueues `WalletLowBalance` (`reason=LOW_AFTER_DEBIT` or `DEBIT_REFUSED`) if under threshold — **not** for `WALLET_NOT_ACTIVE` (no balance to compare).
  - `get_internal_balance(user_id) -> {balancePaise, status}` for FR-3.
- `services/wallet/src/adapters/interfaces.py` — add `debit_for_order(...)` to `WalletRepositoryPort`, doc comment describing the 5-step sequence below.
- `services/wallet/src/adapters/wallet_repository.py` — add `debit_for_order(*, user_id, order_id, amount_paise, correlation_id, outbox_payload_builders)`, one `engine.begin()` transaction:
  1. `SELECT ... FOR UPDATE` the wallet row for `user_id` (the only wallet resolution this method ever does — no `orders` table exists here to resolve a wallet from an `order_id`).
  2. **No wallet row at all** → raise `WalletProvisioningPendingError` (503) rather than returning `WALLET_NOT_ACTIVE` — this is the same `UserRegistered`-before-wallet-exists race `credit_recharge` already treats as retryable (`RetryableConsumerError`), not a settled bad state; folding it into `WALLET_NOT_ACTIVE`'s 200/non-retryable response would let a subscription's first-ever order (the same-day-emission case, §1) permanently fail instead of retrying once provisioning catches up. **Wallet row exists but `status != ACTIVE`** (e.g. `FAILED`) → return `WALLET_NOT_ACTIVE` (no write) — this genuinely is settled, non-retryable. Both checks run **before** the ledger-replay step, since a ledger comparison is meaningless without a locked wallet.
  3. `SELECT` an `ORDER_DEBIT` ledger row with `ref = f"order:{order_id}"`. If it exists but belongs to a **different** `wallet_id` than the one just locked → raise `OrderUserMismatchError` (the only place this check can run — entirely local data, no Order Service call). If it exists and matches → return its `balance_after_paise` as a `DEBITED` replay (no new write).
  4. Else if `balance_paise < amount_paise` → return `INSUFFICIENT_BALANCE` (no write).
  5. Else → `INSERT` the `ORDER_DEBIT` ledger row (`amount_paise = -amount_paise`, `ref = f"order:{order_id}"`), `UPDATE wallets.balance_paise`, `INSERT` a `WalletDebited` outbox row — all in the transaction from step 1.
- `services/wallet/src/handlers/internal_handlers.py` — add `POST /wallet/internal/debit` (body `{userId, orderId, amountPaise, correlationId?}`, all required except `correlationId`) and `GET /wallet/internal/balance?userId=`, same thin/SigV4-gated-in-theory convention as the existing `GET /wallet/internal/limits` in this file. `WalletProvisioningPendingError` goes through the existing `@app.exception_handler(WalletError)` path like any other `WalletError` (503, `{"errorCode": "WALLET_PROVISIONING_PENDING", ...}`) — Order Service's `shared.adapters.retry.call_with_retry` retries a 503 the same way it retries a transport timeout.
- `services/wallet/src/handlers/dto.py` — serializers for the debit/balance response bodies (`{status: "DEBITED", balanceAfterPaise}` / `{status: "INSUFFICIENT_BALANCE", balancePaise, requiredPaise}` / `{status: "WALLET_NOT_ACTIVE"}` / `{balancePaise, status}`).
- `services/wallet/src/config/env.py` — add `WALLET_LOW_BALANCE_THRESHOLD_PAISE` (default `10000`).

**Files to create:**
- No new files — this step is a pure extension of the existing service (per MA-130 §7: no schema migration needed either, `ledger_entries.type` already accepts `ORDER_DEBIT`, `amount_paise` already a signed `BigInteger`).

**Implementation steps:**
1. Add the two new domain exceptions.
2. Add `DebitResult`/`DebitOutcome` + `WalletService.debit_for_order` + `get_internal_balance`.
3. Add `WalletRepositoryPort.debit_for_order` to the interface.
4. Implement `SqlAlchemyWalletRepository.debit_for_order` per the 5-step sequence above.
5. Wire `POST /wallet/internal/debit` + `GET /wallet/internal/balance` in `internal_handlers.py` + `dto.py`.
6. `WALLET_LOW_BALANCE_THRESHOLD_PAISE` config field.
7. `WalletDebited`/`WalletLowBalance` schemas (Step 1) — no new outbox-publisher code needed, the existing `outbox_publisher.py` loop (already shared-consolidated) picks up any new `event_type` row for free.

**Tests to write:**
- Unit (`test_wallet_service.py` additions): `debit_for_order` sufficient → `DEBITED`, correct `balance_after_paise`, ledger `amount_paise` negative, `WalletDebited` outbox row; insufficient → `INSUFFICIENT_BALANCE`, no ledger row, `WalletLowBalance{reason: DEBIT_REFUSED}`; retried (already `DEBITED`) → verbatim replay, no second write; retried (previously `INSUFFICIENT_BALANCE`, wallet recharged since) → re-evaluates fresh; post-debit balance under threshold → `WalletLowBalance{reason: LOW_AFTER_DEBIT}`; wallet exists but `status != ACTIVE` (e.g. `FAILED`) → `WALLET_NOT_ACTIVE`, no ledger row, **assert the HTTP layer returns 200** (regression test for the review-fixed contract-shape gap); **no wallet row at all → raises `WalletProvisioningPendingError`, asserted as a 503, not folded into the 200 `WALLET_NOT_ACTIVE` path** (regression test for the review-fixed provisioning-race gap — this case must remain retryable); `amountPaise <= 0` → `InvalidAmountError`, no repository call; replayed `debit_for_order` for an already-debited `orderId` called with a **different** `userId` → `OrderUserMismatchError`; the first-ever call for a brand-new `orderId` never raises this (regression test — the check must never be a first-call check).
- Integration (`test_wallet_http.py` additions): `POST /wallet/internal/debit` full round trip — sufficient, insufficient, wallet-not-active (asserting `200`), replay, replay under a mismatched `userId`. `GET /wallet/internal/balance` returns the current balance without mutating anything.

**Acceptance check:**
- `cd services/wallet && pytest` — all green.
- `services/local-dev` up → `curl -XPOST localhost:8006/wallet/internal/debit -d '{"userId":"u1","orderId":"o1","amountPaise":10000}'` → `{status:"DEBITED", balanceAfterPaise}`; a second identical call → the same body, verbatim.

---

### Step 3 — MA-131 Subscription Service: full new service

**Files to create** (mirror `services/wallet/`'s Fargate layout; **import `shared/adapters/retry.py`, `shared/handlers/auth.py`, `shared/adapters/outbox_event_publisher.py` directly — no local copies**):
- `services/subscription/Dockerfile` — `context: ..`, `COPY subscription/requirements.txt .`, `COPY subscription/src/ ./`, `COPY shared/ ./shared/` (the correct pattern from day one — see §1's note on why `wallet`/`payment` needed a follow-up fix for this).
- `services/subscription/pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `README.md`.
- `services/subscription/src/__init__.py`, `src/config/__init__.py`, `src/domain/__init__.py`, `src/adapters/__init__.py`, `src/handlers/__init__.py`.
- `services/subscription/src/config/env.py` — pydantic-settings `SubscriptionSettings` prefix `SUBSCRIPTION_`: `SUBSCRIPTION_AWS_REGION`, `SUBSCRIPTION_DB_DSN`, `SUBSCRIPTION_EVENT_BUS_NAME`, `SUBSCRIPTION_CATALOG_BASE_URL`, `SUBSCRIPTION_CUTOFF_HOUR_IST` (default `20`), `AWS_ENDPOINT_URL`.
- `services/subscription/src/domain/models.py` — `ScheduleType(StrEnum){DAILY,ALTERNATE_DAYS,WEEKLY,CUSTOM_DAYS}`; `Schedule{type, days_of_week: list[int] | None}`; `SubscriptionStatus(StrEnum){ACTIVE,PAUSED,STOPPED}`; `Subscription{id, user_id, product_id, quantity, schedule, slot_id, status, start_date, pause_from, pause_until, pending_edit: dict | None, created_at, updated_at}` — exact shape from MA-131 §6.
- `services/subscription/src/domain/exceptions.py` — `SubscriptionNotFoundError` (404), `InvalidScheduleError` (400), `InvalidRangeError` (400, `from`>`until` or past `from`), `SubscriptionStoppedError` (409, resume-from-stopped), `DateNotDueError` (400, skip a non-due date), `CutoffPassedError` (409, skip/edit after cut-off), `ProductNotEligibleError` (400/422, create with a non-subscription-eligible product), `ServiceUnavailableError` (503, DB unreachable) — mirrors `wallet`'s `WalletError` base-class-with-`error_code`/`http_status` pattern exactly.
- `services/subscription/src/domain/subscription_service.py` — `SubscriptionService`:
  - **`is_due(subscription, target_date) -> bool`** — the reusable due-computation function MA-131.md's review-fix requires be callable for an arbitrary `target_date`, not just literally "tomorrow": `target_date < subscription.start_date` → `False` unconditionally (the explicit guard the review added, applying uniformly before any type-specific check — **not** safe to infer from `ALTERNATE_DAYS`'s parity formula alone, per MA-131.md §6: the formula is periodic and can still land on `0` for a `target_date` before `start_date`, e.g. two full periods early, and Python's modulo of a negative `timedelta.days` doesn't reliably exclude every pre-`start_date` date either — corrected here from an earlier, math-incorrect draft of this rationale that claimed the formula only breaks down "far enough" before `start_date`, which isn't how modular parity behaves); else `DAILY` → `True`; `ALTERNATE_DAYS` → `(target_date - start_date).days % 2 == 0`; `WEEKLY`/`CUSTOM_DAYS` → `target_date`'s ISO weekday in `schedule.days_of_week`. Also excludes a `target_date` inside `[pause_from, pause_until]` (or from `pause_from` onward if `pause_until` is absent) and a `target_date` matching a `subscription_skips` row.
  - `create(user_id, product_id, quantity, schedule, start_date, slot_id, idempotency_key, correlation_id) -> {subscriptionId, status, nextDeliveryDate}` — FR-1: idempotent on `idempotency_key`; validates `product_id` via Catalog `GET /products/{id}` (must exist + `subscriptionEligible`) else `ProductNotEligibleError`; validates `schedule` (`days_of_week` required/non-empty for `WEEKLY`/`CUSTOM_DAYS`, absent for `DAILY`/`ALTERNATE_DAYS`) else `InvalidScheduleError`; inserts the row `ACTIVE`. **Same-day case (review-fixed)**: if `start_date == today` and `is_due(subscription, today)` and now is still before today's `SUBSCRIPTION_CUTOFF_HOUR_IST`, emits `SubscriptionOrderDue{deliveryDate: today}` synchronously in the same create transaction, recorded in `subscription_run_log` exactly like the Daily Run would (so this call's own retry is idempotent and the Daily Run never double-emits for that date) — this is the *only* way a `start_date == today` subscription ever gets its first delivery, since the Daily Run structurally only ever computes tomorrow's due list (see `run_daily` below) and this subscription didn't exist at yesterday's run. `nextDeliveryDate` in the response is computed via `is_due` projected forward from tomorrow (or from today if the same-day emit fired).
  - `pause(id, from_, until) -> Subscription` — FR-2: both optional per the three pause shapes; past `from_` or `until < from_` → `InvalidRangeError`; a new pause call replaces any existing window entirely (not additive).
  - `resume(id) -> Subscription` — FR-3: clears the pause window; `STOPPED` → `SubscriptionStoppedError` (409).
  - `stop(id) -> Subscription` — FR-4: terminal, idempotent (already-`STOPPED` is a no-op 200).
  - `skip(id, date) -> None` — FR-5: `date` must satisfy `is_due(subscription, date)` else `DateNotDueError`; must be before that date's cut-off else `CutoffPassedError`; recorded in `subscription_skips` (append-only).
  - `edit(id, quantity, schedule) -> {effectiveFrom}` — FR-6: re-validates `schedule` the same way `create` does; before cut-off for the next due date → applies immediately (`pending_edit = None`); after → stores `pending_edit = {quantity, schedule, effective_from: <due-date-after-next>}`, applied by `run_daily` (below) before that run's own due-check.
  - `list_for_user(user_id) -> list[Subscription]`, `get(id, user_id) -> Subscription` — FR-9, `nextDeliveryDate` computed via `is_due` projected forward per subscription.
  - `run_daily(now) -> list[str]` — FR-8: fetches `list_logged_subscription_ids(tomorrow)` **once** up front (not per-subscription — see the repository note above), then for every `ACTIVE` subscription: applies any `pending_edit` whose `effective_from <= tomorrow`, calls `is_due(subscription, tomorrow)`, and for each due one not already in that in-memory set, emits `SubscriptionOrderDue{deliveryDate: tomorrow}` (Scheduler-retry idempotency). One bad subscription's exception is logged and does **not** abort the run (MA-131 §5 NFR: "isolate failures").
- `services/subscription/src/adapters/interfaces.py` — `SubscriptionRepositoryPort`, `CatalogClientPort`.
- `services/subscription/src/adapters/subscription_repository.py` — Aurora (psycopg): `insert_if_absent` (idempotency key), `get_by_id`, `list_by_user`, `update_status`/`update_pause`/`update_pending_edit`, `insert_skip`, `has_run_logged(subscription_id, date)` (single-row check, used by `create`'s same-day-emission path — see FR-1 — where only one subscription is ever involved), `list_logged_subscription_ids(date) -> set[str]` (**new, batched** — one query returning every `subscription_id` already logged for `date`, used by `run_daily` instead of calling `has_run_logged` per subscription; closes the N+1 the plan's own "batched, not one query per subscription" NFR otherwise only half-applies), `insert_run_log`, `list_active` (for the Daily Run's batch query — MA-131 §5 NFR: "batched due-date computation, not one query per subscription"), plus the shared outbox-insert-in-the-same-tx pattern `credit_recharge`/`debit_for_order` both already establish.
- `services/subscription/src/adapters/catalog_client_adapter.py` — `GET {SUBSCRIPTION_CATALOG_BASE_URL}/products/{id}`, `shared.adapters.retry.call_with_retry`, no fallback (fails closed per FR-1's "Catalog unavailable → create fails closed" requirement) — mirrors `cart/src/adapters/catalog_client_adapter.py`'s shape, not `wallet_limits_client.py`'s (which does fall back).
- `services/subscription/src/handlers/composition.py`, `dto.py`, `app.py` (FastAPI app + `@app.exception_handler(SubscriptionError)`, mirrors `wallet/src/handlers/app.py`), `dependencies.py`, `health.py` (2-line singleton wrapper per §1), `subscription_handlers.py` (FR-1–FR-7, FR-9 routes, Cognito via `shared.handlers.auth.current_user_id`), `internal_run_daily_handler.py` (`POST /internal/run-daily`, network-level-auth-only like Wallet's internal routes), `outbox_publisher.py` (thin wrapper around `shared.adapters.outbox_event_publisher.EventBridgeOutboxPublisher`, mirrors `wallet/src/handlers/outbox_publisher.py`).
- `services/subscription/src/main.py` — mirrors `wallet/src/main.py`: local-env-file load, FastAPI + uvicorn in the main thread; **no background SQS-consumer thread** (Subscription Service consumes nothing) — instead nothing extra runs in-process; the Daily Run is triggered externally via `POST /internal/run-daily`, not a loop this process owns.
- `services/subscription/migrations/0001_subscriptions.sql` — `subscriptions` (columns matching the dataclass, `schedule`/`pending_edit` JSONB per MA-131 §7's "matches Catalog/Payment's own established JSONB convention"), `subscription_skips (subscription_id, skipped_date)`, `subscription_run_log (subscription_id, delivery_date)` UNIQUE, `outbox` (same shape as every other service).
- `services/subscription/infra/` — CDK stack (`subscription_stack.py`) mirroring `inventory_stack.py`'s Fargate pattern: `ecs.FargateService` behind an internal ALB, Aurora `subscriptions` cluster, EventBridge Scheduler rule → `POST /internal/run-daily` (the real Scheduler-to-HTTP-target wiring; local-dev only emulates this with a script, per §2's prerequisite note), EventBridge rule/permission for `SubscriptionOrderDue` → the (Order Service-owned) `order-events-q`, Secrets/KMS, IAM.
- `services/subscription/tests/` — `conftest.py`, `unit/domain/test_subscription_service.py`, `unit/adapters/test_subscription_repository.py`, `integration/test_subscription_http.py`.

**Files to modify:**
- `services/local-dev/init-databases.sql` — add `CREATE DATABASE milkful_subscription;`
- `services/local-dev/apply_migrations.py` — add `("subscription", "milkful_subscription")`.

**Implementation steps:**
1. Scaffold the tree from `services/wallet/` (copy structure, strip wallet domain, repoint `shared.*` imports — no local `retry.py`/`auth.py`/`outbox_event_publisher.py`).
2. `0001_subscriptions.sql`.
3. Implement `SubscriptionRepository` (psycopg), including `list_active` and `list_logged_subscription_ids` both batched for the Daily Run — no per-subscription query in `run_daily`.
4. Implement `is_due` — every schedule type **plus** the explicit `target_date < start_date` guard, as its own well-isolated, heavily-unit-tested function (it's called from three places: `create`'s same-day case, `run_daily`, and `nextDeliveryDate` projection — get it right once).
5. Implement `create` (incl. the same-day emit), `pause`, `resume`, `stop`, `skip`, `edit`.
6. Implement `run_daily` (applies `pending_edit` → `is_due` → emit → `subscription_run_log`, isolating per-subscription failures).
7. Implement `list_for_user`/`get` (FR-9, `nextDeliveryDate` via `is_due`).
8. `catalog_client_adapter.py` (fail-closed, no fallback).
9. Wire `composition.py`, `app.py`, all handlers, `main.py`.
10. CDK stack (mirror `inventory_stack.py`) + local-dev wiring (step 5).

**Tests to write:**
- Unit (`test_subscription_service.py`): create — all four schedule types valid, invalid `daysOfWeek` (empty for `WEEKLY`), non-eligible product rejected, idempotent replay; **same-day emission**: `startDate == today` + due + before cutoff → one `SubscriptionOrderDue{deliveryDate: today}` + `subscription_run_log` row; same case after cutoff → no emission, `nextDeliveryDate` is the real next due date; a retried create call never double-emits. Pause/resume/stop/skip/edit per MA-131 §10's own bullet list. `is_due`: one case per `ScheduleType`, **plus** a dedicated `target_date < startDate` regression case per type (not just `ALTERNATE_DAYS`) — including a `DAILY`/`WEEKLY` case whose weekday/daily-always condition would otherwise be satisfied, proving the guard is schedule-type-independent. `run_daily`: paused/skipped exclusion, `pending_edit` applied before due-check, duplicate run for the same cut-off emits nothing new, one bad subscription's exception doesn't abort the batch.
- Integration (`test_subscription_http.py`): full round trip create→pause→resume→skip→edit→stop; `POST /internal/run-daily` against a seeded mixed set → the exact `SubscriptionOrderDue` set, schema-validated against `shared/events/SubscriptionOrderDue.schema.json`.

**Acceptance check:**
- `cd services/subscription && pytest` — all green; `ruff check` clean.
- A subscription created via `POST /subscriptions`, run through several simulated Daily Runs (fake clock), produces exactly the due-date sequence its schedule predicts, including its same-day delivery when `startDate == today`.

---

### Step 4 — MA-132 Order Service: full new service

**Files to create** (mirror `services/wallet/`'s Fargate layout; shared `retry`/`auth`/`outbox` imports, same as Step 3):
- `services/order/Dockerfile` — same `context: ..` + `COPY shared/ ./shared/` pattern as Step 3.
- `services/order/pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `README.md`.
- `services/order/src/config/env.py` — `OrderSettings` prefix `ORDER_`: `ORDER_AWS_REGION`, `ORDER_DB_DSN`, `ORDER_EVENT_BUS_NAME`, `ORDER_EVENTS_QUEUE_URL` (`order-events-q`), `ORDER_USER_INTERNAL_BASE_URL`, `ORDER_PRICING_BASE_URL`, `ORDER_WALLET_INTERNAL_BASE_URL`, `AWS_ENDPOINT_URL`.
- `services/order/src/domain/models.py` — `OrderStatus(StrEnum){CREATED,CONFIRMED,PAYMENT_FAILED,FAILED}`; `Order{id, user_id, subscription_id, product_id, quantity, amount_paise, delivery_date, status, failure_reason, created_at, confirmed_at}` — exact shape from MA-132 §6.
- `services/order/src/domain/exceptions.py` — `OrderNotFoundError` (404), `ServiceUnavailableError` (503) — same pattern as every other service.
- `services/order/src/domain/order_service.py` — `OrderService`:
  - `materialize(subscription_id, user_id, product_id, quantity, delivery_date, slot_id, correlation_id) -> None` — FR-1/FR-2, the consumer's core logic:
    1. `(subscription_id, delivery_date)` already has an `Order` row: `CONFIRMED` or `PAYMENT_FAILED` → true no-op, return immediately (idempotency, DB-level UNIQUE backstop). Still `CREATED` (a prior attempt crashed between step 4's insert and step 5's debit call) → **resume at step 5** with the existing row's `order_id`/`amount_paise`, skipping steps 2-4 rather than re-inserting or silently dropping the redelivery.
    2. Resolve `deliveryState` via `user_client.get_delivery_address_state(user_id)` (User Service's `GET /v1/internal/users/address-state?cognitoSub={userId}` — **the same internal endpoint Cart Service already calls for the identical need**, confirmed reading `cart/src/adapters/user_client_adapter.py`). **This call is SigV4-signed** — see §1's corrected finding and the adapter description below; it is not part of this plan's general unauthenticated-internal-HTTP pattern. No profile / unavailable → `PAYMENT_FAILED`-shaped materialization with `reason: DELIVERY_ADDRESS_UNKNOWN` (message stays unacked at the handler level so this whole attempt retries — see the consumer below).
    3. Get a quote via `pricing_client.quote(items=[{productId, quantity, frequency: "ONE_TIME"}], deliveryState)` (Pricing Service's `POST /pricing/quote`, **not** a raw Catalog lookup — `frequency: "ONE_TIME"` because each delivery is priced and charged individually, never as a monthly aggregate). `amount_paise = round(quote.netPayable * 100)` (Pricing/Catalog return rupees; this service is paise throughout). `PRODUCT_PRICING_UNKNOWN` from Pricing → `PAYMENT_FAILED`-shaped, `reason: PRODUCT_UNAVAILABLE`; any other Pricing failure → fails closed, message unacked.
    4. Insert **only** the `Order` row `CREATED` — no outbox row yet (clarifying an ambiguity in MA-132.md §6, which reads as if a placeholder outbox row is written here too; there is nothing publishable yet at this point, since the outcome — confirmed or failed — isn't known until step 5 resolves). `(subscription_id, delivery_date)` UNIQUE at insert time is what makes re-entry after a crash between this step and step 5 safe (a redelivered message re-enters `materialize` and resumes via step 1's `CREATED`-row check above, rather than re-inserting).
    5. Call `wallet_client.debit(user_id, order_id, amount_paise, correlation_id)` (Wallet Service's new `POST /wallet/internal/debit`, Step 2) **outside** the DB transaction from step 4 (an external HTTP call inside a held DB transaction is the exact anti-pattern MA-132 §6 calls out as avoided elsewhere in this codebase). Exactly **one** outbox row is written here, in the same transaction as the status update, once the outcome is actually known: `DEBITED` → `set_status(CONFIRMED, confirmed_at=now)` + insert one `OrderConfirmed` outbox row; `INSUFFICIENT_BALANCE`/`WALLET_NOT_ACTIVE` → `set_status(PAYMENT_FAILED, failure_reason)` + insert one `OrderPaymentFailed` outbox row; a transport failure/timeout → leave `CREATED`, propagate the exception so the consumer (below) does **not** ack the message (safe to redeliver — a redelivery re-enters `materialize`, step 1's `(subscription_id, delivery_date)` lookup finds the existing `CREATED` row and resumes from step 5 rather than re-inserting, and Wallet's own `orderId` idempotency, Step 2, makes a repeated debit call safe either way).
  - `get(order_id, user_id) -> dict`, `list_for_user(user_id, subscription_id, limit, cursor) -> Page` — FR-3, keyset-paginated newest-first (mirrors Wallet's own `list_transactions` convention).
- `services/order/src/adapters/interfaces.py` — `OrderRepositoryPort`, `UserClientPort`, `PricingClientPort`, `WalletClientPort`.
- `services/order/src/adapters/order_repository.py` — Aurora (psycopg): `get_by_subscription_and_date`, `insert_created`, `set_status`, `get`, `list_for_user` (keyset), `enqueue_outbox` — same shape as `payment_repository.py`/`wallet_repository.py`.
- `services/order/src/adapters/user_client_adapter.py` — `GET {ORDER_USER_INTERNAL_BASE_URL}/v1/internal/users/address-state?cognitoSub={userId}`, `shared.adapters.retry.call_with_retry`, no fallback (fails closed, matching `materialize` step 2 above) — mirrors `cart/src/adapters/user_client_adapter.py` **including its SigV4 request signing** (`botocore.auth.SigV4Auth` via a `boto3.Session()`, signed before every call) — this route is `HttpIamAuthorizer`-protected at API Gateway; an unsigned request 403s before User's handler runs. This is the one adapter in this service that is *not* plain unauthenticated HTTP (§1).
- `services/order/src/adapters/pricing_client_adapter.py` — `POST {ORDER_PRICING_BASE_URL}/pricing/quote`, `shared.adapters.retry.call_with_retry`, no fallback — mirrors `cart/src/adapters/pricing_client_adapter.py`.
- `services/order/src/adapters/wallet_client_adapter.py` — `POST {ORDER_WALLET_INTERNAL_BASE_URL}/wallet/internal/debit`, branches on the response's `status` field (`DEBITED`/`INSUFFICIENT_BALANCE`/`WALLET_NOT_ACTIVE` all 200s per Step 2's contract-shape fix — this adapter must **not** treat any of the three as an HTTP error). A `503 WALLET_PROVISIONING_PENDING` (Step 2, review-added) is **not** one of the three — `shared.adapters.retry.call_with_retry` retries it like any other 5xx, and if it's still failing after retries it propagates as the ordinary transport-failure exception `materialize` step 5 already leaves `CREATED`/unacked for, so a subscription's first order right after registration retries via SQS redelivery instead of permanently failing.
- `services/order/src/adapters/order_events_consumer.py` — SQS handler for `order-events-q`: parse `SubscriptionOrderDue` (validate against `shared/events/SubscriptionOrderDue.schema.json` first, same `jsonschema.ValidationError`-caught pattern MA-24's own PR #19 review fixed in Wallet's consumer — MA-132 §8 cites this exact precedent), call `order_service.materialize(...)`; delete the message only after `materialize` completes without raising.
- `services/order/src/handlers/composition.py`, `dto.py`, `app.py`, `dependencies.py`, `health.py` (2-line shared wrapper), `order_handlers.py` (FR-3 routes, Cognito via `shared.handlers.auth`), `outbox_publisher.py` (thin `shared.adapters.outbox_event_publisher` wrapper).
- `services/order/src/main.py` — mirrors `wallet/src/main.py`: background SQS-consumer thread (`order_events_consumer.poll_once` loop, this service's equivalent of Wallet's own consumer thread) + FastAPI/uvicorn in the main thread.
- `services/order/migrations/0001_orders.sql` — `orders` table (`UNIQUE(subscription_id, delivery_date)`, `CHECK (amount_paise > 0)`), `outbox` — per MA-132 §7.
- `services/order/infra/` — CDK stack (`order_stack.py`) mirroring `inventory_stack.py`'s Fargate pattern: Fargate service, Aurora `orders`, **owns `order-events-q` + DLQ** (this service's own queue — Order Service creates and owns the queue Subscription Service's EventBridge rule targets; no existing Payment/Wallet CDK stack to contrast against, since neither exists yet per §1), IAM (`sqs:*` on its queue, `events:PutEvents`, `rds` connect, **plus `execute-api:Invoke` scoped to User Service's `address-state` API Gateway resource** — the one outbound call this service SigV4-signs, per the corrected `user_client_adapter.py` note above; `pricing_client_adapter.py`/`wallet_client_adapter.py` need no such grant).
- `services/order/tests/` — `conftest.py`, `unit/domain/test_order_service.py`, `unit/adapters/test_order_events_consumer.py`, `integration/test_order_flow.py`.

**Files to modify:**
- `services/local-dev/init-databases.sql` — add `CREATE DATABASE milkful_order;`
- `services/local-dev/apply_migrations.py` — add `("order", "milkful_order")`.

**Implementation steps:**
1. Scaffold from `services/wallet/`.
2. `0001_orders.sql`.
3. `user_client_adapter.py`, `pricing_client_adapter.py`, `wallet_client_adapter.py` — all fail-closed, no fallback; `wallet_client_adapter.py`'s three-way 200-status branch specifically (not an error-status branch); `user_client_adapter.py` specifically SigV4-signed (see adapter description above) — verify against a real API Gateway `HttpIamAuthorizer` in local-dev/staging before assuming an unsigned call would work.
4. `OrderService.materialize` — the full insert→price→debit sequence, HTTP call kept outside the DB transaction.
5. `order_events_consumer.py` — schema validation + the `jsonschema.ValidationError` catch (MA-24 PR #19 precedent).
6. `OrderService.get`/`list_for_user` (FR-3).
7. Wire `composition.py`, `app.py`, handlers, `main.py` (consumer thread + FastAPI).
8. CDK stack incl. `order-events-q` ownership; local-dev wiring (step 5).

**Tests to write:**
- Unit (`test_order_service.py`): fresh `SubscriptionOrderDue` → order created, Pricing quoted with `frequency: ONE_TIME`, `amountPaise` correctly tax/delivery-fee-inclusive (regression test for the review-fixed pricing gap — assert `amountPaise > catalogPrice * quantity * 100` whenever tax/delivery fee is non-zero), Wallet debited with the right `orderId`/`amountPaise`, `DEBITED` → `CONFIRMED` + `OrderConfirmed` enqueued. `INSUFFICIENT_BALANCE`/`WALLET_NOT_ACTIVE` from Wallet → `PAYMENT_FAILED` + `OrderPaymentFailed`, reason recorded, **asserting the wallet client never raised** (both are 200-status responses per Step 2); **Wallet returns `503 WALLET_PROVISIONING_PENDING`** (no wallet row yet, e.g. a subscription's same-day-emission order racing registration) **→ order stays `CREATED`, exception propagates, message not acked** — regression test that this case is *not* treated the same as `WALLET_NOT_ACTIVE`. Redelivered message for an already-materialized pair → no second Pricing/Wallet call. Pricing reports `PRODUCT_PRICING_UNKNOWN` → `PAYMENT_FAILED`/`PRODUCT_UNAVAILABLE`. User Service has no address for `userId` → `PAYMENT_FAILED`/`DELIVERY_ADDRESS_UNKNOWN`. Wallet transport failure → order stays `CREATED`, exception propagates (message not acked). User/Pricing unavailable (not a typed refusal, a real outage) → order not created, message not acked.
- Unit (`test_order_events_consumer.py`): a schema-invalid `SubscriptionOrderDue` message is caught, left for redelivery/DLQ, does not crash the poll loop (mirrors MA-24 PR #19's wallet-consumer regression test exactly).
- Integration (`test_order_flow.py`): seed a `SubscriptionOrderDue`-shaped SQS message → consumer processes it → fake User/Pricing/Wallet clients return success → `orders` row `CONFIRMED`, an `OrderConfirmed` event schema-validated on the mocked bus. Same flow with a fake Wallet client returning `INSUFFICIENT_BALANCE` → `PAYMENT_FAILED` + `OrderPaymentFailed`, schema-validated.

**Acceptance check:**
- `cd services/order && pytest` — all green; `ruff check` clean.
- `GET /orders/me` reflects both a `CONFIRMED` and a `PAYMENT_FAILED` order correctly after the above flows.

---

### Step 5 — local-dev wiring (all five services)

**Files to modify:**
- `services/local-dev/docker-compose.yml` — add `subscription` (build `../subscription`, port `8008:8008`), `order` (build `../order`, port `8009:8009`, plus an `order-events-consumer` thread already inside `main.py` — no separate container needed, mirroring `wallet`'s own single-deployable-does-both convention), `depends_on: [bootstrap]`, outbox-loop/reconcile containers matching each service's own established pattern (`order-outbox`, `subscription-outbox`). **In a separate commit**, also add the still-missing `cart` (build `../cart`), `payment` (build `../payment`, port `8007:8007`), `wallet` (build `../wallet`, port `8006:8006`) entries carried over from MA-24 (§1), plus their own outbox/reconcile containers (`payment-reconcile`, `wallet-invariant-check`) — a real, pre-existing gap worth closing now rather than compounding it to a sixth missing service, but kept as its own commit (see Implementation step 3 and §7) rather than folded into MA-25's own wiring.
- `services/local-dev/bootstrap.py` — add: create `milkful_subscription`/`milkful_order` DBs (or rely on `init-databases.sql`); create SQS `order-events-q` + `order-events-q-dlq`; create EventBridge rule `SubscriptionOrderDue → order-events-q`; write `subscription/.env.local` + `order/.env.local` with the bus name, queue URL, DSNs, `ORDER_USER_INTERNAL_BASE_URL=http://localhost:8002`, `ORDER_PRICING_BASE_URL=http://localhost:8005`, `ORDER_WALLET_INTERNAL_BASE_URL=http://localhost:8006`, `SUBSCRIPTION_CATALOG_BASE_URL=http://localhost:8003`.
- `services/local-dev/init-databases.sql` — `CREATE DATABASE milkful_subscription;` + `CREATE DATABASE milkful_order;` (done in steps 3/4).
- `services/local-dev/apply_migrations.py` — include `subscription` and `order` (done in steps 3/4).
- A cron-like local invocation script (new, e.g. `services/local-dev/run_daily_local.py`) that `POST`s `http://localhost:8008/internal/run-daily` — the documented Scheduler-emulation gap (MA-131 §6/§11), not real EventBridge Scheduler behavior.
- `services/local-dev/README.md` — document the two new services (ports 8008/8009), the closed `cart`/`payment`/`wallet` compose gap, and the end-to-end subscription→order→debit curl recipe.

**Implementation steps:**
1. `init-databases.sql` + `apply_migrations.py` (from steps 3/4).
2. `bootstrap.py` — `order-events-q` + DLQ + the `SubscriptionOrderDue` rule + the two new `.env.local` writers.
3. `docker-compose.yml` — **`subscription` and `order` entries only**, as their own commit (§7). The pre-existing `cart`/`payment`/`wallet` gap (carried from MA-24, §1) is real and worth closing, but is orthogonal to this feature's own two new services — closed as a **separate commit in the same PR** (not a separate PR — see §7's reasoning) so a reviewer can tell "infra catch-up" from "MA-25's own wiring" at a glance, and so it doesn't collide with an unrelated parallel fix to the same file.
4. `run_daily_local.py` + README recipe.

**Acceptance check:**
- `cd services/local-dev && docker compose up -d` → all containers healthy, including the three that were missing before this plan; `bootstrap` exits 0; `aws --endpoint-url http://localhost:5000 sqs list-queues` shows `order-events-q` + DLQ; `events list-rules` shows the `SubscriptionOrderDue` rule.
- End-to-end: register a user → recharge the wallet (MA-24 flow) → `POST /subscriptions` (DAILY, `startDate: today`) → same-day `SubscriptionOrderDue` fires → Order Service materializes, quotes via Pricing, debits via Wallet → `GET /orders/me` shows one `CONFIRMED` order for today, `GET /wallet/me` balance decreased by the tax/delivery-fee-inclusive amount.

---

### Step 6 — MA-133 Flutter My Subscriptions & Lifecycle Screens (`milkful2026/milkful-app`)

**Backend companion change — `services/user`: `defaultAddressZoneId` (review-found; required before the slot picker below can work for a returning user).** Mirrors the precedent MA-23's own implementation plan §4A/§2.1 set for `defaultAddressState`, but the underlying data doesn't exist yet — the mobile app's own `checkServiceability` call (`GET {inventoryBaseUrl}/v1/serviceability/check`, made during address entry) already resolves a `zoneId`, but `AddressDraft.toRegisterJson()` never sends it to `POST /users/register`, so `addresses_table` has no `zone_id` column and never has. Lands on the **services repo**, `services/user`, as its own commit (§7):
- `services/user/migrations/` — new migration: `ALTER TABLE addresses ADD COLUMN zone_id VARCHAR(64);` (nullable — existing rows and any registration that predates this change have no zone).
- `services/user/src/domain/models.py` — `Address` gains `zone_id: str | None = None`; `UserProfile` gains `default_address_zone_id: str | None = None` (alongside the existing `default_address_state`).
- `services/user/src/adapters/user_repository.py` — `addresses_table` gains the `zone_id` column; the `register(...)` insert persists `address.zone_id` for each address row; `_fetch_user_with_default_address`'s existing default-address query already selects the whole row, so `get_profile_by_sub` threads `default_row.zone_id` into `UserProfile.default_address_zone_id` exactly the way it already threads `default_row.state` (`None` when no default address, same fallback as `default_address_state`).
- `services/user/src/handlers/dto.py` — `serialize_user_profile` adds `"defaultAddressZoneId": profile.default_address_zone_id`.
- `services/user/src/domain/registration_service.py` / the `RegistrationRequest` path — no change needed; `Address.zone_id` flows through from the request body's `addresses` entries, which the mobile change below now populates.

**Mobile-side companion change (still services/user's commit boundary conceptually, but these files live in `milkful-app` — folded into Step 6.5's commit since they're both needed for the same slot picker to work):**
- `lib/features/onboarding/models/registration_draft.dart` — `AddressDraft` gains `final String? zoneId;`, included in `toRegisterJson()` as `'zoneId'` (omitted when null, same pattern as `landmark`) and in `toDraftJson()`/`fromDraftJson()` for local persistence.
- `lib/features/onboarding/presentation/address_screen.dart` (or wherever `checkServiceability`'s result is currently consumed to build the submitted `AddressDraft`) — thread `ServiceabilityResult.zoneId` into the `AddressDraft` being built, instead of leaving it to live only in `RegistrationBloc`'s separate `draft.zoneId` tracking.
- `lib/features/auth/models/user_profile.dart` — add `final String? defaultAddressZoneId;`, parsed in `fromJson`, added to `props` (same shape as `defaultAddressState`).
- `test/features/auth/models/user_profile_test.dart`, `services/user/tests/` — extend fixtures for the new field, both directions.

**Tests to write (backend):**
- Unit: `register` persists `zone_id` on each address row when the request supplies it, `None` when it doesn't (backward-compatible with any client that predates this field).
- Unit: `get_profile_by_sub` returns `default_address_zone_id` from the default address row when one exists and has one, `None` otherwise (mirrors the existing `default_address_state` test).
- Unit: `serialize_user_profile` emits `defaultAddressZoneId` from `profile.default_address_zone_id`, both populated and `None`.
- Regression: existing `GET /users/me` and `POST /users/register` integration tests still pass with the new field present but unpopulated by old request bodies.

**Files to create:**
- `lib/features/subscriptions/models/schedule.dart` — `ScheduleType{daily,alternateDays,weekly,customDays}`; `Schedule{type, daysOfWeek: List<int>?}` — wire values match MA-131 §6 exactly.
- `lib/features/subscriptions/models/subscription_status.dart` — `SubscriptionStatus{active,paused,stopped}`.
- `lib/features/subscriptions/models/subscription_view.dart` — `SubscriptionView{id, productId, productName, quantity, schedule, status, nextDeliveryDate?, pauseFrom?, pauseUntil?}` + `fromJson`.
- `lib/features/subscriptions/data/subscription_repository.dart` — `abstract class SubscriptionRepository{ list(), create({...}), pause(id,{from,until}), resume(id), stop(id), skip(id,date), edit(id,{quantity,schedule}) }`; `DioSubscriptionRepository(ApiClient)` hitting `AppConfig.subscriptionBaseUrl`.
- `test/fakes/fake_subscription_repository.dart` — configurable list/create/action results, matching `FakeWalletRepository`'s established shape.
- `lib/features/subscriptions/bloc/subscription_event.dart`, `subscription_state.dart`, `subscription_bloc.dart` — per MA-133 §6: events `SubscriptionsStarted`, `SubscriptionsRefreshRequested`, `VacationModeToggled(bool)`, `PauseRequested`/`ResumeRequested`/`StopRequested`/`SkipRequested`/`EditRequested`; state with `loadStatus`, `subscriptions`, per-subscription `ActionStatus` map, `vacationModeOn` (computed: every subscription `PAUSED` with no `pauseUntil`).
- `lib/features/subscriptions/presentation/subscriptions_screen.dart` — `SubscriptionsScreen` → `_SubscriptionsView` per MA-133 §4/§6's ASCII mock structure, all `Key(...)`s from §4 (`subscriptions-title`, `subscriptions-vacation-toggle`, `subscriptions-active-count`, `subscription-card-{id}`, `subscriptions-new-product-cta`, `subscriptions-custom-schedule-cta`, `subscriptions-loading-skeleton`, `subscriptions-load-error`/`-retry`, `subscriptions-empty-state`).
- `lib/features/subscriptions/presentation/subscription_detail_sheet.dart` — FR-5: Pause (date-range picker)/Resume/Stop(confirm dialog)/Skip(confirm dialog, disabled+captioned past cut-off)/Edit(quantity+schedule form), all `Key(...)`s from §4.
- **Slot picker addition (new UI, not in the mock — MA-133 §11 Risk, review-added)**: a compact slot chip row (`Key('product-config-slot-{slotId}')` per chip) added to `ProductConfigScreen`'s subscription branch, reusing `RegistrationRepository.getDeliverySlots(zoneId)` where `zoneId` comes from `context.read<ProfileRepository>().getMe().defaultAddressZoneId` (the new field above) — **not** `RegistrationBloc.state.draft.zoneId` as MA-133 FR-6 names, since that source is `null` outside an active registration session (review-found, fixed above). No slots fetched (missing zone / empty response) → the picker doesn't render and Subscribe Now stays disabled, same fail-closed posture MA-133 §11 already specifies for the empty-response case.
- `test/fakes/fake_registration_repository.dart` — confirm `getDeliverySlots` is already fakeable (extend if not) for the new `ProductConfigBloc` tests.

**Files to modify:**
- `lib/core/config/app_config.dart` — add `subscriptionBaseUrl` (default `http://localhost:8008`), `orderBaseUrl` (default `http://localhost:8009`, unused by this spec directly per MA-133 §8 — "not called directly by this spec's screens" — but added now since MA-133 §6 lists it and a future order-status affordance will need it).
- `lib/core/router/app_router.dart` — add `GoRoute('/subscriptions', ...)`.
- `lib/features/home/presentation/home_screen.dart` — `_HomeBottomNav.onTap`: index 1 (Schedule) → `context.go('/subscriptions')` (currently a stub, confirmed §1).
- `lib/features/wallet/presentation/wallet_screen.dart` — `_WalletBottomNav.onTap`: add the same index-1 wiring (currently only wires index 0, confirmed §1).
- `lib/features/cart/bloc/product_config_state.dart` — add `slotId: String?` field (`copyWith`-able, same shape as the existing `startDate` field); `canConfirm` additionally requires `slotId != null` when `frequency.isSubscription`.
- `lib/features/cart/bloc/product_config_event.dart` — add `SlotSelected(String slotId)`.
- `lib/features/cart/bloc/product_config_bloc.dart` — `_onStarted`: for a subscription-eligible product, resolve `zoneId` from `ProfileRepository.getMe().defaultAddressZoneId` (not `RegistrationBloc` — see the backend companion change above) and, if non-null, fetch delivery slots (`RegistrationRepository.getDeliverySlots(zoneId)`) and default-select the first `available` one; `zoneId == null` → skip the fetch, no slots, picker doesn't render. `_onSlotSelected` handler; `_onAddToCartRequested`: when `state.frequency.isSubscription`, call `SubscriptionRepository.create(productId, quantity, schedule, startDate, slotId, idempotencyKey)` (MA-131 FR-1) **instead of** `CartRepository.addItem(...)` — a one-time frequency confirm is unchanged.

**Implementation steps:**
0. **`services/user`: `defaultAddressZoneId`** (backend companion change above) — lands first; everything below that touches the slot picker depends on it.
1. `AppConfig` fields.
2. Models (`Schedule`, `SubscriptionStatus`, `SubscriptionView`) + `SubscriptionRepository` (abstract + Dio) + `FakeSubscriptionRepository`.
3. `SubscriptionBloc` + events + state — the full lifecycle state machine, `vacationModeOn` as a pure computed property (never a client-tracked flag — review-fixed, see below).
4. `SubscriptionsScreen` + `_SubscriptionDetailSheet` + all `Key`s + a11y.
5. `AddressDraft.zoneId` + `UserProfile.defaultAddressZoneId` (mobile-side companion change above) + `ProductConfigState`/`Event`/`Bloc` — the slot picker addition (reading `zoneId` from the profile, not `RegistrationBloc`) + the `slotId`-aware `create()` call. **`ProductConfigBloc._onAddToCartRequested` is a real, tested behavior change** — extend `product_config_bloc_test.dart`, don't replace it (MA-133 §11 Risk).
6. Router + bottom-nav wiring (both `home_screen.dart` and `wallet_screen.dart`) + `main.dart` providers.
7. Tests (bloc + widget, both features).
8. `flutter analyze` + `flutter test`.

**Tests to write:**
- Unit (`subscription_bloc_test.dart`): `SubscriptionsStarted` loads the list; a failure → `loadStatus.failed`. `VacationModeToggled(true)` pauses every `ACTIVE` subscription concurrently, no `from`/`until`. **`VacationModeToggled(false)` resumes every currently-`PAUSED`-with-no-`pauseUntil` subscription** — including one seeded directly into that state (simulating a fresh session with no client-tracked history, or a subscription paused via its own detail sheet rather than the toggle) — **never scoped to a client-side-tracked subset** (regression test for the review-fixed toggle-off gap: the original design tracked "which subscriptions I personally vacation-paused" client-side per session, which silently no-op'd after any app restart since a fresh session tracks nothing even though the server-computed `vacationModeOn` still correctly showed ON). `PauseRequested`/`ResumeRequested`/`StopRequested`/`SkipRequested`/`EditRequested` call the right repository method, update only that subscription's per-action status. A failure on one action doesn't affect others.
- Widget (`subscriptions_screen_test.dart`): renders the mock layout; Vacation Mode toggle-on pauses every active subscription; **toggle-off resumes every indefinitely-paused subscription even on a freshly-opened screen with no prior toggle-on this session** (same regression as above, at the widget layer); pausing one subscription with a date range; skip disabled past cut-off; two-devices-diverge-then-refresh scenario.
- Unit (`product_config_bloc_test.dart` additions): with `FakeProfileRepository.getMe()` returning a non-null `defaultAddressZoneId`, the slot chip row renders once `getDeliverySlots` resolves, defaults to the first available slot; **with `defaultAddressZoneId == null`, `getDeliverySlots` is never called and the slot row doesn't render** (regression test for the review-fixed `RegistrationBloc`-sourced gap — a returning user with no in-session registration draft must still be able to reach a working, if empty, state, not a crash); `SlotSelected` updates state; `canConfirm` is `false` with no slot selected (subscription frequency only — one-time is unaffected); `AddToCartRequested` for a subscription frequency calls `SubscriptionRepository.create` (not `CartRepository.addItem`) with the selected `slotId`; a one-time-frequency confirm still calls `CartRepository.addItem` exactly as before, `SubscriptionRepository.create` never called.
- Widget (`product_config_screen_test.dart` additions): Subscribe Now is disabled with no delivery slots returned (including the `defaultAddressZoneId == null` case above); creating a DAILY subscription shows the slot chips, submits the selected one.

**Acceptance check:**
- `flutter test test/features/subscriptions/` and the extended `test/features/cart/bloc/product_config_bloc_test.dart` — all green; `flutter analyze` clean.
- `flutter test` (full suite) — still green.
- Manual (once steps 2–5 done, real device): create a DAILY subscription with `startDate` today → order appears same-day in the backend; Vacation Mode toggle on/off across an app restart correctly resumes everything; skip a delivery before/after cut-off.

---

## 5. Cross-Cutting Steps

- **Shared event schemas** (`services/shared/events/`) — the four new schemas (Step 1) join the three from MA-24; all seven stay the single source of truth for every producer/consumer test.
- **`services/README.md` service inventory** — no change needed; Order (Fargate) and Subscription (Lambda-on-paper, Fargate-in-practice — MA-131's own flagged, accepted deviation) are already listed in the canonical 13 and already placeholders in the "Repository Structure (target)" tree.
- **`services/README.md` "Human approval gate — new service"** — satisfied per §1's note (the merged, SDD-reviewed spec PR is the approval evidence for both Subscription and Order); no further action, documented here for traceability per the README's own convention.
- **`milkful-app` `analysis_options.yaml`** — no new lint rules; `lib/features/subscriptions/` and the `ProductConfigScreen` changes must pass the existing `flutter_lints ^6` set.
- **Dependency manifests** — no new Flutter packages; `services/subscription/requirements.txt` and `services/order/requirements.txt` both need `fastapi`, `uvicorn`, `psycopg[binary]`, `pydantic-settings`, `requests`, `boto3` — the same baseline every Fargate service in this repo already has, no new third-party dependency introduced by this plan.
- **EventBridge topology** — Subscription Service's stack owns the new `SubscriptionOrderDue → order-events-q` rule; Order Service's stack owns `order-events-q` + DLQ itself (Order both owns and is targeted, since nothing else currently produces to this queue). Local-dev `bootstrap.py` mirrors this. Note: `wallet-events-q`'s equivalent queue/rule split between Payment and Wallet (MA-24) has no CDK stack to point to as precedent either — §1 confirms neither has an `infra/` stack yet, so this plan's topology is the first real CDK instance of the pattern, not a copy of an existing one.
- **Architect follow-up (carried, non-blocking)** — `milkful-well-architected.md` + `milkful-messaging.drawio` (referenced throughout all four specs but not present in either checked-out repo — confirmed via search, presumably maintained outside git) need `SubscriptionOrderDue`/`OrderPaymentFailed`/`WalletDebited`/`WalletLowBalance` and the `order-events-q` topology added. Not code; a doc PR for the architect, same non-blocking precedent MA-24 established. Note in the code PR description.
- **Closing the pre-existing `docker-compose.yml` gap** — `cart`/`payment`/`wallet` never got compose entries despite `bootstrap.py` preparing their config (§1). Bundled into Step 5 rather than left to compound into a sixth missing service.

---

## 6. Test Strategy

| Layer | Where | How to run |
|-------|-------|-----------|
| Flutter unit + widget (subscriptions) | `milkful-app/test/features/subscriptions/` | `cd milkful-app && flutter test test/features/subscriptions/` |
| Flutter unit + widget (product config, extended) | `milkful-app/test/features/cart/` | `cd milkful-app && flutter test test/features/cart/` |
| Flutter full regression | `milkful-app/test/` | `cd milkful-app && flutter test` |
| Flutter static analysis | — | `cd milkful-app && flutter analyze` |
| Wallet Service unit (debit extension) | `services/wallet/tests/unit/` | `cd services/wallet && pytest tests/unit` |
| Wallet Service integration | `services/wallet/tests/integration/` | `cd services/wallet && pytest tests/integration` |
| Subscription Service unit | `services/subscription/tests/unit/` | `cd services/subscription && pytest tests/unit` |
| Subscription Service integration | `services/subscription/tests/integration/` | `cd services/subscription && pytest tests/integration` |
| Order Service unit | `services/order/tests/unit/` | `cd services/order && pytest tests/unit` |
| Order Service integration (local SQS/EventBridge + fake User/Pricing/Wallet) | `services/order/tests/integration/` | `cd services/order && pytest tests/integration` |
| Contract | subscription, order, wallet | schema-validate every emitted/consumed event against `services/shared/events/*.schema.json` inside the unit suites |
| End-to-end | `services/local-dev` | `docker compose up -d` then the README recipe: register → recharge → subscribe (same-day) → Daily Run or same-day emit → order materializes → Wallet debited exactly once |
| Infra | `services/{subscription,order}/tests/infra/` | `pytest tests/infra` (CDK synth assertions, mirror `inventory/tests/infra/test_inventory_stack.py` — the actual Fargate precedent, not `cart`'s Lambda one) |

- **Unit vs integration:** anything touching a real Postgres, a real (moto) queue, or a real Catalog/Pricing/User/Wallet HTTP call is integration; pure domain logic (`is_due`, the debit lock-check-write sequence with a fake repo, `OrderService.materialize` with fake clients) is unit.
- **Coverage:** match `services/wallet/pyproject.toml`'s existing threshold in the two new services' `pyproject.toml`. Flutter: no enforced threshold in this repo; every FR path in MA-131/MA-133 needs a test.
- **Lint:** `flutter analyze` (Flutter); `ruff`/`black` per `wallet/pyproject.toml` (mirror, not `cart`'s — different linter config history is unlikely but confirm at implementation time).

---

## 7. Commit Strategy

One commit per numbered step, on feature branches per repo:

**`milkful2026/services`** — branch `feat/MA-25-subscription-order-wallet-debit`:
- `feat(MA-25): shared event schemas (SubscriptionOrderDue/OrderPaymentFailed/WalletDebited/WalletLowBalance)` — Step 1
- `feat(MA-25): Wallet Service — debit capability (ORDER_DEBIT, POST /wallet/internal/debit)` — Step 2
- `feat(MA-25): Subscription Service — lifecycle, cut-off enforcement, Daily Run` — Step 3
- `feat(MA-25): Order Service — SubscriptionOrderDue consumer, Pricing+User+Wallet integration` — Step 4
- `feat(MA-25): services/user — defaultAddressZoneId, mirrors defaultAddressState (MA-23)` — Step 6's backend companion change; independent of steps 1-4, land whenever convenient before Step 6.5 needs it
- `chore(MA-25): local-dev wiring for subscription (:8008) and order (:8009)` — Step 5, first commit
- `chore(MA-25): close the pre-existing cart/payment/wallet docker-compose gap carried from MA-24` — Step 5, second commit, kept separate from the one above so the two scopes stay reviewable independently (review-found — was previously one combined commit)

**`milkful2026/milkful-app`** — branch `feat/MA-25-my-subscriptions-screen`:
- `feat(MA-25): Subscription feature — models, SubscriptionRepository, fakes` — Step 6.1–6.2
- `feat(MA-25): SubscriptionBloc — lifecycle state machine, server-computed Vacation Mode` — Step 6.3
- `feat(MA-25): SubscriptionsScreen + detail sheet — mock layout, all UI states, a11y, keys` — Step 6.4
- `feat(MA-25): ProductConfigScreen — delivery-slot picker sourced from defaultAddressZoneId, subscription create re-pointed to SubscriptionRepository` — Step 6.5 (depends on the `services/user` commit above being merged/deployed first)
- `feat(MA-25): wire /subscriptions route + Schedule bottom-nav tab (Home + Wallet)` — Step 6.6
- `test(MA-25): SubscriptionBloc + SubscriptionsScreen + ProductConfigBloc tests` — Step 6.7

Commit message format: `feat(MA-25): {imperative summary}` / `test(MA-25): …` / `chore(MA-25): …`, matching this project's history.

---

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| **New-service governance gate** (`services/README.md` "Human approval gate") applies to both Subscription and Order | Satisfied via the SDD-reviewed, merged spec PR (§1/§5) — same mechanism MA-126/MA-127 relied on. Flagged for transparency, not a blocker at implementation time. |
| **No `infra/` CDK precedent for a *recently-added* Fargate service** — `wallet`/`payment` (MA-24) still have no CDK stack of their own to copy | `inventory_stack.py` is the only real, working Fargate CDK stack in this repo; both new stacks mirror it directly. If `wallet_stack.py`/`payment_stack.py` land first from a separate effort, reconcile any drift then. |
| **`docker-compose.yml` gap carried from MA-24** (`cart`/`payment`/`wallet` never wired) compounds if left alone | Step 5 closes all five outstanding services (three carried + two new) in one pass rather than deferring again. |
| **EventBridge Scheduler has no local emulation** (MA-131 §11, already flagged in the spec itself) | Local-dev uses a cron-like invocation script hitting `POST /internal/run-daily` directly — documented fidelity gap, same shape as Inventory's SQLite-for-Aurora precedent. Real Scheduler wiring only exists in the deployed CDK stack. |
| **Order Service's synchronous critical path now chains three internal HTTP calls** (User → Pricing → Wallet) before an order is confirmed | Each has its own retry+backoff (`shared.adapters.retry`); MA-132 §5's p99 target (700ms, this plan's revised number) assumes all three are in-VPC/same-region internal calls, not real network hops. **Considered and rejected**: running User and Pricing concurrently, since `pricing_service.py` only checks `deliveryState` for *presence* today, not its value (no CGST/SGST split yet). Rejected because doing so would mean passing Pricing a placeholder `deliveryState` before the real one is known, purely to unblock concurrency — fragile against the day Pricing actually starts using the value (its own docstring flags this as a real future direction), with nothing to catch the regression since Pricing's own tests wouldn't change. If p99 proves too slow in practice, the safer lever is caching User's address-state result per-user (not built here — no evidence of need yet, same "build it when you have evidence" restraint MA-132 §11 already applies to its own reconciliation-sweep decision). |
| **No reconciliation sweep for an Order stuck in `CREATED`** (crash between insert and the Wallet call) | MA-132 §11 already accepts this — the sequence is synchronous and should resolve in milliseconds under normal operation, so a stuck row implies a genuine crash, not a routine timing gap; SQS redelivery (visibility timeout) is the recovery path until real operational evidence justifies a sweep. |
| **`ORDER_USER_MISMATCH`'s redefinition (replay-time-only, Step 2) must not regress into a first-call check** | Explicit regression test in Step 2's unit suite: the first-ever call for a brand-new `orderId` must never raise it. |
| **Vacation Mode toggle-off now resumes an individually-paused subscription it didn't pause** (accepted trade-off, MA-133 §11, review-added) | No server-side `pausedBy` field exists to distinguish the two cases — flagged as a genuine, documented UX cost, not silently decided away. A future `pausedBy: VACATION_MODE | MANUAL` field is the real fix if product confirms it matters (schema change, out of scope here). |
| **`ProductConfigBloc`'s new slot-picker requirement blocks Subscribe Now with no fallback** if `GET /delivery/slots` is empty/unavailable for a zone | Matches FR-1's own "no value to guess a slot with" reasoning — the CTA stays disabled rather than submitting a null `slotId`; same fail-closed posture as every other adapter in this plan. |
| **Retiring nothing, but `ProductConfigBloc._onAddToCartRequested`'s subscription branch is a real, tested behavior change** | `product_config_bloc_test.dart` is extended, not replaced (Step 6.5/6.7); the one-time-frequency path is explicitly, separately verified unchanged, same acceptance-gate pattern MA-24 used for `StubWalletBalanceRepository`'s retirement. |

---

*Plan covers all four MA-25 specs (MA-130 / MA-131 / MA-132 / MA-133) as reviewed and merged on PR #19 (merge `e680e4f`, review-fix revisions `fa92641`). MA-133 is unblocked and may start immediately against `FakeSubscriptionRepository`; MA-130 extends the already-shipped `services/wallet/`; MA-131 and MA-132 create two new Fargate services in `milkful2026/services`, mirroring `services/wallet/`'s layout and importing `services/shared/` directly rather than repeating MA-24's local-copy-then-consolidate detour.*
