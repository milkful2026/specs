# Implementation Plan — MA-48: Inventory Service (MA-118 + MA-119 + MA-150)

## 1. Overview

**Story:** [MA-48](https://milkfuldairyindia.atlassian.net/browse/MA-48) — Inventory & Procurement Control
**Date:** 2026-10-03
**Author:** Claude Code (session), implementing the merged MA-150 spec and its two hard prerequisites

**Specs implemented, in dependency order:**

| Spec | Area | Status |
|------|------|--------|
| Inventory — Reserve/Commit/Release, Batch & Expiry, Read API (MA-118) | `services/inventory` | `SDD: Approved`, **unimplemented** |
| Inventory — Admin Manual Adjustment & Audit Trail (MA-119) | `services/inventory` | `SDD: Approved`, **unimplemented** |
| Inventory Service — Admin Receive, Batch Detail & Stock List (MA-150) | `services/inventory` | `SDD: Approved`, **unimplemented** |

**What this delivers:** the full stock system-of-record (`stock`/`stock_batches`/`reservations`/`inventory_audit_log`), reserve/commit/release with overselling-prevention locking, a TTL-expiry sweep, the real `StockChanged`/`LowStock` producer, `PATCH /inventory` (admin adjustment), and MA-150's four additions (`POST /inventory/receive`, `GET /inventory/{productId}/batches`, `GET /inventory`, `GET /inventory/{productId}/audit-log`) — all in one `services/inventory` deployable, no new service.

**Path note:** single-area story (`services` only) — this plan covers all three Tasks together because MA-150 has no independent implementation order from MA-118/MA-119 (confirmed in Step 2: MA-150's endpoints read/write tables MA-118/MA-119 define, nothing else). Portal-UI's plan (MA-151) is separate, at `portal-ui/tasks/MA/MA-48/impl-plan/`.

## 2. Prerequisites

**Confirmed by reading `services/inventory` directly, not assumed from the specs:**

| Assumption (from MA-118/MA-119/MA-150) | Verified against real code |
|---|---|
| `services/inventory` is FastAPI/Fargate, one deployable, background-thread SQS consumer pattern already exists (`zone_update_consumer.py`) | **Confirmed.** `src/main.py` runs uvicorn in the main thread, `ZoneUpdated` consumer in a background thread — `OrderCancelled` (MA-118 FR-5) and the TTL sweep (MA-118 FR-2) follow the identical shape, not a new compute pattern. |
| No `stock`/`stock_batches`/`reservations`/`inventory_audit_log` tables exist yet | **Confirmed.** Only migration is `0001_serviceability_zones.sql`. All four new tables are genuinely new, additive migrations (`0002_stock.sql`, or split further — implementer's call, see §3 step 1). |
| No admin routes exist yet | **Confirmed.** Only `serviceability_check_handler.py` (public) and `internal_serviceability_check_handler.py` (internal-ALB-trust) exist. |
| Catalog's `StockChanged` consumer has no real producer | **Confirmed independently** — `catalog/src/adapters/stock_changed_consumer.py`'s own docstring states this outright. |
| Local-dev EventBridge wiring for `StockChanged` needs to be built | **False — already exists.** `local-dev/bootstrap.py` line 375 already wires an EventBridge rule (`{"source": ["inventory"], "detail-type": ["inventory.stock.changed"]}`) to a `stock-changed-target` queue. **This is not a new local-dev task** — only the producer code (MA-118 FR-6) needs to be written to actually publish to it. |
| No row-level-locking precedent exists in this codebase to follow | **False — real precedent exists.** `wallet/src/adapters/wallet_repository.py`'s `debit_for_order` (lines ~284-340) already implements the exact "SELECT ... FOR UPDATE, lock-check-write, single transaction" shape MA-118's reserve/commit/release and MA-119's adjustment need for the `stock` row. **Mirror this file's structure directly** — don't design concurrency control from the spec prose alone; read `debit_for_order` first. |
| `inventory` has no `retry.py` (unlike `user`/`identity-auth`/`cart`/`pricing-offer`) | **Confirmed, and correct as-is** — Inventory's new work (MA-118/119/150) makes no outbound HTTP calls to other services (only DB + SQS publish/consume), so no retry helper is needed. Don't add one speculatively. |

**No cross-service blockers.** Unlike MA-96's cart implementation plan (which found two services that didn't exist at all), everything MA-118/MA-119/MA-150 need is either already real (Catalog's consumer, the EventBridge rule, the locking precedent) or self-contained within `services/inventory`.

## 3. Implementation Order

Strict dependency order — each step's tests must pass before the next starts, since MA-119/MA-150 both read/write what MA-118 creates:

1. **Schema migration(s)** — `stock`, `stock_batches`, `reservations` (MA-118 §7), `inventory_audit_log` (MA-119 §7). One migration file or several, additive to `0001_serviceability_zones.sql`. Recommend splitting by spec (`0002_inventory_stock.sql` for MA-118's three tables, `0003_inventory_audit_log.sql` for MA-119's one) so each is independently reviewable against its own spec, matching this repo's existing one-migration-per-logical-change convention (see `identity-auth`'s `0001_admin_user.sql` / `0002_fix_admin_ip_allowlist_type.sql` split).
2. **MA-118 domain + adapters**: `Stock`/`StockBatch`/`Reservation` models, `InventoryStockService.reserve/commit/release`, FIFO batch consumption, the row-level lock (mirror `wallet_repository.py`'s `debit_for_order`, per §2). Unit + concurrency tests (MA-118 §10's N-concurrent-reserve test is the single highest-priority test in this entire plan — do not skip or weaken it).
3. **MA-118 read API + TTL sweep + `StockChanged`/`LowStock` producer**: `GET /inventory/{productId}`, the sweep job (mirrors `user` service's outbox-publisher polling pattern per MA-118 §FR-2), the event publish. **Live-verify Catalog's consumer actually reacts** — this is the first real end-to-end test of a contract that's existed only on paper until now.
4. **MA-118 `OrderCancelled` consumption**: new SQS consumer, same background-thread shape as `zone_update_consumer.py`. No real producer exists yet (Order Service, MA-97, not built) — test against a fake/moto-published event, same documented posture MA-118 §11 Risk 1 already states.
5. **MA-119 admin adjustment**: `PATCH /inventory`, floor-at-zero on both `on_hand` and `available`, the audit-log write (same transaction, same lock). Unit + integration tests per MA-119 §10.
6. **MA-150's four endpoints**, each independently small once steps 1-5 exist: `POST /inventory/receive` (FR-1), `GET /inventory/{productId}/batches` (FR-2), `GET /inventory` (FR-3), `GET /inventory/{productId}/audit-log` (FR-4).
7. **Admin authorizer wiring**: cross-stack API Gateway Lambda REQUEST authorizer referencing Identity & Auth's existing `admin_authorizer_handler`, mirroring `user_stack.py`'s `admin_authorizer_fn_arn` pattern exactly (MA-139 precedent) — including, honestly, inheriting that same placeholder-ARN gap rather than solving it twice.
8. **`local-dev` integration**: `bootstrap.py` migrations already apply automatically (per the existing `apply_migrations.py` pattern); no new EventBridge wiring needed (§2); `run_local.py` needs the new admin routes wired with the local-dev auth stand-in, mirroring `user/run_local.py`'s `_local_admin_authorizer` precedent from MA-139.
9. **CDK stack**: extend `inventory_stack.py` with the new routes + the admin authorizer cross-stack reference + any new IAM grants (none beyond what Inventory's own Aurora/EventBridge access already covers — no new external service calls).

## 4. Key Design Decisions to Carry Into Implementation (not re-litigate)

- **Row-level pessimistic locking**, not optimistic concurrency (MA-118 §6/§9, precedent: `wallet_repository.py`) — do not substitute a different concurrency strategy without flagging it as a spec deviation.
- **`POST /inventory/receive` is deliberately non-idempotent** (MA-150 §4 FR-1/§11 Risk 1) — do not add an idempotency key speculatively; it's an open question (MA-150 §12), not a decided requirement.
- **`GET /inventory` has no product-name search** (MA-150 §11 Risk 2) — Inventory doesn't own product identity; don't reach into Catalog's database to add this.
- **Audit log has no update/delete path** (MA-119 FR-2) — immutability is enforced by omission, not a DB trigger; don't add one.
- **DB-commit-then-Cognito-call ordering** doesn't apply here (that was MA-139's pattern, not this story's) — Inventory's writes are self-contained within its own Aurora transaction, no external synchronous call to compensate for.

## 5. Testing Strategy (consolidated across MA-118/MA-119/MA-150)

- **The concurrency/load test (MA-118 §10) is this plan's single most important test** — N concurrent `reserve` calls against stock for exactly N-1, asserting exactly N-1 succeed, 1 fails cleanly, and `available` never goes negative at any point. Do not consider this story done without it passing against real Postgres (not just SQLite), since lock behavior under contention is exactly what SQLite's test-double fidelity gap (documented elsewhere in this repo) can't verify.
- **Live Catalog verification** (§3 step 3) — reserve/commit/release a real product locally, confirm `products.stock_state` in Catalog's own database actually updates. This closes a gap that's existed since Catalog's consumer was first written against a fake event.
- Standard unit/integration coverage per each spec's own §10 — not re-enumerated here, the specs are authoritative for test-case lists.

## 6. Acceptance Check

- `pytest services/inventory/tests/` passes, including the concurrency test, before this plan is considered complete.
- A manual curl walkthrough (mirroring the pattern established for MA-39/MA-47 in this repo's own `local-dev/README.md`) — register a product in Catalog, receive stock, reserve/commit it, adjust it, confirm the audit log and `StockChanged` both reflect reality — before declaring this done, not just unit tests in isolation.
