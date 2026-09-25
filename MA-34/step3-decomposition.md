### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for MA-34 (dry run — Jira Tasks created 2026-09-25):

* ✓ **MA-135 — Cart & User Service: checkout support** (`services`) — `slotId` on
  subscription lines, `payNowQuote`/`perDeliveryQuote` split in `GET /cart`, internal
  read-cart and remove-lines endpoints for Order Service; full default address on
  `GET /users/me` (one additive field, folded in per the sizing rule).
* ⚠ **MA-136 — Order Service: cart checkout** (`services`) — `POST /orders/checkout`
  orchestration (quote → one-time order + wallet debit → subscriptions → clear cart),
  resumable `checkouts` record, one-time multi-line orders, schema migration, event
  schema updates; plus Subscription Service's internal create endpoint it calls.
  * Concern: the `OrderConfirmed`/`OrderPaymentFailed` schema change (`subscriptionId`
    nullable, `items[]`) touches any existing consumer — none subscribes today, verify
    at implementation time.
* ✓ **MA-137 — Flutter Review Cart & Confirm Order** (`mobile-app`) — retitle, Add more
  items, split summary, wallet shortfall/Top Up, Confirm Order, success screen, and
  ProductConfig subscription confirm → cart line (reverts MA-133 FR-6).

Build order: MA-135 → MA-136 → MA-137 (MA-137 can start in parallel against fakes).

Subscription Service's internal endpoint is folded into MA-136 rather than its own spec:
it is a thin wrapper over the existing `SubscriptionService.create` and only exists for
MA-136 to call (skill sizing rule: a trivial change merges into the related spec).
