## SDD Step 2 — Technical Context

**Story:** MA-48 · **Status:** SDD: Building Context
**Context layers used:** `app/docs/design/milkful-well-architected.md` + `milkful-messaging.drawio`; MA-118/MA-119 (Inventory Service, approved, unimplemented); MA-139 (User Service admin pattern, shipped, MA-39); `services/inventory` source; `services/catalog`'s `stock_changed_consumer.py`.

---

### Current State Summary

**`services/inventory` today:** FastAPI app on Fargate (not Lambda, unlike User/Identity-Auth) — `APIRouter` + `Depends`-based routes, one deployable running both the HTTP app (uvicorn, main thread) and a background-thread SQS consumer (`zone_update_consumer.py`, for `ZoneUpdated`). Only real functionality: serviceability-zone checks (`serviceability_check_handler.py`, public via API Gateway; `internal_serviceability_check_handler.py`, network-trust-only via internal ALB). No `stock`/`stock_batches`/`reservations`/`inventory_audit_log` tables exist. No admin routes exist.

**MA-118 and MA-119 (both `SDD: Approved`, both unimplemented)** already fully design: the `stock`/`stock_batches`/`reservations` schema (§7 of MA-118), reserve/commit/release with row-level-lock overselling prevention, a TTL sweep, `GET /inventory/{productId}`, `PATCH /inventory` (admin adjustment) with its own `inventory_audit_log` table and floor-at-zero-on-`available` check, and the real `StockChanged`/`LowStock` producer. **This story's implementation must build these two specs' content as a prerequisite** — there is nothing to layer MA-48's own new pieces on top of otherwise.

**Catalog's `stock_changed_consumer.py` is a proven, tested, currently-orphaned consumer** — its own docstring states "No real producer exists yet." Implementing MA-118 directly un-orphans it; this is a real, immediate, verifiable payoff independent of anything else in MA-48, worth calling out as an implementation-sequencing incentive.

**Admin-route pattern to mirror (from MA-139/User Service, shipped):** a cross-stack API Gateway Lambda REQUEST authorizer referencing Identity & Auth's existing `admin_authorizer_handler` (same ARN-parameter pattern `user_stack.py` uses, including that implementation's own placeholder-ARN caveat — not a new problem MA-48 introduces, an existing one it inherits), plus a small `admin_context.py`-style helper reading `{adminId, email, role}` out of the authorizer context. Inventory being FastAPI/Fargate rather than Lambda doesn't change this — the authorizer attaches at API Gateway, in front of either compute model identically; the FastAPI side consumes it via a `Depends(get_caller_admin)` dependency instead of a bare function call, idiomatic for this service's existing style (`Depends(get_serviceability_service)` is the exact precedent already in `serviceability_check_handler.py`).

### Impacted Systems

| System | Change |
|--------|--------|
| **Inventory Service (MA-95)** | Implements MA-118 + MA-119 in full (prerequisite). Adds three new pieces for this story: (1) `POST /inventory/receive` — goods receipt (D2), new `stock_batches` row with a real `expiry_date`, same audit/lock pattern as MA-119's adjustment; (2) `GET /inventory/{productId}/batches` — batch-detail read, additive to MA-118's existing aggregate-only `GET /inventory/{productId}`; (3) `GET /inventory` — list/summary across all products with `stockState`, for the admin list view (D3) and reorder-alert surfacing. All three sit behind the new admin authorizer (Ops role, D4). |
| **`portal-ui`** | New Admin / Inventory section: product/stock list with low-stock indicators, per-product detail (on-hand/reserved/available + batch table), adjustment dialog (reason, matches MA-39's Customer Accounts dialog pattern), goods-receipt dialog (quantity + expiry date), audit-trail view. Gated to Ops (+ SuperAdmin, same question MA-39 left open for its own role split). |
| **Catalog Service (MA-94)** | No code change — its existing `StockChanged` consumer starts receiving real events for the first time once Inventory implements MA-118. Verification-only impact: confirm live, don't just trust the contract on paper (same "don't trust unverified claims" discipline this project has used throughout). |
| **Identity & Auth (MA-92)** | No change — reuses the existing admin authorizer Lambda as-is, same cross-stack reference pattern already proven by MA-139. |
| `mobile-app` | None. |

### Dependencies

- **MA-118/MA-119 implementation is this story's hard prerequisite** — not parallelizable the way MA-39's three specs were, since MA-48's own new endpoints (`receive`, `batches`, the list view) all read/write the `stock`/`stock_batches` tables MA-118 defines. Recommend: implement MA-118 → MA-119 → MA-48's three additions, in that order, as one continuous engineering effort rather than three separately-sequenced stories, even though they're three separate Jira items.
- **Identity & Auth's admin authorizer** — existing, no new dependency, same ARN-wiring caveat as MA-139 inherits.
- **Catalog's `StockChanged` consumer** — existing, tested, becomes a real integration point (not a new dependency to build, but a real one to verify live) the moment MA-118 ships.

### Architecture Notes

**New endpoint: `POST /inventory/receive`** (D2)
```
Body: { productId, quantity, expiryDate, reason? }
  → row-level lock on `stock` (same lock MA-118/MA-119 already use)
  → INSERT stock_batches (product_id, quantity, expiry_date, available_from=NULL i.e. available now)
  → UPDATE stock SET on_hand = on_hand + quantity
  → INSERT inventory_audit_log (adminId, productId, previousQuantity, newQuantity,
                                  adjustment=+quantity, reason="goods_receipt: " + reason)
  → publish StockChanged (shares MA-118/MA-119's contract — a third producer of the same event)
  → same single-Aurora-transaction guarantee MA-119 NFR already states (write + audit atomic)
```
Deliberately NOT the same endpoint as MA-119's `PATCH /inventory` (D2's resolution) — a goods receipt creates a real batch with its own expiry date (feeding MA-118's FIFO consumption and `AVAILABLE_FROM` derivation correctly for *this* batch specifically), whereas `PATCH /inventory` only moves the aggregate `on_hand` number with no batch identity at all. Reusing the adjustment endpoint would have silently broken batch/expiry accuracy for every future FIFO draw against received stock.

**New endpoint: `GET /inventory/{productId}/batches`**
Read-only, lists `stock_batches` rows for a product (quantity remaining, expiry date, received date) — the detail MA-118 FR-7 deliberately left out of the aggregate endpoint. Additive; does not change `GET /inventory/{productId}`'s existing response shape at all.

**New endpoint: `GET /inventory`**
Paginated list across all products: `productId`, `onHand`, `reserved`, `available`, `stockState`, `lowStockThreshold`. This is the list/summary view D3 resolved as sufficient for "reorder alerts" — an admin sees every `OUT_OF_STOCK` or near-`lowStockThreshold` row without needing a notification pipeline. No new storage; reads the same `stock` table MA-118 already defines, same shape `GET /inventory/{productId}` already derives per-product.

**Admin authorization wiring** — mirrors MA-139's exactly: new API Gateway route integrations for all three endpoints (plus MA-119's own `PATCH /inventory`, when implemented) reference the existing admin authorizer Lambda by ARN; a new `admin_context.py`-equivalent (or a direct adaptation, not a cross-service import, per the existing "never import another service's src/" rule) reads `{adminId, email, role}`; Ops role required (D4), checked server-side.

### Data / Integration Considerations

**Schema — all additive, same `milkful_inventory` Aurora database MA-118/MA-119 already extend (no new migration file conflicts, assuming MA-118/MA-119's own migrations land first):**

```sql
-- No new tables for receive/batches/list — they read/write MA-118's
-- existing stock/stock_batches tables and MA-119's existing
-- inventory_audit_log exactly as those specs already define them.
-- This story's only schema footprint, if any, is confirming
-- stock_batches has every column receive() needs (quantity,
-- expiry_date, available_from, received_at — all present per MA-118
-- §7 already).
```

This is a deliberate, notable property of this story's design: **zero new tables.** Every new endpoint is a new read or write shape over schema MA-118/MA-119 already specified — the cleanest possible confirmation that those two specs correctly anticipated what an admin-facing layer would eventually need.

**Event contract:** `StockChanged` — no change to MA-118's existing contract (FR-6); `receive()` is simply a third publisher alongside reserve/commit/release and MA-119's adjustment.

### Constraints and Guardrails (from L1)

- **Database-per-service** — unchanged; Inventory's Aurora stays Inventory's alone, Catalog only ever learns of stock state via `StockChanged`, never a DB read.
- **Zero-trust** — new endpoints behind the admin authorizer, Ops role checked server-side, never trusting a client-supplied role (same posture as MA-139).
- **Row-level locking, not optimistic concurrency** — `receive()` reuses MA-118/MA-119's existing lock strategy on the `stock` row, not a new concurrency mechanism; a goods receipt racing a `reserve`/`commit`/adjustment serializes the same way those already do against each other.
- **Single-transaction audit guarantee** — `receive()`'s batch insert, `on_hand` update, and audit-log insert are one Aurora transaction, matching MA-119's own NFR for `PATCH /inventory`.
- **Compute unchanged** — still one Fargate deployable; no new service, no new compute model.

### Risk Register

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | MA-118/MA-119 implementation is a real, non-trivial prerequisite (concurrency-safe reserve/commit/release, a TTL sweep, an audit log) bundled into what Jira tracks as a separate, already-"Approved" pair of tickets — easy to underestimate this story's actual size if read as "just add 3 endpoints." | High | Flagged explicitly here and in Step 1; implementation planning must size MA-118+MA-119+MA-48's additions as one continuous effort, not three independent small tickets. |
| R2 | Catalog's `StockChanged` consumer has never run against a real producer — contract correctness is currently "proven" only against a fake/moto-published test event (per its own docstring). | Med | Verify live, end-to-end, the first time MA-118 ships (reserve/commit/release a real product, confirm Catalog's `products.stock_state` actually updates) — don't trust the paper contract alone, consistent with this project's established verification discipline. |
| R3 | `receive()` and `PATCH /inventory` (MA-119) both publish `StockChanged` and both write `inventory_audit_log` — two producers of the same event/audit shape from two different code paths (plus reserve/commit/release as a third). | Low | Both specs already agree on the exact payload/audit-row shape; as long as `receive()`'s implementation is built by literally reusing MA-119's existing audit-write helper (not re-deriving it), this is a non-issue — flagged so the implementer reuses rather than re-implements. |
| R4 | The admin authorizer ARN cross-stack wiring is the same placeholder-pattern gap MA-139 already shipped with (a known, disclosed, not-yet-wired TODO) — MA-48 would inherit, not introduce, this gap. | Low | Not this story's problem to solve; worth a single combined fix (wire the real ARN once, for both User Service's and Inventory's stacks) whenever that TODO is actually addressed. |

### Operational Considerations

- **Observability:** reuses MA-118's existing CloudWatch alarms (TTL-sweep backlog, elevated reserve-rejection rate) and MA-119's audit-completeness expectation (100% of successful adjustments produce exactly one audit row) — `receive()` held to the same bar. New metric: `inventory.receive.count`, tagged by product, for visibility into goods-receipt volume.
- **Rollout:** since MA-118/MA-119 are prerequisites, no dark-launch/feature-flag concern specific to MA-48's own three endpoints beyond whatever sequencing MA-118/MA-119's own implementation plan uses.
- **Backward compatibility:** fully additive — `GET /inventory/{productId}`'s existing (once MA-118 ships) response shape is untouched by `/batches` or the new list endpoint.

---

*Next: Step 3 — Decomposition proposal (halt for human approval). Expect specs for: Inventory Service (implementing MA-118+MA-119 plus this story's 3 new endpoints — likely proposed as building on/extending those existing Tasks rather than a 4th parallel spec, to avoid re-specifying already-approved content) and Portal-UI (Admin/Inventory screens).*
