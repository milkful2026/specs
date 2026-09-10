### SDD Step 1 — Analysis

**Story:** MA-24 — Payment Gateway Integration · Checkout / Payments (Flutter)
**Status:** SDD: Analyzing
**Sources:** NSMB App Feature Spec rows 5.0 + 14.0 (epic MA-18); ticket mock `image-20260806-182611.png` (attachment 10250).

---

#### The mock is the source of truth

The single attached screen (`image-20260806-182611.png`, 313×672) is a **Wallet screen**, not a cart/order checkout. It shows, top to bottom:

| Region | Elements |
|--------|----------|
| App bar | Location ("Mumbai, India"), Freshoza logo, notification bell |
| **Available Balance card** (green) | "Available Balance", "₹450.00", **`Top Up`** button, **`Passbook`** button |
| Link | **"View All Transactions"** |
| **Quick Top Up** | Three chips — **`Add ₹500`**, **`Add ₹1000`**, **`Add ₹2000`** |
| **Payment Methods** | Radio list — **"UPI Payments"** (Google Pay, PhonePe, BHIM); **"Credit / Debit Card"** (Visa, Mastercard, RuPay), selected by default in the mock |
| CTA | **`Proceed to Payment`** (full-width) |
| Bottom nav | Home · Schedule · **Wallet** (active) · Profile |

So MA-24's deliverable is the **Wallet tab**: see balance → choose a top-up amount → choose a payment method → pay via the gateway → balance credited. Plus the passbook entry points to Transaction History (MA-27) — called out explicitly in the ticket ("Link passbook button to Transaction page → MA-27").

The screen has **no cart, no order summary, no delivery address/slot, no "pay for this order" action**. The "Checkout" in the story title refers to the gateway integration that funds the wallet; the cart's own "Proceed to Checkout" (MA-123 FR-7, still disabled) is a separate, later screen and is **not** in this mock.

#### User Story Summary

A Milkful customer keeps a prepaid wallet that is the primary payment source for orders and subscriptions (auto-debit). MA-24 gives them the screen to **see that balance and recharge it through a payment gateway (Razorpay)** using UPI or a card, with quick-amount shortcuts, and to reach their transaction passbook. Recharge crediting is instant, idempotent, and safe against double charges; async UPI "pending" is handled without a second debit.

#### User / Actor

- **Primary:** authenticated B2C customer (Cognito JWT), Android or iOS.
- **Secondary (systems):** Razorpay (gateway, via `razorpay_flutter`), Payment Service (MA-99 — creates the gateway order, verifies the signature/webhook), Wallet Service (MA-100 — balance, credit-on-confirmed, ledger), Transaction History screen (MA-27 — passbook target).

#### Goal and Business Outcome

- **Customer goal:** top up the wallet in a few taps so wallet-first payment for milk/dairy and instant-buy items always has funds; check the balance and recent transactions at a glance.
- **Business outcome:** the wallet is the settlement rail for the whole platform (orders, subscription auto-debit, refunds, referral/cashback credit). Nothing downstream can charge a customer until the wallet can be funded. This story delivers the **first real money-in path** and the Razorpay + Payment Service + Wallet Service backbone every later billing story reuses.

#### Functional Intent (what, not how)

1. Show the current wallet balance prominently, refreshed on screen open.
2. Let the customer pick a recharge amount — one tap on a Quick Top Up chip (₹500 / ₹1000 / ₹2000) or a custom amount via "Top Up".
3. Let the customer pick a payment method — **UPI** or **Credit/Debit Card** — with a sensible default.
4. "Proceed to Payment" hands off to the gateway for exactly the chosen amount via the chosen method.
5. On gateway **success**, the wallet is credited once (idempotent), the balance on screen updates, and the customer sees a confirmation.
6. On **failure**, a clear reason; balance unchanged; the customer can retry.
7. On **pending** (async UPI collect), a non-blocking "processing" state that resolves via the Payment Service webhook — the wallet is credited when (and only when) the gateway confirms, never twice.
8. "Passbook" / "View All Transactions" opens the Transaction History screen (MA-27).

#### Initial Acceptance Criteria → spec-boundary mapping

| # | Acceptance criterion (draft, observable) | Likely spec owner |
|---|------------------------------------------|-------------------|
| AC-1 | Opening the Wallet tab shows "Available Balance" with the server's current value; a stale/failed load shows a retry affordance, not ₹0. | Mobile |
| AC-2 | Tapping `Add ₹500` selects ₹500 as the recharge amount; `Top Up` opens a field for a custom amount with min/max validation. | Mobile |
| AC-3 | The Payment Methods list shows UPI and Card with one selected; changing selection changes what `Proceed to Payment` launches. | Mobile |
| AC-4 | `Proceed to Payment` with amount A and method M opens the Razorpay sheet for exactly A via M; cancelling returns to the Wallet screen with balance unchanged. | Mobile + Payment Service |
| AC-5 | On Razorpay success, within a few seconds the balance increases by A exactly once, even if the app is killed and reopened mid-flow. | Payment Service + Wallet Service (idempotency) |
| AC-6 | A failed payment shows the gateway's reason inline; no balance change; `Proceed to Payment` is tappable again. | Mobile + Payment Service |
| AC-7 | A UPI payment left "pending" shows a "processing" state; the balance updates only when Payment Service receives the confirming webhook; no double credit if the client also reports success. | Payment Service + Wallet Service |
| AC-8 | `Passbook` and `View All Transactions` navigate to the Transaction History screen (MA-27). | Mobile |
| AC-9 | Every recharge persists the Razorpay order/payment ID server-side for reconciliation; the app never handles PAN/card data. | Payment Service |

#### In Scope

- Flutter **Wallet screen** exactly as mocked: balance card, `Top Up` (custom amount), `Passbook`, `View All Transactions`, Quick Top Up chips, Payment Methods selector (UPI / Card), `Proceed to Payment`.
- The **Wallet** bottom-navigation tab and its route.
- **Razorpay Flutter SDK** integration for the recharge charge (UPI + card; Razorpay-native saved instruments as they appear in its sheet).
- **Wallet-first + gateway top-up** realised as: gateway *funds the wallet*; wallet is then the settlement source for downstream orders (those downstream flows are out of scope here).
- **Idempotent crediting** and duplicate-charge / duplicate-credit prevention end to end.
- Success / failure / **pending (async UPI)** handling, incl. webhook-driven credit.
- Gateway reference persisted server-side for reconciliation.
- Backend specs (full cross-area, user decision 2026-09-10): **Payment Service (MA-99)** recharge slice (create gateway order, verify webhook, idempotency, refs, `PaymentConfirmed`/`PaymentFailed`); **Wallet Service (MA-100)** (`GET /wallets/{userId}`, `POST /wallets/{id}/recharge` / credit-on-confirmed, `GET /wallets/{id}/transactions`, ledger, idempotent credit).

#### Out of Scope

- **The cart → order checkout flow** ("pay for this order", delivery address/slot review, `cart-checkout-cta`). Not in the mock; a separate screen/story. MA-123's disabled checkout CTA stays disabled after MA-24.
- **The 10 PM cut-off batch**, Unified Delivery Object, instant-buy inventory locking, subscription first-payment / activation — the hybrid milk-vs-perishable settlement model (per chat 2026-09-10) is downstream **consumer** behaviour of the wallet balance, specified under **MA-25 (Subscription) / MA-97 (Order) / MA-98**, not here.
- **Transaction History screen itself (MA-27)** — MA-24 only links to it.
- **Refunds & cancellation** (MA-32, MA-16) — Payment/Wallet refund APIs may be *named* but their flows are out of scope.
- **Custom "saved payment methods" management UI** — v1 uses Razorpay-native saved instruments (user decision 2026-09-10).
- **Recharge offers / cashback on top-up, low-balance auto-recharge** (NSMB row 14.0 extras) — deferred; not in the mock.
- **Low-balance alerts / push notifications** — Notification Service territory (MA-103), triggered by `WalletDebited` downstream.
- **Admin reconciliation tooling** (MA-40), **invoice generation** (MA-38).
- **B2B / credit-terms** wallets — B2C prepaid only.
- **GST on recharge** — a wallet top-up is not a taxable supply; no invoice.

#### Assumptions

- A1. Razorpay is the sole gateway for v1 (user decision). Paytm/PhonePe/GPay in the ticket text are UPI apps reached *through* Razorpay's UPI intent, not separate SDKs.
- A2. The Wallet exists per user (auto-created on registration — MA-1 `wallet-auto-provision`; `walletStatus` is `PENDING` until MA-100 ships, then `ACTIVE`).
- A3. Recharge flow: client asks **Payment Service** to create a Razorpay order for amount A → client opens the Razorpay sheet → on client success the client reports the signed result to Payment Service → Payment Service verifies signature **and** relies on the Razorpay **webhook** as the authoritative confirmation → on confirmed payment Wallet Service credits the ledger. Client success alone never credits.
- A4. Credit is keyed by the Razorpay `payment_id` (and/or a client idempotency key) so retries, webhook + client double-report, and app restarts credit at most once.
- A5. Cognito JWT at API Gateway for mobile calls; service-to-service SigV4/mTLS; correlation ID across the recharge saga.
- A6. Amount handling is integer paise server-side; the UI shows ₹ with 2 dp. Min/max recharge bounds are a Wallet Service rule surfaced to the client (assume ₹100 min / ₹100000 max pending confirmation).
- A7. `razorpay_flutter` (official Razorpay SDK) is an acceptable new Flutter dependency; it needs a Razorpay **key id** (publishable) shipped in the app via `--dart-define`, never the secret.

#### Resolved decisions (chat 2026-09-10 — not open questions)

- **D1.** Run mode: **live** SDD (real Jira transitions, Tasks, `milkful2026/specs` PR).
- **D2.** Decomposition breadth: **full cross-area** — mobile + Payment Service (MA-99) + Wallet Service (MA-100). (Order/Subscription services drop out — not in the mock.)
- **D3.** Gateway: **Razorpay**.
- **D4.** Checkout output for MA-24 = **wallet is funded**; order/subscription creation is downstream and out of scope for this screen.
- **D5.** Screen scope = the attached Wallet mock, as drawn.
- **D6.** Subscription first payment = **₹0 activation**, charged on the delivery cycle — a downstream concern; confirms MA-24 has no order/subscription payment action.
- **D7.** Saved cards: **Razorpay-native** only.
- **D8.** Wallet-first + gateway top-up settlement (hybrid milk/perishable, 10 PM cut-off, instant-buy locking) is **downstream consumer behaviour**, specified under MA-25 / MA-97, not MA-24.

#### Items to settle in Step 2–3 (proposed resolutions — none blocks decomposition)

- **Custom "Top Up" amount bounds** — Step 2 will pin min/max against the Wallet Service rule. Proposed: ₹100 min, ₹1,00,000 max, any integer-rupee amount; the UI reads the bound from the service rather than hard-coding it.
- **"Payment Methods" selection persistence** — proposed: remember the last-used method per user; fall back to the mock's default (Card) on first visit.
- **`Passbook` vs `View All Transactions`** — proposed: both navigate to Transaction History (MA-27); reconcile against MA-27's own spec during drafting (drop one entry point if MA-27 defines a distinction).

#### Impacted areas (Jira Components)

- **`mobile-app`** — new `wallet` feature (Wallet screen, bloc, repository), Wallet bottom-nav tab + route, `razorpay_flutter` dependency, `--dart-define` for the Razorpay key id. Links to MA-27 (Transaction History) and MA-123's cart is untouched.
- **`services`** — **Payment Service (MA-99)** (recharge slice) and **Wallet Service (MA-100)** (balance + credit + ledger). Both `SDD: Pending` / not implemented; MA-24 is **blocked by** both (existing Jira links).
- No `portal-ui` impact.

---

*Next: Step 2 — Build Technical Context (well-architected guardrails, HLD/LLD, EventBridge messaging map for `PaymentConfirmed`/`WalletCredited`, prior Cart/Pricing/User + MA-1 wallet-auto-provision specs, `razorpay_flutter` + Razorpay Orders API constraints, PCI-DSS scope boundary).*
