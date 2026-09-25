### SDD Step 1 — Analysis

**Story:** [MA-34](https://milkfuldairyindia.atlassian.net/browse/MA-34) — Order Confirmation / Preview · Checkout (Flutter)
**Status:** SDD: Pending → Analyzing (dry run, local only — no Jira writes yet)
**Sources:** MA-34 ticket text (NSMB App Feature Spec, epic MA-18); product-owner direction in chat 2026-09-25; the current cart screen (MA-123) screenshot.
**Blocked by (Jira):** MA-97 Order Service, MA-101 Pricing & Offer (Impl: Done), MA-100 Wallet Service.

---

#### Why this story, not MA-24

MA-123 FR-7 left the cart's `cart-checkout-cta` disabled with "coming soon", citing
MA-24. MA-24 turned out to be the **Wallet top-up** story (MA-125/126/127, shipped) and
its own Step 1 explicitly lists "the cart → order checkout flow" as **out of scope**.
MA-132 (Order Service) likewise scoped the "full checkout-driven Order Saga" out. MA-34
is the story whose text actually describes the missing flow: *review items / address /
date / price breakup / wallet used → confirm → place order, deduct payment → success
screen with order ID and ETA.*

#### No mock is attached

MA-34 has no attachment. The product owner's direction (chat, 2026-09-25) replaces a
mock by evolving the existing cart screen (MA-123) rather than adding a separate
preview screen:

| # | Direction | Consequence |
|---|-----------|-------------|
| PO-1 | Title "Your Cart" → **"Review Cart"** | The cart screen *is* the review/preview step |
| PO-2 | CTA "Proceed to Checkout — coming soon" → **"Confirm Order"**, enabled | Confirm places the order directly from this screen |
| PO-3 | Let the customer **add more items** from this screen | New "Add more items" entry point → Catalog, cart refreshes on return |
| PO-4 | A subscription the customer picks **goes into the cart by default**, and checkout handles **one-time items + subscriptions together** | Reverts MA-133 FR-6 (subscription confirm bypassing the cart); checkout creates the subscriptions |
| PO-5 | Checkout is **wallet-only**, stock is **not reserved**, delivery is the **next deliverable day** with no slot picker for one-time items | Keeps backend scope to what existing services support (answers to the four questions asked 2026-09-25) |

#### User Story Summary

A customer builds a cart that may mix one-time items (delivered once) and subscription
items (delivered on a recurring schedule). On the **Review Cart** screen they see what
they'll pay now, what each subscription will cost per delivery, their wallet balance,
and when delivery happens; they can still edit quantities, remove lines or go add more.
**Confirm Order** debits the wallet for the one-time items, starts every subscription in
the cart, empties the cart and shows a success screen with the order ID and delivery date.

#### Functional Intent

1. Cart screen retitled "Review Cart"; line-item editing unchanged (MA-123 FR-3..FR-6).
2. "Add more items" routes to the Catalog; returning re-fetches the cart.
3. Subscription-frequency confirm on the product screen adds a cart line (with its
   start date and delivery slot) instead of creating a subscription immediately.
4. Price summary split into **Pay now** (one-time lines) and **Subscriptions**
   (per-delivery amount, charged from the wallet on each delivery).
5. Wallet balance shown; a shortfall against "Pay now" is flagged with a Top Up path.
6. Delivery info: default address (state) and the one-time delivery date.
7. "Confirm Order" → one server call that (a) charges the one-time lines as a single
   order, (b) creates each subscription, (c) removes the checked-out lines from the cart —
   idempotently, safe to retry, never charging twice.
8. Success screen: order ID, delivery date, subscriptions started; links to Home and
   My Subscriptions.
9. Clear outcomes for insufficient balance, cart/price changed since review, and
   transient failures.

#### Draft acceptance criteria → spec owner

| # | Acceptance criterion | Owner |
|---|----------------------|-------|
| AC-1 | Screen title reads "Review Cart"; CTA reads "Confirm Order" and is enabled for a non-empty, loaded cart | Mobile |
| AC-2 | "Add more items" opens the Catalog; adding a product and returning shows it in the list with an updated summary | Mobile |
| AC-3 | Choosing Daily/Alternate Days on the product screen and confirming adds a cart line showing frequency and start date; no subscription exists yet | Mobile + Cart |
| AC-4 | For a mixed cart, "Pay now" totals only one-time lines; "Subscriptions" shows the per-delivery amount | Mobile + Cart |
| AC-5 | Confirm with enough balance: wallet debited exactly once by "Pay now"; one CONFIRMED order; one ACTIVE subscription per subscription line; cart empty; success screen shows the order ID and date | Order + Subscription + Cart + Mobile |
| AC-6 | Confirm with insufficient balance: nothing charged, no subscription created, cart unchanged; the customer is offered Top Up with the shortfall amount | Order + Mobile |
| AC-7 | Tapping Confirm twice, or retrying after a network drop, never creates a second order or debit | Order + Mobile |
| AC-8 | If the cart or price changed after the screen loaded, Confirm is rejected, the screen refreshes and says why | Order + Cart + Mobile |
| AC-9 | A subscription-only cart creates the subscriptions with no immediate debit (first delivery is charged by the existing Daily Run → Order Service path) | Order + Subscription |

#### In scope

- Mobile: Review Cart screen changes, Add more items, Confirm Order, success screen,
  ProductConfig subscription → cart, checkout repository/bloc.
- Order Service (MA-97 slice): `POST /orders/checkout` orchestration, checkout record,
  multi-line one-time orders, schema migration, event schema updates.
- User Service (MA-93 slice): full default address on `GET /users/me`.
- Cart Service (MA-96 slice): `slotId` on subscription lines, split quote in `GET /cart`,
  internal read + remove-lines endpoints for Order Service.
- Subscription Service (MA-98 slice): internal create endpoint callable by Order Service.

#### Out of scope

- Inventory/stock reservation (no stock model exists — MA-132 §3, cart README Known Gaps).
- Paying at checkout via Razorpay directly (wallet-only; Top Up reuses the MA-24 screen).
- Offers/coupons entry (MA-29), delivery slot choice for one-time items, address
  selection/editing, ETA beyond the delivery date.
- Order tracking/details (MA-35/MA-36), cancellation (MA-32), invoices (MA-38).
- My Subscriptions' own create flow (MA-133 FR-7 custom schedule) — unchanged, still
  calls `POST /subscriptions` directly.

#### Open questions

All resolved by Product on 2026-09-25:

- Q1: Full address on the review screen → **yes**: show the full default address the
  customer saved on the onboarding Google Maps / Places screen. User Service already
  stores it; `GET /users/me` is extended to return it (MA-135 FR-6).
- Q2: One-time delivery date → **yes**, the same 20:00 IST cut-off as subscriptions:
  tomorrow if confirmed before 20:00, otherwise the day after.
- Q3: A subscription line that can't be started → **does not block** the rest of the
  order; it stays in the cart.
