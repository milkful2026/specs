## SDD Step 2 — Technical Context

**Story:** MA-42 · **Status:** SDD: Building Context
**Context layers used:** `app/docs/design/milkful-well-architected.md` + `milkful-messaging.drawio`; MA-116/MA-117 (Catalog Service, shipped); MA-118/MA-119 (Inventory Service, shipped via MA-48) — specifically its admin-authorizer pattern, the most relevant precedent since Inventory is the only other FastAPI/Fargate (non-Lambda) admin-gated service in this codebase; `services/catalog` source in full; `services/inventory/src/handlers/admin_context.py` + `local_admin_auth.py` (built this session).

---

### Current State Summary

**`services/catalog` today:** FastAPI on Fargate (confirmed: `app = FastAPI(...)` in `src/handlers/app.py`, same shape as Inventory, unlike Lambda-based User/Identity-Auth/Order/etc.) — one deployable running both the HTTP app (uvicorn) and a background-thread `StockChanged` SQS consumer (`stock_changed_consumer.py`). `CatalogService` (domain layer) is a thin pass-through to `SqlAlchemyProductRepository` — four read methods (`get_categories`, `get_products(category_id)` — **category_id is required, there is no list-all**, `get_product`, `search`) plus `apply_stock_change` (the consumer's own write path). **Zero create/update methods exist anywhere in the service** — not hidden behind an unused route, genuinely absent from the repository, the domain service, and the handlers.

**No CDK/infra stack exists for Catalog** (confirmed — `services/catalog/` has no `infra/` directory, unlike Inventory). This story's implementation will need to either add one or extend whatever deploys this service today; flagged as a real gap, not assumed solved.

**Admin-authorization precedent, freshly built and directly applicable:** Inventory (MA-48) just solved the exact same problem — a FastAPI/Fargate service needing admin-role gating with no Lambda authorizer context to read from. Its solution (`services/inventory/src/handlers/admin_context.py`):
```python
ALLOWED_ROLES = frozenset({"Ops", "SuperAdmin"})

def get_caller_admin(request: Request) -> dict:
    admin_id = request.headers.get("x-admin-id")
    role = request.headers.get("x-admin-role")
    if not admin_id or not role:
        raise AdminAuthenticationError(...)
    return {"adminId": admin_id, "email": request.headers.get("x-admin-email"), "role": role}

def require_ops_role(request: Request) -> dict:
    admin = get_caller_admin(request)
    if admin["role"] not in ALLOWED_ROLES:
        raise AdminForbiddenError(...)
    return admin
```
reading `X-Admin-Id`/`X-Admin-Email`/`X-Admin-Role` headers that, in production, API Gateway's Lambda REQUEST authorizer + parameter mapping populates (same cross-stack `admin_authorizer_fn_arn` reference pattern MA-139/MA-48 both use) — and, for local-dev (where no such API Gateway hop exists), a small ASGI middleware (`local_admin_auth.py`) that decodes the browser's real `Authorization: Bearer` token's claims (unsigned, same trust model `_lambda_local_server.py` already documents) and injects those same three headers, gated behind an env var (`INVENTORY_LOCAL_ADMIN_AUTH`) so it never runs against real traffic. **This is directly reusable for Catalog, file-for-file** — same compute model, same gap, same fix shape, right down to the `{"Ops", "SuperAdmin"}` role set this session separately confirmed as a real (not default) business requirement.

### Impacted Systems

| System | Change |
|--------|--------|
| **Catalog Service (MA-94)** | Adds an admin-write API: `POST /products`, `PATCH /products/{id}` (incl. activate/deactivate via a new `is_active` field), `POST /categories`, `PATCH /categories/{id}`. New `is_active`, `hsn_code`, `tax_rate` columns on `products`. A new `catalog_audit_log` table (same shape as Inventory's `inventory_audit_log` — adminId/productId/previous/new/reason/timestamp — proven pattern, not reinvented). Existing `GET /products`/`GET /search` gain an `is_active = true` filter (a behavior change to shipped code — flagged in Step 1's A2, confirmed here as real and necessary, not optional). New admin-authorizer wiring, reusing Inventory's exact pattern above. New CDK/infra stack (doesn't exist today). |
| **`portal-ui`** | New Admin / Catalog section: product list (all products, including inactive — distinct from the consumer app's filtered view), create/edit product form (name, category, unit, description, price B2C/B2B, HSN/tax, veg/organic, subscription-eligible, active toggle, image URL as a plain text field), category list + create/edit, audit-trail view. Mirrors Inventory's own just-shipped screens (`InventoryListPage.tsx`/`InventoryDetailPage.tsx`/`AdjustStockDialog.tsx`) — same `RequireRole(['Ops', 'SuperAdmin'])`, React Query hooks, MUI table/dialog pattern, down to the shared `formatDate`/`formatDateTime` utils already factored out in `src/utils/formatters.ts`. |
| **Inventory Service (MA-48)** | No code change, but its existing `CatalogUpdated` consumer (MA-118 FR-8, implemented, currently orphaned — proven so far only against a manually-published test event) starts receiving real events for the first time once this story's `POST /products` publishes for real. Verification-only impact on Inventory itself, same "confirm live, don't just trust the contract on paper" discipline MA-48 applied to Catalog's own `StockChanged` consumer. |
| **Pricing & Offer Service (MA-101)** | No change. Keeps reading `price_b2c` from Catalog at quote time; this story only changes *how* that value gets set, not the read contract `pricing-offer` depends on. |
| **Identity & Auth (MA-92)** | No change — reuses the existing admin authorizer Lambda as-is, same cross-stack reference pattern MA-139/MA-48 both already use. |
| `mobile-app` | Indirect only: an admin-deactivated product disappears from `GET /products`/`GET /search` results — a real behavior change the Flutter client will observe, but no contract/shape change to those endpoints. |

### Dependencies

- **Inventory's admin-auth pattern (`admin_context.py` + `local_admin_auth.py`)** — existing, proven, directly portable; not a blocking dependency, just the template to copy rather than design fresh.
- **Inventory's `CatalogUpdated` consumer (MA-118 FR-8) — confirmed to already exist, and confirmed to be exactly as orphaned as `StockChanged` was before MA-48.** Directly read `services/inventory/src/adapters/catalog_updated_consumer.py`: it's implemented, tested, and is "the *only* documented mechanism by which a `stock` row ever comes to exist" — but its own docstring states Catalog "has no outbox/event-publish mechanism of any kind today... no `outbox` table, no `EventBridgeOutboxPublisher` usage, nothing publishes on product create," and explicitly names building that publish side as "Catalog's own scope (MA-94/MA-116)" — i.e. this story's scope. **This is not an open question; it's a confirmed, mandatory piece of this story's backend work**, symmetric to how MA-48 had to become `StockChanged`'s real producer for Catalog's own previously-orphaned consumer. Payload contract is already pinned by the consumer side: `{"payload": {"productId": "..."}}`.
- **No CDK/infra stack for Catalog today** — this story (or a close prerequisite) needs to add one, same as Inventory's `infra/inventory/inventory_stack.py`.

### Architecture Notes

**New endpoints on Catalog Service:**
```
POST   /products              body: {categoryId, name, description, unit, priceB2c, priceB2b?,
                                      imageUrl?, tag?, subscriptionEligible, isVeg, isOrganic,
                                      hsnCode?, taxRate?}
                               → INSERT products (is_active=true by default)
                               → INSERT catalog_audit_log (action="CREATE")
                               → publish CatalogUpdated {"payload": {"productId": "..."}} —
                                 un-orphans Inventory's existing MA-118 FR-8 consumer, same
                                 "new real producer for an already-built, tested, waiting
                                 consumer" shape as MA-48's own StockChanged work. Needs an
                                 outbox table + EventBridgeOutboxPublisher in Catalog — neither
                                 exists today (confirmed), so this is new infrastructure for
                                 this service, not just a new call site.

PATCH  /products/{id}         body: any subset of the above fields, plus {isActive}
                               → UPDATE products SET <changed fields>
                               → INSERT catalog_audit_log (action="UPDATE", previous/new per
                                 changed field — same shape as Inventory's adjustment audit row)

POST   /categories            body: {name, iconName, sortOrder?}
PATCH  /categories/{id}       body: any subset of {name, iconName, sortOrder}

GET    /admin/products        admin list (unlike the public GET /products, no categoryId
                               required, includes inactive products) — paginated, mirrors
                               Inventory's own GET /inventory list-view shape exactly.
```
All five sit behind the admin authorizer (Ops + SuperAdmin, same as Inventory).

**Existing-endpoint behavior change:** `GET /products`, `GET /products/{id}`, `GET /search` all add `WHERE is_active = true` (or, for the single-product get, 404 on an inactive product — Step 3 to settle which, since "deactivated but directly linked, e.g. in an old order" is a real edge case worth deciding explicitly rather than defaulting silently).

**Audit trail:** a new `catalog_audit_log` table, not a reuse of Inventory's `inventory_audit_log` (different database — `database-per-service` — Catalog's own Aurora, Inventory's is separate) but the *same shape*: `id, productId, adminId, action, previousValue, newValue, reason?, createdAt`. Proven pattern, zero new design risk.

### Data / Integration Considerations

```sql
-- New columns on products (all additive, all nullable or defaulted so
-- existing seeded rows stay valid with no backfill migration needed):
ALTER TABLE products ADD COLUMN is_active  BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE products ADD COLUMN hsn_code   VARCHAR(16);
ALTER TABLE products ADD COLUMN tax_rate   NUMERIC(5, 2);

-- New table, same shape as inventory_audit_log (MA-119 §7), this
-- service's own Aurora database:
CREATE TABLE catalog_audit_log (
    id              VARCHAR(64) PRIMARY KEY,
    product_id      VARCHAR(64) NOT NULL REFERENCES products(id),
    admin_id        VARCHAR(64) NOT NULL,
    action          VARCHAR(16) NOT NULL,   -- 'CREATE' | 'UPDATE' | 'ACTIVATE' | 'DEACTIVATE'
    previous_value  JSONB,
    new_value       JSONB,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
No change to `categories`' existing columns — create/edit uses them as-is.

**Event contract:** no new events. `StockChanged` consumption is unchanged. Whether product creation needs to *emit* an event Inventory listens for (to auto-provision a `stock` row) is the one open integration question carried into Step 3 (see Dependencies above) — Inventory's own `provision_stock_if_absent` machinery (confirmed to exist from this session's own Inventory work) suggests it already tolerates a product appearing with no prior signal, which may mean this is a non-issue; needs direct confirmation, not assumption, before decomposition finalizes.

### Constraints and Guardrails (from L1)

- **Database-per-service** — unchanged; `catalog_audit_log` lives in Catalog's own Aurora, not Inventory's, despite the shape-reuse.
- **Zero-trust** — new endpoints behind the admin authorizer, Ops+SuperAdmin checked server-side, never a client-supplied role — identical posture to Inventory.
- **Compute unchanged** — still one Fargate deployable; no new service.
- **Additive-only to existing read endpoints** — the `is_active` filter is the one deliberate behavior change to shipped code, called out explicitly rather than snuck in as a side effect.

### Risk Register

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | No CDK/infra stack exists for Catalog today — this story can't deploy anywhere real without one, a materially bigger prerequisite than it looks from the Jira description alone. | High | Flagged explicitly here, same as MA-48 flagged MA-118/MA-119's size; implementation planning must size "stand up Catalog's infra stack" as real, separate work, not assume it already exists. |
| R2 | Deactivating a product that's referenced by an existing order/cart/subscription has undefined behavior today — nothing in Cart/Order/Subscription's own code was checked for how they'd handle a product disappearing mid-flow. | Med | Out of this story's own scope to fix those services, but the `is_active` filter's exact enforcement point (hide from new reads vs. hard-block) needs to be chosen defensively in Step 3 — likely "hide from list/search, but `GET /products/{id}` by direct id still resolves" so an existing cart/order line referencing it doesn't start 404ing. |
| R3 | **Confirmed, not speculative**: Catalog has never adopted the shared `EventBridgeOutboxPublisher` (`shared/adapters/outbox_event_publisher.py` — already used by Inventory/Wallet/etc., so this is adoption, not new design) to un-orphan Inventory's existing `CatalogUpdated` consumer — still real, non-zero work (outbox table migration, wiring the publish call into `POST /products`'s transaction), easy to underestimate as "just call publish()" if the outbox-table prerequisite is missed. | Med | Flagged explicitly here, same as MA-48 flagged `StockChanged`'s producer-side work; implementation planning sizes "adopt the shared outbox publisher in Catalog" as its own step, not a one-line addition to `POST /products`. |
| R4 | Same admin-authorizer ARN cross-stack placeholder gap MA-139/MA-48 both already carry — this story would inherit, not introduce, it. | Low | Not this story's problem to solve originally; same single combined future fix note as MA-48's own R4. |

### Operational Considerations

- **Observability:** new metric `catalog.admin.product_write.count`, tagged by action (create/update/activate/deactivate), mirroring Inventory's `inventory.receive.count` precedent.
- **Rollout:** additive for the write API; the `is_active` filter on existing read endpoints is the one change needing a real rollout thought (all existing seeded products default `is_active=true` via the migration's own `DEFAULT true`, so no pre-migration product silently disappears).
- **Backward compatibility:** `GET /products`/`GET /products/{id}`/`GET /search` response shapes are unchanged (new fields like `isActive`/`hsnCode`/`taxRate` are additive to the serialized `Product`, not breaking); only the *filter* behavior changes.

---

*Next: Step 3 — Decomposition proposal (halt for human approval). Expect specs for: Catalog Service (admin-write API + schema + infra stack) and Portal-UI (Admin/Catalog screens) — same two-spec shape as MA-48's MA-150/MA-151 split.*
