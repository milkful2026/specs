## SDD Step 2 — Technical Context

**Story:** MA-24 · **Status:** SDD: Building Context
**Context layers used:** L1 `milkful-well-architected.md` + `milkful-messaging.drawio` + `services/README.md`; L3 prior specs — MA-1 `wallet-auto-provision`, MA-121 Cart Service, MA-122 Pricing; L4 `milkful-app` source (`home_screen.dart` bottom nav, `wallet_balance_repository.dart`, `pubspec.yaml`, `app_router.dart`, `api_client.dart`).

---

### Current State Summary

**Mobile (`milkful-app`, on `main`):**
- Bottom nav already exists as a stub — `_HomeBottomNav` in `home_screen.dart:944`: `BottomNavigationBar` with **Home · Schedule · Wallet · Profile** (comment: *"Schedule/Wallet/Profile have no screens or specs behind them yet"*). Matches the mock's nav bar exactly. **MA-24 wires the Wallet tab.**
- `WalletBalanceRepository` abstraction exists with `StubWalletBalanceRepository` (`lib/features/cart/data/wallet_balance_repository.dart`) — `getBalance() → Future<int>` **in whole rupees**, always throws `WALLET_CHECK_UNAVAILABLE` (no endpoint). Consumed only by `ProductConfigBloc` (MA-120's ≥₹500 gate). MA-24 introduces the real wallet data layer; the stub's rupee-granularity balance is superseded by a paise-precise one.
- `ApiClient` (Dio) — single shared instance, interceptor attaches the Cognito access token to every request; unwraps the `{requestId, status, data}` envelope; maps non-2xx to `ApiException(errorCode, message, statusCode)`. 409/422/etc. surface with `statusCode` (used by MA-123's `_writeQuantity`).
- Routing: `go_router` 17.5, flat paths (`/home`, `/cart`, `/catalog`), `context.push`. Auth redirect guards only `/` and `/home`.
- No `razorpay_flutter` (or any payment SDK) in `pubspec.yaml`. Present: `dio`, `flutter_bloc`, `bloc_concurrency`, `go_router`, `equatable`, `intl`, `shared_preferences`, `flutter_secure_storage`.
- Bloc + repository-per-feature pattern (see `features/cart/`): `XxxScreen` (StatelessWidget → `BlocProvider`) → `_XxxView` (StatefulWidget) → `XxxBloc` (sealed events, `Equatable` state, `bloc_concurrency` transformers) → `XxxRepository` (abstract + `DioXxxRepository` + `FakeXxxRepository` in `test/fakes/`).

**Backend (`services`):** scaffold only — **no service code**. `local-dev` runs identity-auth, user, inventory, catalog, cart, pricing-offer. **No Payment Service, no Wallet Service.**

**Prior wallet spec (MA-1 `wallet-auto-provision`, dry-run 2026-07-20)** already defines the Wallet Service seed:
- Aurora `wallet`: `wallets(id, user_id UNIQUE, balance, currency, status, created_at)`, `ledger_entries(id, wallet_id, type, amount, ref, created_at)`; opening entry `type=OPENING, amount=0`.
- `GET /wallet/me/status` → `{walletId, status: ACTIVE|CREATING|FAILED, balance, currency}` (JWT-derived user — **`/wallet/me/*`**, not `/wallets/{userId}`).
- Consumes `UserRegistered` (idempotent create), publishes `WalletCreated`.
- Compute: **Fargate** consumer + **Lambda** status API. DLQ `wallet-user-registered-dlq`.
- Explicitly *out of scope there*: "Recharge (MA-33), ledger transactions, admin adjustments" → **that is MA-24's Wallet Service slice.**

### Impacted Systems

| System | Change |
|--------|--------|
| **`milkful-app`** | New `features/wallet/` (screen, bloc, repository, models); Wallet bottom-nav tab wired to a `/wallet` route; `razorpay_flutter` dependency; Razorpay **key id** via `--dart-define`; `shared_preferences` key for last-used method. `StubWalletBalanceRepository` retired in favour of the real repo (and MA-120's gate re-pointed). |
| **Wallet Service (MA-99→ MA-100)** | **Extends** the MA-1 seed: `GET /wallet/me` (balance + status), `GET /wallet/me/transactions` (paged ledger), recharge credit path (`RECHARGE` ledger entry, idempotent), min/max recharge rule. Consumes a payment-confirmed signal for recharge. Publishes `WalletCredited`. Aurora `wallet`, Fargate. |
| **Payment Service (MA-99)** | **New service** (in the canonical 13, so no new-service architect gate — but first scaffold). `POST /payments` (create Razorpay order, idempotency-key), `POST /payments/webhook` (Razorpay signature-verified), read `GET /payments/{id}`. Aurora `payments`, Fargate. Publishes `PaymentConfirmed` / `PaymentFailed`. Secrets Manager holds the Razorpay key secret + webhook secret. |
| **API Gateway** | New routes: `/wallet/*`, `/payments/*` (Cognito JWT authorizer); `/payments/webhook` is **public** (no JWT) but Razorpay-signature-gated. |
| **EventBridge `milkful-events`** | New rule routing recharge-type `PaymentConfirmed` → `wallet-events-q` (see Architecture Notes — this path is **not** in the current messaging topology). |
| **Notification Service (MA-103)** | *Downstream only* — `WalletCredited` → optional "₹X added" push. Out of MA-24 scope; noted for the event contract. |
| `portal-ui` | None. |

### Dependencies

- **Razorpay** — Orders API (`orders.create`), Checkout (`razorpay_flutter`), Webhooks (`payment.captured`, `payment.failed`, `order.paid`), signature verification (`razorpay_signature` = HMAC-SHA256 of `order_id|payment_id` with key secret; webhook uses the webhook secret). Egress via NAT Gateway only. Circuit-breaker + retry/backoff around all calls (mandated, well-architected §3).
- **Cognito / API Gateway** — JWT on every mobile call; `sub` → `userId`.
- **User Service (MA-93)** — `UserRegistered` already drives wallet auto-create; no new dependency.
- **MA-27 (Transaction History screen)** — MA-24's `Passbook` / `View All Transactions` navigate here; MA-27 consumes `GET /wallet/me/transactions` (defined by MA-24's Wallet slice). MA-27 is `SDD: Pending`; MA-24 defines the contract it will use.
- **Blocking:** MA-99 + MA-100 have no implementation. MA-24's mobile spec can be drafted and even built against a **fake** repository, but end-to-end needs both services. This is the MA-120/MA-123 pattern — draft now, implementation-plan flags the backend gap.

### Architecture Notes

**Recharge saga (new — not in `milkful-messaging.drawio`, which only shows the Order Saga's `Charge (Payment/Wallet)` and refund):**

```
Flutter                Payment Svc            Razorpay            Wallet Svc
  │  POST /payments  ─────►│                                        
  │  {amount, purpose:      │  orders.create(amount, receipt) ──►│  
  │   WALLET_RECHARGE,      │◄── order_id ──────────────────────┘  
  │   Idempotency-Key}      │  persist payment(PENDING, order_id)     
  │◄── {paymentId, razorpayOrderId, keyId} ──┤                        
  │  open Razorpay sheet ───────────────────────►│  (UPI / card)      
  │◄── success {paymentId, orderId, signature} ─┤                     
  │  POST /payments/{id}/confirm  ─────►│  verify signature            
  │                                    │  (mark CONFIRMING; await webhook)
  Razorpay  ── webhook payment.captured ──►│  verify webhook sig         
  │                                    │  payment→CONFIRMED              
  │                                    │  emit PaymentConfirmed ──────► EventBridge
  │                                                         rule (purpose=WALLET_RECHARGE)
  │                                                              └─► wallet-events-q ─► Wallet Svc
  │                                                                    credit ledger (idempotent on paymentId)
  │                                                                    emit WalletCredited
  Flutter: GET /wallet/me  (poll / on resume) ─────────────────────► balance reflects credit
```

Key rulings for Step 3 to lock:
1. **Authoritative confirmation = the webhook**, never the client callback. Client `confirm` only advances state to `CONFIRMING` and lets the UI show "processing"; the credit happens on `payment.captured`.
2. **Crediting trigger** — event-driven (`PaymentConfirmed` → `wallet-events-q`) keeps services decoupled per the guardrails, but adds a new EventBridge rule + a `purpose`/`type` discriminator on the event so Wallet only credits recharge payments (not order payments, which it handles via `OrderConfirmed`). Alternative (sync Payment→Wallet call) is simpler but couples them — **recommend event-driven, flagged in decomposition.**
3. **Idempotency** — three layers: client `Idempotency-Key` header on `POST /payments`; Payment Service dedupes on `(userId, idempotencyKey)` and on Razorpay `order_id`; Wallet Service dedupes the credit on `payment_id` (ledger `ref` UNIQUE). Webhook + client-confirm racing → at-most-once credit.
4. **Pending UPI** — `POST /payments` returns fast; if the user completes UPI later, only the webhook arrives. UI shows "processing" and resolves on the next `GET /wallet/me` / a `GET /payments/{id}` poll. No client timeout cancels the payment.
5. **Compute:** both Fargate behind the internal ALB (well-architected §6 — Aurora connection management, no cold starts on the money path). Wallet status API may stay Lambda per the MA-1 spec; recharge credit consumer is Fargate.

**Mobile screen composition (maps to widget/integration tests):**

```
WalletScreen (StatelessWidget → BlocProvider<WalletBloc>)
└─ _WalletView (StatefulWidget)
   ├─ AppBar-equivalent: location chip · logo · notifications icon   [reuse Home's]
   ├─ _BalanceCard            Key('wallet-balance-card')
   │   ├─ Text "Available Balance" / "₹{balance}"   Key('wallet-balance-amount')
   │   ├─ FilledButton "Top Up"        Key('wallet-topup-button')
   │   └─ OutlinedButton "Passbook"    Key('wallet-passbook-button')  → push MA-27 route
   ├─ TextButton "View All Transactions"  Key('wallet-view-all-transactions')  → push MA-27 route
   ├─ _QuickTopUp  (Wrap of ChoiceChips)
   │   └─ Key('wallet-quick-topup-500' | '-1000' | '-2000')
   ├─ _PaymentMethods (RadioListTile group)
   │   ├─ Key('wallet-method-upi')     "UPI Payments"  · semantic "UPI Payments, Google Pay PhonePe BHIM"
   │   └─ Key('wallet-method-card')    "Credit / Debit Card" · default-selected
   └─ FilledButton "Proceed to Payment"  Key('wallet-proceed-to-payment')
      (disabled until an amount is chosen; shows spinner while creating the Razorpay order)

_TopUpAmountSheet (modal) — Key('wallet-topup-sheet'), TextField Key('wallet-topup-amount-field'),
   inline error Key('wallet-topup-amount-error'), CTA "Continue"

Result states (SnackBar + card refresh, or a _PaymentResultSheet):
   success  Key('wallet-recharge-success')   "₹{A} added to your wallet"
   failure  Key('wallet-recharge-error')     gateway reason, retry
   pending  Key('wallet-recharge-pending')   "Payment processing — we'll update your balance shortly"
```

**All UI states:** loading (skeleton balance card + shimmer chips — mirror `catalog_screen`'s `_LoadingSkeleton`), loaded, balance-load error (retry, **not ₹0**), amount-not-chosen (CTA disabled), creating-order (CTA spinner), gateway-open, success, failure, pending, offline.

### Data / Integration Considerations

**Wallet Service — Aurora `wallet` (extends MA-1 seed):**
```sql
wallets(id, user_id UNIQUE, balance_paise BIGINT, currency='INR', status, created_at, updated_at)
ledger_entries(
  id, wallet_id, type,                    -- OPENING | RECHARGE | ORDER_DEBIT | REFUND | CASHBACK | ADJUSTMENT
  amount_paise BIGINT,                    -- signed: +credit / -debit
  balance_after_paise BIGINT,             -- running balance snapshot for the passbook
  ref TEXT UNIQUE,                        -- e.g. "razorpay_payment:pay_XXX" — dedupe key
  correlation_id, created_at
)
```
- Balance is **derived + snapshotted**: every entry writes `balance_after_paise` atomically (single SQL transaction, `SELECT ... FOR UPDATE` on the wallet row). `GET /wallet/me` returns `wallets.balance_paise` (fast); the passbook reads `ledger_entries` desc-paginated.
- **Min/max recharge** — `wallet` config rule; proposed ₹100–₹1,00,000 (10_000–1_00_00_000 paise), integer rupees. Client fetches bounds from `GET /wallet/me` (`rechargeMin/Max`) — no hard-coded limits in the app.

**Payment Service — Aurora `payments`:**
```sql
payments(
  id, user_id, purpose,                   -- WALLET_RECHARGE (MA-24) | ORDER (future)
  amount_paise BIGINT, currency='INR',
  status,                                  -- CREATED | CONFIRMING | CONFIRMED | FAILED
  method,                                  -- UPI | CARD | (razorpay reports actuals)
  razorpay_order_id UNIQUE, razorpay_payment_id, razorpay_signature,
  idempotency_key, user_idem UNIQUE(user_id, idempotency_key),
  failure_code, failure_reason,
  correlation_id, created_at, updated_at
)
payment_events(id, payment_id, source, raw_payload JSONB, received_at)   -- webhook + client-confirm audit
```
- **Reconciliation reference** surfaced to mobile = `payments.id` + `razorpay_payment_id`; admin reconciliation (MA-40) reads `payment_events` vs Razorpay settlement reports.
- **Transactional outbox** (mandated) — `PaymentConfirmed` / `PaymentFailed` written to an `outbox` table in the same tx as the status change; a poller publishes to EventBridge.

**Event contract (`PaymentConfirmed`):**
```json
{ "eventId","occurredAt","correlationId",
  "detail": { "paymentId","userId","purpose":"WALLET_RECHARGE",
              "amountPaise","currency":"INR",
              "razorpayPaymentId","razorpayOrderId","method" } }
```
- Naming discrepancy to resolve in Step 3: well-architected §7 lists **`WalletLowBalance`** as Wallet's only published event; MA-100 ticket says `WalletDebited`/`WalletCredited`; MA-1 spec says `WalletCreated`. **Recommend:** `WalletCredited` / `WalletDebited` / `WalletCreated` / `WalletLowBalance` — align the well-architected doc via the spec.
- Endpoint-style discrepancy: MA-100 ticket `GET /wallets/{userId}` vs MA-1 spec `GET /wallet/me/status`. **Recommend `/wallet/me/*`** (JWT-derived, no IDOR surface, matches shipped MA-1 spec).

### Constraints and Guardrails (from L1)

- **Database-per-service** — Wallet owns `wallet`, Payment owns `payments`; neither cross-reads. Balance is Wallet's; Payment never writes it.
- **Thin handlers, thick domain**; Razorpay SDK lives in a Payment Service **adapter**, never the handler.
- **Zero-trust** — Cognito JWT at API Gateway for `/wallet/*` & `/payments/*` (except `/payments/webhook`, which is Razorpay-signature-gated + IP-allowlisted). Service-to-service SigV4/mTLS. Razorpay egress **only** via NAT.
- **Secrets** — Razorpay key secret + webhook secret in **Secrets Manager** with rotation; the app ships only the **publishable key id** (via `--dart-define`, never committed — same pattern as `GOOGLE_MAPS_API_KEY` in `AppConfig`).
- **PCI-DSS** — SAQ-A posture: **no PAN, CVV, or card data ever touches the app or our servers.** Razorpay's SDK/checkout collects and tokenizes; we store only Razorpay token/customer refs. Card entry is entirely within Razorpay's UI.
- **KMS** at rest on both Aurora clusters; TLS 1.2+ in transit.
- **Correlation ID** propagated: app generates it, passes as header; flows app → Payment → EventBridge `detail.correlationId` → Wallet → logs. CloudWatch + X-Ray on the money path.
- **Idempotent consumers**; **DLQ** on `wallet-events-q` (already exists) with a CloudWatch alarm.
- **Amounts in integer paise** server-side end-to-end; rupee formatting is presentation-only. No floats for money.
- **Money-path compute = Fargate** (well-architected §6.1 — Aurora connection storms, no cold starts).

### Risk Register

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | Client reports success but webhook is delayed/lost → user sees "processing" indefinitely; balance never credits. | High | Webhook is source of truth + a **reconciliation sweep** (Payment Service polls Razorpay `orders/{id}/payments` for `CONFIRMING` payments older than N min); `GET /payments/{id}` lets the app re-poll. |
| R2 | Double credit (webhook + client-confirm both processed). | High | Wallet ledger `ref` UNIQUE on `razorpay_payment:{id}`; credit is `INSERT ... ON CONFLICT DO NOTHING` inside the balance tx. |
| R3 | Razorpay signature spoofing on the webhook. | High | HMAC-SHA256 verify with the **webhook secret**; reject on mismatch; IP allowlist; the endpoint never trusts the body without a valid signature. |
| R4 | New service scaffold (Payment) — no prior art in `services/`. | Med | It's in the canonical 13, so no architect new-service gate; mirror Cart Service's structure (handler→domain→adapter, outbox, idempotency table). |
| R5 | `razorpay_flutter` SDK — iOS/Android native config (URL schemes, ProGuard), and it does **not** support Flutter web. | Med | Spec calls out `razorpay_flutter` mobile-only; web build of `/wallet` shows an "open the app to add money" fallback (or hides `Proceed to Payment`). Add platform config to the spec's Technical Design. |
| R6 | Recharge event path (`PaymentConfirmed` → wallet) not in the current messaging topology → risk of Wallet also crediting *order* payments. | Med | `purpose` discriminator on the event + an EventBridge rule that matches only `purpose=WALLET_RECHARGE`; Wallet's order-debit path stays on `OrderConfirmed`. |
| R7 | UPI collect can take minutes; user backgrounds/kills the app. | Med | No client-side state needed to complete — webhook + reconciliation sweep credit regardless; app reconciles balance on next open. |
| R8 | Partial failure: Payment `CONFIRMED` but Wallet credit consumer keeps failing → DLQ. | Med | `wallet-events-q` DLQ + alarm; manual/auto replay (idempotent); user-facing balance is eventually consistent, `GET /payments/{id}` shows `CONFIRMED` so support can see money was taken. |
| R9 | Amount tampering — client sends amount, could send ₹1 and expect ₹1000. | Low | Server charges exactly `POST /payments.amount`; Razorpay order is created server-side for that amount; the sheet cannot exceed it. Min/max enforced server-side. |
| R10 | Wallet Service `status != ACTIVE` (still `CREATING`/`FAILED` from MA-1 flow). | Low | `Proceed to Payment` disabled with "Wallet setup in progress" if status ≠ ACTIVE; reuse MA-1's `POST /wallet/me/retry`. |

### Operational Considerations

- **Observability:** structured logs with `correlationId` on every hop; CloudWatch metrics — `recharge.initiated`, `recharge.confirmed`, `recharge.failed`, `recharge.pending_over_5m`, `webhook.signature_invalid`, `wallet.credit.dlq_depth`. X-Ray trace app→Payment→Wallet. Alarm on `dlq_depth > 0` and `pending_over_5m > 0`.
- **Reconciliation:** daily job compares `payments` (CONFIRMED, purpose=WALLET_RECHARGE) against Razorpay settlement report; mismatches → ops queue (admin MA-40 surface, out of MA-24 build scope but the data contract is set here).
- **Rollout:** Razorpay **test mode** keys in dev/staging (`rzp_test_*`), live keys via Secrets Manager in prod. Feature-flag the Wallet tab (`--dart-define=WALLET_ENABLED`) so the screen can ship dark until MA-99/MA-100 are live.
- **Backward compatibility:** `StubWalletBalanceRepository` removal — MA-120's ProductConfig gate must re-point to the real repo in the same change; its `getBalance()` semantics move from whole-rupees to paise (spec notes the conversion).
- **Data retention / audit:** `payment_events` and `ledger_entries` are immutable, retained per finance policy (assume 7y); PITR on both Aurora clusters.
- **Offline:** the Wallet screen requires connectivity; offline shows a retry state, never a stale cached balance presented as current.

---

*Next: Step 3 — Decomposition proposal (halt for human approval).*
