### SDD Step 2 — Technical Context

**Story:** MA-34 — Order Confirmation / Preview · Checkout (Flutter)
**Verified against source on 2026-09-25** (`milkful-app` @ `a8e9436`, `services` @ `2bd88dd`).

---

#### What exists today

| Capability | Where | State |
|------------|-------|-------|
| Cart line items, quote, optimistic `cartVersion`, Idempotency-Key | Cart Service `GET/PUT /cart`, `POST /cart/items`, `DELETE /cart/items/{id}` | Built (MA-96/MA-121). Line = `{id, productId, quantity, frequency ∈ ONE_TIME/DAILY/ALTERNATE_DAYS, startDate, addedAt}` — **no `slotId`** |
| Cart wallet gate | `CartService._check_wallet_gate` — subscription line requires wallet balance ≥ `wallet_minimum_balance` | Built |
| Pricing quote | Pricing `POST /pricing/quote {items[], deliveryState}` → one aggregated quote; `monthlyEstimate` only for a single-frequency request; **rejects empty `items`** | Built (MA-101/MA-122) |
| Wallet balance / top-up | Wallet `GET /wallet/me`; Payment `POST /payments` (Razorpay) | Built (MA-24) |
| Wallet debit | Wallet `POST /wallet/internal/debit {userId, orderId, amountPaise, correlationId}` → 200 `DEBITED` / `INSUFFICIENT_BALANCE` / `WALLET_NOT_ACTIVE`; idempotent on `order:{orderId}` ledger ref | Built (MA-130) |
| Subscriptions | Subscription `POST /subscriptions {productId, quantity, schedule, startDate, slotId, idempotencyKey}` (JWT); idempotent on `(userId, idempotencyKey)`; same-day `SubscriptionOrderDue` before cut-off | Built (MA-131) |
| Orders | Order Service — **read-only** (`GET /orders/me`, `GET /orders/{id}`); orders created only by consuming `SubscriptionOrderDue` | Built (MA-132) |
| Order schema | `orders(... subscription_id NOT NULL, product_id NOT NULL, quantity NOT NULL ..., UNIQUE(subscription_id, delivery_date))` | **Cannot hold a one-time, multi-line order** |
| Internal auth patterns | User address-state: SigV4-signed (`shared.adapters.sigv4`); Wallet internal: VPC-only, unauthenticated; Subscription `/internal/run-daily`: VPC-only | Both conventions exist |
| Mobile cart screen | `cart_screen.dart` — title "Your Cart", `FilledButton(key: cart-checkout-cta, onPressed: null)` | Built (MA-123) |
| Mobile subscription confirm | `ProductConfigBloc._onAddToCartRequested` — subscription frequency → `SubscriptionRepository.create(...)` with `slotId` from Inventory slots; one-time → `CartRepository.addItem` | Built (MA-133 FR-6) |
| Mobile profile | `UserProfile{defaultAddressId, defaultAddressState, defaultAddressZoneId}` — no address text | Built (MA-1) |
| Stored address | User Service `Address{lines, landmark, city, state, pincode, lat, lng, zone_id}` saved from the onboarding Google Maps / Places screen; `GET /users/me` exposes only id/state/zone | Built (MA-93/MA-107) |

#### Gaps this story must close

1. **No write path for a cart-driven order** (Order Service has no public POST; schema is
   subscription-shaped).
2. **Cart can't carry what a subscription needs** (`slotId` missing).
3. **Cart quote can't be split** into "pay now" vs "per delivery" for a mixed cart.
4. **No server-side way for Order Service to read or clear a user's cart**, or to
   create a subscription on the user's behalf (both public APIs are JWT-only).
5. Mobile: CTA disabled, no add-more entry point, subscription confirm bypasses cart.

#### Impacted systems

| System | Change | Risk |
|--------|--------|------|
| Order Service | New checkout orchestration + `checkouts` table + `order_items`; migration relaxing subscription-only columns; `OrderConfirmed`/`OrderPaymentFailed` schema change (`subscriptionId` nullable, `items[]`) | High — money path |
| Cart Service | `slotId` field; split quote; two internal endpoints | Medium — additive, Pricing called up to 3× per `GET /cart` |
| Subscription Service | Internal create endpoint reusing `SubscriptionService.create` | Low |
| Wallet / Pricing / User | No change — consumed as-is | — |
| Mobile app | Cart screen, ProductConfig bloc (reverts MA-133 FR-6), new checkout feature, new route | Medium |

#### Key decisions (from chat 2026-09-25, recorded here)

- Checkout orchestration lives **server-side in Order Service** (one idempotent call from
  the app) rather than the app calling Order + Subscription + Cart separately — a
  client-orchestrated saga could charge the customer and then fail to start their
  subscription with nothing left to resume it.
- One-time lines are charged **now** as a single order; subscription lines are **not**
  charged at checkout — each delivery is charged by the existing Daily Run →
  `SubscriptionOrderDue` → Order Service path (MA-131/MA-132), unchanged.
- The debit happens **before** subscriptions are created, and an insufficient balance
  stops the whole checkout — the customer never ends up with half a checkout because of
  money.
