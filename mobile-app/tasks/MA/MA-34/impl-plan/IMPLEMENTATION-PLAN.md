# Implementation Plan — MA-34: Order Confirmation / Preview — Checkout

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-34](https://milkfuldairyindia.atlassian.net/browse/MA-34) — Order Confirmation / Preview · Checkout (Flutter) |
| **Date** | 2026-09-25 |
| **Specs implemented** | [MA-135](https://milkfuldairyindia.atlassian.net/browse/MA-135) — Cart & User Service: Checkout Support (`services`) · [MA-136](https://milkfuldairyindia.atlassian.net/browse/MA-136) — Order Service: Cart Checkout (`services`) · [MA-137](https://milkfuldairyindia.atlassian.net/browse/MA-137) — Flutter Review Cart & Confirm Order (`mobile-app`) |
| **Spec branch** | `spec/MA-34` ([specs#21](https://github.com/milkful2026/specs/pull/21), in review) |
| **Repos touched** | `milkful2026/services` (cart, user, order, subscription, shared/events, local-dev), `milkful2026/milkful-app` |
| **Code branches** | `services`: `feat/MA-34-cart-checkout` · `milkful-app`: `feat/MA-34-review-cart-checkout` (separate git worktree, see §8) |

**What this delivers:** the cart screen becomes **Review Cart**. It shows a "Pay now" / "Subscriptions" split, the full saved delivery address, the wallet balance with a shortfall hint, and **Add more items**. **Confirm Order** calls a new server-side checkout that charges one-time items from the wallet as one order, starts every subscription in the cart, empties the cart and lands on an Order Confirmed screen. Subscriptions picked on the product screen now go into the cart first.

**Codebase reality found during analysis (Step 2), which changes the plan versus a literal read of the specs:**

1. **Cart's wallet gate is a permanent stub.** `cart/src/adapters/wallet_client_adapter.py` always raises `WalletCheckUnavailableError` (written before Wallet existed), so today every subscription line added to the cart fails. That is why MA-133 routed subscriptions around the cart. PO-4 can't work without a real client. **Added to MA-135:** `HttpWalletClient.get_balance` calls Wallet's existing `GET /wallet/internal/balance?userId=` (MA-130 FR-3, VPC-only, unauthenticated, the same convention Order's wallet adapter uses).
2. **The app sends `startDate` as a full ISO timestamp** (`DateTime.toIso8601String()` → `2026-09-27T00:00:00.000`), and Cart stores the string verbatim. Order's checkout takes the leading `YYYY-MM-DD` as the subscription start date. The app is also changed to send the date only, and the Order-side parse stays tolerant of existing lines.
3. **`AuthBloc` state doesn't carry the profile** (`AuthAuthenticated` holds only `accountType`/`name`). MA-137 FR-6 said "read from AuthBloc, re-fetch if missing". The established pattern (`ProductConfigBloc._resolveDeliveryState`) is to call `ProfileRepository.getMe()` directly, and `CartBloc` will do the same. That call also supplies `userId` for the pending-key scope (MA-137 FR-9).
4. **`ApiException` has no `details`.** The backend error envelope spreads details into `data` (`shared/handlers/dto.py:error_envelope`), but the app's `ApiClient._mapError` drops them. MA-137 needs `shortfallPaise` and `lines`, so `ApiException` gains an optional `details` map (additive).
5. **Uncommitted, unrelated work exists in `milkful-app`'s `main` working tree** (the `AuthNeedsRegistration` flow and a `ProductConfig` retry rework, 12 files). MA-137 is built in a separate worktree from committed `main` so that work is untouched. See §8 for the merge overlap in `product_config_bloc.dart` / `product_config_screen.dart`.

## 2. Prerequisites

| Prerequisite | Status | Action |
|--------------|--------|--------|
| Order/User/Subscription test venvs | Done during analysis (`.venv` per service, already gitignored per service) | — |
| `CART_WALLET_INTERNAL_BASE_URL` | Setting exists (`""` default), **not written** by local-dev | `local-dev/bootstrap.py`: write `WALLET_HTTP_URL` |
| `ORDER_CART_INTERNAL_BASE_URL`, `ORDER_SUBSCRIPTION_INTERNAL_BASE_URL`, `ORDER_CHECKOUT_CUTOFF_HOUR_IST`, `ORDER_SUBSCRIPTION_MIN_BALANCE_PAISE` | Not done | Add to `order/src/config/env.py`; write the two URLs in `bootstrap.py` (`LOCAL_DEV_CART_HTTP_URL` default `http://localhost:8004`, `LOCAL_DEV_SUBSCRIPTION_HTTP_URL` default `http://localhost:8008`), set both in `docker-compose.yml`'s bootstrap environment |
| Order compose `depends_on` cart + subscription | Not done | `docker-compose.yml` |
| Migration runner handles `0002_*.sql` | Already satisfied (`apply_migrations.py` applies sorted `*.sql`, tracked in `schema_migrations`) | — |
| New Python / Dart packages | None needed (`requests`, `boto3`, `shared_preferences` already present) | Verify `shared_preferences` in `pubspec.yaml`; add only if missing |

## 3. Implementation Order

1. **MA-135 (Cart + User)** first. Order's checkout reads and clears the cart through MA-135's internal routes, and the app reads MA-135's split quote and address.
2. **MA-136 (Order + Subscription internal create)** second. It depends on MA-135's internal contract. Subscription's internal route goes first within this spec because checkout calls it.
3. **MA-137 (Flutter)** last. It consumes both. It's buildable in parallel against fakes, but the integration check needs 1 and 2.

## 4. Per-Spec Implementation Steps

### MA-135: Cart & User Service — Checkout Support

**Files to modify (cart):**
- `cart/src/domain/models.py`: `LineItem.slot_id: str | None = None`; `CartView.pay_now_quote`, `CartView.per_delivery_quote` (both `Quote | None`, default `None`).
- `cart/src/domain/cart_service.py`:
  - `_validate_item` gains `slot_id`: required (non-blank) for subscription frequencies, forbidden for `ONE_TIME`, with the exact messages from MA-135 FR-1. `add_item` and `replace_cart` pass it through, and `replace_cart`'s `is_new_or_changed` also compares `slot_id`.
  - `get_cart` partitions lines by `frequency.is_subscription` and requests `quote` (all lines), `pay_now_quote` (one-time lines) and `per_delivery_quote` (subscription lines) concurrently with the existing `ThreadPoolExecutor` pattern. An empty partition is skipped (`None`), and the first exception propagates.
  - New `get_cart_internal(user_id) -> Cart` and `remove_items_internal(user_id, item_ids, if_version, checkout_id) -> Cart`, delegating to the repository.
  - `_check_wallet_gate` compares paise: `balance_paise < wallet_minimum_balance * 100`.
- `cart/src/adapters/interfaces.py`: `add_item`/`replace_cart` carry `slot_id`; new `remove_items(user_id, item_ids, if_version, reason, checkout_id) -> Cart`; `WalletClientPort.get_balance` documented as **paise**.
- `cart/src/adapters/cart_repository.py`: persist and read the `slotId` attribute in `add_item`, `replace_cart`, `_item_to_line_item` and the idempotency-replay dicts. New `remove_items`: one `transact_write_items` with a `Delete` per present `ITEM#`, the `META` version check and increment (`_meta_upsert_transact_item` with `if_version`), and an outbox row whose payload carries `reason`/`checkoutId`. Implement the FR-4 replay rule: nothing present and stored version > `if_version` → return the current cart. `_outbox_put_transact_item` gains an optional extra-payload argument.
- `cart/src/adapters/wallet_client_adapter.py`: replace the stub with a real `HttpWalletClient(base_url, timeout)` → `GET {base}/wallet/internal/balance?userId=` → `data.balancePaise`. Retry with `adapters/retry.py`, and raise `WalletCheckUnavailableError` after retries or when `base_url` is empty (keeps today's fail-closed behaviour when unconfigured).
- `cart/src/handlers/dto.py`: `slotId` on both request DTOs and in `serialize_line_item`; `serialize_cart_view` adds `payNowQuote`/`perDeliveryQuote`; new `InternalRemoveItemsRequestDto(itemIds: list[str] (min 1), ifVersion: int, reason: "CHECKOUT", checkoutId: str | None)`.
- `cart/src/handlers/add_item_handler.py`, `put_cart_handler.py`: pass `slot_id`.
- `cart/src/handlers/composition.py`: `HttpWalletClient(settings.wallet_internal_base_url, settings.request_timeout_seconds)`.
- `cart/run_local.py`: register the two internal routes.
- `cart/infra/cart/cart_stack.py`: two new Lambda functions and routes under `/cart/internal/users/{userId}` and `/cart/internal/users/{userId}/remove-items` with `HttpIamAuthorizer()`, plus an `InternalRoutesArn` `CfnOutput`, mirroring `user_stack.py`'s internal route and `_grant_internal_callers`.
- `cart/README.md`: endpoints table and Known Gaps (the wallet gap is closed).

**Files to create (cart):**
- `cart/src/handlers/internal_get_cart_handler.py`: reads `pathParameters.userId`, returns `serialize_cart`.
- `cart/src/handlers/internal_remove_items_handler.py`: validates the DTO and returns `serialize_cart`; `CartVersionMismatchError` → existing 409 mapping.

**Files to modify (user):**
- `user/src/domain/models.py`: `UserProfile.default_address: Address | None = None`.
- `user/src/adapters/user_repository.py`: `get_profile_by_sub` sets `default_address` from the already-loaded default row (no new query).
- `user/src/handlers/dto.py`: `serialize_address(address)` → `{id, lines, landmark, city, state, pincode, lat, lng}`; `serialize_user_profile` adds `defaultAddress` (or `null`).
- `user/README.md`: `/users/me` shape note.

**Files to modify (shared):**
- `shared/events/CartUpdated.schema.json` (if present) or the cart outbox payload docs: optional `reason`, `checkoutId`.

**Tests to write:**
- Unit (`cart/tests/unit/domain`): slot validation matrix; `get_cart` partition cases (one-time only, subscription only, mixed, empty) asserting pricing calls and which quote is `None`; the wallet gate in paise.
- Unit (`cart/tests/unit/adapters`): repository `slotId` round-trip; `remove_items` match / mismatch (409) / replay-after-success / partial-present; outbox payload has `reason: CHECKOUT` and `checkoutId`. Wallet client: 200 → paise, 5xx → retry → `WalletCheckUnavailableError`, empty base URL → raises.
- Handler tests for both internal handlers (path param, DTO validation, 409).
- Infra test: both internal routes use the IAM authorizer (extend `test_cart_stack.py`; update "five lambdas" / "all four routes use JWT" to the new counts, with public routes still JWT).
- User: `get_me` returns `defaultAddress` fully populated, `landmark: null`, and `null` when there's no default address; the flat fields are unchanged.

**Acceptance check:** `cd cart && .venv/Scripts/python -m pytest -q` and `cd user && .venv/Scripts/python -m pytest -q` both green; `ruff check` clean in both.

### MA-136: Order Service — Cart Checkout (+ Subscription internal create)

**Subscription (first):**
- Modify `subscription/src/handlers/dto.py`: `InternalCreateSubscriptionRequest(CreateSubscriptionRequest)` + `userId: str`, `correlationId: str | None`.
- Modify `subscription/src/handlers/internal_run_daily_handler.py` (the existing VPC-only internal router): add `POST /subscriptions/internal/create` → `SubscriptionService.create(...)` with the body's `userId`. It returns the same `success_envelope` shape as the public create, with status 201 to match the public route (check the public handler and mirror its status).
- Test: `subscription/tests/integration/test_internal_create.py`: same body as public create for identical input; idempotent on key; 422 for an ineligible product; no JWT required.

**Order files to create:**
- `order/migrations/0002_checkout.sql`: exactly MA-136 §7 (Postgres). Use `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL`, `ADD COLUMN source ... DEFAULT 'SUBSCRIPTION'`, `ADD COLUMN checkout_id VARCHAR(64) UNIQUE`, the `orders_source_shape` CHECK, `order_items`, `checkouts`, and the partial unique index.
- `order/src/domain/checkout_service.py`: `CheckoutService(repository, cart_client, user_client, pricing_client, wallet_client, subscription_client, settings_like)` with public `checkout(user_id, idempotency_key, cart_version, expected_pay_now_paise, correlation_id, now=None) -> dict`. Private steps: `_replay_or_resume`, `_validate_and_price` (FR-3 in order), `_start` (FR-4), `_charge` (FR-5), `_start_subscriptions` (FR-6), `_clear_cart` (FR-7), `_delivery_date(now)` (FR-8), `_result(checkout)` (FR-9). The resumable state machine is `step ∈ STARTED → PAID → SUBSCRIPTIONS_DONE → COMPLETED`, and every step is idempotent.
- `order/src/domain/checkout_models.py`: `Checkout`, `CheckoutLine`, `SubscriptionLineResult` dataclasses; enums `CheckoutStatus`, `CheckoutStep`.
- `order/src/adapters/cart_client_adapter.py`: `HttpCartClient.get_cart(user_id)` and `.remove_items(user_id, item_ids, if_version, checkout_id)`. SigV4-signed (extend `shared/adapters/sigv4.py` with `sign_request(method, url, params, body, region)` keeping `sign_get_request` as a wrapper). Retries via `call_with_retry`; `409` → `CartVersionConflictError`; other failures → `CartUnavailableError`.
- `order/src/adapters/subscription_client_adapter.py`: `HttpSubscriptionClient.create(...)` → returns `{subscriptionId, nextDeliveryDate}`; a `422` with an errorCode → `SubscriptionRejectedError(code)`; transport/5xx after retries → `SubscriptionUnavailableError`.
- `order/src/handlers/checkout_handlers.py`: `POST /orders/checkout`; `Idempotency-Key` header required (8–128 chars) else `400 VALIDATION_ERROR`; body `CheckoutRequest(cartVersion: int, expectedPayNowPaise: int | None)`.

**Order files to modify:**
- `order/src/domain/models.py`: `Order.subscription_id/product_id/quantity` optional; add `source` (`OrderSource` enum: `SUBSCRIPTION`/`CHECKOUT`), `checkout_id`, `items: list[OrderItem]`.
- `order/src/domain/exceptions.py`: `CartEmptyError(409 CART_EMPTY)`, `CartChangedError(409 CART_CHANGED)`, `CheckoutInProgressError(409 CHECKOUT_IN_PROGRESS)`, `PriceChangedError(409 PRICE_CHANGED)`, `LineInvalidError(422 LINE_INVALID)`, `DeliveryAddressUnknownError(422 DELIVERY_ADDRESS_UNKNOWN)`, `InsufficientBalanceError(402 INSUFFICIENT_BALANCE)`, `WalletNotActiveError(403 WALLET_NOT_ACTIVE)`, `CheckoutIncompleteError(503 CHECKOUT_INCOMPLETE)`, `DependencyUnavailableError(503 DEPENDENCY_UNAVAILABLE)`, `ValidationError(400 VALIDATION_ERROR)`, plus adapter-level `CartUnavailableError`, `CartVersionConflictError`, `SubscriptionUnavailableError`, `SubscriptionRejectedError`.
- `order/src/adapters/order_repository.py`: table columns match `0002`. New `order_items_table` and `checkouts_table` (JSON via `JSONColumn`), the partial unique index via `Index(..., unique=True, sqlite_where=..., postgresql_where=...)`, and the CHECK constraint. New methods:
  - `get_checkout(user_id, key)`, `get_live_checkout(user_id)`
  - `start_checkout(checkout, order | None, items)` (one transaction; IntegrityError on the live-index → `CheckoutInProgressError`; on `(user_id, key)` → return the existing row)
  - `mark_checkout_paid(checkout_id)`, `record_subscription_result(checkout_id, result)`, `mark_checkout_subscriptions_done`, `complete_checkout(checkout_id, result)`, `fail_checkout(checkout_id, result)`
  - `get_items(order_id)`

  `_row_to_order` handles null columns, and `get`/`list_for_user` load items for checkout orders.
- `order/src/adapters/pricing_client_adapter.py`: `quote_items(items, delivery_state)` for multi-line ONE_TIME quotes; `quote()` becomes a wrapper. For `PRODUCT_PRICING_UNKNOWN`, include the product id from the error body when present.
- `order/src/adapters/wallet_client_adapter.py`: add `get_balance(user_id) -> int` (paise) via `GET /wallet/internal/balance`.
- `order/src/adapters/interfaces.py`: new ports for the above.
- `order/src/domain/order_service.py`: `_serialize` adds `source`, `items`; event payloads add `source: "SUBSCRIPTION"`.
- `order/src/config/env.py`: `cart_internal_base_url`, `subscription_internal_base_url`, `checkout_cutoff_hour_ist: int = 20`, `subscription_min_balance_paise: int = 50000`.
- `order/src/handlers/dependencies.py`: `get_checkout_service()` (`lru_cache`, shares the engine with `get_order_service`; refactor into one cached `_engine()`).
- `order/src/handlers/app.py`: include the checkout router.
- `shared/events/OrderConfirmed.schema.json`, `OrderPaymentFailed.schema.json`: `subscriptionId` nullable and not required; `source` required (enum); optional `checkoutId`, `items`.
- `order/README.md`: endpoints, the checkout flow diagram, and Known Gaps (the stale-checkout sweep is deferred).

**Tests to write:**
- `order/tests/unit/domain/test_checkout_service.py` (fakes for all ports in `conftest.py`): each FR-3 rejection with no side effects; one-time only / subscription only / mixed; `DEBITED` / `INSUFFICIENT_BALANCE` / `WALLET_NOT_ACTIVE` / wallet unavailable; subscription 422 continues vs transient stops; cart-clear 409 → re-read → retry; replay of `COMPLETED` / `PAYMENT_FAILED`; resume from `STARTED` (no second debit call beyond the idempotent one), `PAID` and `SUBSCRIPTIONS_DONE`; derived subscription idempotency keys; `startDate` ISO-timestamp parse; delivery date before and after the cut-off.
- `order/tests/unit/adapters/test_order_repository.py` (extend): checkout rows round-trip; the live-index rejects a second `IN_PROGRESS`; the source-shape CHECK; items load.
- `order/tests/unit/adapters/test_cart_client_adapter.py`, `test_subscription_client_adapter.py`: status mapping and retries (`requests` monkeypatched, as existing adapter tests do).
- `order/tests/integration/test_checkout_flow.py`: TestClient `POST /orders/checkout` happy path → one order + items + an outbox row validating against the updated `OrderConfirmed` schema; `GET /orders/me` shows `source: CHECKOUT` with items; same-key replay → identical body and no extra debit.
- Existing `test_order_flow.py` stays green (subscription path unchanged apart from the added fields).

**Acceptance check:** `cd order && .venv/Scripts/python -m pytest -q` and `cd subscription && .venv/Scripts/python -m pytest -q` green; `ruff check` clean.

### MA-137: Flutter Review Cart & Confirm Order

**Files to modify:**
- `lib/core/network/api_client.dart`: `ApiException.details` (`Map<String, dynamic>`, default empty), filled from the envelope `data` minus `errorCode`/`message`.
- `lib/features/cart/models/cart_line_item.dart`: `slotId` (nullable) in `fromJson`/`toJson`/`copyWith`/`props`.
- `lib/features/cart/models/cart_view.dart`: `payNowQuote`, `perDeliveryQuote`.
- `lib/features/cart/data/cart_repository.dart`: `addItem(..., String? slotId)`; `startDate` sent as `yyyy-MM-dd`.
- `lib/features/cart/bloc/product_config_bloc.dart`: the subscription confirm calls `_cartRepository.addItem(..., slotId: state.slotId)`; remove the `SubscriptionRepository` dependency and `_scheduleTypeFor`.
- `lib/features/cart/presentation/product_config_screen.dart`: stop passing `SubscriptionRepository`; subscription CTA copy "Add subscription to cart"; success SnackBar "Subscription added to cart".
- `lib/features/cart/bloc/cart_event.dart`: `CartRefreshRequested`, `CheckoutRequested`, `CheckoutFeedbackConsumed`.
- `lib/features/cart/bloc/cart_state.dart`: `payNowQuote`, `perDeliveryQuote`, `walletBalancePaise`, `walletStatus`, `deliveryAddress`, `addressStatus`, `checkoutStatus` (`idle|submitting|incomplete`), `checkoutFailure`, `lineErrors`, `checkoutResult`; derived `hasSubscriptionLines`, `requiredPaise`, `shortfallPaise`, `canConfirm`.
- `lib/features/cart/bloc/cart_bloc.dart`: new constructor deps `WalletBalanceRepository`, `ProfileRepository`, `CheckoutRepository`, `PendingCheckoutStore`. `_onStarted`/`_onRefreshRequested` load the cart, balance and profile in parallel (balance/profile failures are non-fatal). `_onCheckoutRequested` implements FR-7..FR-9 (persisted key, retries at 1/2/4 s, outcome mapping). Keep `quote` fallback behaviour for a stale backend (MA-137 §7).
- `lib/features/cart/presentation/cart_screen.dart`: title "Review Cart"; `cart-add-more` button; the delivery card; the split summary; the wallet row with `cart-wallet-topup`; the "Confirm Order" CTA with progress, incomplete banner and dialogs; per-line error text; empty-state CTA awaits the push and refreshes. The subscription line subtitle reads "Daily · starts 27 Sep".
- `lib/features/wallet/data/wallet_balance_repository.dart`: expose paise alongside rupees if it only returns rupees today (read it and keep the existing API).
- `lib/features/auth/models/user_profile.dart`: `DeliveryAddress? defaultAddress`.
- `lib/core/router/app_router.dart`: `GoRoute('/order-success')` with the `extra` guard → `/home`.
- `lib/main.dart`: provide `CheckoutRepository` (`DioCheckoutRepository`) and `PendingCheckoutStore`.
- `lib/features/cart/bloc/product_config_bloc.dart` constant: move the ₹500 literal to a shared `kSubscriptionMinWalletBalanceRupees` in `lib/features/cart/models/wallet_rules.dart` and use it from both blocs.

**Files to create:**
- `lib/features/auth/models/delivery_address.dart`: `DeliveryAddress.fromJson`, `formattedLines`, `cityStatePincode`.
- `lib/features/checkout/data/checkout_repository.dart`: abstract + `DioCheckoutRepository` (`POST {orderBaseUrl}/orders/checkout`, `Idempotency-Key` header), mapping `ApiException.errorCode` → `CheckoutFailure`.
- `lib/features/checkout/data/pending_checkout_store.dart`: `SharedPreferences` key `checkout.pendingKey.{userId}`; `read/write/clear`; all failures swallowed (per-device convenience only).
- `lib/features/checkout/models/checkout_result.dart`, `checkout_failure.dart` (sealed).
- `lib/features/checkout/presentation/order_success_screen.dart` (`order-success-id`, "Back to Home", "View subscriptions").
- Test fakes: `test/helpers/fake_checkout_repository.dart`, `fake_pending_checkout_store.dart` (follow the existing fakes' location and pattern).

**Tests to write:** the bloc and widget scenarios listed in MA-137 §10, plus: `CartLineItem`/`CartView`/`UserProfile`/`ApiException.details` JSON parsing; the product-config test that asserted `FakeSubscriptionRepository.create` now asserts `FakeCartRepository.addItem(slotId: ...)`.

**Acceptance check:** `flutter analyze` clean; `flutter test` green (baseline 199 plus new tests).

## 5. Cross-Cutting Steps

- `local-dev/bootstrap.py` + `docker-compose.yml`: the env vars and `depends_on` from §2.
- `services/README.md`: service-map rows for the new internal routes if the README lists routes.
- Root checks: every touched service's `pytest -q` and `ruff check .`; `flutter analyze` + `flutter test`.
- End-to-end smoke on local-dev (`start-backend`): add a one-time and a Daily item → Review Cart → Confirm → success screen; `GET /orders/me` shows the order; My Subscriptions lists the subscription; the cart is empty.

## 6. Test Strategy

| Layer | Where | Command |
|-------|-------|---------|
| Unit + integration (Cart) | `services/cart/tests` | `cd services/cart && .venv/Scripts/python -m pytest -q` |
| Unit + integration (User) | `services/user/tests` | `cd services/user && .venv/Scripts/python -m pytest -q` |
| Unit + integration (Subscription) | `services/subscription/tests` | `cd services/subscription && .venv/Scripts/python -m pytest -q` |
| Unit + integration (Order) | `services/order/tests` | `cd services/order && .venv/Scripts/python -m pytest -q` |
| Lint (services) | each service | `.venv/Scripts/python -m ruff check .` |
| Flutter | `milkful-app/test` | `flutter analyze && flutter test` |

Baseline before changes: cart 108, user 110, subscription 66, order 36, Flutter 199, all passing. Coverage target: every new domain branch in `CheckoutService` and `CartBloc` exercised (no numeric gate exists in these repos; don't invent one).

## 7. Commit Strategy

- `services` on `feat/MA-34-cart-checkout`: one commit per spec, `[MA-34] [Services] feat(cart,user): checkout support (MA-135)`, then `[MA-34] [Services] feat(order,subscription): cart checkout (MA-136)`, then `[MA-34] [Services] chore(local-dev): checkout wiring`. PR to `main`.
- `milkful-app` on `feat/MA-34-review-cart-checkout`: `[MA-34] [App] feat: Review Cart & Confirm Order (MA-137)`, with separate commits for the ProductConfig → cart change and the success screen if they help review. PR to `main`.
- Commit messages follow the repos' existing `[STORY] [Area] type(scope): …` format.

## 8. Risks and Blockers

- **Money path.** Double-charge protection relies on four layers (client key, `checkouts` unique key, `orders.checkout_id` unique, Wallet ledger ref). Tests must cover replay and resume explicitly; don't merge without them.
- **SQLite vs Postgres fidelity.** Partial unique index and CHECK constraints behave the same in SQLite 3.8+, but `ALTER COLUMN DROP NOT NULL` exists only in Postgres. The migration is Postgres-only and tests use `create_schema`. Verify `0002` against local-dev Postgres with `apply_migrations.py` before the PR.
- **Uncommitted app work on `main`.** The in-progress (uncommitted, unrelated) `AuthNeedsRegistration` / `RetryRequested` changes touch `product_config_bloc.dart` and `product_config_screen.dart`, which MA-137 also edits (the confirm branch and constructor). Expect a small conflict when both land. Resolve by keeping both: the `RetryRequested` handler stays, and the subscription confirm goes to the cart.
- **Stale `IN_PROGRESS` checkouts** block a user's next checkout until the app retries (it does so automatically). The reconciliation sweep is deferred per MA-136 §11 and must land before production.
- **Cart infra IAM routes** can't be exercised locally (the local shim doesn't verify SigV4). Covered by the CDK assertion test only.
- **Recovery:** each spec is a separate commit, so a failing MA-136 can be reverted without losing MA-135. The migration is additive apart from relaxed NOT NULLs, and a rollback script is not required for local-dev.
