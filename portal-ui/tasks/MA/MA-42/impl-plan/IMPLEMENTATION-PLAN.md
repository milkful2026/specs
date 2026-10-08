# Implementation Plan — MA-42: Admin Catalog Management (MA-157)

## 1. Overview

**Story:** [MA-42](https://milkfuldairyindia.atlassian.net/browse/MA-42) — Product & Catalog Management
**Date:** 2026-10-08
**Author:** Claude Code (session), implementing the merged MA-157 spec

**Spec implemented:**

| Spec | Area | Status |
|------|------|--------|
| Admin Catalog Management (MA-157) | `portal-ui` | `SDD: Approved`, unimplemented |

**What this delivers:** a "Catalog" section in the admin console — product list (incl. inactive), a create-product page, a per-product edit/detail view with an audit trail, and category management — gated to Ops + SuperAdmin.

**Path note:** single-area story for this plan (`portal-ui` only) — lives at `portal-ui/tasks/MA/MA-42/impl-plan/`, same convention as MA-48's own split (`services/tasks/MA/MA-48/impl-plan/` + `portal-ui/tasks/MA/MA-48/impl-plan/`).

**Hard blocker, stated plainly:** this plan has nothing to build against until `services/tasks/MA/MA-42/impl-plan/IMPLEMENTATION-PLAN.md` (MA-156) is implemented and deployed to local-dev. Do not start FR-2 through FR-5 below until `GET /admin/products` etc. return real data locally — confirm with a direct curl check first, same discipline MA-151's own plan used for MA-150.

## 2. Prerequisites

**Confirmed by reading `portal-ui` directly:**

| Assumption (from MA-157) | Verified against real code |
|---|---|
| The just-shipped Inventory screens are the closer structural template than Admin Users/Customer Accounts | **Confirmed** — `src/pages/inventory/` (`InventoryListPage.tsx`, `InventoryDetailPage.tsx`, `hooks.ts`, dialog components) matches this spec's list→detail→dialog shape almost exactly; copy its file organization, not Customer Accounts'. |
| `RequireRole roles={['Ops', 'SuperAdmin']}` is the correct, already-used gate | **Confirmed** — `src/App.tsx`'s `/inventory` routes use this exact call; `/catalog` routes should mirror it verbatim. |
| `formatDate`/`formatDateTime` are already factored into a shared util | **Confirmed** — `src/utils/formatters.ts`, used by both `CustomerDetailPage` and `InventoryDetailPage`. Reuse directly, don't re-derive. |
| `AdminAnalyticsAction` is meant to be extended per-feature | **Confirmed** — `src/utils/analytics.ts`'s union already grew for `customer_account.*` (MA-141) and `inventory.*` (MA-151); extend again for `catalog.*`, same pattern. |
| MA-156's response field names/paths are exactly as MA-157 §7 documents | **Caveat, not yet independently re-verified against running code** — MA-151's own plan found and fixed two real frontend/backend field-name mismatches (`batches`→`items`, `entries`→`items`) *after* implementation, against the real backend, not before. **Step 1 below must re-confirm MA-156's actual response shapes against the running local-dev service before writing any DTO/type code** — do not trust the spec's JSON examples as the final word; this project has been burned by this exact gap twice already (MA-151's own post-implementation bugs). |

**No surprises found beyond the one flagged above** — MA-156 and MA-157 were drafted together in this session and cross-checked for path/field consistency during the `/code-review` pass before merge (5 findings fixed, including path-prefix and DTO-field mismatches caught *before* implementation this time, unlike MA-151's).

## 3. Implementation Order

1. **Confirm MA-156's endpoints are live locally** (the hard blocker, §1) — `curl localhost:8003/admin/products` (Catalog's local port, no `/v1` prefix — confirmed in MA-156's own implementation plan §2) with a valid admin token returns real data. **Then independently re-verify every response field name against this real output**, not against MA-157 §7's JSON examples alone (§2 caveat above) — write the actual TypeScript types from the real response, cross-checking the spec's examples rather than trusting them blindly.
2. **API types + client functions** (`src/api/types.ts`, `src/api/client.ts`) — `CatalogProduct`/`CatalogCategory`/`ListAdminProductsResponseData` types; `catalogApi.listAdmin/create/update/listCategories/createCategory/updateCategory` functions, mirroring `inventoryApi`'s exact shape (`src/api/client.ts`'s existing `inventoryApi` object).
3. **MSW mocks** (`src/mocks/handlers.ts`, `src/mocks/db.ts`) — seed realistic products (mix of active/inactive, with/without `priceB2b`/`hsnCode`/`taxRate`/`tag`) and categories. **Must enforce the same real validation MA-156 defines** (positive price, required name/unit, unknown-category 404) — this repo has repeatedly shipped a mock that was too permissive and let a real bug through (MA-39's two review rounds, flagged again in MA-151's own plan); don't repeat it a fourth time.
4. **`CatalogListPage`** (FR-2) — table incl. inactive products (visually de-emphasized, not hidden), category + active-status filters, mirrors `InventoryListPage`'s structure.
5. **Create-product page** (FR-3) — dedicated route (`/catalog/new` or similar), not a dialog, per the spec's own recommendation (§11) given the field count (11 fields incl. the newly-added `tag`). Client-side validation mirrors `src/utils/inventoryValidation.ts`'s existing pattern — add a sibling `catalogValidation.ts`, don't bolt onto the inventory-specific file.
6. **`CatalogDetailPage`** (FR-4) — every field from the create form, editable, plus an Active toggle (with a confirm step before deactivating, mirroring `DeactivateDialog.tsx`) and an audit-trail table reusing `InventoryDetailPage`'s exact table shape, including its "Showing the most recent N of {total} entries" truncation handling if MA-156's audit-log read endpoint paginates the same way (**confirm this against MA-156's actual implementation, not assumed** — MA-156 §4 FR-3 doesn't define a category audit log at all, and the spec's own FR-4 doesn't fully pin down whether `catalog_audit_log` has a dedicated read endpoint or is read some other way; resolve this against the real MA-156 implementation before building this table, not against the spec prose alone).
7. **Category management screen** (FR-5) — list + create/edit form dialog, mirrors `AdminFormDialog.tsx`'s shape.
8. **Navigation + routing** (FR-1) — nav item, `RequireRole` route gating, `/catalog`, `/catalog/new`, `/catalog/{productId}` routes in `App.tsx`.
9. **E2E tests** — the three scenarios in MA-157 §10 at minimum (create product, deactivate requires confirmation + hides from public catalog, non-Ops/SuperAdmin access denial).

## 4. Key Design Decisions to Carry Into Implementation (not re-litigate)

- **Dedicated page for create-product, not a dialog** (MA-157 §4 FR-3/§11) — a recommendation, not a hard mandate; a dialog is acceptable if it proves workable, but don't default to one without considering the field count first.
- **Server-side filtering from day one** (MA-157 §5), matching MA-151's own precedent — `GET /admin/products` already supports `categoryId`/`isActive` filters server-side.
- **No audit view for categories** (MA-157 §5 FR-5) — matches MA-156's own backend scope line; don't build UI for data that doesn't exist.
- **Deactivation requires an explicit confirm step** (MA-157 §4 FR-4) — it's customer-visible, not a casual toggle; don't skip the confirm dialog for "simplicity."

## 5. Testing Strategy

- Unit: create-product form validation (required fields, positive price), mirroring `inventoryValidation.test.ts`'s existing pattern.
- Integration: mocked against MA-156's **actually-verified** DTOs (§3 step 1 — not MA-157 §7's examples taken on faith).
- E2E: the three MA-157 §10 scenarios, run against mocks per this repo's standard `npm run dev` default, **and once more manually against the real backend** (`VITE_USE_MOCKS=false`) before declaring this done — MA-151's own implementation shipped two real field-name bugs that only a real-backend check caught (`batches`/`entries` vs. `items`); this spec already fixed its own equivalent mismatches at review time (`/v1` prefix, `tag` field, DTO omissions), but a fresh real-backend pass is still mandatory, not optional, since review catches documentation bugs, not implementation bugs.

## 6. Acceptance Check

- `npx tsc -b`, `npx vitest run`, `npx playwright test` all pass.
- A manual walkthrough against the real local-dev backend (after `services/tasks/MA/MA-42/impl-plan/IMPLEMENTATION-PLAN.md` is complete): log in as an Ops or SuperAdmin admin, create a product, confirm it's visible, edit it, deactivate it, confirm it disappears from the default list filter but its detail page still loads, manage a category — before declaring this done.
