# Implementation Plan — MA-42: Catalog Service Admin API (MA-156)

## 1. Overview

**Story:** [MA-42](https://milkfuldairyindia.atlassian.net/browse/MA-42) — Product & Catalog Management
**Date:** 2026-10-08
**Author:** Claude Code (session), implementing the merged MA-156 spec

**Spec implemented:**

| Spec | Area | Status |
|------|------|--------|
| Catalog Service — Admin Product & Category Management (MA-156) | `services/catalog` | `SDD: Approved`, unimplemented |

**What this delivers:** an admin-write API on the existing `services/catalog` deployable — create/edit products (incl. activate/deactivate, new `isActive`/`hsnCode`/`taxRate` fields), create/edit categories, an admin-only product list (incl. inactive), a `catalog_audit_log` table, Catalog's first real event publish (`CatalogUpdated`, un-orphaning Inventory's existing consumer), and a new CDK/infra stack. No new service.

**Path note:** single-area story for this plan (`services` only) — portal-ui's plan (MA-157) is separate, at `portal-ui/tasks/MA/MA-42/impl-plan/`, and is **blocked on this one** — it has nothing real to call otherwise.

## 2. Prerequisites

**Confirmed by reading `services/catalog` directly, not assumed from the spec:**

| Assumption (from MA-156) | Verified against real code |
|---|---|
| Catalog is FastAPI/Fargate, one deployable, background-thread SQS consumer pattern already exists (`stock_changed_consumer.py`) | **Confirmed.** `src/main.py` runs uvicorn in the main thread, the `StockChanged` consumer in a background thread — identical shape to Inventory's `src/main.py`. |
| Zero write routes exist today | **Confirmed.** `products_handler.py`/`categories_handler.py` are `GET`-only; `product_repository.py` has no create/update method. |
| Catalog's existing routes have no `/v1` path prefix | **Confirmed** (caught during spec review, MA-156 §6 point 2) — `products_handler.py`/`categories_handler.py`/`app.py` all mount bare paths (`/products`, `/categories`, `/search`). New admin routes follow this, **not** Inventory's `/v1`-prefixed convention. |
| Inventory's `CatalogUpdated` consumer already exists, waiting for a producer | **Confirmed.** `inventory/src/adapters/catalog_updated_consumer.py` is implemented, tested, and its own docstring states Catalog "has no outbox/event-publish mechanism of any kind today." |
| Local-dev EventBridge wiring for `CatalogUpdated` already exists | **Confirmed — not a new local-dev task.** `local-dev/bootstrap.py`'s `bootstrap_catalog_updated_queue()` already wires a `CatalogUpdatedRule` (`source: ["catalog"]`, `detail-type: ["CatalogUpdated"]`, `unwrap_detail=True`) to a real SQS queue. Only the producer code needs writing — the rule, queue, and DLQ are already there. |
| Catalog's `.env.local` has the event-bus/event-source config a publisher needs | **False — missing.** Confirmed by reading the running container's env directly: unlike Inventory (`INVENTORY_EVENT_BUS_NAME`/`INVENTORY_EVENT_SOURCE`), Catalog's `bootstrap.py` env block (line ~700) has no equivalent keys at all today. **Must be added** to `bootstrap.py`'s `_write_env_file("catalog", {...})` call as part of this work. |
| No CDK/infra stack exists for Catalog | **Confirmed.** No `catalog/infra/` directory, unlike `inventory/infra/`. |
| `shared.adapters.outbox_event_publisher.EventBridgeOutboxPublisher` is reusable for a direct (non-table-backed) publish | **Confirmed** — Inventory's own `adapters/stock_event_publisher.py` already uses it this exact way (wraps it, doesn't duplicate boto3 logic); `adapters/catalog_event_publisher.py` should mirror that file's structure directly. |
| A local-dev admin-auth gap exists for FastAPI/Fargate services without a Lambda authorizer context | **Confirmed, and already solved once** — Inventory hit and fixed this identical problem (`inventory/src/handlers/admin_context.py` + `local_admin_auth.py`, `INVENTORY_LOCAL_ADMIN_AUTH` env var). **Port both files near-verbatim**, renaming `INVENTORY_*` → `CATALOG_*`; do not re-derive this from scratch. **Caveat:** as of this plan, Inventory's `admin_context.py` on `main` correctly has `ALLOWED_ROLES = frozenset({"Ops", "SuperAdmin"})` (recovered via `services` PR #36, merged 2026-10-08) — port from current `main`, confirmed current at the time of writing. |

**No cross-service blockers.** Everything this spec needs (the EventBridge rule, the shared outbox publisher, the admin-auth pattern to port) already exists somewhere in this codebase.

## 3. Implementation Order

1. **Schema migration** — `0003_catalog_admin.sql` (next in sequence after `0001_products_categories.sql`/`0002_stock_change_ordering.sql`): `ALTER TABLE products ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true`, `hsn_code VARCHAR(16)`, `tax_rate NUMERIC(5,2)`; new `catalog_audit_log` table (MA-156 §7). Extend `src/adapters/product_repository.py`'s `products_table` SQLAlchemy Core definition column-for-column to match (same hand-sync discipline that file's own header comment already documents).
2. **Domain + repository writes**: `CatalogService.create_product/update_product/create_category/update_category/list_products_admin`, backed by new `SqlAlchemyProductRepository` methods. `update_product` must diff only the *changed* fields for the audit row (MA-156 §4 FR-2) — write this diffing logic carefully and test it directly; it has no precedent in this codebase (MA-156 §11 Risk 5) to copy from.
3. **`catalog_audit_log` writes**: one Aurora transaction per create/edit (product write + audit insert together), mirroring the transaction-shape precedent `wallet_repository.py`'s `debit_for_order` / Inventory's `PATCH /inventory` already established — not a new transactional pattern, just a new table.
4. **`is_active` filtering on existing read endpoints** (MA-156 §4 FR-6): add the filter to `get_products`/`search`, but explicitly **not** to `get_product` (single-id lookup) — this asymmetry is a resolved spec decision, not an oversight; a test must assert both halves (list hides inactive, direct-id-get doesn't).
5. **Admin auth port** (§2 above): copy `inventory/src/handlers/admin_context.py` → `catalog/src/handlers/admin_context.py` and `inventory/src/handlers/local_admin_auth.py` → `catalog/src/handlers/local_admin_auth.py`, renaming the env var to `CATALOG_LOCAL_ADMIN_AUTH`. Wire into `catalog/src/handlers/app.py` the same way Inventory's `app.py` does (env-var-gated `add_middleware` call, same pattern as the existing `CATALOG_CORS_ALLOW_ALL` block already there).
6. **New FastAPI routes** (`admin_catalog_handler.py`, no path prefix per §2 above): `POST /products`, `PATCH /products/{id}`, `POST /categories`, `PATCH /categories/{id}`, `GET /admin/products`, `GET /products/{id}/audit-log` — all behind `require_ops_role` (Ops + SuperAdmin per the ported `admin_context.py`).
7. **`CatalogUpdated` publish**: new `adapters/catalog_event_publisher.py` (mirrors `inventory/src/adapters/stock_event_publisher.py`'s structure — wraps `EventBridgeOutboxPublisher`, direct publish not a polling outbox), called from `create_product` after the DB transaction commits. Payload exactly `{"payload": {"productId": "..."}}` (pinned by the consumer side, not re-derived). A publish failure must be caught and logged, **not** re-raised — the product row is already committed (MA-156 §4 FR-1/§11 Risk 1).
8. **`local-dev` integration**: add `CATALOG_EVENT_BUS_NAME`/`CATALOG_EVENT_SOURCE`/`CATALOG_LOCAL_ADMIN_AUTH` to `bootstrap.py`'s existing `_write_env_file("catalog", {...})` call (§2 above — this is new, unlike the EventBridge rule itself which already exists).
9. **Live-verify the `CatalogUpdated` round trip** (mandatory per MA-156 §10, not optional): `POST /products` against the running local-dev stack, confirm Inventory's `catalog_updated_consumer.py` actually provisions a `stock` row for the new product — the first time this consumer runs against a genuine producer instead of a manually-published test event.
10. **CDK stack**: new `catalog/infra/catalog/catalog_stack.py`, mirroring `inventory/infra/inventory/inventory_stack.py`'s structure (Fargate + ALB + Aurora + the new admin routes' API Gateway integrations referencing the existing admin authorizer Lambda by ARN, same cross-stack pattern MA-139/MA-48 both already use, including their disclosed placeholder-ARN gap — inherited, not solved here).

## 4. Key Design Decisions to Carry Into Implementation (not re-litigate)

- **No `/v1` prefix on any new route** (§2) — matches Catalog's own existing convention, deliberately different from Inventory's.
- **`PATCH /products/{id}` is both the edit and the activate/deactivate endpoint** (MA-156 §4 FR-2) — do not add a separate `/deactivate` route.
- **`GET /products/{id}` does not filter on `is_active`** (MA-156 §4 FR-6) — a direct-id lookup must keep resolving for an old order/cart reference; only list/search hide inactive products. Get this asymmetry right; it's the one resolved edge case this spec explicitly calls out.
- **A failed `CatalogUpdated` publish does not roll back the product write** (MA-156 §4 FR-1/§9/§11 Risk 1) — accepted trade-off, not a bug to "fix" by adding a rollback.
- **Categories get no audit log** (MA-156 §4 FR-3) — deliberate scope line, don't add one speculatively.
- **`catalog_audit_log`'s JSONB diff is new design work** (§11 Risk 5) — don't assume it's a drop-in copy of Inventory's typed-integer audit log; budget real time for the field-diffing logic and its own tests.

## 5. Testing Strategy

- **Unit:** validation (unknown category → 404, non-positive price → 400), the audit-row diff logic (only changed fields recorded, not the whole row), `get_audit_log`'s newest-first ordering and that it surfaces both `CREATE`- and `UPDATE`-originated rows, `is_active` filtering on `get_products`/`search` vs. its absence on `get_product`, `list_products_admin`'s `categoryId`/`isActive` filters.
- **Integration (local-dev, offline per Catalog's own SQLite-in-memory + `moto[sqs]` convention, see its README):** full `POST /products` asserting the product row + audit row land in one transaction; `PATCH /products/{id}` with `isActive: false` then confirming `GET /products/{id}` still 200s while `GET /products?categoryId=` no longer lists it; `GET /products/{id}/audit-log` after both a create and an edit shows both rows, newest-first.
- **Contract — mandatory live verification** (§3 step 9, MA-156 §10): not satisfied by a schema-shape assertion alone.
- **Negative scenarios required:** unknown category, non-positive price, unknown product on edit, unknown product on audit-log read, non-{Ops,SuperAdmin} caller, `CatalogUpdated` publish failure (product still created, failure logged, not silently swallowed without a trace — assert a log line, not just that the request still returns 201).

## 6. Acceptance Check

- `pytest services/catalog/tests/` passes, including the new admin-write and `is_active`-filtering tests.
- `ruff check . --select F` clean (this repo's actual blocking CI lint gate — confirmed, not assumed, from the inventory/subscription/user CI incident earlier this project).
- A manual curl walkthrough against the real local-dev stack: create a product, confirm it appears in `GET /admin/products` but also in the public `GET /products?categoryId=`, deactivate it, confirm it disappears from the public list but `GET /products/{id}` still 200s, and confirm Inventory's `stock` table gained a row for it (§3 step 9) — before declaring this done.
