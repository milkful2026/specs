### SDD Step 1 — Analysis

**Story:** MA-42 — Product & Catalog Management · Admin / Catalog (Admin UI)
**Status:** SDD: Analyzing
**Sources:** NSMB App Feature Spec — Admin / Back-Office section (via Jira description); epic MA-20 (Admin-UI). No mock or attachment on the ticket. No blocked-by link, but MA-94 (Catalog Service, `Impl:Done`) is the obvious prerequisite by name alone.

---

#### The ground truth changes this story's whole shape

MA-94 (Catalog Service) and its two Tasks — MA-116 (Product & Category Data API) and MA-117 (Search/Filter/Sort) — are **already implemented** (`Impl:Done`), but **read-only**. Confirmed directly from the running code:

- `services/catalog/src/handlers/products_handler.py` and `categories_handler.py` expose exactly `GET /products`, `GET /products/{id}`, `GET /categories`, `GET /search` — no POST/PUT/PATCH anywhere in the service.
- `services/catalog/src/adapters/product_repository.py` has no create/update method at all — only read queries and `apply_stock_change` (the `StockChanged` consumer's own write path, unrelated to admin edits).
- **Catalog's own README says this outright, already attributed to this story**: *"Admin/write API for products & categories (create/edit/deactivate, bulk import) — MA-42's territory, out of scope for MA-94/this service per its own spec's explicit Scope section."* This is not a discovery — MA-94 already drew this exact boundary and pointed at MA-42 by name.
- Symmetric confirmation from the other side: MA-48's own step1-analysis (Out of Scope) says *"Any change to Catalog's product identity/pricing — Catalog's (MA-94) territory, MA-118/MA-119 already respect this boundary and this story will too."* No cross-story ownership conflict here, unlike MA-48's MA-42-mis-attribution discrepancy (which that story's own D1 already resolved the other way — inventory admin screens stayed with MA-48, not this one).

**Pricing is split across two services, and neither one lets anyone set it:**
- `pricing-offer` (MA-101/MA-122, `Impl:Done`) only **computes a quote** (tax + delivery fee on top of whatever price Catalog returns) via `POST /pricing/quote` — it has no persistence layer, no DB, never stores or sets a price. Its own README calls itself "deliberately scoped-down."
- The actual price lives on Catalog's `products.price_b2c`/`price_b2b` (`src/domain/models.py`), and Catalog exposes no write route for it at all (above).
- **No tax/HSN field exists anywhere in the schema** (`migrations/0001_products_categories.sql` — no `hsn_code`, no `tax_rate`, nothing). The Jira description's "taxes/HSN" line has no backing data model yet.
- **No active/inactive flag exists on `products` either** — the Jira description's "activate/deactivate" has nothing to toggle today; a product can currently only be created (never, since there's no create route) or implicitly hidden by not seeding it.
- **No image upload/CDN pipeline** — `image_url` is a nullable text column; nothing populates it (seed data ships with `image_url = NULL`, per Catalog's README's own "Deferred / tech debt" section).
- **No scheduled price-change mechanism** and **no CSV bulk import/export** anywhere in the codebase — these are wholly new capabilities, not gaps in an existing one.
- **"Sync with Inventory for live stock"** is **already fully built and running** — `stock_changed_consumer.py` consumes Inventory's `StockChanged` events and keeps `stock_state`/`available_from` current on each product row (MA-116 FR-5/FR-6, implemented as part of MA-48's own work). This line in the Jira description is already satisfied; nothing new needed here.

#### User Story Summary

An admin/operations user needs to create and maintain the product catalog itself (not stock levels, which is MA-48's territory): add new products, edit their identity/pricing/eligibility, retire discontinued ones, organize categories, and eventually bulk-manage the catalog via CSV and schedule future price changes.

#### User / Actor

- **Primary:** authenticated admin (Cognito admin pool, role-gated — built in MA-47).
- **Secondary (systems):** Catalog Service (MA-94/MA-116 — product/category system-of-record, currently read-only), Inventory Service (MA-48/MA-118/MA-119 — stock sync already wired, this story doesn't touch it), Pricing & Offer Service (MA-101/MA-122 — consumes `price_b2c` at quote time, doesn't store it).

#### Goal and Business Outcome

- **Admin goal:** stand up and maintain the product catalog without a developer manually editing seed data or running SQL — today's only way to change a price or add a product (confirmed empirically: `services/local-dev/_catalog_seed_data.py` + `seed_catalog_products.py`'s idempotent upsert is the *only* mechanism that exists).
- **Business outcome:** every other admin console screen built so far (Customer Accounts, Inventory) assumes products already exist and have correct prices; this story is the missing origin point for that data, not an independent feature.

#### Functional Intent (what, not how) — mapped against the Jira description's own FR list

| MA-42's ask | Already specified/built anywhere? | Gap |
|---|---|---|
| Create/edit products | **No** — zero write routes on Catalog | New: full admin CRUD API |
| Activate/deactivate products | **No** — no status column exists | New: schema + API + UI |
| Manage categories | **Partially** — `GET /categories` exists, read-only | New: admin CRUD for categories |
| Images | **Schema-ready, unpopulated** — `image_url` column exists, nothing sets it, no CDN/upload pipeline | A real upload path is new infrastructure (storage + CDN), distinct in size from the rest of this story |
| Units, descriptions, subscription eligibility | **Schema-ready** — all exist as columns, no write path | Covered by the same new CRUD API as pricing |
| Pricing tiers (B2C/B2B) | **Schema-ready, B2B unused by any caller** (MA-116's own Open Question Q2) | Covered by the same new CRUD API; B2B-aware callers remain out of scope (unchanged from MA-116) |
| Taxes/HSN | **No** — no field anywhere | New: schema + API + UI, same size as any other product field |
| Schedule price changes | **No** — no concept of a future-effective price anywhere | A materially separate capability (needs an effective-dating/scheduling mechanism, not just a form field) |
| Bulk import/export via CSV | **No** — nothing in the codebase | A materially separate capability (file parsing/validation, partial-failure handling) |
| Sync with Inventory for live stock | **Yes, already built** (MA-116 FR-5/FR-6's `StockChanged` consumer) | None — already satisfied, nothing for this story to do |

#### Initial Acceptance Criteria → spec-boundary mapping

| # | Acceptance criterion (draft, observable) | Likely spec owner |
|---|------------------------------------------|-------------------|
| AC-1 | An admin can create a new product with name, category, unit, description, B2C/B2B price, tax/HSN, veg/organic flags, subscription eligibility | New: Catalog admin-write API |
| AC-2 | An admin can edit any of the above fields on an existing product | Same new API |
| AC-3 | An admin can activate/deactivate a product (and inactive products are excluded from the consumer-facing catalog) | Same new API — needs a new schema field |
| AC-4 | An admin can create/edit/reorder categories | Same new API, categories side |
| AC-5 | An admin can see a list of all products (including inactive ones, unlike the consumer app) and open one to edit it | portal-ui, new Admin / Catalog screens |
| AC-6 | Every create/edit/activate/deactivate is attributable to an admin (audit trail) | Likely the same `inventory_audit_log`-style pattern MA-119 already established — Step 2/3 to confirm whether this reuses that shape or needs its own table |

#### In Scope (proposed)

- A new admin-write API on Catalog Service: create/edit products (all existing fields + new `is_active` + new tax/HSN fields), create/edit categories.
- Admin / Catalog screens in portal-ui: product list (including inactive), create/edit product form, category management, mirroring the Customer Accounts / Inventory screens' established RequireRole + React Query + MUI table pattern.
- An audit trail for catalog admin actions (exact shape — new table vs. reusing a pattern — a Step 2/3 decision).

#### Out of Scope (proposed)

- **Image upload/CDN pipeline** — a genuinely separate infrastructure concern (storage + CDN), not a form field. Proposed: this story keeps `image_url` as a plain text/URL field in the admin form (an admin pastes an already-hosted URL), same as the schema already supports; a real upload pipeline is flagged as explicit future work, not silently assumed.
- **Scheduled/future-effective price changes** — needs its own effective-dating design (closer in shape to Inventory's `available_from` batch scheduling than to a simple field edit). Flagged as a distinct future capability, not folded into this pass.
- **CSV bulk import/export** — file parsing, validation, and partial-failure handling is a materially separate capability from single-record CRUD. Flagged as future work.
- **B2B-aware pricing callers** — unchanged from MA-116's own still-unresolved Open Question Q2; this story makes `price_b2b` editable but doesn't make any caller use it.
- **Inventory stock sync** — already fully built (MA-116 FR-5/FR-6); nothing for this story to add.
- **Pricing & Offer Service changes** — MA-101/MA-122's territory; this story only changes where `price_b2c`/`price_b2b` come from (now admin-editable), not how `pricing-offer` consumes them.

#### Assumptions

- A1. The admin UI lives in portal-ui under the existing MA-47 RBAC console, same pattern as MA-39 (Customer Accounts) and MA-48 (Inventory) — not a new app.
- A2. "Activate/deactivate" means a new boolean/status field that the consumer-facing `GET /products`/`GET /search` endpoints must now filter on (an inactive product should stop appearing to the Flutter app) — this touches MA-116/MA-117's existing read endpoints, not just a new write path. Flagged explicitly since it's a real behavior change to already-shipped code, not assumed silently.
- A3. Tax/HSN is a flat `hsn_code` + `tax_rate` pair on the product row (matching how `price_b2c`/`price_b2b` are modeled today) — not a separate tax-rules engine. Nothing in the ticket or codebase suggests tax varies by anything other than the product itself (e.g. no per-state/per-zone tax logic exists anywhere).

#### Resolved decisions (human, this session — not open questions)

- **D1 (ownership).** Confirmed, not re-litigated: MA-94/Catalog's own README already names MA-42 as the owner of admin/write product-catalog capability, and MA-48's own analysis independently agreed. No discrepancy to resolve here (unlike MA-48's own Q1).
- **D2 (role gate).** Same precedent as MA-39/MA-48: **Ops + SuperAdmin**, matching `RequireRole(['Ops', 'SuperAdmin'])` already used for both existing admin-gated portal-ui screens and Inventory's own backend gate.

#### Impacted areas (Jira Components)

- **`services`** — Catalog Service (MA-94) gains a new admin-write API; a schema migration for `is_active`/`hsn_code`/`tax_rate`.
- **`portal-ui`** — new Admin / Catalog screens under the existing MA-47 console and RBAC.
- No `mobile-app` impact, beyond the consumer app's existing `GET /products`/`GET /search` now also respecting `is_active` (a filter addition, not a contract change for the mobile client).

---

*Next: Step 2 — Build Technical Context (confirm exact schema/API shape for the new admin-write endpoints, resolve the audit-trail question, ground A2's "inactive products disappear from consumer endpoints" behavior change against existing read-path code).*
