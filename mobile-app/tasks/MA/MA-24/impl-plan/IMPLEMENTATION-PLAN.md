# Implementation Plan — MA-24: Payment Gateway Integration · Wallet / Recharge

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-24](https://milkfuldairyindia.atlassian.net/browse/MA-24) — Payment Gateway Integration · Checkout / Payments (Flutter) |
| **Date** | 2026-09-11 |
| **Specs implemented** | [MA-125](https://milkfuldairyindia.atlassian.net/browse/MA-125) — Flutter Wallet & Recharge Screen (`mobile-app`) · [MA-126](https://milkfuldairyindia.atlassian.net/browse/MA-126) — Payment Service: Razorpay Wallet-Recharge Slice (`services`) · [MA-127](https://milkfuldairyindia.atlassian.net/browse/MA-127) — Wallet Service: Recharge Crediting & Passbook Slice (`services`) |
| **Spec branch** | `main` (PR #16 merged, incl. the round-2 `/code-review` revisions `01af5e6`) |
| **Repos touched** | `milkful2026/milkful-app` (MA-125), `milkful2026/services` (MA-126, MA-127) |

**What this delivers:** the Wallet tab from the MA-24 mock — see a prepaid-wallet balance, top up via **Razorpay** (UPI / card) with quick or custom amounts, get an honest success / failure / async-UPI-pending result that can never double-charge, and reach the passbook (MA-27). Backed by two new AWS microservices: **Payment Service** (Razorpay orders + authoritative webhook + `PaymentConfirmed`) and **Wallet Service** (idempotent ledger crediting + balance/passbook read APIs).

**Codebase reality found during analysis:**
- `milkful2026/services` has **no `payment/` and no `wallet/` directory** — both are created from scratch here, mirroring `services/cart/`.
- The MA-1 `wallet-auto-provision` spec was a **dry-run** artefact and was never implemented, so MA-127's work includes the MA-1 baseline (the `UserRegistered → wallet create` consumer, the `wallets` / `ledger_entries` tables, `GET /wallet/me/status`, `POST /wallet/me/retry`) as its foundation — not just the recharge extension.
- `milkful-app` already has the bottom-nav **Wallet** item stubbed (`home_screen.dart` `_HomeBottomNav`, `onTap: null`), the `WalletBalanceRepository` abstraction + `StubWalletBalanceRepository`, and the `Screen → _View → Bloc → Repository(+Fake)` feature pattern (see `lib/features/cart/`).

---

## 2. Prerequisites

### `milkful-app` (MA-125)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `razorpay_flutter` dependency | **Not done** | Add to `pubspec.yaml` `dependencies:` — pin the latest 1.4.x (`razorpay_flutter: ^1.4.0`; confirm exact latest at implementation time). |
| `shared_preferences` | **Already satisfied** | `^2.5.5` present — used for `wallet.lastPaymentMethod` + `wallet.pendingRecharge`. |
| `bloc_test`, `mocktail` (dev) | **Already satisfied** | `bloc_test ^10.0.0`, `mocktail ^1.0.5` present. |
| `--dart-define=RAZORPAY_KEY_ID` | **Not done** | New `AppConfig` field; supplied at run/build time. Empty default → guarded error (MA-125 §9). Never committed. |
| `--dart-define=WALLET_ENABLED` | **Not done** | New `AppConfig` bool, default `false` (dark-ship). |
| `--dart-define=WALLET_BASE_URL` / `PAYMENT_BASE_URL` | **Not done** | New `AppConfig` fields; local-dev defaults `http://localhost:8006` / `http://localhost:8007` (confirm with local-dev maintainer — see §8). |
| iOS `Info.plist` `LSApplicationQueriesSchemes` | **Not done** | Add `tez`, `phonepe`, `paytmmp`, `bhim`, `credpay` (UPI intent app checks for Razorpay). |
| Android ProGuard / R8 keep rules for `com.razorpay.**` | **Not done** | Add to `android/app/proguard-rules.pro` (create if absent) + reference in `build.gradle` if release minification is on. |

### `services` (MA-126, MA-127)

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `services/payment/` directory tree | **Not done** | Create, mirroring `services/cart/` layout (`src/{adapters,config,domain,handlers}`, `infra/`, `tests/{unit,integration,infra}`, `pyproject.toml`, `requirements*.txt`, `run_local.py`, `run_local_outbox_publisher.py`). |
| `services/wallet/` directory tree | **Not done** | Same — create from scratch. |
| `services/shared/events/` schema folder | **Not done** | Create `PaymentConfirmed.schema.json`, `PaymentFailed.schema.json`, `WalletCredited.schema.json` (JSON Schema draft 2020-12). Per `services/README.md` §2, `shared/` may hold transport/envelope helpers — event schemas qualify. |
| Aurora databases `milkful_payment`, `milkful_wallet` | **Not done** | Add `CREATE DATABASE` lines to `services/local-dev/init-databases.sql` (currently creates `milkful_user`, `milkful_inventory`, `milkful_catalog`). |
| Razorpay secrets (`key_id`, `key_secret`, `webhook_secret`) | **Not done** | Secrets Manager entries in `payment/infra`; locally a `payment/.env.local` with `rzp_test_*` keys (gitignored, mirrors `cart/.env.local`). |
| local-dev wiring | **Not done** | `services/local-dev/docker-compose.yml` + `bootstrap.py` + `_lambda_local_server.py` route tables for `payment` (:8007) and `wallet` (:8006); `apply_migrations.py` to run their `migrations/*.sql`. |
| EventBridge rule `payment-confirmed-wallet-recharge` | **Not done** | CDK in `payment/infra` (MA-126 §8.3); local-dev bootstrap adds the equivalent moto rule → the existing `wallet-events-q`. |
| `wallet-events-q` + DLQ | **Not done locally** | Created by MA-127's `wallet/infra` (CDK) and by local-dev bootstrap; the queue does not exist yet (no wallet service). |

---

## 3. Implementation Order

1. **Shared event schemas** (`services/shared/events/*.schema.json`) — both backend services validate against these; write them first so the two services and their contract tests share one source of truth.
2. **MA-127 Wallet Service** — build the scaffold + the MA-1 baseline (tables, `UserRegistered` consumer, `/wallet/me/status`, `/wallet/me/retry`) + `GET /wallet/me`, `GET /wallet/me/transactions`, `GET /wallet/internal/limits`, and the recharge-limit config. *Reason:* MA-126 `POST /payments` calls `GET /wallet/internal/limits`; MA-125 calls `GET /wallet/me`. The credit **consumer** is wired in step 4.
3. **MA-126 Payment Service** — scaffold + `POST /payments` (+ FR-1 idempotency branching), `POST /payments/{id}/confirm`, `POST /payments/webhook`, `GET /payments/{id}`, the reconciliation sweep, the transactional outbox, and the `PaymentConfirmed`/`PaymentFailed` publication + the new EventBridge rule. *Reason:* depends on MA-127's limits endpoint and the shared event schema; produces the event MA-127's consumer needs.
4. **MA-127 Wallet Service — recharge consumer** — add the `wallet-events-q` handler for `PaymentConfirmed`(purpose=`WALLET_RECHARGE`) → `credit_recharge` transaction → `WalletCredited`. *Reason:* needs MA-126 emitting the event and the EventBridge rule routing it.
5. **local-dev wiring** — both services in `docker-compose.yml` / `bootstrap.py` / `apply_migrations.py`, ports 8006/8007, the moto EventBridge rule, `rzp_test_*` keys. *Reason:* enables the end-to-end acceptance run.
6. **MA-125 Flutter Wallet screen** — **may start in parallel with step 1** against `FakeWalletRepository`; the real `DioWalletRepository` is validated against the live services once steps 2–5 are done. Ships dark behind `--dart-define=WALLET_ENABLED=false` until then.

> Steps 2–4 are one service (`services/wallet/`) split by dependency; commit them separately (§7).

---

## 4. Per-Spec Implementation Steps

### Step 1 — Shared event schemas (`services/shared/events/`)

**Files to create:**
- `services/shared/events/PaymentConfirmed.schema.json` — JSON Schema for the EventBridge `detail` per MA-126 §8.1: `eventId, occurredAt, correlationId, paymentId, userId, purpose (enum: WALLET_RECHARGE|ORDER), amountPaise (integer), currency (const "INR"), method (enum: UPI|CARD|NETBANKING|WALLET|OTHER), razorpayPaymentId, razorpayOrderId`. Required: all except `method`.
- `services/shared/events/PaymentFailed.schema.json` — same base minus `method` (optional), plus `failureCode`, `failureReason` (required).
- `services/shared/events/WalletCredited.schema.json` — per MA-126 §8.4: `eventId, occurredAt, correlationId, userId, walletId, amountPaise (integer), balanceAfterPaise (integer), type (const "RECHARGE"), ref, paymentId`.
- `services/shared/events/README.md` — one paragraph: these are the authoritative EventBridge `detail` contracts; both producer and consumer services validate against them in tests.

**Implementation steps:**
1. Draft the three schemas as JSON Schema 2020-12, `additionalProperties: false`.
2. Add a tiny `services/shared/events/__init__.py` exposing a `load_schema(name)` helper (reads the `.json` beside it) so each service's tests can `from shared.events import load_schema`.

**Tests to write:**
- None here directly — the schema files are exercised by MA-126 and MA-127 contract tests (§4 steps 3, 4).

**Acceptance check:**
- `python -c "import json; [json.load(open(f)) for f in ['services/shared/events/PaymentConfirmed.schema.json','services/shared/events/PaymentFailed.schema.json','services/shared/events/WalletCredited.schema.json']]"` runs clean.

---

### Step 2 — MA-127 Wallet Service: scaffold + MA-1 baseline + read APIs

**Files to create** (mirror `services/cart/`):
- `services/wallet/pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `README.md`.
- `services/wallet/src/__init__.py`
- `services/wallet/src/config/env.py` — pydantic-settings `WalletSettings` with prefix `WALLET_`: `WALLET_AWS_REGION`, `WALLET_DB_DSN`, `WALLET_EVENT_BUS_NAME`, `WALLET_EVENTS_QUEUE_URL`, `WALLET_RECHARGE_MIN_PAISE` (default `10000`), `WALLET_RECHARGE_MAX_PAISE` (default `10000000`), `AWS_ENDPOINT_URL` (local-dev).
- `services/wallet/src/domain/models.py` — `Wallet(id, user_id, balance_paise, currency, status: WalletStatus{ACTIVE,CREATING,FAILED}, created_at, updated_at)`; `LedgerEntry(id, wallet_id, type: LedgerType{OPENING,RECHARGE,ORDER_DEBIT,REFUND,CASHBACK,REFERRAL_CREDIT,ADJUSTMENT}, amount_paise (signed), balance_after_paise, ref, correlation_id, created_at)`; `TransactionsPage(items, next_cursor)`.
- `services/wallet/src/domain/exceptions.py` — `WalletNotFoundError`, `InvalidCursorError`, `RetryableConsumerError` (raised by the consumer to force an SQS retry — step 4).
- `services/wallet/src/domain/wallet_service.py` — `WalletService` with: `create_wallet(user_registered_evt)` (MA-1 baseline: idempotent insert `wallets` + opening `ledger_entries` `type=OPENING, amount_paise=0, balance_after_paise=0, ref='opening:'+wallet_id`, then enqueue `WalletCreated` to outbox); `get_wallet_me(user_id)` → the FR-1 body (`walletId, status, balancePaise, currency, rechargeMinPaise, rechargeMaxPaise`); `get_wallet_status_legacy(user_id)` → the **MA-1** body verbatim (`walletId, status, balance` in **whole rupees** = `balance_paise // 100`, `currency`); `list_transactions(user_id, limit, cursor)` → keyset pagination; `get_internal_limits()` → `{rechargeMinPaise, rechargeMaxPaise}`; `retry_provision(user_id)` (MA-1 `POST /wallet/me/retry` — internal replay by user id); `check_balance_invariant()` (MA-127 §5/§7/§11 NFR) — for every wallet, assert `wallets.balance_paise == SUM(ledger_entries.amount_paise)`; on a mismatch, log + emit metric `wallet.balance_invariant_violations` per offending wallet (alarmed at any violation) rather than raising, so one bad wallet doesn't abort the sweep.
- `services/wallet/src/adapters/interfaces.py` — `WalletRepositoryPort`, `OutboxPort`.
- `services/wallet/src/adapters/wallet_repository.py` — Aurora (psycopg) impl: `insert_wallet_if_absent`, `get_wallet_by_user`, `lock_wallet_by_user` (`SELECT ... FOR UPDATE`), `insert_ledger_entry` (`INSERT ... ON CONFLICT (ref) DO NOTHING` returning inserted?), `set_balance`, `list_ledger_entries(wallet_id, limit, keyset)`. Keyset cursor = base64 of `(created_at_iso, id)`.
- `services/wallet/src/adapters/outbox_event_publisher.py` — copy `cart/src/adapters/outbox_event_publisher.py`; publishes `WalletCreated` / `WalletCredited` from an `outbox` table.
- `services/wallet/src/handlers/composition.py` — wires settings → repo → service (mirror `cart/src/handlers/composition.py`).
- `services/wallet/src/handlers/dto.py` — request/response DTOs + serializers for FR-1, FR-1-legacy, FR-2, FR-3.
- `services/wallet/src/handlers/http_handlers.py` — `get_wallet_me_handler`, `get_wallet_status_handler` (legacy), `get_transactions_handler`, `retry_provision_handler`; thin (authn hook extracts `sub` → `user_id`, DTO map, exception → HTTP).
- `services/wallet/src/handlers/internal_handlers.py` — `get_internal_limits_handler` (SigV4-gated; no Cognito).
- `services/wallet/src/handlers/wallet_events_consumer.py` — SQS handler for `wallet-events-q`; this step wires only the `UserRegistered` branch → `wallet_service.create_wallet` (MA-1 baseline). Per MA-127.md §6/§13c this is **the single multiplexing consumer** for the queue — Step 4 extends this same file with the `PaymentConfirmed` branch rather than adding a second consumer file.
- `services/wallet/src/handlers/outbox_publisher_handler.py` — copy from cart.
- `services/wallet/src/handlers/invariant_check_handler.py` — nightly scheduled task (in-service, mirroring MA-126's reconcile-sweep decision — MA-127 §12) invoking `WalletService.check_balance_invariant()`; wired the same way as `services/payment`'s reconcile task (EventBridge Scheduler → the service, or an internal cron thread).
- `services/wallet/migrations/0001_wallets_ledger.sql` — the **MA-1 baseline** schema (`wallets`, `ledger_entries`, `outbox`) already in the **paise** shape (there is no prior deployed schema to migrate from, so create it correct from the start — the "ALTER" migration in MA-127 §7 is only relevant if MA-1 shipped first; it did not). Include `wallets(id, user_id UNIQUE, balance_paise BIGINT NOT NULL DEFAULT 0, currency CHAR(3) DEFAULT 'INR', status TEXT, created_at, updated_at)`, `ledger_type` enum, `ledger_entries(... amount_paise BIGINT, balance_after_paise BIGINT, ref TEXT NOT NULL UNIQUE, correlation_id TEXT, created_at)`, `CREATE INDEX ledger_entries_wallet_created_idx ON ledger_entries (wallet_id, created_at DESC, id DESC)`, `outbox(...)` + partial index.
- `services/wallet/run_local.py`, `run_local_outbox_publisher.py` — mirror cart; `run_local.py` route table maps `(GET,/wallet/me)`, `(GET,/wallet/me/status)`, `(GET,/wallet/me/transactions)`, `(POST,/wallet/me/retry)`, `(GET,/wallet/internal/limits)`, the SQS consumer, and a thread running `invariant_check_handler` on a local interval (mirror `services/payment`'s reconcile thread).
- `services/wallet/infra/` — CDK stack (`wallet_stack.py`): Fargate service behind the internal ALB, Aurora `wallet` cluster ref, `wallet-events-q` + DLQ, EventBridge rule on `UserRegistered` → the queue, Secrets/KMS, IAM (`sqs:*` on the queue, `events:PutEvents`, `rds` connect).
- `services/wallet/tests/` — `conftest.py`, `unit/domain/test_wallet_service.py`, `unit/adapters/test_wallet_repository.py`, `integration/test_wallet_http.py`.

**Files to modify:**
- `services/local-dev/init-databases.sql` — add `CREATE DATABASE milkful_wallet;`
- `services/local-dev/apply_migrations.py` — add `wallet` to the services whose `migrations/*.sql` are applied.

**Implementation steps:**
1. Scaffold the tree from `services/cart/` (copy structure, strip cart domain).
2. Write `0001_wallets_ledger.sql` in the paise shape.
3. Implement `WalletRepository` (psycopg): connection from `WALLET_DB_DSN`; `lock_wallet_by_user` uses `SELECT ... FOR UPDATE`; `insert_ledger_entry` returns whether a row was inserted (`ON CONFLICT (ref) DO NOTHING RETURNING id`).
4. Implement `WalletService.create_wallet` (MA-1): idempotent on `user_id` (unique) — a duplicate `UserRegistered` is a no-op; writes the opening ledger entry + `WalletCreated` outbox row in one tx.
5. Implement `get_wallet_me` (FR-1 body) and `get_wallet_status_legacy` (MA-1 body, rupees) — **two distinct serializers**; `/wallet/me/status` must NOT return `balancePaise` or the recharge bounds (MA-127.md §4 FR-1/FR-7).
6. Implement `list_transactions` — keyset on `(created_at DESC, id DESC)`; `limit` clamped 1..100; `cursor` decode failure → `InvalidCursorError` → 400 `INVALID_CURSOR`. `description` rendered per `type` ("Wallet top-up" for `RECHARGE`, "Wallet created" for `OPENING`); amounts signed.
7. Implement `get_internal_limits` from `WalletSettings`.
8. Implement `retry_provision` (MA-1) — enqueue/replay the create by `user_id`.
9. Implement `check_balance_invariant` + `invariant_check_handler.py` (MA-127 §5/§7/§11) — per-wallet `balance_paise` vs `SUM(ledger_entries.amount_paise)` check, `wallet.balance_invariant_violations` metric.
10. Wire `run_local.py` + `composition.py`.
11. CDK stack + local-dev `docker-compose.yml` service + `bootstrap.py` (create `wallet-events-q` + DLQ, the `UserRegistered` rule) — coordinate with step 5.

**Tests to write:**
- Unit (`test_wallet_service.py`): `create_wallet` idempotent (2× `UserRegistered` → one row, one opening entry, one `WalletCreated`); `get_wallet_me` shape incl. bounds; `get_wallet_status_legacy` returns rupees + no `balancePaise` key; `list_transactions` newest-first, cursor round-trips, `limit` clamp, empty ledger → `items: [], next_cursor: null`; a hand-seeded `ORDER_DEBIT` of `-1000` keeps `get_wallet_me` + the `SUM(amount_paise)` invariant consistent; `check_balance_invariant` — a ledger with mixed entry types (`OPENING`/`RECHARGE`/`ORDER_DEBIT`) passes on a consistent wallet and emits `wallet.balance_invariant_violations` for a hand-seeded mismatched one (MA-127 §10 acceptance bar).
- Unit (`test_wallet_repository.py`): `insert_ledger_entry` returns `False` on `ref` conflict and does not change the balance; `lock_wallet_by_user` serialization (two "threads" via two connections — the second blocks/sees terminal state).
- Integration (`test_wallet_http.py`): seed a wallet row, hit `GET /wallet/me`, `/wallet/me/status`, `/wallet/me/transactions` over the local HTTP shim; assert the two `me` bodies differ as specified.
- Migration: apply `0001_wallets_ledger.sql` to a fresh Postgres; insert an `OPENING` row; assert `ref` NOT NULL/UNIQUE holds and `balance_paise` default `0`.

**Acceptance check:**
- `cd services/wallet && pytest` — all green, including `check_balance_invariant` passing on a ledger with mixed entry types (MA-127 §10 go/no-go criterion).
- `services/local-dev` up → `curl localhost:8006/wallet/me -H "Authorization: Bearer <token>"` returns the FR-1 body; `curl localhost:8006/wallet/me/status ...` returns the MA-1 body with `balance` in rupees.

---

### Step 3 — MA-126 Payment Service: full slice

**Files to create** (mirror `services/cart/`):
- `services/payment/pyproject.toml`, `requirements.txt` (add `razorpay` SDK), `requirements-dev.txt`, `.gitignore`, `README.md`, `.env.local.example` (`PAYMENT_RAZORPAY_KEY_ID=rzp_test_...`, `_KEY_SECRET`, `_WEBHOOK_SECRET`).
- `services/payment/src/config/env.py` — `PaymentSettings` prefix `PAYMENT_`: `PAYMENT_AWS_REGION`, `PAYMENT_DB_DSN`, `PAYMENT_EVENT_BUS_NAME`, `PAYMENT_RAZORPAY_KEY_ID/_KEY_SECRET/_WEBHOOK_SECRET`, `PAYMENT_WALLET_INTERNAL_BASE_URL`, `PAYMENT_RECONCILE_INTERVAL_SECONDS` (default `120`), `PAYMENT_RECONCILE_STALE_SECONDS` (default `180`), `PAYMENT_RECONCILE_CONFIRMING_ALERT_SECONDS` (default `1800` = 30 min, MA-126 §5), `PAYMENT_RECONCILE_HARD_CAP_SECONDS` (default `21600` = 6 h), `AWS_ENDPOINT_URL`.
- `services/payment/src/domain/models.py` — `Payment(id, user_id, purpose: Purpose{WALLET_RECHARGE,ORDER}, amount_paise, currency, status: PaymentStatus{CREATED,CONFIRMING,CONFIRMED,FAILED}, method, razorpay_order_id, razorpay_payment_id, razorpay_signature, idempotency_key, failure_code, failure_reason, correlation_id, captured_at, created_at, updated_at)`; `PaymentEvent(id, payment_id, source, raw_payload, received_at)`.
- `services/payment/src/domain/exceptions.py` — `UnsupportedPurposeError`, `AmountOutOfRangeError`, `IdempotencyKeyReusedError` (→ 409), `SignatureInvalidError`, `OrderMismatchError`, `GatewayUnavailableError`.
- `services/payment/src/domain/payment_service.py` — `PaymentService`:
  - **Metrics (MA-126 §5)** — inject a small metrics recorder (mirror `cart`'s if one exists, else a thin `boto3` CloudWatch `put_metric_data` wrapper) and emit: `create` → `recharge.created`; `confirm` → `recharge.confirming`; `apply_webhook` → `webhook.received{event}` on every parse, `recharge.confirmed` on a `captured`→`CONFIRMED` transition, `recharge.failed{code}` on `failed`→`FAILED`, `webhook.signature_invalid` on a bad signature (below); `reconcile_once` → `recharge.reconciled{outcome}` per row plus `payment.confirming_over_30m` (below). All are alarmable per MA-126 §5.
  - `create(user_id, purpose, amount_paise, currency, method, idempotency_key, correlation_id)` — **FR-1 with round-2 branching**:
    - existing row for `(user_id, idempotency_key)` **with** `razorpay_order_id` → return its create-response verbatim (200);
    - existing row **without** `razorpay_order_id` → resume: call `gateway.orders_create` once, persist `razorpay_order_id`, return;
    - existing row whose stored `amount_paise` / `purpose` / `currency` **differ** from the request → raise `IdempotencyKeyReusedError` (409 `IDEMPOTENCY_KEY_REUSED`, echo stored `amountPaise`/`purpose`);
    - no row → validate (`purpose == WALLET_RECHARGE` else `UnsupportedPurposeError`; `amount_paise` in `[min,max]` from `wallet_limits_client` else `AmountOutOfRangeError`; `currency == INR`), insert `CREATED` row, `gateway.orders_create`, persist `razorpay_order_id`, append `INTERNAL_CREATE` `payment_events`.
  - `confirm(payment_id, user_id, razorpay_payment_id, razorpay_order_id, razorpay_signature)` — owner check (404 if not caller's); verify client signature `HMAC_SHA256(order_id + "|" + payment_id, key_secret)` else `SignatureInvalidError` (+ `CLIENT_CONFIRM_REJECTED` event, no state change); `razorpay_order_id` must equal the row's else `OrderMismatchError` (409); idempotent (already terminal → return current; `CONFIRMING` → no-op); valid → set `CONFIRMING`, persist `razorpay_payment_id`/`razorpay_signature`, append `CLIENT_CONFIRM`. **Never** emits `PaymentConfirmed`.
  - `apply_webhook(raw_body, signature_header)` — verify `HMAC_SHA256(raw_body, webhook_secret)` else reject (400, metric `webhook.signature_invalid`); parse; branch on event type:
    - `payment.captured` / `order.paid` → resolve row by `razorpay_order_id`; unknown → 200 ack + `orphan_webhook` log/alert-if-recharge; already `CONFIRMED` → `WEBHOOK_DUP` + 200; amount mismatch → `FAILED` `AMOUNT_MISMATCH` + alert + 200; else in one tx: `status=CONFIRMED`, `method`, `captured_at`, `WEBHOOK` event, `outbox` row for `PaymentConfirmed`. **Round-2**: if the row is currently `FAILED` with `failure_code = TIMEOUT` (provisional), a `captured` recovers it → `CONFIRMED` + `LATE_CAPTURE_RECOVERED` event + `PaymentConfirmed`. A row `FAILED` from a real Razorpay `payment.failed` stays terminal (late `captured` → `WEBHOOK_DUP` + `late_capture_after_fail` alert).
    - `payment.failed` → if not already `CONFIRMED`, set `FAILED` + `failure_code`/`failure_reason` + `WEBHOOK` event + `outbox` `PaymentFailed`.
  - `get(payment_id, user_id)` — owner-scoped read → the FR-4 body.
  - `reconcile_once()` — **FR-5 round-2**: for rows `CONFIRMING` (or `CREATED` with a `razorpay_order_id`) older than `RECONCILE_STALE_SECONDS`: call `gateway.fetch_order_payments(order_id)`; captured → the `captured` path; all attempts failed / order expired → `FAILED` (real, terminal); still payable and age `< HARD_CAP_SECONDS` → leave `CONFIRMING`, emitting `payment.confirming_over_30m` once age `>= RECONCILE_CONFIRMING_ALERT_SECONDS` (alarmed at `> 0`, MA-126 §5 FR-5); age `>= HARD_CAP_SECONDS` → `FAILED` `failure_code = TIMEOUT` (**provisional** — a later `captured` webhook recovers it) + `PaymentFailed`. Emits `recharge.reconciled{outcome}` for every branch.
- `services/payment/src/adapters/interfaces.py` — `PaymentRepositoryPort`, `PaymentGatewayPort`, `OutboxPort`, `WalletLimitsPort`.
- `services/payment/src/adapters/payment_repository.py` — Aurora (psycopg): `get_by_user_idem`, `insert_created`, `set_order_id`, `lock_by_order_id` (`SELECT ... FOR UPDATE`), `lock_by_id`, `set_status`, `append_event`, `list_stale_confirming`.
- `services/payment/src/adapters/razorpay_gateway.py` — the only file importing the `razorpay` SDK / making HTTP to Razorpay: `orders_create(amount_paise, receipt, notes)`, `verify_webhook_signature(raw_body, header)`, `verify_client_signature(order_id, payment_id, header)`, `fetch_order_payments(order_id)`. Wrap calls with `adapters/retry.py` (copy from cart) + a simple circuit breaker.
- `services/payment/src/adapters/wallet_limits_client.py` — SigV4 `GET {PAYMENT_WALLET_INTERNAL_BASE_URL}/wallet/internal/limits`, 5-min in-process cache, config fallback (`WALLET_RECHARGE_MIN/MAX_PAISE`) + `limits_fallback` log on failure.
- `services/payment/src/adapters/outbox_event_publisher.py` — copy from cart; emit metric `outbox.publish_lag_seconds` (now − oldest unpublished `outbox.created_at`) each poll (MA-126 §5), alarmed at `> 60`.
- `services/payment/src/handlers/` — `composition.py`, `dto.py`, `create_payment_handler.py`, `confirm_payment_handler.py`, `webhook_handler.py` (public — no Cognito authn hook), `get_payment_handler.py`, `outbox_publisher_handler.py`, `reconcile_handler.py` (invoked by the in-task scheduler).
- `services/payment/migrations/0001_payments.sql` — `payment_purpose` / `payment_status` / `payment_method` enums; `payments` table (with `UNIQUE(user_id, idempotency_key)`, `razorpay_order_id UNIQUE`, `CHECK (amount_paise > 0)`, `payments_status_updated_idx`); `payment_events`; `outbox` + partial index. Per MA-126 §7.
- `services/payment/run_local.py` (route table: `(POST,/payments)`, `(POST,/payments/{id}/confirm)`, `(POST,/payments/webhook)`, `(GET,/payments/{id})`; plus start the in-task reconcile loop on a thread), `run_local_outbox_publisher.py`.
- `services/payment/infra/` — CDK `payment_stack.py`: Fargate service, Aurora `payments`, Secrets Manager (`razorpay/*`), the **EventBridge rule `payment-confirmed-wallet-recharge`** (`detail-type: PaymentConfirmed`, `detail.purpose: [WALLET_RECHARGE]`) → target `wallet-events-q` (import its ARN from the wallet stack / SSM), API Gateway routes (`/payments/*` JWT; `/payments/webhook` public + WAF rate-limit + optional IP allowlist), IAM least-privilege.
- `services/payment/tests/` — `conftest.py`, `unit/domain/test_payment_service.py`, `unit/adapters/test_razorpay_gateway.py` (HMAC known-vectors), `integration/test_payment_flow.py` (Razorpay test mode + local EventBridge).

**Files to modify:**
- `services/local-dev/init-databases.sql` — add `CREATE DATABASE milkful_payment;`
- `services/local-dev/apply_migrations.py` — add `payment`.
- `services/cart/src/adapters/wallet_client_adapter.py` — **no change now**; note only: once Wallet Service is real, MA-120's cart wallet-balance stub path could later point here, but that is out of MA-24 scope.

**Implementation steps:**
1. Scaffold from `services/cart/`.
2. `0001_payments.sql`.
3. `razorpay_gateway.py` — isolate all Razorpay knowledge here; implement the two HMAC verifiers with the exact formulae (client: `order_id|payment_id` + key_secret; webhook: raw body + webhook_secret).
4. `PaymentService.create` with the three-way FR-1 branch + `IdempotencyKeyReusedError`.
5. `PaymentService.confirm` — signature + order-id checks, `CONFIRMING` only.
6. `PaymentService.apply_webhook` — the `captured` / `failed` paths + the round-2 `LATE_CAPTURE_RECOVERED` recovery from a provisional `TIMEOUT`; all state changes + `outbox` insert in one `lock_by_order_id` tx.
7. `PaymentService.reconcile_once` — the round-2 non-force-fail behaviour + 6 h hard cap + provisional `TIMEOUT`.
8. `wallet_limits_client.py` with cache + fallback.
9. Outbox publisher (copy) → `events.PutEvents(PAYMENT_EVENT_BUS_NAME, ...)` validated against `shared/events/PaymentConfirmed.schema.json`.
10. `run_local.py` (+ reconcile thread), `composition.py`.
11. CDK stack incl. the EventBridge rule; local-dev wiring (step 5).

**Tests to write:**
- Unit (`test_payment_service.py`):
  - `create`: new key → one `orders_create` + row persisted; dup key **with** order → verbatim replay, `orders_create` NOT called; dup key **without** order (simulate prior `GatewayUnavailableError`) → resumes, `orders_create` called once now; dup key with a different `amount_paise` → `IdempotencyKeyReusedError` (409); amount out of range → `AmountOutOfRangeError` (422); `purpose=ORDER` → `UnsupportedPurposeError`.
  - `confirm`: valid sig → `CONFIRMING` + `CLIENT_CONFIRM`; bad sig → `SignatureInvalidError`, no state change, `CLIENT_CONFIRM_REJECTED`; wrong `order_id` → `OrderMismatchError`; already `CONFIRMED` → 200 no-op.
  - `apply_webhook(captured)`: `CREATED→CONFIRMED` + exactly one `PaymentConfirmed` outbox row (schema-valid, `purpose=WALLET_RECHARGE`); 2nd call → `WEBHOOK_DUP`, no new outbox row; amount mismatch → `FAILED AMOUNT_MISMATCH`.
  - `apply_webhook(failed)` → `FAILED` + `PaymentFailed` outbox.
  - **round-2**: provisional `TIMEOUT` row + later `captured` → `CONFIRMED` + `LATE_CAPTURE_RECOVERED` + `PaymentConfirmed`; real `payment.failed` row + later `captured` → stays `FAILED`, `WEBHOOK_DUP` + alert flag.
  - `reconcile_once`: `CONFIRMING` + Razorpay shows captured → `CONFIRMED`; shows all failed → `FAILED`; still payable, age < 30 min → stays `CONFIRMING`, no alert metric; still payable, age ≥ 30 min → stays `CONFIRMING` + emits `payment.confirming_over_30m`; age ≥ 6 h → provisional `TIMEOUT` + `PaymentFailed`; every branch emits `recharge.reconciled{outcome}`.
  - Metrics: `create` emits `recharge.created`; `confirm` emits `recharge.confirming`; a `captured` webhook transition emits `recharge.confirmed`; a `failed` webhook/reconcile transition emits `recharge.failed{code}`; every parsed webhook emits `webhook.received{event}` — assert each against an injected metrics stub/recorder.
- Unit (`test_razorpay_gateway.py`): fixed `(order_id, payment_id, secret)` → known signature; tampered body → verify fails.
- Unit (`test_outbox_event_publisher.py`, mirror cart's): emits `outbox.publish_lag_seconds` reflecting the oldest unpublished row's age.
- Integration (`test_payment_flow.py`): `POST /payments` → real Razorpay test `orders.create`; POST a webhook signed with the test `webhook_secret` → row `CONFIRMED` → an `outbox` row → local `PutEvents` → the new rule delivers to a test `wallet-events-q`; fire the same signed webhook 5× → one `CONFIRMED`, one outbox row, 5 `payment_events` (1 `WEBHOOK` + 4 `WEBHOOK_DUP`); drop the webhook and run `reconcile_once` after capturing in Razorpay → `CONFIRMED`.

**Acceptance check:**
- `cd services/payment && pytest` — all green.
- Local: `curl -XPOST localhost:8007/payments -H "Authorization: Bearer <t>" -H "Idempotency-Key: k1" -d '{"purpose":"WALLET_RECHARGE","amountPaise":50000,"currency":"INR","method":"UPI"}'` → `{paymentId, razorpayOrderId, razorpayKeyId, ...}`.

---

### Step 4 — MA-127 Wallet Service: recharge consumer

**Files to modify:**
- `services/wallet/src/domain/wallet_service.py` — add `credit_recharge(evt)` exactly per MA-127 §6 pseudo-code: `ref = "razorpay_payment:" + evt.razorpayPaymentId`; one tx: `lock_wallet_by_user(evt.userId)` (None or `status != ACTIVE` → raise `RetryableConsumerError`); `insert_ledger_entry(type=RECHARGE, amount_paise=+evt.amountPaise, balance_after_paise=balance+amount, ref, correlation_id)` `ON CONFLICT DO NOTHING`; if not inserted → return (dup, no event) — emit `wallet.recharge.duplicate`; else emit `wallet.recharge.credited`; `set_balance(+amount)`; `outbox` row for `WalletCredited` (schema-valid). Amount outside current limits → still credit + `recharge_outside_current_limits` log. `currency != INR` → raise (→ DLQ). `RetryableConsumerError` (no wallet row / not `ACTIVE`) → emit `wallet.recharge.no_wallet_retry` (MA-127 §5).
- `services/wallet/src/handlers/wallet_events_consumer.py` (created in Step 2 with the `UserRegistered` branch only) — extend the same handler with the `PaymentConfirmed` branch: `detail-type == "PaymentConfirmed"` **and** `detail.purpose == "WALLET_RECHARGE"` → `credit_recharge` (validate the message against `shared/events/PaymentConfirmed.schema.json` first); `OrderConfirmed`/`OrderCancelled` → ack + `log "unhandled (MA-97)"`; else ack + `log "unhandled"`. On `RetryableConsumerError` → do **not** delete the message (let SQS redrive → DLQ after N attempts). Emit `wallet.credit.consumer_lag_seconds` (now − the SQS message's `SentTimestamp`) on every receive, alarmed at `> 60` (MA-127 §5).
- `services/wallet/run_local.py` — register the consumer for the local `wallet-events-q`.
- `services/wallet/infra/wallet_stack.py` — no rule change needed here (MA-126's stack owns the recharge rule); ensure `wallet-events-q` ARN is exported (SSM param) so `payment_stack.py` can target it.

**Implementation steps:**
1. Add `credit_recharge` to `WalletService`.
2. Extend `wallet_events_consumer.py` (from Step 2) with the `PaymentConfirmed` branch.
3. Local: register on `wallet-events-q`.

**Tests to write:**
- Unit (`test_wallet_service.py` additions): fresh `PaymentConfirmed` → one `RECHARGE` entry (`amount_paise`, `balance_after_paise` correct), `wallets.balance_paise` bumped, one `WalletCredited` outbox row with `ref`, emits `wallet.recharge.credited`; duplicate event (same `razorpayPaymentId`) → `ON CONFLICT` no-op, no balance change, **no** second outbox row, emits `wallet.recharge.duplicate`; no wallet row → `RetryableConsumerError` + `wallet.recharge.no_wallet_retry` (assert the message is not acked in a handler-level test); `status != ACTIVE` → `RetryableConsumerError`; `amountPaise` outside limits → still credits + logs; `currency != INR` → raises.
- Unit (`test_wallet_events_consumer.py`): `wallet.credit.consumer_lag_seconds` recorded on receipt against a stubbed metrics recorder.
- Integration (`test_wallet_events.py`): publish a schema-valid `PaymentConfirmed` (purpose=WALLET_RECHARGE) to the local `wallet-events-q` → assert the ledger row + balance + a `WalletCredited` on the local bus; fire it 5× → one credit, one `WalletCredited`; publish `purpose=ORDER` → acked, no credit; publish with no wallet row → lands in the DLQ after the retry count, then create the wallet + redrive → credit succeeds.
- Contract: the consumer validates against `shared/events/PaymentConfirmed.schema.json`; publisher validates `WalletCredited`.

**Acceptance check:**
- `cd services/wallet && pytest` — all green (baseline + consumer).
- End-to-end (needs step 5): `POST /payments` → Razorpay test capture → webhook → `PaymentConfirmed` → this consumer → `GET /wallet/me` balance increased by the amount, exactly once.

---

### Step 5 — local-dev wiring (both services)

**Files to modify:**
- `services/local-dev/docker-compose.yml` — add `payment` (build `../payment`, port `8007:8007`, env: `PAYMENT_DB_DSN` → the `milkful_payment` DB, `PAYMENT_EVENT_BUS_NAME`, `AWS_ENDPOINT_URL=http://moto:5000`, Razorpay test keys from a compose `env_file: ../payment/.env.local`) and `wallet` (build `../wallet`, port `8006:8006`, `WALLET_DB_DSN` → `milkful_wallet`, `WALLET_EVENTS_QUEUE_URL`, `AWS_ENDPOINT_URL`). Both `depends_on: [bootstrap]` like the other services. Add `payment-outbox` and `wallet-outbox` one-shot-loop containers mirroring the cart outbox publisher, plus a `payment-reconcile` loop and a `wallet-invariant-check` loop (or run either as a thread inside its service).
- `services/local-dev/bootstrap.py` — add: create the `milkful_payment` / `milkful_wallet` DBs (or rely on `init-databases.sql`); create SQS `wallet-events-q` + `wallet-events-q-dlq` (redrive policy); create EventBridge rules — `UserRegistered → wallet-events-q` and `PaymentConfirmed` (filter `detail.purpose = WALLET_RECHARGE`) `→ wallet-events-q`; write `payment/.env.local` + `wallet/.env.local` (localhost hostnames) with the bus name, queue URLs, DSNs, and `PAYMENT_WALLET_INTERNAL_BASE_URL=http://localhost:8006`.
- `services/local-dev/init-databases.sql` — `CREATE DATABASE milkful_payment;` + `CREATE DATABASE milkful_wallet;` (done in steps 2/3).
- `services/local-dev/apply_migrations.py` — include `payment` and `wallet` (done in steps 2/3).
- `services/local-dev/README.md` — document the two new services, their ports (8006 wallet, 8007 payment), the `rzp_test_*` key requirement, and the recharge end-to-end curl recipe.

**Implementation steps:**
1. `init-databases.sql` + `apply_migrations.py` (from steps 2/3).
2. `bootstrap.py` — queue + DLQ + the two EventBridge rules + `.env.local` writers.
3. `docker-compose.yml` — the two services + their outbox loops + `payment-reconcile`.
4. README recipe.

**Acceptance check:**
- `cd services/local-dev && docker compose up -d` → all containers healthy; `bootstrap` exits 0; `aws --endpoint-url http://localhost:5000 sqs list-queues` shows `wallet-events-q` + DLQ; `aws --endpoint-url http://localhost:5000 events list-rules` shows the two rules.
- The full recipe in the README runs green: register a user → `GET /wallet/me/status` shows `balance: 0` → `POST /payments` (₹500) → simulate Razorpay `payment.captured` webhook (signed) → within seconds `GET /wallet/me` shows `balancePaise: 50000` and `GET /wallet/me/transactions` has one `RECHARGE` entry.

---

### Step 6 — MA-125 Flutter Wallet & Recharge Screen (`milkful2026/milkful-app`)

**Files to create:**
- `lib/features/wallet/models/wallet_view.dart` — `WalletView { walletId, status: WalletStatus{active,creating,failed}, balancePaise (int), currency, rechargeMinPaise (int), rechargeMaxPaise (int) }` + `fromJson`.
- `lib/features/wallet/models/payment_view.dart` — `PaymentView { paymentId, status: PaymentStatus{created,confirming,confirmed,failed}, amountPaise (int), failureReason? }` + `fromJson`.
- `lib/features/wallet/models/recharge_order.dart` — `RechargeOrder { paymentId, razorpayOrderId, razorpayKeyId, amountPaise (int), currency }` + `fromJson`.
- `lib/features/wallet/models/payment_method.dart` — `enum PaymentMethod { upi, card }` with `wireValue` (`"UPI"`/`"CARD"`).
- `lib/features/wallet/models/pending_recharge.dart` — `PendingRecharge { idempotencyKey, paymentId, amountPaise, method, createdAtIso }` + `toJson`/`fromJson` (the `wallet.pendingRecharge` shared_preferences blob).
- `lib/features/wallet/data/wallet_repository.dart` — `abstract class WalletRepository` with `getWallet()`, `getPayment(paymentId)`, `createRecharge({amountPaise, method, idempotencyKey})`, `confirmRecharge({paymentId, razorpayPaymentId, razorpayOrderId, razorpaySignature})`, `retryProvision()`; + `DioWalletRepository(ApiClient)` hitting `AppConfig.walletBaseUrl` / `AppConfig.paymentBaseUrl`.
- `lib/features/wallet/data/dio_wallet_balance_repository.dart` — `DioWalletBalanceRepository implements WalletBalanceRepository` — `getBalance()` = `(await walletRepository.getWallet()).balancePaise ~/ 100` (preserves MA-120's whole-rupee contract).
- `lib/features/wallet/data/razorpay_checkout.dart` — `abstract class RazorpayCheckout { Future<RazorpayResult> open(RazorpayOptions) }`; `RazorpayResult` = sealed `success(razorpayPaymentId, razorpayOrderId, razorpaySignature) | failed(code, description) | dismissed`; `RealRazorpayCheckout` wraps `package:razorpay_flutter` (`Razorpay()` + `on(EVENT_PAYMENT_SUCCESS/ERROR/EXTERNAL_WALLET)` → completes a `Completer`); throws a guarded `StateError` if `AppConfig.razorpayKeyId` is empty.
- `lib/features/wallet/bloc/wallet_event.dart` — `sealed class WalletEvent`: `WalletStarted`, `WalletRefreshRequested`, `QuickAmountSelected(int)`, `CustomAmountEntered(int)`, `AmountCleared`, `PaymentMethodSelected(PaymentMethod)`, `RechargeRequested`, `RechargeGatewaySucceeded(String razorpayPaymentId, String razorpayOrderId, String razorpaySignature)`, `RechargeGatewayFailed(String code, String description)`, `RechargeGatewayDismissed`, `RechargePollTick`, `WalletProvisionRetryRequested`, `PendingRechargeAbandoned`.
- `lib/features/wallet/bloc/wallet_state.dart` — `WalletState extends Equatable` with the fields listed in MA-125 §6 (`loadStatus`, `walletStatus`, `balancePaise`, `currency`, `rechargeMin/MaxPaise`, `selectedAmountPaise?`, `selectedMethod`, `rechargeStatus: {idle,creatingOrder,awaitingGateway,confirming,pending,success,failed}`, `rechargeErrorMessage?`, `lastConfirmedAmountPaise?`, `idempotencyKey?`, `pendingPaymentId?`).
- `lib/features/wallet/bloc/wallet_bloc.dart` — `WalletBloc(walletRepository, {clock/uuid injectable})`; handlers per MA-125 §6 + §10 unit list; `droppable()` on `RechargeRequested`/`RechargeGatewaySucceeded`/`WalletProvisionRetryRequested`, `restartable()` on `RechargePollTick`. Persists/reads `wallet.pendingRecharge` via an injected `PendingRechargeStore` (thin `shared_preferences` wrapper) so it is testable.
- `lib/features/wallet/data/pending_recharge_store.dart` — `PendingRechargeStore` (`read()/write(PendingRecharge)/clear()` over `shared_preferences` key `wallet.pendingRecharge`) + `PaymentMethodStore` (key `wallet.lastPaymentMethod`).
- `lib/features/wallet/presentation/wallet_screen.dart` — `WalletScreen` (StatelessWidget → `BlocProvider<WalletBloc>`) → `_WalletView` (StatefulWidget: owns the poll `Timer`, the `RazorpayCheckout` instance, and drives the sheet from a `BlocListener`). Sub-widgets: `_WalletLoadingSkeleton` (mirror `catalog_screen.dart`'s `_LoadingSkeleton`), `_WalletLoadError`, `_BalanceCard`, `_ViewAllTransactionsLink`, `_QuickTopUp` (ChoiceChips), `_PaymentMethods` (RadioListTile group), `_ProceedButton`, `_PendingBanner`, `_TopUpAmountSheet` (modal), `_SuccessSheet`, `_ErrorCard`. Every interactive element + result state gets the `Key(...)` from MA-125 §4/§6 (`wallet-balance-card`, `wallet-balance-amount`, `wallet-topup-button`, `wallet-passbook-button`, `wallet-view-all-transactions`, `wallet-quick-topup-500|-1000|-2000`, `wallet-method-upi|-card`, `wallet-proceed-to-payment`, `wallet-proceed-loading`, `wallet-topup-sheet`, `wallet-topup-amount-field`, `wallet-topup-amount-error`, `wallet-recharge-success|-error|-pending|-cancelled|-abandon`, `wallet-loading-skeleton`, `wallet-load-error`, `wallet-load-retry`, `wallet-coming-soon`, `wallet-web-unsupported`). `Semantics` labels on the two method options + icon-only controls; touch targets ≥ 48dp.
- `lib/features/wallet/presentation/wallet_transactions_placeholder.dart` — `WalletTransactionsPlaceholder` (`Key('wallet-transactions-placeholder')`, "Transaction history coming soon"); MA-27 replaces the route builder later.
- `lib/features/wallet/presentation/wallet_coming_soon.dart` — `_WalletComingSoon` shown when `WALLET_ENABLED == false`.
- `test/fakes/fake_wallet_repository.dart` — configurable `getWallet` / `getPayment` / `createRecharge` / `confirmRecharge` results + call recording (idempotency-key capture).
- `test/fakes/fake_razorpay_checkout.dart` — returns a preset `RazorpayResult`.
- `test/features/wallet/bloc/wallet_bloc_test.dart`, `test/features/wallet/presentation/wallet_screen_test.dart` — the scenarios in MA-125 §10 (round-2 versions: `getPayment`-only success, `FAILED`-branch, resume-on-reopen, pending holds the CTA + keeps `wallet.pendingRecharge`, retry reuses the idempotency key).

**Files to modify:**
- `pubspec.yaml` — add `razorpay_flutter: ^1.4.0` (confirm latest).
- `lib/core/config/app_config.dart` — add `walletBaseUrl`, `paymentBaseUrl`, `razorpayKeyId`, `walletEnabled` (per MA-125 §6).
- `lib/core/router/app_router.dart` — add `GoRoute('/wallet', ...)` (gated on `AppConfig.walletEnabled` → `WalletScreen` else `_WalletComingSoon`) and `GoRoute('/wallet/transactions', ...)`.
- `lib/features/home/presentation/home_screen.dart` — `_HomeBottomNav`: replace `onTap: null` with an `onTap` that, for index 2 (Wallet), does `context.go('/wallet')`; index 0 → `/home`; indices 1/3 stay no-ops. Keep `currentIndex` correct per the active route (or leave `0` on Home and let the Wallet screen render its own `BottomNavigationBar` with `currentIndex: 2` — mirror how the mock shows the nav on the Wallet screen; decide in implementation, prefer a shared `_AppBottomNav` extracted from `_HomeBottomNav` if low-risk).
- `lib/main.dart` — follow the file's existing pattern: every repo is built from the one shared local `apiClient` (there is no `RepositoryProvider<ApiClient>` — `ctx.read<ApiClient>()` is not available). Add `final walletRepository = DioWalletRepository(apiClient);` alongside the other repo locals (near line 47), add `RepositoryProvider<WalletRepository>.value(value: walletRepository)` to the `providers` list, and change the `WalletBalanceRepository` provider (line ~75, currently `const StubWalletBalanceRepository()`) to `RepositoryProvider<WalletBalanceRepository>.value(value: DioWalletBalanceRepository(walletRepository))`.
- `ios/Runner/Info.plist` — add the `LSApplicationQueriesSchemes` array (§2).
- `android/app/proguard-rules.pro` — add `-keep class com.razorpay.** { *; }` and `-dontwarn com.razorpay.**` (create the file + wire it in `android/app/build.gradle` `buildTypes.release.proguardFiles` if not already).
- Delete `lib/features/cart/data/wallet_balance_repository.dart`'s `StubWalletBalanceRepository` **only after** `DioWalletBalanceRepository` is wired and `flutter test` is green (keep the `WalletBalanceRepository` abstract class; move it to `lib/features/wallet/data/` or leave in place and re-export — prefer moving; update all 8 current importers of `wallet_balance_repository.dart`: `lib/main.dart`, `lib/features/cart/bloc/product_config_bloc.dart`, `lib/features/cart/presentation/product_config_screen.dart`, `tool/preview_product_config.dart`, `test/fakes/fake_wallet_balance_repository.dart`, `test/features/cart/bloc/product_config_bloc_test.dart`, `test/features/cart/presentation/product_config_screen_test.dart`, `test/core/router/app_router_test.dart`).

**Implementation steps:**
1. `pubspec.yaml` + `flutter pub get`; add the iOS/Android native config.
2. `AppConfig` fields.
3. Models + `WalletRepository` (abstract + Dio) + `FakeWalletRepository`.
4. `RazorpayCheckout` wrapper + `FakeRazorpayCheckout`.
5. `PendingRechargeStore` / `PaymentMethodStore`.
6. `WalletBloc` + events + state — implement the full state machine incl. FR-6a resume/abandon and the round-2 `getPayment`-only success / `FAILED` branch.
7. `WalletScreen` + sub-widgets + all `Key`s + a11y; skeleton mirrors `catalog_screen._LoadingSkeleton`.
8. Router + bottom-nav wiring + `main.dart` providers.
9. Retire `StubWalletBalanceRepository` → `DioWalletBalanceRepository`; fix all 8 imports of `wallet_balance_repository.dart`.
10. Tests (bloc + widget).
11. `flutter analyze` + `flutter test`.

**Tests to write:**
- Unit (`wallet_bloc_test.dart`): every bullet in MA-125 §10 "Unit — WalletBloc" (round-2 revision) — notably: `RechargeRequested` writes `wallet.pendingRecharge` + one `createRecharge`; second is dropped; `RechargeGatewaySucceeded` passes all four ids to `confirmRecharge`; poll success is `getPayment == CONFIRMED` only (an unrelated `getWallet` +sameAmount does **not** trigger success); `getPayment == FAILED` → failure + record cleared; 20s cutoff → stays `pending`, `wallet.pendingRecharge` retained, CTA disabled; `WalletStarted` with a seeded record resumes polling; a >30-min seeded record surfaces `PendingRechargeAbandoned`; `RechargeGatewayFailed` → retry re-uses the same idempotency key (assert identical key on both `createRecharge` calls); `RechargeGatewayDismissed` clears the record.
- Widget (`wallet_screen_test.dart`): the nine+ scenarios in MA-125 §10 (round-2) — layout renders the mock; quick amount enables the CTA; sub-min custom amount rejected; successful recharge updates the balance + clears `wallet.pendingRecharge` + persists the method; gateway failure + retry reuses the key; async-UPI pending holds the CTA + keeps the record; pending attempt resumes on re-open; `getPayment` FAILED surfaces the failure; wallet-not-provisioned disables the CTA; bottom-nav Wallet tab routes here; `WALLET_ENABLED=false` shows `wallet-coming-soon` with no repo calls.

**Acceptance check:**
- `flutter test test/features/wallet/` — all pass; `flutter analyze` — clean.
- `flutter test` (full suite) — still green (MA-120's `ProductConfigBloc` gate now on `DioWalletBalanceRepository`; `product_config_bloc_test.dart` still passes with the fake).
- Manual (once steps 2–5 done, real device, Razorpay **test mode**): quick amount → UPI test VPA `success@razorpay` → balance credited; custom amount → card `4111 1111 1111 1111`; `failure@razorpay` → failure card; a UPI collect left pending → pending banner, kill the app, reopen → the same attempt resumes and resolves; passbook link opens the placeholder. (Same "real backend before sign-off" bar as MA-123.)

---

## 5. Cross-Cutting Steps

- **Shared event schema** (`services/shared/events/`) is created first (Step 1) and imported by both `services/payment` and `services/wallet` test suites — keep the three `.json` files the single source of truth; any contract change touches only these.
- **`services/README.md` service inventory** — no change (Payment + Wallet are already listed in the canonical 13); add `payment/` and `wallet/` to the "Repository Structure (target)" tree if that list is kept literal.
- **`milkful-app` `analysis_options.yaml`** — no new lint rules; the new `lib/features/wallet/` tree must pass the existing `flutter_lints ^6` set.
- **Dependency manifests** — `pubspec.yaml` (`razorpay_flutter`); `services/payment/requirements.txt` (`razorpay`); no shared-lib version bumps.
- **EventBridge topology** — MA-126's `payment_stack.py` owns the new rule; `wallet_stack.py` exports the `wallet-events-q` ARN (SSM). Local-dev `bootstrap.py` mirrors both.
- **Architect follow-up (carried, non-blocking)** — `milkful-well-architected.md` §7.1 + `milkful-messaging.drawio` need the `WalletCredited`/`WalletDebited` events and the recharge `PaymentConfirmed → wallet-events-q` path added. Not code; a doc PR for the architect (MA-126 §8.5 / §13). Note in the code PR description.
- **MA-33 (NR : Wallet Recharge)** — recommend closing as duplicate of MA-24 or repurposing for the deferred extras (recharge offers/cashback, low-balance auto-recharge). A Jira housekeeping action, not code.

---

## 6. Test Strategy

| Layer | Where | How to run |
|-------|-------|-----------|
| Flutter unit + widget | `milkful-app/test/features/wallet/` | `cd milkful-app && flutter test test/features/wallet/` |
| Flutter full regression | `milkful-app/test/` | `cd milkful-app && flutter test` |
| Flutter static analysis | — | `cd milkful-app && flutter analyze` |
| Payment Service unit | `services/payment/tests/unit/` | `cd services/payment && pytest tests/unit` |
| Payment Service integration (Razorpay test mode + local EventBridge) | `services/payment/tests/integration/` | `cd services/payment && pytest tests/integration` (needs `PAYMENT_RAZORPAY_*` test keys + a local moto) |
| Wallet Service unit | `services/wallet/tests/unit/` | `cd services/wallet && pytest tests/unit` |
| Wallet Service integration (local SQS/EventBridge) | `services/wallet/tests/integration/` | `cd services/wallet && pytest tests/integration` |
| Contract | both services | schema-validate every emitted/consumed event against `services/shared/events/*.schema.json` inside the unit suites |
| End-to-end | `services/local-dev` | `docker compose up -d` then the README recipe: register → `POST /payments` → signed webhook → `GET /wallet/me` reflects the credit exactly once; redrive a DLQ message → still one credit |
| Infra | `services/{payment,wallet}/tests/infra/` | `pytest tests/infra` (CDK synth assertions, mirror `cart/tests/infra/test_cart_stack.py`) |

- **Unit vs integration:** anything touching Razorpay's real test API, a real Postgres, or a real (moto) queue is integration; pure domain logic (idempotency branching, state transitions, the `credit_recharge` tx logic with a fake repo) is unit.
- **Coverage:** match the existing `services/cart/` threshold (check `cart/pyproject.toml` — mirror it in `payment`/`wallet` `pyproject.toml`). Flutter: no enforced threshold in this repo today; every FR path in MA-125 §10 must have a test.
- **Lint:** `flutter analyze` (Flutter); the Python services follow `services/cart/`'s configured linters (`ruff`/`black` per `cart/pyproject.toml` — mirror).

---

## 7. Commit Strategy

One commit per numbered step, on feature branches per repo:

**`milkful2026/services`** — branch `feat/MA-24-payment-wallet-services`:
- `feat(MA-24): shared EventBridge event schemas (PaymentConfirmed/PaymentFailed/WalletCredited)` — Step 1
- `feat(MA-24): Wallet Service scaffold, MA-1 baseline schema + create-consumer, read APIs` — Step 2
- `feat(MA-24): Payment Service — Razorpay recharge slice (create/confirm/webhook/reconcile/outbox)` — Step 3
- `feat(MA-24): Wallet Service — recharge PaymentConfirmed consumer + WalletCredited` — Step 4
- `chore(MA-24): local-dev wiring for payment (:8007) and wallet (:8006)` — Step 5

**`milkful2026/milkful-app`** — branch `feat/MA-24-wallet-recharge-screen`:
- `feat(MA-24): Wallet feature — models, WalletRepository, RazorpayCheckout wrapper, fakes` — Step 6.1–6.5
- `feat(MA-24): WalletBloc — recharge state machine, pending-attempt persistence (FR-6a)` — Step 6.6
- `feat(MA-24): WalletScreen — mock layout, all UI states, a11y, keys` — Step 6.7
- `feat(MA-24): wire /wallet route + bottom-nav tab; retire StubWalletBalanceRepository` — Step 6.8–6.9
- `test(MA-24): WalletBloc + WalletScreen tests` — Step 6.10

Commit message format: `feat(MA-24): {imperative summary}` / `test(MA-24): …` / `chore(MA-24): …`, matching this project's history.

---

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| **`services/wallet/` and `services/payment/` do not exist; MA-1 baseline never built** | The plan builds both from scratch off `services/cart/`. MA-127's Step 2 explicitly includes the MA-1 wallet-create baseline. If MA-1 later ships its own `services/wallet/`, reconcile — but as of now there is nothing to collide with. |
| **`razorpay_flutter` native setup** (iOS URL schemes, Android ProGuard) missed → runtime crash on release builds | §2 lists both; the `RazorpayCheckout` wrapper + `kIsWeb`/empty-key guards keep failures graceful; widget tests never touch the real SDK. |
| **Razorpay merchant account / API keys** for local + CI test mode not provisioned | Blocker for Steps 3/5 integration tests and the manual pass. Needs a `rzp_test_*` key pair + webhook secret. Ask before starting the backend integration tests. Unit tests + MA-125 (fake) proceed without it. |
| **Local-dev ports 8006/8007** clash with something on a dev machine | Configurable via compose; `AppConfig` reads them from `--dart-define`. Confirm with the local-dev maintainer (MA-125 §12). |
| **EventBridge rule wiring across two CDK stacks** (`payment_stack` targets `wallet_stack`'s queue) | Export the queue ARN via SSM param from `wallet_stack`; `payment_stack` imports it. Local-dev `bootstrap.py` creates both rules against moto directly — verify with `events list-rules` / `sqs list-queues` in the Step 5 acceptance. |
| **`credit_recharge` "no wallet row" retry could loop forever** if provisioning never completes | `RetryableConsumerError` → SQS redrive → DLQ after N attempts + a CloudWatch alarm (never acked-and-dropped — MA-127 §9). Manual replay after fixing provisioning. |
| **Round-2 `LATE_CAPTURE_RECOVERED`** path (provisional `TIMEOUT` → `CONFIRMED`) is subtle | Covered by a dedicated unit test in Step 3; the distinction is "was the `FAILED` from a real `payment.failed` (terminal) or from the sweep's provisional `TIMEOUT` (recoverable)" — store `failure_code` and branch on it. |
| **MA-125 shipped before the backend is up** | `--dart-define=WALLET_ENABLED=false` hides the tab; `DioWalletRepository` is exercised only in the manual pass once Steps 2–5 land. Merge order: services branch first (or both together behind the flag). |
| **Retiring `StubWalletBalanceRepository` breaks MA-120's gate** | `DioWalletBalanceRepository` preserves the exact `getBalance() → Future<int>` (whole rupees) contract; run the full `flutter test` (incl. `product_config_bloc_test.dart`) as an acceptance gate for Step 6.9. |
| **`GET /wallet/me/status` regression for MA-1** | MA-127.md §4 FR-1/FR-7: `/status` keeps MA-1's rupee body verbatim; `/wallet/me` is a *new* endpoint. Two serializers, one integration test asserting they differ. Do not "alias" them. |

---

*Plan covers all three MA-24 specs (MA-125 / MA-126 / MA-127) as revised on PR #16 (merge `c2e2102`, round-2 revisions `01af5e6`). MA-125 is unblocked and may start immediately against `FakeWalletRepository`; MA-126 + MA-127 create two new services in `milkful2026/services` from the `services/cart/` template.*
