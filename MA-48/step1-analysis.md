### SDD Step 1 — Analysis

**Story:** MA-48 — Inventory & Procurement Control · Admin / Inventory (Admin UI)
**Status:** SDD: Analyzing
**Sources:** NSMB App Feature Spec — Admin / Back-Office section (via Jira description); epic MA-20 (Admin-UI). No mock or attachment on the ticket. Blocked-by link: MA-95 (Inventory Service, `SDD: Approved`).

---

#### The ground truth changes this story's whole shape

Two Tasks under the already-**Approved** MA-95 (Inventory Service) story already cover most of this ticket's backend, in detail, unimplemented:

- **MA-118 — Reserve/Commit/Release, Batch & Expiry, Read API.** Defines `GET /inventory/{productId}` (on-hand/reserved/available/stockState), `POST /inventory/reserve|commit|release`, FIFO batch/expiry consumption, overselling-prevention row-level locking, a reservation-TTL sweep, and the real `StockChanged`/`LowStock` event producer.
- **MA-119 — Admin Manual Adjustment & Audit Trail.** Defines `PATCH /inventory` (signed adjustment, floor-at-zero on both `on_hand` and `available`), an immutable `inventory_audit_log` table, and admin-JWT authorization — explicitly split from MA-118 because admin-triggered adjustment is a distinct access pattern from order-driven reserve/commit/release.

**Neither is implemented.** `services/inventory`'s actual code today is serviceability-zone checks only (`serviceability_check_handler.py` and its internal twin) — no `stock`/`stock_batches`/`reservations`/`inventory_audit_log` tables, no reserve/commit/release/adjust endpoints, no `StockChanged`/`LowStock` producer anywhere in the repo. **Confirmed independently**: Catalog Service already *consumes* `StockChanged` (`stock_changed_consumer.py`, tracks `stock_state`/`last_stock_event_id`/`last_stock_event_at` on `products`) — its own docstring says outright "No real producer exists yet... this consumer is implemented and tested against a fake/moto-published event now." MA-118 is that missing producer.

**A cross-spec discrepancy worth flagging now:** MA-119 §3 names the admin UI as "portal-ui, **MA-42's** territory" (MA-42 = Product & Catalog Management). Given MA-48's own Jira description is explicitly about admin stock/inventory screens, this looks like a mis-attribution written before MA-48 existed as its own ticket — not a deliberate decision to fold inventory's admin screen into Catalog's. Flagged as an item to settle in Step 2/3, not assumed either way here.

#### User Story Summary

An admin/operations user needs to see and control physical stock from the admin console: manually adjust quantities (with audit trail), see batch/expiry detail, get reorder alerts for low stock, log wastage/spoilage, reconcile stock counts, and manage procurement (goods receipt) from the parent plant.

#### User / Actor

- **Primary:** authenticated admin (Cognito admin pool, role-gated — built in MA-47).
- **Secondary (systems):** Inventory Service (MA-95/MA-118/MA-119 — stock system-of-record), Catalog Service (MA-94 — the only existing real consumer of `StockChanged`, product identity owner), Order Service (MA-97, not yet built — future caller of reserve/commit/release, not this story's concern).

#### Goal and Business Outcome

- **Admin goal:** keep the platform's stock numbers true to physical reality, catch low stock before it becomes a stockout, and have a defensible record of every manual change.
- **Business outcome:** MA-118/MA-119's entire overselling-prevention design is only as good as the manual-adjustment and procurement processes that keep `on_hand` accurate in the first place — this story is the operational completion of the stock system MA-118/MA-119 already designed, not a separate concern.

#### Functional Intent (what, not how) — mapped against what MA-118/MA-119 already give us

| MA-48's ask | Already specified (MA-118/MA-119)? | Gap |
|---|---|---|
| Manual stock adjustments | **Yes** — `PATCH /inventory` (MA-119 FR-1), floor-at-zero on `on_hand` and `available`, immutable audit row | None on the backend; needs the admin UI only |
| Batch/expiry tracking | **Partially** — MA-118 tracks batches internally for FIFO consumption and `AVAILABLE_FROM` derivation, but **deliberately does not expose batch-level detail** via `GET /inventory/{productId}` (MA-118 FR-7, "a future batch-detail endpoint can be added... e.g. an admin dashboard") | A new batch-detail read endpoint is needed for an admin screen to show real batch/expiry rows, not just the aggregate `available`/`stockState` |
| Reorder alerts | **Half** — `LowStock` is published (MA-118 FR-6) but **has no consumer today** (MA-118 §8: "no defined consumer yet... Notification Service... out of scope") | None on the backend (D3) — the admin UI surfaces `stockState` across the product list; no new consumer/storage built |
| Wastage/spoilage logging | **Mostly** — a negative `PATCH /inventory` adjustment with a `reason` already captures this (MA-119 FR-1/FR-2); MA-119 §12 Q2 flags reason as free-text now, a constrained enum (spoilage/damage/recount/other) a "natural, non-breaking future refinement" | Possibly just a UI-level categorization (a reason dropdown) rather than a new backend concept — Step 2/3 to confirm |
| Stock reconciliation | **No** — not addressed by either spec | A new capability: comparing a physical count against `on_hand` and reconciling the difference (which is itself just an adjustment with a specific reason/workflow, per MA-119's own shape) |
| Procurement from the parent plant / goods receipt | **Explicitly deferred** — MA-118 §12 Q3: "a dedicated receiving workflow is future scope, same bucket as MA-119's already-out-of-scope reorder/procurement workflow"; MA-119 §3 explicitly excludes "Reorder/procurement workflow — item 29.0 in the NSMB spec, a separate future admin story" | This is new, unspecced backend work — the real remaining gap this story's SDD needs to design |

#### Initial Acceptance Criteria → spec-boundary mapping

| # | Acceptance criterion (draft, observable) | Likely spec owner |
|---|------------------------------------------|-------------------|
| AC-1 | An admin can see a product's on-hand/reserved/available/stock-state and act on it | portal-ui, consuming MA-118's existing `GET /inventory/{productId}` |
| AC-2 | An admin can adjust stock with a reason; the change and its audit row are both visible | portal-ui, consuming MA-119's existing `PATCH /inventory` (once implemented) |
| AC-3 | An admin can see batch/expiry detail for a product, not just an aggregate number | New: a batch-detail read endpoint (extends MA-118's data model, doesn't change its write-side contract) |
| AC-4 | An admin sees which products are low-stock / out-of-stock without manually checking each one | A list/summary endpoint surfacing `stockState` per product (D3) |
| AC-5 | An admin can record a goods-receipt (incoming stock from the parent plant) distinct from an ad-hoc correction | New: `POST /inventory/receive` (D2) — this story's one genuinely new backend capability |
| AC-6 | Every stock-affecting admin action is audited (who/what/when/why) | MA-119's existing `inventory_audit_log`, extended to cover the new goods-receipt action too |

#### In Scope (proposed)

- Admin Inventory screens in portal-ui: stock list/search, per-product detail (on-hand/reserved/available/batches), manual adjustment with reason, audit-trail view, low-stock indicators.
- Implementing MA-118 and MA-119's already-approved backend (currently spec-only) — this story cannot ship without them existing.
- A new batch-detail read endpoint (extends MA-118's read API, additive).
- A new goods-receipt/procurement capability (new stock-batches rows with real quantity, "from the parent plant") — the one genuinely new backend design this story needs.

#### Out of Scope (proposed)

- Reservation/commit/release lifecycle itself — MA-118's concern, consumed by Cart/Order (not yet built), untouched by this story.
- Accounting integration — Jira's "Key Dependencies" names Accounting, but nothing in MA-118/MA-119 or the current codebase defines any accounting system to integrate with; treat as aspirational/future unless the human flags otherwise.
- Order engine integration beyond what MA-118 already defines (`OrderCancelled` consumption) — MA-97 doesn't exist yet.
- A `LowStock` consumer/notification pipeline — Notification Service territory, explicitly deferred by MA-118 itself.
- Any change to Catalog's product identity/pricing — Catalog's (MA-94) territory, MA-118/MA-119 already respect this boundary and this story will too.

#### Assumptions

- A1. MA-118 and MA-119 are implemented as part of (or immediately ahead of) this story's own implementation — this story's admin UI has nothing to call otherwise. Flagged explicitly since it's a real sequencing dependency, not assumed silently.
- A2. The admin UI lives in portal-ui under the existing MA-47 RBAC console, same pattern as MA-39's Customer Accounts — not a new app.
- A3. "Procurement from the parent plant" means recording a goods-receipt event that increases `on_hand` (and creates a new batch row with its own expiry), attributed to an admin, auditable the same way MA-119's adjustments are — not a supplier-facing ordering/PO system (nothing in the ticket or codebase suggests the platform has suppliers other than "the parent plant" as a single internal source).

#### Resolved decisions (human, this session — not open questions)

- **D1 (Q1, the MA-42-vs-MA-48 discrepancy).** The inventory admin UI belongs to **this story (MA-48)**. MA-119's reference to "MA-42" is treated as a mis-attribution predating MA-48's creation as its own ticket, not a deliberate decision — MA-42's own description ("Product & Catalog Management") doesn't mention stock.
- **D2 (Q2, goods-receipt design).** A **new dedicated endpoint** (e.g. `POST /inventory/receive`) — creates a new `stock_batches` row with a real `expiry_date`, under the same row-level-lock/audit pattern MA-119's adjustment already uses. Not folded into the adjustment endpoint, since a goods receipt needs to establish a real batch (with its own expiry) rather than just moving the aggregate `on_hand` number.
- **D3 (Q3, reorder-alert scope).** **List view only** for v1 — the admin opens an Inventory screen and sees which products are low/out of stock, surfaced from `stockState` across the product list. No new backend state, no `LowStock` consumer — matches MA-118's own existing "publish-only, no consumer needed yet" posture.
- **D4 (role gate, resolving MA-119 §12 Q1 — "exact admin-role/claim name... deferred to implementation").** **Ops** is the role that updates inventory (adjustments, goods receipt) — not SuperAdmin-only. Matches the "admin/operations user" framing in this ticket's own description and the precedent set by MA-39's Customer Accounts (Ops + SuperAdmin). Exact split (e.g. whether SuperAdmin should also always be included alongside Ops) to be confirmed the same way MA-39 left it open, but Ops having access is now settled, not deferred.

#### Impacted areas (Jira Components)

- **`services`** — Inventory Service (MA-95/MA-118/MA-119, implementing the existing approved specs) + a new goods-receipt capability.
- **`portal-ui`** — new Admin / Inventory screens under the existing MA-47 console and RBAC.
- No `mobile-app` impact.

---

*Next: Step 2 — Build Technical Context (confirm MA-118/MA-119's implementation status precisely, design the goods-receipt capability, resolve Q1–Q3 above).*
