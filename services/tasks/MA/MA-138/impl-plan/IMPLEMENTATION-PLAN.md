# Implementation Plan — MA-138: Order Service Reconciliation Sweep

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-138](https://milkfuldairyindia.atlassian.net/browse/MA-138) — Order Service: recover stuck checkouts and stuck subscription orders (reconciliation sweep) |
| **Date** | 2026-09-29 |
| **Specs implemented** | [MA-142](https://milkfuldairyindia.atlassian.net/browse/MA-142) — Wallet Service: Debit Lookup by Order · [MA-143](https://milkfuldairyindia.atlassian.net/browse/MA-143) — Order Service: Sweep Framework & Stuck Subscription-Order Recovery · [MA-144](https://milkfuldairyindia.atlassian.net/browse/MA-144) — Order Service: Stuck Checkout Recovery |
| **Spec source** | `services/tasks/MA/MA-138/*.md` on `main` (merged via [specs#25](https://github.com/milkful2026/specs/pull/25), `0b747bd`) |
| **Repos touched** | `milkful2026/services` (`wallet`, `order`, `local-dev`) · `milkful2026/milkful-app` (one test file only) |
| **Code branches** | `services`: `feat/MA-138-order-sweep` (one PR; see §7) · `milkful-app`: `test/MA-138-unknown-409` |

**What this delivers:** a background sweep inside Order Service that finishes or safely
closes every half-done record. Subscription orders stuck `CREATED` are charged once or
escalated without charging after the 20:00 IST day-before cut-off. Abandoned checkouts are
completed, cancelled without charging (PD-1, only after Wallet confirms no debit), or
completed with unstarted subscription lines left in the cart (PD-2). A lease stops the
sweep, SQS redelivery and customer retries from working on the same record at once.

**Codebase reality found during analysis (Step 2), which shapes the plan:**

1. **Neither `order` nor `wallet` has an `infra/` CDK stack** (`order/README.md` lists it as
   not done). MA-143 §6's CloudWatch alarm can't be built in this story. The plan emits the
   metrics exactly as specified and records the alarm definition in `order/README.md`'s
   infra to-do, for the stack story to pick up. Everything else in the specs is buildable.
2. **`CheckoutService` has no clock parameter, but `checkout(..., now=...)` does.** The sweep
   passes `now` the same way, so IST cut-off tests stay deterministic without a clock
   abstraction.
3. **`update_checkout` always bumps `updated_at`.** The sweep's own writes would reset the
   stale timer. That is correct (a record the sweep just touched isn't stale), and the lease
   helpers must **not** bump `updated_at`, so a claim alone doesn't hide a stuck checkout
   from the next run.
4. **Status columns are `VARCHAR(16)` with no CHECK constraint** (`0001_orders.sql`,
   `0002_checkout.sql`). `NEEDS_ATTENTION` (15 chars) fits; no constraint change is needed.
5. **The consumer already leaves any `OrderError` unacked** (`order_events_consumer.py`
   `_process_message`), so MA-143 FR-5's `OrderBusyError` needs no consumer change, only the
   new exception class.
6. **Wallet already has the 404 pattern** (`WalletNotFoundError`, `http_status = 404`) and
   `ledger_entries.ref` is `UNIQUE`, so MA-142 is a read method plus a route.
7. Baseline: `order` 100 tests pass, `wallet` 67 pass (per-service `.venv`, `pytest`).
   `ruff 0.16.5` is installed in the venvs.

## 2. Prerequisites

| Prerequisite | Status | Action |
|--------------|--------|--------|
| Per-service test venvs (`order/.venv`, `wallet/.venv`) | Already satisfied | — |
| New Python packages | None needed (`sqlalchemy`, `requests`, `fastapi` present) | — |
| `ORDER_SWEEP_*` / `ORDER_SUBSCRIPTION_ORDER_STALE_SECONDS` / `ORDER_CHECKOUT_STALE_SECONDS` settings | Not done | Add to `order/src/config/env.py` (MA-143 FR-7 defaults) |
| local-dev short thresholds | Not done | `local-dev/docker-compose.yml` `order` service `environment:` (MA-143 FR-7 local column) |
| Migration runner applies `0003_*.sql` | Already satisfied (`local-dev/apply_migrations.py` applies sorted `*.sql`, tracked in `schema_migrations`) | — |
| Scratch Postgres 16 for migration verification | Already satisfied (`local-dev-postgres-1`, user `milkful`) | Create a throwaway `milkful_order_scratch` DB for §6 check 4; drop it after |
| CloudWatch alarm | **Blocked** (no `order/infra`) | Document in `order/README.md` (§4, MA-143 step 9) |

## 3. Implementation Order

1. **MA-142 (Wallet debit lookup)** first. MA-144's PD-1 must not ship without it, and it
   has no dependencies.
2. **MA-143 (sweep framework + subscription orders)** second. It owns the migration, the
   lease, the budget and the loop that MA-144 plugs into.
3. **MA-144 (checkout recovery)** last. It uses MA-142's client and MA-143's loop, columns
   and lease.

## 4. Per-Spec Implementation Steps

### MA-142: Wallet Service — Debit Lookup by Order

**Files to modify (wallet):**
- `wallet/src/adapters/interfaces.py`: `WalletRepositoryPort.get_ledger_entry_by_ref(ref: str) -> LedgerEntry | None`.
- `wallet/src/adapters/wallet_repository.py`: implement it as a plain `select(ledger_entries_table).where(ref == :ref)` with **no** `with_for_update`; map the row with the existing row-mapping helper (add a `LedgerEntry` dataclass in `domain/models.py` if none exists: `wallet_id`, `type`, `amount_paise`, `balance_after_paise`, `ref`, `created_at`).
- `wallet/src/domain/exceptions.py`: `DebitNotFoundError(WalletError)`, `error_code = "DEBIT_NOT_FOUND"`, `http_status = 404`; `InvalidOrderIdError(WalletError)`, `error_code = "VALIDATION_ERROR"`, `http_status = 400` (Wallet has no validation-error class and no `RequestValidationError` handler, so FastAPI's default 422 must not be relied on).
- `wallet/src/domain/wallet_service.py`: `get_debit_for_order(order_id) -> dict`. Build `ref = f"order:{order_id}"`. No row, or a row whose `type != LedgerType.ORDER_DEBIT` (log `ERROR` for the latter) → raise `DebitNotFoundError`. Otherwise return `{orderId, status: "DEBITED", amountPaise: abs(amount_paise), balanceAfterPaise, debitedAt: created_at ISO-8601, walletId}`.
- `wallet/src/handlers/internal_handlers.py`: `@router.get("/wallet/internal/debits/{orderId}")`. Take `orderId` as a plain `str` path parameter and validate it in the handler against `^[A-Za-z0-9_-]{1,64}$`; on mismatch raise `InvalidOrderIdError`, which the existing `WalletError` handler renders as `400 VALIDATION_ERROR`. Return `success_envelope(...)`. Log `orderId`, `found`, and `correlationId` from `X-Correlation-Id`. Update the module docstring's route list.
- `wallet/README.md`: add the route to the internal endpoints table.

**Files to modify (order, the client half of MA-142 FR-5):**
- `order/src/domain/models.py` (or `checkout_models.py`, wherever `DebitResult` lives): `DebitLookup(amount_paise: int, balance_after_paise: int, debited_at: datetime)` frozen dataclass.
- `order/src/adapters/wallet_client_adapter.py`: `HttpWalletClient.get_debit(order_id) -> DebitLookup | None`, reusing the class's existing retry helper and timeout exactly as `debit` does. `200` → `DebitLookup`; `404` with `errorCode == "DEBIT_NOT_FOUND"` → `None`; 5xx/timeout/connection → retry, then `WalletUnavailableError`; any other 4xx (including a 404 without that code) → log `ERROR` and raise `WalletUnavailableError`.
- `order/src/adapters/interfaces.py`: add `get_debit` to the wallet port.

**Tests to write:**
- `wallet/tests/unit/domain/test_wallet_service.py`: found → dict with a positive `amountPaise` equal to the debited amount; unknown ref → `DebitNotFoundError`; a non-`ORDER_DEBIT` row on the ref → `DebitNotFoundError` and an `ERROR` log (`caplog`).
- `wallet/tests/integration/test_wallet_http.py`: `POST /wallet/internal/debit` for `ord_x`, then `GET /wallet/internal/debits/ord_x` → 200 with matching `amountPaise` and `balanceAfterPaise`; `GET …/ord_unknown` → 404 `DEBIT_NOT_FOUND`; `GET …/bad%20id` → 400 `VALIDATION_ERROR`; a repeated GET returns an identical body.
- `wallet/tests/integration/test_wallet_http.py`: route-table test that no JWT/public router mounts `/wallet/internal/debits`.
- `order/tests/unit/adapters/test_wallet_client_adapter.py`: 200 → `DebitLookup`; 404 `DEBIT_NOT_FOUND` → `None`; 503, 503, 200 → `DebitLookup`; 503 on every attempt → `WalletUnavailableError`; 400 → `WalletUnavailableError`; 404 without the code → `WalletUnavailableError`.

**Acceptance check:** `cd wallet && .venv/Scripts/python -m pytest -q` and `cd order && .venv/Scripts/python -m pytest tests/unit/adapters/test_wallet_client_adapter.py -q` pass; `curl localhost:8006/wallet/internal/debits/<a real checkout order id>` on the local stack returns 200.

### MA-143: Order Service — Sweep Framework & Stuck Subscription-Order Recovery

**Files to create:**
- `order/migrations/0003_sweep.sql`: exactly MA-143 §7 (four columns on each of `orders` and `checkouts`, plus the two partial indexes). Header comment in the style of `0002_checkout.sql`.
- `order/src/domain/sweep_service.py`: `SweepService` (subscription-order pass now; checkout pass added by MA-144).
- `order/src/handlers/sweep.py`: `run_once()` / `run_forever()` loop (the Payment `handlers/reconcile.py` shape).
- `order/tests/unit/domain/test_sweep_service.py`
- `order/tests/unit/adapters/test_sweep_repository.py`
- `order/tests/integration/test_sweep_flow.py`

**Files to modify:**
- `order/src/config/env.py`: `sweep_enabled: bool = True`, `sweep_interval_seconds: float = 300`, `subscription_order_stale_seconds: float = 900`, `checkout_stale_seconds: float = 600`, `sweep_max_attempts: int = 6`, `sweep_lease_seconds: float = 120`, `sweep_batch_size: int = 50`. Add a pydantic validator rejecting `sweep_lease_seconds < 60` (MA-143 FR-7).
- `order/src/domain/models.py`: `OrderStatus.NEEDS_ATTENTION`; `Order` gains `sweep_attempts: int = 0`, `claimed_until: datetime | None = None`, `claim_owner: str | None = None`, `last_sweep_error: str | None = None`. Failure reasons `CUTOFF_PASSED`, `SWEEP_EXHAUSTED` as constants.
- `order/src/domain/checkout_models.py`: `Checkout` gains the same four fields (read by MA-144; added now so `_row_to_checkout` maps the new columns in one place).
- `order/src/domain/exceptions.py`: `OrderBusyError(OrderError)` (`error_code = "ORDER_BUSY"`, `http_status = 409`; never reaches HTTP, it's for the consumer path).
- `order/src/adapters/order_repository.py`:
  - Table definitions: add the four columns to `orders_table` and `checkouts_table`; `_row_to_order` / `_row_to_checkout` map them. `create_schema` (SQLite tests) picks them up.
  - `list_stale_subscription_orders(older_than_seconds, limit) -> list[str]`: MA-143 FR-4 query. Compute the cutoff timestamp in Python (`datetime.now(UTC) - timedelta(...)`) so the same statement works on SQLite and Postgres.
  - Generic lease helpers parameterised by table: `claim(table, record_id, owner, lease_seconds, status_predicate) -> bool`, `renew(table, record_id, owner, lease_seconds) -> bool`, `release(table, record_id, owner) -> None`. Each is one `UPDATE … WHERE` with `rowcount == 1` as the result. **Use the database clock for "now"** (`func.now()` in the `SET`/`WHERE`), never the app clock (MA-143 §9 clock skew). They must not touch `updated_at` (§1 item 3). Expose thin wrappers `claim_order` / `renew_order` / `release_order` (and the checkout ones for MA-144).
  - `record_order_sweep_failure(order_id, owner, error_code, max_attempts) -> bool`: one `UPDATE` that increments `sweep_attempts`, sets `last_sweep_error`, clears the lease, and sets `status = NEEDS_ATTENTION`, `failure_reason = SWEEP_EXHAUSTED` when the new count reaches `max_attempts` (use a `CASE` expression). Returns whether it escalated.
  - `escalate_order(order_id, owner, reason)`: `status = NEEDS_ATTENTION`, `failure_reason = reason`, lease cleared, guarded by `status = CREATED`.
  - `mark_confirmed` and `mark_payment_failed`: also set `claimed_until = NULL, claim_owner = NULL` in the same `UPDATE`.
- `order/src/domain/order_service.py`: `materialize`'s "existing `CREATED`" branch gains a `claim_owner` argument (default `None` for callers that don't pass one). When given, claim with `status_predicate = CREATED` first. Lost → raise `OrderBusyError`. Won → `_debit_and_finalize`; on `WalletUnavailableError` release the lease, then re-raise. The terminal-order no-op branch treats `NEEDS_ATTENTION` like any terminal status (acked, logged, not charged).
- `order/src/adapters/order_events_consumer.py`: pass `claim_owner=f"sqs:{message['MessageId']}"` into `materialize` (thread it through `_dispatch`). No change to error handling (§1 item 5).
- `order/src/domain/sweep_service.py` (new): `SweepService(repository, order_service, *, settings, owner, metrics)` with `sweep_subscription_orders(correlation_id, now) -> dict[str, int]`. Per MA-143 FR-4: list → claim (skip on loss) → re-read (release and skip if not `CREATED`) → cut-off check `now_ist >= datetime.combine(delivery_date - 1 day, time(cutoff_hour), IST)` → `escalate_order(CUTOFF_PASSED)` with no Wallet call; else `renew` then `order_service._debit_and_finalize(order, correlation_id)` (make it a public `resume_debit` alias rather than calling a private method across classes); `WalletUnavailableError` → `record_order_sweep_failure`. Each record runs in its own `try/except Exception` (log with `exc_info`, count `failed_attempt`, attempt `record_order_sweep_failure`). Returns the counters.
- Metrics: emit via the service's existing structured-log metric style (see `order.confirmed` in `order_service.py`): `sweep.subscription_order.{found,resumed,confirmed,payment_failed,escalated,failed_attempt}` with `reason` on `escalated`; `sweep.run_duration_ms`; `sweep.run_failed`. Every record decision logs `orderId`, `attempt`, `outcome`, `correlationId`, `claimOwner`.
- `order/src/handlers/sweep.py` (new): `build_sweep_service()` (reuses `handlers/dependencies.py` factories so the Wallet/Order wiring is identical to the API); `run_once()` generates a `correlationId`, calls the subscription-order pass then the checkout pass (a no-op until MA-144), logs duration; `run_forever()` loops with `time.sleep(settings.sweep_interval_seconds)` and catches any run-level exception (`sweep.run_failed`).
- `order/src/handlers/health.py`: add `sweep_health = ConsumerHealth()`.
- `order/src/handlers/app.py`: `/healthz` is unhealthy if **either** `consumer_health` or `sweep_health` is not alive (the latter only when `sweep_enabled`).
- `order/src/main.py`: `_run_sweep()` wrapper (like `_run_consumer`: catch, log `CRITICAL`, set `sweep_health.alive = False`); start the `order-sweep` daemon thread when `settings.sweep_enabled`. Owner string `sweep:{socket.gethostname()}:{os.getpid()}`.
- `order/tests/conftest.py`: set `ORDER_SWEEP_ENABLED=false` for the test session so no background thread starts under `TestClient`.
- `local-dev/docker-compose.yml`: `order` service `environment:` gains `ORDER_SWEEP_INTERVAL_SECONDS: "15"`, `ORDER_SUBSCRIPTION_ORDER_STALE_SECONDS: "60"`, `ORDER_CHECKOUT_STALE_SECONDS: "60"`, `ORDER_SWEEP_MAX_ATTEMPTS: "3"`, `ORDER_SWEEP_LEASE_SECONDS: "60"`, with a comment pointing to MA-143 FR-7. `order-outbox` does **not** get them (it doesn't run the sweep).
- `order/README.md`: remove the two "Not yet done" sweep bullets; add a "Reconciliation sweep" section (what it does, config table, metrics); add the alarm definition (MA-143 §6: any `sweep.*.escalated` > 0 in 5 min; `sweep.run_failed` ≥ 3 in 15 min) to the infra to-do bullet.

**Tests to write:**
- `test_sweep_service.py` (fakes for the repository and Wallet, following `test_order_service.py`'s fakes):
  - stale `CREATED` order, before cut-off, Wallet `DEBITED` → `CONFIRMED`, one debit call, one `OrderConfirmed` outbox row, lease released;
  - Wallet `INSUFFICIENT_BALANCE` → `PAYMENT_FAILED` + one `OrderPaymentFailed` row;
  - `WalletUnavailableError` → `sweep_attempts` 1, `last_sweep_error` set, still `CREATED`, lease released;
  - the attempt that reaches `max_attempts` → `NEEDS_ATTENTION`, `failure_reason = SWEEP_EXHAUSTED`, `escalated` counted;
  - cut-off boundary: `now` = 19:59:59 IST the day before delivery → charged; 20:00:00 → `NEEDS_ATTENTION(CUTOFF_PASSED)` and **zero** Wallet calls;
  - claim lost → skipped, zero Wallet calls; re-read finds `CONFIRMED` → released and skipped;
  - one record raising `RuntimeError` doesn't stop the next record.
- `test_sweep_repository.py` (SQLite in-memory, as `test_order_repository.py`): claim once succeeds, a second owner fails until `claimed_until` passes (set it in the past directly), then succeeds; `renew`/`release` by a non-owner change nothing; `record_order_sweep_failure` escalates exactly at `max_attempts`; stale selection ignores fresh, terminal, `CHECKOUT`-source and leased rows; `mark_confirmed` clears the lease; claiming does not change `updated_at`.
- `test_order_service.py` (extend): `materialize` with an existing `CREATED` order leased by `sweep:x` → `OrderBusyError`, no Wallet call; with no lease → resumes and releases; a redelivery for a `NEEDS_ATTENTION` order → no-op, no Wallet call.
- `test_order_events_consumer.py` (extend): `OrderBusyError` from `materialize` → message not deleted.
- `test_sweep_flow.py` (TestClient + stubbed Wallet via the existing integration fakes): insert a `SUBSCRIPTION` `CREATED` order with `created_at` 16 min ago → `run_once()` → `CONFIRMED`, exactly one debit call, exactly one `OrderConfirmed` outbox row (ticket AC 4); a past-cut-off order → `NEEDS_ATTENTION`, no debit (ticket AC 5).
- Race test in `test_sweep_flow.py`: a Wallet stub that blocks on a `threading.Event`; start the sweep on the order in one thread, call `materialize` (SQS resume) for the same order in another → the second raises `OrderBusyError`; release the event → one debit call, one outbox row (ticket AC 6, subscription half).
- Loop robustness (`test_sweep_flow.py`): `run_forever` with `sweep_interval_seconds=0` survives a `run_once` that raises (patch it to raise once, then stop via a flag); a crashing `_run_sweep` sets `sweep_health.alive = False` and `/healthz` returns unhealthy.

**Acceptance check:** `cd order && .venv/Scripts/python -m pytest -q` passes (the 100 existing + new). The migration applies on the scratch Postgres (§6 check 4). local-dev: stop `wallet`, run `python local-dev/run_daily_local.py`, wait for the order to be `CREATED` for over 60 s, start `wallet` → within about 15 s the order is `CONFIRMED` and the wallet has exactly one `ORDER_DEBIT` for it.

### MA-144: Order Service — Stuck Checkout Recovery

**Files to modify:**
- `order/src/domain/checkout_models.py`: `CheckoutStatus.CANCELLED`, `CheckoutStatus.NEEDS_ATTENTION`.
- `order/src/domain/models.py`: `OrderStatus.CANCELLED`.
- `order/src/domain/exceptions.py`: `CheckoutCancelledError` (`CHECKOUT_CANCELLED`, 409), `CheckoutNeedsAttentionError` (`CHECKOUT_NEEDS_ATTENTION`, 409); `CheckoutInProgressError` callers pass `details = {checkoutId, retryAfterSeconds}` when a lease blocks them. The message strings are exactly MA-144 FR-2 / FR-5.
- `order/src/adapters/order_repository.py`:
  - `list_stale_checkouts(older_than_seconds, limit) -> list[str]` (MA-144 FR-1).
  - `claim_checkout` / `renew_checkout` / `release_checkout` wrappers over the MA-143 lease helpers (predicate `status = IN_PROGRESS`), plus `lease_remaining_seconds(checkout_id) -> int | None` for `retryAfterSeconds` (DB clock).
  - `start_checkout`: insert with `claim_owner` and `claimed_until = now + lease` from new keyword arguments.
  - `update_checkout`: any terminal `status` also clears the lease columns.
  - `record_checkout_sweep_failure(checkout_id, owner, error_code) -> int` (increments, stores the error, releases; returns the new count; escalation is decided in the domain because it depends on `step`).
  - `cancel_checkout_and_order(checkout_id, order_id, result)`: **one transaction**: order `CREATED → CANCELLED` (`failure_reason = CUTOFF_PASSED`, guarded by `status = CREATED`), checkout `IN_PROGRESS → CANCELLED` with `result`, lease cleared. Raise if either guard matches 0 rows (roll back).
  - `escalate_checkout(checkout_id, error_code, order_id_to_escalate: str | None)`: checkout → `NEEDS_ATTENTION` (`last_sweep_error` kept); if an order id is given and that order is still `CREATED`, order → `NEEDS_ATTENTION` (`SWEEP_EXHAUSTED`); lease cleared; one transaction.
- `order/src/domain/checkout_service.py`:
  - Constructor gains `lease_seconds` and `wallet_lookup` is the existing `wallet_client` (it now has `get_debit`).
  - `_is_cutoff_passed(delivery_date, now) -> bool` (shared rule with MA-143's cut-off; move both to one helper in `domain/cutoff.py` so the two specs can't drift).
  - `cancel_if_cutoff_passed(checkout, now) -> bool` (MA-144 FR-2): eligibility (`step == STARTED`, has `order_id`, order `CREATED`, `amount_paise > 0`, cut-off passed) → `get_debit` → `None` → `cancel_checkout_and_order` with the stored `CHECKOUT_CANCELLED` error, return `True`; found → return `False` (caller resumes; emits `charged_after_cutoff`); `WalletUnavailableError` propagates.
  - `_run`: call `renew_checkout` before the debit, before each subscription create (inside `_start_subscriptions`'s loop) and before `_clear_cart`. A `False` renew raises a new internal `LeaseLostError` that `_run`'s callers treat as "stop, write nothing".
  - `finish_partial(checkout, correlation_id)` (PD-2): record every unrecorded subscription line as `FAILED/SUBSCRIPTION_UNAVAILABLE`, set step `SUBSCRIPTIONS_DONE`, then `_clear_cart` and store the normal result as `COMPLETED`. Let the cart-clear `CheckoutIncompleteError` propagate for the caller's `CART_CLEAR_FAILED` branch.
  - `checkout()` (MA-144 FR-6): new-checkout path inserts with the request lease (`request:{uuid4}`) and releases it in a `finally` on `CheckoutIncompleteError`; same-key `IN_PROGRESS` path claims first (lost → `CheckoutInProgressError` with `retryAfterSeconds = max(1, ceil(lease_remaining))`), then `cancel_if_cutoff_passed` (→ `CheckoutCancelledError` from the stored result), then resume; replay branch handles `CANCELLED` (raise the stored `CHECKOUT_CANCELLED`) and `NEEDS_ATTENTION` (`CheckoutNeedsAttentionError`).
  - `_settle_live_checkout`: after the 2-minute busy rule, claim; lost → `CheckoutInProgressError` with `retryAfterSeconds`; won → if `cancel_if_cutoff_passed` → return (the caller proceeds as a new checkout); else resume as today, releasing the lease afterwards.
- `order/src/domain/sweep_service.py`: `sweep_checkouts(correlation_id, now) -> dict[str, int]` (MA-144 FR-1 → FR-4): list → claim (skip on loss) → re-read (release and skip unless `IN_PROGRESS`) → `cancel_if_cutoff_passed` (`cancelled`) → otherwise `checkout_service._run(...)` via a public `resume(checkout, correlation_id, now)` method → map outcomes per the FR-3 table. On `CheckoutIncompleteError` or `WalletUnavailableError`: `record_checkout_sweep_failure`; if the returned count `>= max_attempts`, branch on the stored `step`: `STARTED` → `escalate_checkout(CHARGE_UNKNOWN, order_id)`; `PAID` → re-claim and `finish_partial` (`completed_partial` + `escalated{SUBSCRIPTIONS_ABANDONED}`), falling back to `escalate_checkout(CART_CLEAR_FAILED, None)` if its cart clear fails; `SUBSCRIPTIONS_DONE` → `escalate_checkout(CART_CLEAR_FAILED, None)`. `LeaseLostError` → stop that record, no writes, no counters beyond a log.
- `order/src/handlers/sweep.py`: `run_once` calls `sweep_checkouts` after `sweep_subscription_orders`.
- `order/src/handlers/dependencies.py`: pass `lease_seconds` into `CheckoutService`.
- `order/README.md`: checkout recovery paragraph in the sweep section; the new 409 codes in the error table.

**Tests to write:**
- `test_checkout_service.py` (extend, existing fakes plus a fake `get_debit`):
  - same-key resume while leased by `sweep:x` → 409 `CHECKOUT_IN_PROGRESS` with integer `retryAfterSeconds ≥ 1`;
  - takeover while leased → 409 with `retryAfterSeconds`;
  - takeover of a PD-1-eligible checkout, lookup `None` → it is `CANCELLED` (order too), zero debit calls, and the new request completes as a fresh checkout;
  - same-key retry of a PD-1-eligible checkout, lookup `None` → 409 `CHECKOUT_CANCELLED`, zero debit calls, no cart call;
  - replay of `CANCELLED` / `NEEDS_ATTENTION` → the FR-5 errors, no port calls;
  - a fresh checkout's lease is released after `CHECKOUT_INCOMPLETE` (the row has `claim_owner` NULL).
- `test_sweep_service.py` (extend):
  - from each step (`STARTED` valid date, `PAID`, `SUBSCRIPTIONS_DONE`) with dependencies up → `COMPLETED`, one debit in total;
  - `STARTED` + 402 → `PAYMENT_FAILED`;
  - PD-1 lookup `None` → both `CANCELLED`, zero debit calls, no outbox row, no cart call; lookup found → `COMPLETED` via a debit replay, `charged_after_cutoff` counted; lookup unavailable → attempt+1, nothing cancelled;
  - cut-off boundary 19:59:59 vs 20:00:00 IST;
  - exhaustion per step: `STARTED` → checkout and order `NEEDS_ATTENTION`; `PAID` → `COMPLETED` with `SUBSCRIPTION_UNAVAILABLE` lines, and those lines not in the remove-items call; `SUBSCRIPTIONS_DONE` → `NEEDS_ATTENTION(CART_CLEAR_FAILED)`;
  - renew returns `False` mid-subscriptions → stop, no further port calls, no status write.
- `test_checkout_repository.py` (extend): `cancel_checkout_and_order` is atomic (the order already `CONFIRMED` → the checkout stays `IN_PROGRESS`); leaving `IN_PROGRESS` via `CANCELLED` or `NEEDS_ATTENTION` lets a second `start_checkout` for the same user insert (partial unique index freed).
- `test_checkout_flow.py` (extend, TestClient + stubbed Wallet/Subscription/Cart):
  - AC 1: checkout abandoned after `PAID` (Subscription stub failing, then fixed; `updated_at` aged) → `run_once()` → `COMPLETED`, subscriptions created, remove-items called once, one debit;
  - AC 2: abandoned at `STARTED` with Wallet down → Wallet stub fixed → `run_once()` → exactly one debit;
  - AC 3: after completion, cancellation and escalation, a new `POST /orders/checkout` for the same user returns 200;
  - AC 6: customer same-key retry racing the sweep (blocking Subscription stub, two threads) → one debit, one subscription create per line, the loser gets 409 `CHECKOUT_IN_PROGRESS`;
  - AC 7: Wallet down for `max_attempts` runs → `NEEDS_ATTENTION`, `escalated` metric logged (`caplog`).
- Contract: the `CHECKOUT_CANCELLED` / `CHECKOUT_NEEDS_ATTENTION` bodies match the standard error envelope (`shared/handlers/dto.py:error_envelope`).
- App regression (`milkful-app`, test-only): `test/features/checkout/checkout_models_test.dart` checks `VALIDATION_ERROR` → `Unexpected` but not an unknown 409. Add two expectations: `map('CHECKOUT_CANCELLED', status: 409)` and `map('CHECKOUT_NEEDS_ATTENTION', status: 409)` are `Unexpected` with `clearsKey == true`. No `lib/` change. Separate branch/PR in `milkful-app` (`test/MA-138-unknown-409`) since it's another repo.

**Acceptance check:** `cd order && .venv/Scripts/python -m pytest -q` passes. local-dev walkthrough (§6 check 5).

## 5. Cross-Cutting Steps

- `order/src/adapters/interfaces.py` and `wallet/src/adapters/interfaces.py` reflect every new port method (MA-142, MA-143, MA-144).
- `order/README.md` and `wallet/README.md` updated as listed per spec.
- `ruff check` on `order` and `wallet`.
- Full test runs for `order` and `wallet` (§6).
- Rebuild and restart the local stack (`local-dev/start-backend.sh`) so `0003_sweep.sql` applies and the sweep thread starts; confirm `/healthz` on `order` is healthy.

## 6. Test Strategy

| # | Check | Command |
|---|-------|---------|
| 1 | Wallet unit + integration | `cd wallet && .venv/Scripts/python -m pytest -q` |
| 2 | Order unit + integration | `cd order && .venv/Scripts/python -m pytest -q` |
| 3 | Coverage on new modules | `cd order && .venv/Scripts/python -m pytest --cov=src/domain/sweep_service --cov=src/handlers/sweep --cov-report=term-missing -q` — target ≥ 90% line coverage on `sweep_service.py` (every branch in the FR tables has a test) |
| 4 | Migration on real Postgres 16 | `docker exec local-dev-postgres-1 createdb -U milkful milkful_order_scratch`, apply `0001`, `0002`, `0003` with `psql -f`, check the columns and both partial indexes (`\d orders`, `\d checkouts`), then `dropdb` |
| 5 | local-dev end-to-end | (a) Subscription order: stop `wallet`, run the Daily Run, start `wallet` after 60 s → `CONFIRMED`, one debit. (b) Checkout: stop `subscription`, Confirm a mixed cart in the app (gets "incomplete"), close the app, start `subscription` → within about 75 s the checkout is `COMPLETED` and the cart is cleared |
| 6 | Lint | `cd order && .venv/Scripts/python -m ruff check src tests` and the same for `wallet` |

Unit tests use fakes (no network, no Postgres). Integration tests use FastAPI `TestClient` on SQLite in-memory with stubbed HTTP dependencies, the existing pattern in `order/tests/integration`.

## 7. Commit Strategy

One branch `feat/MA-138-order-sweep` in `milkful2026/services`, one PR, one commit per spec
in implementation order (each commit leaves both test suites green):

1. `feat(MA-138): wallet — debit lookup by order (MA-142)`
2. `feat(MA-138): order — sweep framework + stuck subscription orders (MA-143)`
3. `feat(MA-138): order — stuck checkout recovery (MA-144)`

Message format: `feat(MA-138): {area} — {summary} ({SPEC-KEY})`, with the attribution trailer.
Review fixes go in follow-up commits on the same branch (`fix(MA-138): address PR review findings`), as MA-34 did.

## 8. Risks and Blockers

| Risk | Impact | Mitigation / recovery |
|------|--------|-----------------------|
| No `order/infra` stack, so no CloudWatch alarm | Escalations are only visible in logs until the stack exists | Metrics emitted as specified; alarm definition recorded in `order/README.md`; flag in the PR description |
| SQLite vs Postgres differences in lease SQL (`now()`, `CASE`, partial indexes) | Tests pass on SQLite but the SQL fails on Aurora | Use SQLAlchemy `func.now()` and portable `case()`; verify on the scratch Postgres (§6 check 4) and the local stack (§6 check 5) |
| Lease helpers accidentally bump `updated_at` | A leased-but-stuck checkout never looks stale again | Explicit repository test (MA-143 tests) |
| Changing `CheckoutService` entry points breaks MA-136 behaviour | Checkout regressions | Keep all existing `test_checkout_service.py` / `test_checkout_flow.py` tests unchanged and green; new behaviour is additive except PD-1 on the customer path (tested) |
| Background thread under `TestClient` | Flaky tests | `ORDER_SWEEP_ENABLED=false` in `conftest.py`; tests call `run_once()` directly |
| Thread safety of shared SQLAlchemy engine | Connection errors under the sweep + API threads | The engine is already shared by the consumer thread and the API; no change in pattern |
| Uncommitted work in `milkful-app` main | Accidental inclusion in the app test PR | Make the test-only change in a separate worktree from committed `main` (as MA-34 did) |
| Something fails mid-implementation | Partial feature | Each spec is its own commit with green tests; stop after any commit and the service still works (the sweep's checkout pass is a no-op until commit 3) |
