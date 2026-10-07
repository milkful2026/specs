### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for **MA-42 — Product & Catalog Management · Admin / Catalog (Admin UI)**:

---

* **✓ Catalog Service — Admin Product & Category Management** — `services` (MA-94) · spec path `services/tasks/MA/MA-42/{KEY}.md`
  New admin-write API, all behind a new admin authorizer (Ops + SuperAdmin, same role set as Inventory's just-shipped gate): `POST /products` / `PATCH /products/{id}` (create/edit/activate/deactivate — new `isActive`/`hsnCode`/`taxRate` fields); `POST /categories` / `PATCH /categories/{id}`; admin-only `GET /admin/products` (list including inactive, paginated — mirrors Inventory's own `GET /inventory` list shape). New `is_active`, `hsn_code`, `tax_rate` columns on `products` (additive/defaulted, no backfill); new `catalog_audit_log` table, same shape as Inventory's `inventory_audit_log`. **Two pieces of real, non-trivial supporting work, not just CRUD:** (1) `POST /products` adopts the shared `EventBridgeOutboxPublisher` to publish `CatalogUpdated`, un-orphaning Inventory's existing MA-118 FR-8 consumer — Catalog has never published any event before; (2) this service has **no CDK/infra stack today at all** — one must be stood up (mirroring `inventory/infra/inventory/inventory_stack.py`), not assumed to already exist. Admin auth itself is a near-direct port of Inventory's `admin_context.py`/`local_admin_auth.py` (same compute model, same gap, same fix). **Resolved decision carried into this spec:** `GET /products`/`GET /search` filter `is_active = true`, but `GET /products/{id}` by direct id still resolves regardless of `isActive` — a product already referenced by an existing cart/order/subscription line must not start 404ing just because an admin deactivated it later.

* **✓ Portal-UI — Admin Catalog screens** — `portal-ui` (MA-20/Admin-UI) · spec path `portal-ui/tasks/MA/MA-42/{KEY}.md`
  New "Catalog" section under the existing MA-47 console and RBAC (`RequireRole roles={['Ops', 'SuperAdmin']}`, same mechanism as Customer Accounts/Inventory). Product list (all products including inactive, consumes the new `GET /admin/products`); create/edit product form (name, category, unit, description, price B2C/B2B, HSN code/tax rate, veg/organic, subscription-eligible, active toggle, image URL as a plain text field — no upload UI); category list + create/edit; an audit-trail view per product (consumes `catalog_audit_log`). Reuses Inventory's just-shipped screens' exact pattern (`InventoryListPage.tsx`/`InventoryDetailPage.tsx`/dialogs/`formatters.ts`) — no new infra, same Vite + React + TS + MUI stack, same React Query hook shape. **Blocked on** the Catalog Service spec above actually shipping.

---

* **⚠ Image upload/CDN pipeline — explicitly not spec'd, deferred**
  Per Step 1's resolved scope: `image_url` stays a plain admin-entered text field in this pass. A real upload pipeline is new infrastructure (object storage + CDN), not a form-field addition — flagged as explicit future work, not silently folded into either spec above.

* **⚠ Scheduled/future-effective price changes — explicitly not spec'd, deferred**
  Needs its own effective-dating design (closer in shape to Inventory's `available_from` batch scheduling than to a simple field edit). Not included in either spec above; a future story.

* **⚠ CSV bulk import/export — explicitly not spec'd, deferred**
  File parsing, validation, and partial-failure handling is a materially separate capability from the single-record CRUD both specs above cover. Not included; a future story.

* **⚠ Inventory Service (MA-48) — explicitly excluded, verification-only**
  No code change. Its `CatalogUpdated` consumer already exists, already tested (against a fake event) — the only new obligation is live verification once this story's Catalog spec ships a real producer, which belongs in that spec's own testing strategy (an integration/acceptance check), not a separate Inventory-side spec. Exactly symmetric to how MA-48 itself excluded Catalog's `StockChanged` consumer the same way.

* **⚠ Pricing & Offer Service (MA-101) — explicitly excluded, no change**
  Keeps reading `price_b2c` from Catalog at quote time unchanged; this story only changes where that value comes from.

---

#### Notes for the reviewer

- **Two specs, same shape as MA-48's MA-150/MA-151 split** — one backend, one portal-ui, with the backend spec carrying real supporting infrastructure work (outbox adoption + a from-scratch CDK stack) beyond what a plain "add 5 CRUD endpoints" estimate would suggest. Flagging prominently, same reason MA-48 flagged MA-118/MA-119's size: please size the Catalog spec as "CRUD + first-ever event publishing + first-ever infra stack," not just "CRUD."
- **Role gate (Ops + SuperAdmin) is settled**, carried forward from this session's own confirmed business requirement on Inventory — not re-litigated here.
- **The `is_active` filter's edge case (direct-id lookup still resolves) is resolved here as a decomposition-time decision**, not left as an open question into drafting, since getting it wrong would be a real production bug (an old order's product link 404ing) rather than a cosmetic gap.
- **"Pricing/Tax engine" and "CDN" named in MA-42's own Jira "Key Dependencies"** are addressed as: Pricing/Tax → the new `hsnCode`/`taxRate` fields are flat data, not a rules engine (per Step 1's A3, nothing in the codebase suggests per-zone/per-state tax logic exists or is needed); CDN → explicitly deferred (above), not silently assumed.

---

**To approve as-is (2 specs, image/CSV/scheduled-pricing explicitly deferred):** transition MA-42 → `SDD: Drafting`.
**To modify:** post `SDD-DECOMPOSITION-FEEDBACK`, then transition → `SDD: Drafting`.
**To reject:** transition → `SDD: Building Context` and post `SDD-FEEDBACK`.
