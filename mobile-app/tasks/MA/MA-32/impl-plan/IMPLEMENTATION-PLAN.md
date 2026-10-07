# Implementation Plan — MA-32: Order Cancellation

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-32](https://milkfuldairyindia.atlassian.net/browse/MA-32) — Order Cancellation · Orders (Flutter) |
| **Date** | 2026-10-08 |
| **Specs implemented** | [MA-153](https://milkfuldairyindia.atlassian.net/browse/MA-153) — Wallet Service: Order Refund (`services`) · [MA-154](https://milkfuldairyindia.atlassian.net/browse/MA-154) — Order Service: Customer Order Cancellation (`services`) · [MA-155](https://milkfuldairyindia.atlassian.net/browse/MA-155) — Flutter Cancel Order & Cancel Delivery (`mobile-app`) |
| **Spec source** | `main` (specs PR #37, merge `120f0e7`, including the review fixes `3b33015`) |
| **Repos touched** | `milkful2026/services` (MA-153, MA-154), `milkful2026/milkful-app` (MA-155) |

**What this delivers:** a customer can cancel a paid order before the 20:00 IST cut-off on the
day before delivery and get a full refund to their Milkful Wallet. They can also cancel a
subscription's next delivery (which isn't an order yet) by reusing Skip. Order Service cancels
first, then refunds through a new idempotent Wallet route. A new sweep pass finishes any
refund the request couldn't complete. The app shows the policy, an optional reason, the
result, and "Refund in progress" while a refund is still pending.

**Codebase findings that shape this plan** (all read from `origin/main` on 2026-10-08):

1. **Wallet's reused exceptions have the wrong HTTP status for this route.** MA-153 FR-4
   wants `409 DEBIT_NOT_FOUND` and `409 ORDER_USER_MISMATCH`. Wallet's existing
   `DebitNotFoundError` is a **404** (MA-142's lookup route depends on that), and
   `OrderUserMismatchError` is a **400** (the debit route). The plan adds two refund-only
   subclasses that keep the error code and set `http_status = 409`, so the existing routes
   don't change.
2. **Neither service maps FastAPI's own validation errors to 400.** Pydantic body validation
   gives a **422** (Wallet's own test `test_internal_debit_non_positive_amount_is_422`
   shows this). MA-153 wants `400 VALIDATION_ERROR` / `400 INVALID_AMOUNT`, and MA-154
   wants `400 VALIDATION_ERROR` for an unknown reason. So both request models declare their
   fields loosely (optional, untyped where needed), and the handler or service validates by
   hand and raises the typed 400. This is the same pattern as `_validate_order_id` and
   checkout's `Idempotency-Key` check.
3. **The "integration" tests run on SQLite, not Postgres.** Both `wallet/tests/conftest.py`
   and `order/tests/conftest.py` use in-memory SQLite with `StaticPool` behind `TestClient`.
   MA-153 §10 and MA-154 §10 say "real Postgres". The plan writes those tests in the
   existing SQLite harness and checks the Postgres-only behaviour (`FOR UPDATE`, the partial
   index, the migration) in the local-dev E2E run (§6). SQLite ignores `FOR UPDATE`, so the
   "two concurrent requests" tests prove the `ref` UNIQUE / conditional-`UPDATE` replay
   paths, not the row lock.
4. **`OrderService` has no clock and no cut-off hour.** `_serialize(order)` is a module
   function that only takes the order. FR-7's `cancellableUntil` needs `now` and
   `checkout_cutoff_hour_ist`, so both reach `_serialize` (§4, MA-154 steps 4–5).
5. **`OrderDetailScreen` has no clock.** `ScheduledDeliveryScreen` already takes
   `Clock? clock` and the widget tests pass a fixed one (`detail_screens_test.dart:31`).
   `OrderDetailScreen` gets the same parameter, because FR-1/FR-6 visibility depends on
   `now`.
6. **`FakeSubscriptionRepository.skip` records only the id** (`skipCalls`, a
   `List<String>`). MA-155's tests assert `skip('sub_1', date)`. Rather than change
   `skipCalls`' type (existing tests use it), add a parallel `skipDates` list and a
   `skipException`-style hook if one isn't already there.
7. **The architecture doc describes a different refund mechanism.**
   `docs/design/milkful-well-architected.md` lists Wallet consuming `OrderCancelled` on
   `wallet-events-q` ("refund") and a Step Functions refund saga. The approved MA-153/MA-154
   specs chose a synchronous internal HTTP refund plus sweep recovery. This plan follows the
   specs. **Do not add an EventBridge rule routing `OrderCancelled` to `wallet-events-q`.**
   The refund would still be idempotent on the ledger `ref`, but it would be a second,
   undocumented refund path.
8. **My Orders' day total counts every amount that isn't struck through**
   (`order_buckets.dart:115`). MA-155 FR-4 un-strikes customer-cancelled orders, which would
   add refunded orders to the day total. **Decided in chat (2026-10-08): exclude
   customer-cancelled orders from the day total**, while keeping their amount un-struck as
   the spec says (§4, MA-155 step 4).

---

## 2. Prerequisites

### `services` (MA-153, MA-154)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `shared/events/WalletRefunded.schema.json` | **Not done** | MA-153 FR-5 (§4, Step 1) |
| `shared/events/OrderCancelled.schema.json` | **Not done** | MA-154 FR-6 (§4, Step 1) |
| `order/migrations/0004_customer_cancel.sql` | **Not done** | MA-154 §7 (§4, MA-154 step 1) |
| Ledger `REFUND` type, `ref` UNIQUE | **Already satisfied** | `LedgerType.REFUND` in `wallet/src/domain/models.py`; `ledger_entries.ref` is `unique=True`. No Wallet migration |
| `_DESCRIPTIONS[REFUND] = "Refund"` | **Already satisfied** | `wallet/src/domain/wallet_service.py` |
| Order → Wallet base URL | **Already satisfied** | `Settings.wallet_internal_base_url` (Order), used by the debit and void calls |
| Cut-off hour setting | **Already satisfied** | `Settings.checkout_cutoff_hour_ist = 20` (Order) |
| New packages | **Already satisfied** | None needed (`requests`, `sqlalchemy`, `jsonschema` already used) |
| CI coverage | **Already satisfied** | `.github/workflows/ci.yml`'s matrix already includes `wallet` and `order` |
| Local-dev migration pickup | **Already satisfied** | `local-dev/apply_migrations.py` applies every `migrations/*.sql` in name order, so `0004` is picked up automatically |
| Production migration approval | **Not done (process)** | `services/README.md` §3.6: production migrations need human approval. Get it before deploying `0004` |

### `milkful-app` (MA-155)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `intl` (`DateFormat`) | **Already satisfied** | `intl: ^0.19.0`; `order_formatting.dart` already uses it |
| Routes `/catalog`, `/orders/:orderId` | **Already satisfied** | `lib/core/router/app_router.dart` |
| `AppConfig.orderBaseUrl` | **Already satisfied** | Used by `DioOrderRepository` |
| `SubscriptionRepository.skip` | **Already satisfied** | MA-133; throws `ApiException(errorCode: 'CUTOFF_PASSED')` |
| New packages | **Already satisfied** | None needed |

---

## 3. Implementation Order

1. **Shared event schemas** (`WalletRefunded`, `OrderCancelled`). Both services' tests
   validate payloads against them, so they come first.
2. **MA-153 Wallet refund.** Order Service's cancel (step 3) calls it, and the order client
   is part of this spec.
3. **MA-154 Order cancel.** Depends on step 2's route and `HttpWalletClient.refund`.
4. **MA-155 Flutter.** Can start in parallel with steps 2–3, because every new DTO field is
   parsed leniently and missing fields hide the Cancel action (MA-155 §7). The manual E2E
   check needs steps 2–3 running in local-dev.

**Deploy order:** Wallet (MA-153) → Order (MA-154, with migration `0004`) → app release.
Shipping Order before Wallet would leave every cancel at `refundState: PENDING` until Wallet
deploys, then the sweep would catch up. That's safe but noisy, so don't do it.

**Branches:** `services`: `feat/MA-32-order-cancellation` (MA-153 + MA-154 in one PR, so the
client and route are reviewed together). `milkful-app`: `feat/MA-32-cancel-order`.

---

## 4. Per-Spec Implementation Steps

### Step 1 — Shared event schemas (`services`)

**Files to create:**
- `shared/events/WalletRefunded.schema.json` — draft 2020-12, `$id`
  `https://milkful.internal/events/WalletRefunded.schema.json`, `additionalProperties:
  false`. Required: `eventId`, `occurredAt` (date-time), `correlationId` (minLength 1),
  `userId`, `walletId`, `orderId`, `refundId`, `amountPaise` (integer, `exclusiveMinimum:
  0`), `balanceAfterPaise` (integer, `minimum: 0`), `ref`. The description names the
  producer `milkful.wallet` (MA-153) and future consumers MA-103/MA-104.
- `shared/events/OrderCancelled.schema.json` — same conventions as
  `OrderConfirmed.schema.json`. Required: `eventId`, `occurredAt`, `correlationId`,
  `orderId`, `userId`, `source` (`SUBSCRIPTION`|`CHECKOUT`), `amountPaise` (integer,
  `minimum: 0`, since a ₹0 order can be cancelled), `deliveryDate` (date), `cancelledBy`
  (`const: "CUSTOMER"`), `refundState` (`PENDING`|`NOT_REQUIRED`). Optional: `cancelReason`
  (enum of the four reasons, or null), `subscriptionId`, `checkoutId`, `items` (the same
  item shape as `OrderConfirmed`).

**Files to modify:**
- `shared/events/README.md` — add two rows: `WalletRefunded` (Wallet, MA-153; consumers:
  Notification (future), Reporting) and `OrderCancelled` (Order, MA-154; consumers:
  Notification (MA-103), Reporting (MA-104), Delivery (MA-102), all future). Add one line
  saying MA-32 extended it.

**Acceptance check:** each schema loads through `shared.events.load_schema(...)` and rejects
an extra property (covered by the per-service tests below).

### MA-153: Wallet Service — Order Refund

**Files to modify:**
- `wallet/src/domain/exceptions.py`
  - `RefundExceedsDebitError(WalletError)`: `error_code = "REFUND_EXCEEDS_DEBIT"`,
    `http_status = 409`.
  - `RefundDebitNotFoundError(DebitNotFoundError)`: same code `DEBIT_NOT_FOUND`,
    `http_status = 409`. A docstring explains why it's a subclass (finding 1).
  - `RefundOrderUserMismatchError(OrderUserMismatchError)`: same code
    `ORDER_USER_MISMATCH`, `http_status = 409`.
- `wallet/src/domain/models.py` — `@dataclass RefundOutcome`: `order_id`, `refund_id`,
  `amount_paise`, `balance_after_paise`, `ledger_entry_id`, `refunded_at` (datetime),
  `wallet_id`, `replayed: bool`.
- `wallet/src/adapters/interfaces.py` — add `refund_for_order(...)` to
  `WalletRepositoryPort`, with the same keyword-only signature as the repository method
  below.
- `wallet/src/adapters/wallet_repository.py` — `refund_for_order(*, user_id, order_id,
  refund_id, amount_paise, ref, correlation_id, outbox_payload_builder) -> RefundOutcome`.
  One `self._engine.begin()` transaction inside `self._db_operation("refund_for_order",
  "Failed to refund wallet")`, mirroring `debit_for_order`'s structure:
  1. `SELECT wallets ... WHERE user_id = :user_id FOR UPDATE`. No row →
     `WalletNotFoundError` (404; unlike debit's `WalletProvisioningPendingError`, a refund
     with no wallet can't be a provisioning race, because a debit happened).
  2. Look up the `ref` (`refund:{orderId}:{refundId}`). If found: a different `wallet_id` →
     `RefundOrderUserMismatchError`; otherwise return a `RefundOutcome` built from that row,
     with `replayed=True`.
  3. Look up the debit `ref` `order:{orderId}`. Missing, or not `ORDER_DEBIT` type →
     `RefundDebitNotFoundError`. Different `wallet_id` → `RefundOrderUserMismatchError`.
  4. Cap: `SUM(amount_paise)` over `ledger_entries` where `wallet_id` = the locked wallet,
     `type = 'REFUND'`, and `ref` starts with the literal prefix `refund:{orderId}:`. Use
     `ledger_entries_table.c.ref.startswith(prefix, autoescape=True)`; that escapes the `_`
     in `ord_…` (MA-153 §7). If `already + amount_paise > abs(debit.amount_paise)` →
     `RefundExceedsDebitError` with `details={"debitedPaise": …, "alreadyRefundedPaise": …}`.
  5. No wallet-status check (FR-2 step 5; a comment says it's deliberate).
  6. Insert the `REFUND` ledger row (`+amount_paise`, the new balance, `ref`,
     `correlation_id`), update `wallets.balance_paise` / `updated_at`, and insert a
     `WalletRefunded` outbox row from `outbox_payload_builder(wallet.id, new_balance,
     ledger_entry_id)`. Read the new ledger row's id from the insert result's
     `inserted_primary_key[0]` (works on both Postgres and SQLite).
  7. `except IntegrityError`: re-read the wallet and the refund `ref` in a fresh connection,
     then return the replay as in step 2 (re-raise if either is missing). Same shape as
     `debit_for_order`.
- `wallet/src/domain/wallet_service.py` — `refund_for_order(*, user_id, order_id,
  refund_id, amount_paise, correlation_id) -> RefundOutcome`:
  - `amount_paise <= 0` → `InvalidAmountError` (400, FR-4).
  - Mint `correlation_id` if it's falsy (as `debit_for_order` does for `WalletDebited`).
  - Build `ref = f"refund:{order_id}:{refund_id}"` and a `_build_refunded_outbox` closure
    producing the FR-5 payload (`eventId` uuid4, `occurredAt` now UTC, `ref`, …).
  - Call the repository. Then log the structured `refund` event (`orderId`, `refundId`,
    outcome `REFUNDED`/`REPLAYED`/error code, `correlationId`), and emit the metric line
    `wallet.refund.count` with an `outcome` dimension. Log both on success and on
    `WalletError` (log, then re-raise). Mismatch is logged at error level (§9).
- `wallet/src/handlers/dto.py`
  - `RefundRequest(BaseModel)`: every field optional and loosely typed (`userId: str |
    None`, `orderId: str | None`, `refundId: str | None`, `amountPaise: int | None`,
    `correlationId: str | None`), with **no** `Field(gt=0)`, so bad input reaches the
    hand-written 400s (finding 2).
  - `serialize_refund(outcome) -> dict`: the FR-3 body (`orderId`, `refundId`, `status:
    "REFUNDED"`, `amountPaise`, `balanceAfterPaise`, `ledgerEntryId`, `refundedAt` ISO,
    `replayed`).
- `wallet/src/handlers/internal_handlers.py`
  - Add `_REFUND_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")` and
    `_validate_refund_id(...)`, which raises `InvalidOrderIdError` (`VALIDATION_ERROR`, 400).
  - `@router.post("/wallet/internal/refunds")`: a missing or empty `userId` → 400
    `VALIDATION_ERROR`; `_validate_order_id(orderId)`; `_validate_refund_id(refundId)`;
    `amountPaise is None` → 400 `VALIDATION_ERROR`. Then call the service and return
    `success_envelope(serialize_refund(...))`. Update the module docstring's route list.

**Tests to write:**
- Unit (`wallet/tests/unit/domain/test_wallet_service.py`, new `class TestRefundForOrder`,
  using `seed_wallet` + `service.debit_for_order` to create the debit):
  - refund after a debit: balance back to its value before the debit; one `REFUND` row with
    ref `refund:ord_1:cancel` and `+amount`; one `WalletRefunded` outbox row whose payload
    passes `jsonschema.validate` against `load_schema("WalletRefunded")`;
  - replay: the same `ledger_entry_id`, `replayed=True`, still one `REFUND` row and one
    `WalletRefunded` outbox row;
  - no debit → `RefundDebitNotFoundError` (and `isinstance(..., DebitNotFoundError)`);
  - voided order (`service.void_debit_for_order` first) → `RefundDebitNotFoundError`;
  - over-refund (`cancel` for the full amount, then `extra` for 1 paise) →
    `RefundExceedsDebitError`, with `details == {"debitedPaise": …, "alreadyRefundedPaise":
    …}`; two refunds summing exactly to the debit both succeed;
  - prefix guard: debit and refund `ordX1`, then debit `ord_1` and refund `ord_1` in full →
    succeeds (`ordX1`'s refund isn't counted against `ord_1`);
  - `amount_paise` 0 and −1 → `InvalidAmountError`;
  - wallet status `FAILED` (seeded) with an existing debit → credited;
  - a debit on `user-1`'s wallet, refund requested as `user-2` (who also has a wallet) →
    `RefundOrderUserMismatchError`;
  - no wallet for `userId` → `WalletNotFoundError`.
- HTTP (`wallet/tests/integration/test_wallet_http.py`, the existing `TestClient` + SQLite
  harness):
  - `POST /wallet/internal/debit`, then `POST /wallet/internal/refunds` → 200 with the FR-3
    body; then `GET /wallet/me/transactions?types=REFUND` shows one entry with the right
    amount and ref;
  - repeat the refund → 200 with `replayed: true`;
  - one test per FR-4 row, asserting status, `errorCode` and envelope shape: bad `orderId`
    and bad `refundId` → 400 `VALIDATION_ERROR`; a missing field → 400; `amountPaise: 0` →
    400 `INVALID_AMOUNT`; no wallet → 404; no debit → 409 `DEBIT_NOT_FOUND`; over-refund →
    409 `REFUND_EXCEEDS_DEBIT` with `debitedPaise` in `data`; mismatch → 409;
  - two threads posting the same refund → exactly one `REFUND` ledger row (finding 3: this
    proves the UNIQUE/replay path);
  - extend `test_internal_debit_routes_are_only_internal` (or add a sibling) so
    `/wallet/internal/refunds` is in the internal set.
- Order client (`order/tests/unit/adapters/test_wallet_client_adapter.py`, mocked
  `requests`): see MA-153 FR-6 below.

**MA-153 FR-6 — Order Service client** (built here, used by MA-154):
- `order/src/domain/models.py`: `@dataclass(frozen=True) Refunded` with `amount_paise`,
  `balance_after_paise`, `refunded_at` (datetime), `replayed`.
- `order/src/domain/exceptions.py`:
  - `DebitNotFoundError(OrderError)` (`DEBIT_NOT_FOUND`, 409);
  - `RefundExceedsDebitError(OrderError)` (`REFUND_EXCEEDS_DEBIT`, 409);
  - `OrderUserMismatchError(OrderError)` (`ORDER_USER_MISMATCH`, 409).
  - Each docstring says it's never retried.
- `order/src/adapters/wallet_client_adapter.py`: `refund(user_id, order_id, refund_id,
  amount_paise, correlation_id) -> Refunded`.
  - `POST {base}/wallet/internal/refunds` with the FR-1 body and the existing `x-request-id`
    header. Also send `X-Correlation-Id: correlation_id` (MA-154 §5 asks for propagation).
  - `RequestException` and any 5xx → `_RetryableWalletError`.
  - 200 → parse into `Refunded` (malformed → `_UnexpectedWalletResponse`).
  - 409 with code `DEBIT_NOT_FOUND`, `REFUND_EXCEEDS_DEBIT` or `ORDER_USER_MISMATCH` → the
    typed exception (not retried).
  - Anything else → `_UnexpectedWalletResponse`.
  - Run it through `_call_debits_route(attempt, "refund", order_id)`, which already turns
    exhausted retries and unexpected responses into `WalletUnavailableError`. The typed
    409 exceptions aren't in `retryable_exceptions`, so they propagate unchanged.
- `order/src/adapters/interfaces.py`: add `refund(...)` to `WalletClientPort`.
- `order/tests/conftest.py`: `FakeWalletClient` gains `refund(...)`, a `refund_calls` list
  of `(user_id, order_id, refund_id, amount_paise)`, `refund_exception: Exception | None`,
  and a default `Refunded(...)` result.
- Tests (`test_wallet_client_adapter.py`): 200 → `Refunded`; 503 then 200 → retried and
  succeeds (two calls); a timeout then 200 → succeeds; each 409 code → its typed exception
  after **one** call; persistent 503 → `WalletUnavailableError`; 400 →
  `WalletUnavailableError` (unexpected), not retried.

**Acceptance check:** `cd wallet && pytest && ruff check .`, then `cd order && pytest
tests/unit/adapters/test_wallet_client_adapter.py && ruff check .`. All pass.

### MA-154: Order Service — Customer Order Cancellation

**Files to create:**
- `order/migrations/0004_customer_cancel.sql` — a header comment in the style of `0003`
  ("Applies on top of 0003_sweep.sql…"), then:
  - `ALTER TABLE orders ADD COLUMN cancel_reason TEXT NULL CHECK (...)` with the four values;
  - `cancelled_at TIMESTAMPTZ NULL`;
  - `refund_state TEXT NULL CHECK (refund_state IN ('PENDING','REFUNDED','NOT_REQUIRED'))`;
  - `refunded_at TIMESTAMPTZ NULL`;
  - `CREATE INDEX orders_refund_pending ON orders (cancelled_at) WHERE refund_state =
    'PENDING'`.

  Additive only, and immutable once merged.

**Files to modify:**
1. `order/src/domain/models.py`
   - `class CancelReason(StrEnum)`: `ORDERED_BY_MISTAKE`, `NOT_HOME`, `CHANGED_MIND`,
     `OTHER`.
   - `class RefundState(StrEnum)`: `PENDING`, `REFUNDED`, `NOT_REQUIRED`.
   - `FAILURE_CUSTOMER_CANCELLED = "CUSTOMER_CANCELLED"`.
   - `Order` gains `cancel_reason: CancelReason | None = None`, `cancelled_at: datetime |
     None = None`, `refund_state: RefundState | None = None` and `refunded_at: datetime |
     None = None`, all defaulted so existing constructors keep working.
2. `order/src/domain/cutoff.py` — `delivery_cutoff_moment(delivery_date, cutoff_hour_ist) ->
   datetime` (an aware IST datetime). Refactor `delivery_cutoff_passed` to call it, so FR-2
   and FR-7 share one definition (MA-154 FR-7).
3. `order/src/domain/exceptions.py`
   - `OrderNotCancellableError` (`ORDER_NOT_CANCELLABLE`, 409);
   - `CutoffPassedError` (`CUTOFF_PASSED`, 409).
   - The existing `ValidationError` (400) is reused for an unknown reason.
4. `order/src/adapters/order_repository.py`
   - `orders_table` gets the four columns, plus the two `CheckConstraint`s mirroring `0004`.
     Update the module docstring's migration list to include `0004`.
   - `_row_to_order` maps them, with a tolerant `None` for nulls.
   - `cancel_by_customer(order_id, *, reason, now, refund_state, outbox_payload) -> bool`:
     one `begin()` transaction:
     - a conditional `UPDATE ... WHERE id = :id AND status = 'CONFIRMED'`, setting `status`,
       `failure_reason`, `cancel_reason`, `cancelled_at` and `refund_state`;
     - **only if `rowcount == 1`**, insert the `OrderCancelled` outbox row.
     - Return whether it won.
   - `mark_refund_state(order_id, state, *, refunded_at=None, owner=None) -> bool`: a
     conditional `UPDATE ... WHERE id AND refund_state = 'PENDING'` (and `claim_owner =
     owner` when an owner is given), which also clears the lease (`**_LEASE_CLEARED`).
   - `list_pending_refunds(older_than_seconds, limit) -> list[str]`: `refund_state =
     'PENDING' AND cancelled_at < db_now - N` and the lease free, oldest `cancelled_at`
     first. Use `self._db_now_plus(-older_than_seconds)` (the database clock, as the other
     sweep queries do).
   - `claim_pending_refund(order_id, owner, lease_seconds) -> bool`: `self._claim(...)` with
     `refund_state == 'PENDING'`.
   - `oldest_pending_refund_age_seconds() -> float | None`: for the
     `order.refund.pending_age_seconds` metric.
   - Add the matching methods to `OrderRepositoryPort` in `adapters/interfaces.py`.
5. `order/src/domain/order_service.py`
   - The constructor gains keyword-only `cutoff_hour_ist: int = 20`, stored for FR-2/FR-7.
   - `cancel(order_id, user_id, reason: str | None, now: datetime, correlation_id: str) ->
     dict`:
     - parse `reason`: `None` → `None`; not a `CancelReason` value → `ValidationError`
       (`details={"field": "reason"}`);
     - load the order and apply FR-2 through a private `_check_cancellable(order, user_id,
       now)` that returns `"replay"` or raises `OrderNotFoundError` /
       `OrderNotCancellableError` (`details={"status": …}`) / `CutoffPassedError`
       (`details={"cancellableUntil": iso}`).
     - Replay → if `refund_state == PENDING`, run `finish_refund(order, correlation_id)` first,
       then return `_serialize(fresh order, now)`.
     - Otherwise build the `OrderCancelled` payload (FR-6, `refundState` at cancel time;
       `items` only for `CHECKOUT`, as in `OrderConfirmed`) and call
       `repo.cancel_by_customer(...)`. `refund_state` is `PENDING` if `amount_paise > 0`,
       else `NOT_REQUIRED`.
     - Lost the race (`False`) → re-read and re-run `_check_cancellable` (a replay or the
       409).
     - Won → if `PENDING`, `finish_refund(order, correlation_id)`.
     - Return `_serialize(repo.get(order_id), now)`.
     - Log `order.cancel` (`orderId`, outcome, `refundState`, `correlationId`) and emit
       `order.cancel.count{outcome}` through a `LoggingMetricsRecorder` (inject it as an
       optional constructor argument, defaulting to a new instance).
   - `finish_refund(order, correlation_id, *, owner=None) -> str`: public, because the sweep
     calls it too (same convention as `resume_debit`). It calls
     `self._wallet_client.refund(order.user_id, order.id, "cancel", order.amount_paise,
     correlation_id)`:
     - `Refunded` → `mark_refund_state(REFUNDED, refunded_at=now)`, return `"refunded"`;
     - `DebitNotFoundError` → `mark_refund_state(NOT_REQUIRED)` plus a warning log, return
       `"not_required"`;
     - `RefundExceedsDebitError` / `OrderUserMismatchError` → an error log with
       `metric="order.refund.data_error"` (alarm), release the lease if an owner is given,
       return `"error"`;
     - `WalletUnavailableError` or any other `Exception` → leave it `PENDING`, release the
       lease if an owner is given, return `"still_pending"`.
     - It never raises: the cancel request must still succeed (FR-3).
     - Emit `order.refund.outcome{outcome}`.
   - `get(...)` and `list_for_user(...)` gain an optional `now: datetime | None = None`
     (default `datetime.now(UTC)`) and pass `now` and the cut-off hour to `_serialize`.
   - `_serialize(order, now, cutoff_hour_ist)` adds the four FR-7 fields:
     - `cancellableUntil`: the ISO string of `delivery_cutoff_moment(...)`, only when the
       status is `CONFIRMED` and `now <` that moment; else `None`;
     - `cancelReason` and `refundState`: the enum value or `None`;
     - `cancelledAt`: ISO or `None`.
     - `checkout_service.py` doesn't call `_serialize` (verify with grep; if it does, pass
       the same arguments).
6. `order/src/domain/sweep_service.py` — `finish_pending_refunds(correlation_id, now) ->
   Counter`:
   - for each id from `repo.list_pending_refunds(60, self._batch_size)`, `claim_pending_refund`
     (skip if it's lost); re-`get` it; if it's no longer `PENDING`, release and skip;
   - otherwise `outcome = self._order_service.finish_refund(order, correlation_id,
     owner=self._owner)` and count it under `refunded` / `not_required` / `still_pending` /
     `error`;
   - wrap each record in the existing "one record never stops the run" `try/except` with
     `_release_quietly`;
   - after the loop, emit `order.refund.pending_age_seconds` with `value=` the oldest age
     (or 0).
7. `order/src/handlers/sweep.py` — add `("refund", service.finish_pending_refunds)` as the
   fourth pass, after `settle`.
8. `order/src/handlers/order_handlers.py`
   - `CancelRequest(BaseModel)` with `reason: str | None = None` (a string, not the enum,
     so an unknown value reaches the service's 400 and not a 422).
   - `@router.post("/orders/{order_id}/cancel")` with `body: CancelRequest | None = None`,
     `request_id: str | None = Header(default=None, alias="x-request-id")`,
     `X-Correlation-Id` read the same way, `current_user_id`, and `get_order_service`.
     It calls `service.cancel(order_id, user_id, body.reason if body else None,
     datetime.now(UTC), correlation_id or str(uuid4()))` and returns `success_envelope`.
   - Update the module docstring: it's no longer read-only.
   - Route order: `/orders/{order_id}/cancel` is a POST, so it can't collide with
     `/orders/checkout`; the checkout router is already included first.
9. `order/src/handlers/dto.py` — update the docstring ("No request DTOs" is no longer true).
10. `order/src/handlers/dependencies.py` — `get_order_service()` passes
    `cutoff_hour_ist=settings.checkout_cutoff_hour_ist`.
11. `order/README.md` — add the endpoint, the fourth sweep pass and the three metrics.

**Tests to write:**
- Unit (`order/tests/unit/domain/test_order_service.py`, a new `class TestCancel`, fixed
  `now` datetimes, and a helper that seeds a `CONFIRMED` order via `repo.insert_created` +
  `repo.mark_confirmed`):
  - happy path with reason `NOT_HOME`: the status, `failure_reason`, `cancel_reason`; one
    `OrderCancelled` outbox row that passes `jsonschema.validate`; `wallet_client.refund_calls
    == [("user-1", id, "cancel", amount)]`; the returned dict has `refundState ==
    "REFUNDED"`, `cancellableUntil is None`;
  - no reason → `cancel_reason is None`; `"LOL"` → `ValidationError`;
  - `now` exactly at `delivery_cutoff_moment` → `CutoffPassedError`; one second before →
    succeeds;
  - non-owner → `OrderNotFoundError`; `CREATED`, `PAYMENT_FAILED`, and `CANCELLED` with
    `CUTOFF_PASSED` → `OrderNotCancellableError`;
  - replay after `REFUNDED` → the same body, `refund_calls` still has one entry;
  - replay while `PENDING` (first call with `refund_exception = WalletUnavailableError(...)`,
    then cleared) → second call is `REFUNDED`, two refund calls;
  - Wallet unavailable → returns normally with `refundState == "PENDING"`;
    `DebitNotFoundError` → `NOT_REQUIRED`; `RefundExceedsDebitError` → stays `PENDING`;
  - a ₹0 order (seed a `CONFIRMED` row with `amount_paise=0` directly through
    `orders_table`; no existing helper creates one) → `NOT_REQUIRED`, no refund call, and the
    event's `refundState == "NOT_REQUIRED"`;
  - `_serialize`'s `cancellableUntil`: set for `CONFIRMED` before the cut-off (equals
    `delivery_date - 1` at 20:00 IST in ISO), `None` after it, `None` for `CANCELLED`.
- Unit (`test_order_repository.py`): `cancel_by_customer` returns False and writes no outbox
  row when the order isn't `CONFIRMED`; `mark_refund_state` is a no-op once it's not
  `PENDING`.
- Cutoff (`test_order_service.py` or a new `test_cutoff.py`): `delivery_cutoff_moment(date(2026,
  10, 8), 20)` == 2026-10-07 20:00 IST; `delivery_cutoff_passed` is unchanged at the boundary.
- Sweep (`order/tests/unit/domain/test_sweep_service.py`): a `PENDING` order whose
  `cancelled_at` is 2 min old → `refunded`; 30 s old → not listed; a lease held by another
  owner → skipped; Wallet still down → `still_pending`, the lease released, still `PENDING`;
  and `run_once` (`handlers/sweep.py`) includes the `refund.*` counts.
- Integration (`order/tests/integration/test_order_flow.py`, `TestClient` + SQLite,
  `FakeWalletClient` via the service fixture):
  - `POST /orders/{id}/cancel` with `{"reason": "NOT_HOME"}` → 200, then `GET /orders/{id}`
    shows `cancelReason`, `cancelledAt`, `refundState`, and `cancellableUntil: null`;
  - an empty body and no body both → 200;
  - every error: 404 (another user's JWT), 409 `ORDER_NOT_CANCELLABLE` with `status` in
    `data`, 409 `CUTOFF_PASSED` with `cancellableUntil`, 400 `VALIDATION_ERROR` for an
    unknown reason. Assert the envelope shape;
  - two threads cancelling at once → one `OrderCancelled` outbox row, one winning `UPDATE`,
    and a final `refundState == "REFUNDED"`. Assert **1 ≤ refund calls ≤ 2**, not exactly one:
    if the loser's replay lands while the winner is still `PENDING`, it correctly runs its own
    (idempotent) refund. MA-154 §10's "one Wallet refund call" holds at the ledger: MA-153's
    `ref` makes the second call a replay.
- Migration: covered by the local-dev run (§6). `apply_migrations.py` applies `0004` on top
  of `0003` against real Postgres.

**Acceptance check:** `cd order && pytest && ruff check .`. Then the local-dev E2E in §6.

### MA-155: Flutter — Cancel Order & Cancel Delivery

**Files to create:**
- `lib/features/orders/domain/cancel_copy.dart` — pure Dart:
  - `String reasonLabel(CancelReason)` (the four labels);
  - `String cancelPolicyLine(DateTime cancellableUntil)` → "Free cancellation until 8:00 PM,
    Wed 7 Oct". It formats `istNow(() => cancellableUntil)` with `DateFormat('h:mm a')` and
    `DateFormat('EEE d MMM')`;
  - `String deliveryPolicyLine(DateTime deliveryDate)` (FR-5's line);
  - `String sheetPolicy(OrderSummary)` (the full-refund text or "Nothing was charged for
    this order.");
  - `String cancelResultMessage(OrderSummary)` (the three FR-3 SnackBars, by `refundState`);
  - constants for the other FR-3/FR-5 strings: the cut-off, not-cancellable, failed,
    "already an order", "Delivery on … cancelled.", and `cancellationClosedLine`.
- `lib/features/orders/presentation/widgets/cancel_order_sheet.dart` — a `StatefulWidget`
  shown with `showModalBottomSheet(isDismissible: false, enableDrag: false)`.
  - It holds the selected `CancelReason?`, `submitting` and an inline `error`.
  - The confirm button calls an injected `Future<CancelOutcome> Function(CancelReason?)`.
    On `failed` it sets `error` and re-enables, keeping the chip. On any other outcome it
    `Navigator.pop`s with the outcome.
  - It wraps the sheet in `PopScope(canPop: !submitting)`.
  - The keys and copy follow FR-2. Chips use `ChoiceChip(selected:, onSelected:)`, so the
    selected state is announced.
  - The busy confirm button uses the `Semantics(button: true, enabled: false, label:
    'Cancel order', excludeSemantics: true)` pattern from MA-152's Reorder.

**Files to modify:**
1. `lib/core/utils/ist_clock.dart` — `DateTime deliveryCutoff(DateTime deliveryDate, {int
   cutoffHourIst = 20})`: the UTC instant of 20:00 IST on `deliveryDate - 1` (that's 14:30
   UTC). A doc comment says the hour must match Order/Subscription Service's
   `checkout_cutoff_hour_ist`. Used by FR-5 and FR-6.
2. `lib/features/orders/models/order_summary.dart`
   - `enum CancelReason { orderedByMistake, notHome, changedMind, other }` with `wire` and a
     `static CancelReason? fromWire(Object?)` (unknown → null).
   - `enum RefundState { pending, refunded, notRequired }`, the same way.
   - `OrderSummary` gains `cancellableUntil` (`_parseInstant`), `cancelReason`,
     `cancelledAt` and `refundState`, added to the constructor, `fromJson` and `props`.
   - A getter `bool get isCustomerCancelled => status == OrderStatus.cancelled &&
     failureReason == 'CUSTOMER_CANCELLED'`.
3. `lib/features/orders/domain/order_status_copy.dart`
   - `isKnownNotCharged`: `'CANCELLED' => !order.isCustomerCancelled`.
   - `reasonText(String? failureReason, [OrderSummary? order])`: a `'CUSTOMER_CANCELLED'`
     arm that picks one of FR-4's three strings by `order?.refundState`, with the amount
     from `formatPaise(order.amountPaise, alwaysDecimals: true)`. Without an `order`, fall
     back to "You cancelled this order.".
   - `billCaption`: before the existing rules, `if (order.isCustomerCancelled) return switch
     (order.refundState) { refunded => 'Refunded to Wallet', pending => 'Refund in
     progress', _ => null }`.
4. `lib/features/orders/domain/order_buckets.dart:115` — the day total skips
   `order.isCustomerCancelled` as well as struck amounts (finding 8). Add a comment
   citing the decision.
5. `lib/features/orders/data/order_repository.dart` — `Future<OrderSummary> cancel(String
   orderId, {CancelReason? reason})` on the interface. `DioOrderRepository` sends `POST
   ${AppConfig.orderBaseUrl}/orders/${Uri.encodeComponent(orderId)}/cancel` with data
   `{'reason': reason.wire}` or `{}`. Update the class doc ("read APIs" → plus cancel).
6. `lib/features/orders/bloc/order_detail_cubit.dart`
   - `OrderDetailLoaded` gains `cancelling` (default false) in the constructor, `copyWith`
     and `props`.
   - The `_fetch` path keeps `cancelling` the way it keeps `reordering`.
   - `enum CancelOutcome { cancelled, cutoffPassed, notCancellable, failed }`.
   - `Future<CancelOutcome?> cancel(CancelReason? reason)`:
     - null if not loaded or already cancelling;
     - emit `cancelling: true`;
     - on success emit `OrderDetailLoaded(returnedOrder, products)` (re-resolve products
       only if the item ids changed; otherwise reuse);
     - on `ApiException` with `CUTOFF_PASSED` / `ORDER_NOT_CANCELLABLE`, clear `cancelling`,
       `await refresh()`, and return the outcome;
     - anything else: clear `cancelling` and return `failed`.
7. `lib/features/orders/bloc/scheduled_delivery_cubit.dart`
   - `enum SkipOutcome { cancelled, cutoffPassed, alreadyOrder, failed }`.
   - `Future<SkipOutcome?> cancelDelivery()`: only when `ScheduledDeliveryLoaded`; calls
     `_subscriptions.skip(subscriptionId, entry.date)`.
     - Success → `cancelled`.
     - `ApiException(errorCode: 'CUTOFF_PASSED')` → `alreadyOrder` if `_clock() <
       deliveryCutoff(entry.date)`, else `cutoffPassed`; then `await refresh()` (which
       already detects `BecameOrder`).
     - Otherwise `failed`.
   - Add `alreadyOrder` to the outcomes: MA-155 FR-7 lists three, but FR-5's review fix
     needs the fourth to choose the copy.
8. `lib/features/orders/presentation/order_detail_screen.dart`
   - Add `final Clock? clock` (finding 5), resolved once as `clock ?? DateTime.now`.
   - Banner `note:` → `reasonText(order.failureReason, order)`.
   - Under the Reorder/Support column, a `_CancelSection(order, now, cancelling)`:
     - when `order.cancellableUntil != null && now.isBefore(cancellableUntil)`: the policy
       line and the error-coloured `TextButton(key: Key('orderDetail.cancel'))`, at least
       48 dp, which opens the sheet;
     - else when `status == CONFIRMED && !now.isBefore(deliveryCutoff(order.deliveryDate))`:
       the muted `cancellationClosedLine`;
     - else nothing.
   - `_cancel(context)`:
     - capture the messenger and router before any await;
     - `final outcome = await showModalBottomSheet<CancelOutcome>(...)`, passing
       `cubit.cancel` into the sheet;
     - map the outcome to the FR-3 SnackBar. On `cancelled`, use the
       `cancelResultMessage(state.order)` text with a **Shop for tomorrow** action →
       `router.go('/catalog')`.
9. `lib/features/orders/presentation/scheduled_delivery_screen.dart`
   - Above "Manage subscription": when `now < deliveryCutoff(entry.date)`, the policy line
     and `TextButton(key: Key('scheduled.cancel'))`; else the closed line.
   - `_cancelDelivery(context)`: an `AlertDialog(key: Key('cancelDelivery.dialog'))` with
     FR-5's title, body (product name or "Item") and buttons. On confirm, call
     `cubit.cancelDelivery()` and map the outcome:
     - `cancelled` → SnackBar with **Shop for tomorrow**, then `context.pop()`;
     - `cutoffPassed` / `alreadyOrder` → their copy;
     - `failed` → "Couldn't cancel. Try again.".
   - SnackBar ordering for `alreadyOrder`: `cancelDelivery()` only returns after its
     `refresh()`, so the existing `BecameOrder` listener has already shown "This delivery is
     now an order." by then. The screen then calls `hideCurrentSnackBar()` and shows "This
     delivery is already an order. Cancel it from the order instead." with the same **View
     order** action (`pushReplacement('/orders/$orderId')`, the id taken from the state's
     `BecameOrder` change). The user ends up seeing the spec's copy, with a way to reach the
     order.
10. `lib/core/router/app_router.dart` — no route changes. `OrderDetailScreen`'s new `clock`
    is optional.
11. `test/fakes/fake_order_repository.dart`
    - `cancelResult` (`OrderSummary?`), `cancelException`, `cancelGate` (`Completer<void>?`),
      and `cancelCalls` (`List<(String, CancelReason?)>`).
    - `testOrder(...)` gains the optional `cancellableUntil`, `refundState` and
      `cancelReason` arguments.
12. `test/fakes/fake_subscription_repository.dart` — `skipDates` (`List<DateTime>`) next to
    `skipCalls` (finding 6). Reuse the existing failure hook, which per its doc applies to
    skip.

**Tests to write:**
- `test/features/orders/domain/order_domain_test.dart`:
  - update the `isAmountStruck` and `billCaption` expectations so the existing
    `OrderStatus.cancelled` cases still pass when `failureReason` isn't
    `CUSTOMER_CANCELLED`;
  - add: `isKnownNotCharged` false for `CUSTOMER_CANCELLED`, true for `CANCELLED` +
    `CUTOFF_PASSED`;
  - the three `reasonText('CUSTOMER_CANCELLED', order)` variants, with amount formatting;
  - `billCaption` for each `refundState`, and null for `NOT_REQUIRED`/null;
  - `deliveryCutoff(DateTime(2026,10,8))` == `DateTime.utc(2026,10,7,14,30)`;
  - the day total excludes a customer-cancelled order and still counts a confirmed one.
- `order_summary` parsing (in `order_domain_test.dart`, or a new
  `test/features/orders/models/order_summary_test.dart`): the four fields parse; an unknown
  `refundState` / `cancelReason` → null; missing → null.
- `cancel_copy_test.dart` (new, `test/features/orders/domain/`): the policy line for
  `DateTime.utc(2026,10,7,14,30)` → "Free cancellation until 8:00 PM, Wed 7 Oct"; the four
  labels; the three result messages.
- `test/features/orders/bloc/detail_cubits_test.dart` — every MA-155 §10 cubit case, plus
  `cancelDelivery` returning `alreadyOrder` when the fake skip throws `CUTOFF_PASSED` before
  the cut-off, and `cutoffPassed` after it.
- `test/features/orders/presentation/detail_screens_test.dart` — every MA-155 §10 widget
  scenario. Pass `clock:` to `OrderDetailScreen` in the existing router helper (line ~126).
  The "cut-off passed on submit" scenario uses a mutable `DateTime` the clock closure reads,
  advanced past 20:00 IST before tapping confirm. Assert keys and visible copy exactly as
  the spec lists them.

**Acceptance check:** `flutter analyze` (no new issues) and `flutter test`, both from the
`milkful-app` root, all green. **Don't run `dart format` on directories**: the repo isn't
formatter-clean, and it reflows unrelated files. Format only the files you touched, or not
at all.

---

## 5. Cross-Cutting Steps

- **Event schemas:** after both services' tests pass, `grep -r "WalletRefunded\|OrderCancelled"`
  confirms each producer validates its payload against `shared/events` in tests.
- **Docs:** `shared/events/README.md` (Step 1), `order/README.md` (the endpoint, sweep pass and
  metrics), and the module docstrings noted per file.
- **Alarms (record in the PR description for ops; no IaC exists for these services' metric
  filters yet):**
  - `order.refund.pending_age_seconds > 900`;
  - any `order.refund.data_error`;
  - `wallet.refund.count{outcome=ORDER_USER_MISMATCH}`.
- **Lint:** `ruff check .` in `wallet/` and `order/`; `flutter analyze` in `milkful-app`.
- **Full test runs:** each service's `pytest`, then the app's `flutter test`.

## 6. Test Strategy

| Layer | Where | What it proves |
|-------|-------|----------------|
| Unit (Python) | `wallet/tests/unit`, `order/tests/unit` | Business rules, error mapping, idempotency, the cap and prefix guard, cut-off boundaries, sweep selection and claiming |
| HTTP (Python) | `wallet/tests/integration`, `order/tests/integration` (SQLite + `TestClient`) | Routes, envelopes, status codes, replay under threads (UNIQUE / conditional `UPDATE`, not the row lock; finding 3) |
| Unit/bloc (Dart) | `test/features/orders/domain`, `.../bloc` | Copy, parsing, cubit outcomes |
| Widget (Dart) | `test/features/orders/presentation` | The FR-1..FR-6 UI with a fixed clock |
| Local-dev E2E (manual) | `services/local-dev` + the app | Postgres-only behaviour: migration `0004` applies, `FOR UPDATE`, the partial index, and the real Wallet ↔ Order call |

**Commands:**
- `cd services/wallet && pytest && ruff check .`
- `cd services/order && pytest && ruff check .`
- `cd milkful-app && flutter analyze && flutter test`

**Coverage:** no numeric threshold is configured in either repo (`pyproject.toml` has no
`--cov-fail-under`; the app has no coverage gate). The bar is: every FR and every error row in
MA-153 FR-4 and MA-154 FR-2 has at least one test.

**Local-dev E2E (run before opening the code PRs):**
1. `docker compose up -d` in `services/local-dev`; confirm `apply_migrations.py` reports
   `0004_customer_cancel.sql` applied to `milkful_order`.
2. Check out a cart in the app (or `POST /orders/checkout`) so an order is `CONFIRMED` for
   tomorrow, before 20:00 IST.
3. Open it in the app → the policy line shows; cancel with a reason → "Order cancelled.
   ₹… refunded to your Wallet."
4. Transaction History shows "Refund for Order" for that order, and the balance is back to
   its value before checkout.
5. Stop the `wallet` container, cancel another order → "Your refund is on its way." Start
   Wallet again; within one sweep interval the order shows "Refunded to Wallet" after
   pull-to-refresh.
6. Cancel tomorrow's subscription delivery from Scheduled Delivery → it's gone from My Orders.

## 7. Commit Strategy

**`services`** (branch `feat/MA-32-order-cancellation`, one PR), using the repo's
`impl(MA-xx): …` / `fix(MA-xx): …` convention:
1. `impl(MA-32): shared WalletRefunded and OrderCancelled event schemas`
2. `impl(MA-32): wallet internal refund route (MA-153)`
3. `impl(MA-32): order wallet client refund (MA-153 FR-6)`
4. `impl(MA-32): order customer cancel, migration 0004 and refund sweep (MA-154)`

**`milkful-app`** (branch `feat/MA-32-cancel-order`, one PR), using the repo's
`[MA-xx] [App] feat: … (MA-yyy)` convention:
1. `[MA-32] [App] feat: order cancel data layer and copy (MA-155)`
2. `[MA-32] [App] feat: Cancel order sheet on Order Detail (MA-155)`
3. `[MA-32] [App] feat: Cancel delivery on Scheduled Delivery (MA-155)`

Every commit leaves its repo's tests green. End each commit message with the
`Co-Authored-By` trailer when an agent wrote it.

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| Reusing Wallet's `DebitNotFoundError`/`OrderUserMismatchError` as-is would return 404/400 and break MA-154's 409 mapping | Refund-only 409 subclasses (finding 1); the HTTP tests assert the statuses |
| FastAPI's 422 leaking out where the specs promise 400 | Loose request models plus hand validation (finding 2); the HTTP tests assert 400 |
| SQLite tests don't exercise `FOR UPDATE` or Postgres `CHECK`s | The local-dev E2E on Postgres (§6) is required before merge, not optional |
| Unescaped `LIKE` counts another order's refunds (`_` wildcard) | `startswith(..., autoescape=True)` plus a dedicated `ord_1`/`ordX1` test |
| The request's Step B and the sweep refunding the same order at once | The sweep's 60 s grace and lease; MA-153's `ref` idempotency makes a double call a replay, and `mark_refund_state` is conditional on `PENDING` |
| The app shipping before MA-154 | Missing fields hide Cancel; FR-6's "closed" line keys off the device cut-off, so no false "closed" (MA-155 §7) |
| App and backend cut-off hours drifting apart | One app constant in `deliveryCutoff` with a doc comment naming the backend setting; the server stays authoritative |
| The architecture doc's `OrderCancelled → wallet-events-q` refund path added later by someone following the doc | Finding 7; the PR description says the refund is synchronous and that no wallet rule consumes `OrderCancelled` |
| Production migration `0004` | Additive and nullable; needs the human approval in `services/README.md` §3.6 before deploy |
| Scheduled Delivery showing two SnackBars when the delivery has become an order | MA-155 step 9 makes the cancel SnackBar carry "View order" for `alreadyOrder`; covered by the "already an order" widget scenario |
