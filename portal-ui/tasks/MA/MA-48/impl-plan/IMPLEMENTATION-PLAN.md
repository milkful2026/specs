# Implementation Plan — MA-48: Admin Inventory Management (MA-151)

## 1. Overview

**Story:** [MA-48](https://milkfuldairyindia.atlassian.net/browse/MA-48) — Inventory & Procurement Control
**Date:** 2026-10-03
**Author:** Claude Code (session), implementing the merged MA-151 spec

**Spec implemented:**

| Spec | Area | Status |
|------|------|--------|
| Admin Inventory Management (MA-151) | `portal-ui` | `SDD: Approved`, unimplemented |

**What this delivers:** an "Inventory" section in the admin console — product/stock list with low-stock filtering, per-product detail with a batch table and audit trail, an adjust-stock dialog, and a goods-receipt dialog — gated to Ops.

**Path note:** single-area story (`portal-ui` only) — lives at `portal-ui/tasks/MA/MA-48/impl-plan/`, same convention as MA-39's own work (which skipped a formal plan) and MA-96's (`services/tasks/MA/MA-96/impl-plan/`).

**Hard blocker, stated plainly:** this plan has nothing to build against until `services/tasks/MA/MA-48/impl-plan/IMPLEMENTATION-PLAN.md` (MA-118+MA-119+MA-150) is actually implemented and deployed to local-dev. Do not start FR-2 through FR-5 below until `GET /v1/inventory` etc. return real data locally — confirm with a direct curl check first, the same discipline this repo used throughout MA-39.

## 2. Prerequisites

**Confirmed by reading `portal-ui` directly:**

| Assumption (from MA-151) | Verified against real code |
|---|---|
| MUI, React Query, `notistack`, `RequireRole` are the established patterns | **Confirmed** — `src/pages/customer-accounts/` (MA-141, shipped) is the direct structural template: `hooks.ts`, a status-badge component, a dialog-per-action pattern, a dedicated detail route. |
| `CustomerAccountsPage`'s role-gate (`RequireRole roles={['Ops', 'SuperAdmin']}`) is a real, reusable pattern | **Confirmed** — `src/routes/guards.tsx`'s `RequireRole` takes a `roles` array; the Inventory routes use the identical call, just a different screen. |
| `CustomerDetailPage`'s routing choice (dedicated route, not a drawer) is the established precedent for a detail view | **Confirmed**, and MA-151 §6 already cites this precedent explicitly — `InventoryDetailPage` follows the same shape, not re-litigated. |
| `logAdminAnalyticsEvent`'s action-type union is meant to be extended per-feature | **Confirmed** — MA-141 already did this for `customer_account.*`; this plan extends it again for `inventory.*`, same pattern, not a new logging mechanism. |

**No surprises found** — unlike MA-96's cart plan (which found contract mismatches between specs drafted in the same pass), MA-150 and MA-151 were drafted together in this session and already cross-checked for DTO consistency during Step 5 (see `specs/MA-48/step5-review.md`). The one gap that review found (no audit-log read endpoint) was fixed in both specs before this plan was written — nothing left to reconcile here.

## 3. Implementation Order

1. **Confirm MA-150's endpoints are live locally** (the hard blocker, §1) — `curl localhost:8000/v1/inventory` (or whatever port `services/inventory` runs on locally) with a valid admin token returns real data, not a 404. Do not proceed past this check.
2. **API types + client functions** (`src/api/types.ts`, `src/api/client.ts`) — `InventoryItem`, `StockBatch`, `InventoryAuditLogEntry` types; `inventoryApi.list/getDetail/getBatches/getAuditLog/adjust/receive` functions, mirroring `customerAccountsApi`'s exact shape.
3. **MSW mocks** (`src/mocks/handlers.ts`, `src/mocks/db.ts`) — seed realistic products with a mix of `IN_STOCK`/`OUT_OF_STOCK`/`AVAILABLE_FROM` states and batch/audit history, so the UI is demoable and testable before the real backend is fully wired end-to-end. **Must enforce the same real validation MA-150 defines** (floor-at-zero on both `on_hand` and `available`, future-expiry-date requirement on receive) — this repo has twice now (MA-39's two review rounds) shipped a mock that was too permissive and let a real bug through; don't repeat it a third time.
4. **`InventoryListPage`** (FR-2) — table, stock-state filter, mirrors `CustomerAccountsPage`'s structure.
5. **`InventoryDetailPage`** (FR-3) — aggregate numbers + batch table + audit-trail table, mirrors `CustomerDetailPage`'s structure.
6. **`AdjustStockDialog`** (FR-4) — including the two-distinct-error-message requirement (MA-151 §4/§9) for the `on_hand`-floor vs. `available`-floor rejection cases; this is a real, spec'd UX requirement, not optional polish.
7. **`ReceiveStockDialog`** (FR-5) — quantity + required future-date expiry validation, mirroring `CustomerStatusDialog`'s Suspend-dialog date-validation pattern.
8. **Navigation + routing** (FR-1) — nav item, `RequireRole` route gating, `/inventory` and `/inventory/{productId}` routes in `App.tsx`.
9. **E2E tests** — the three scenarios in MA-151 §10 at minimum (goods receipt, non-Ops access denial, the two-distinct-floor-check-messages scenario), following this repo's established "prove the test actually catches the bug" discipline (temporarily revert the fix, confirm the test fails, restore, confirm it passes) for at least the floor-check-message scenario, since that's the one genuinely new piece of UI logic in this story (not a copy of an existing pattern).

## 4. Key Design Decisions to Carry Into Implementation (not re-litigate)

- **Two separate dialogs (Adjust vs. Receive), not one combined dialog** (MA-151 §11) — a deliberate choice mirroring MA-150's own backend design (a receipt is categorically different from a correction).
- **Server-side filtering from day one** (MA-151 §5), not client-side-first like MA-128's original choice — `GET /inventory` already supports it server-side.
- **Raw `productId` display, no product-name cross-reference** (MA-151 §11/§12 Q2) — a known, accepted v1 gap, not something to silently work around with a client-side Catalog call (which would violate the database-per-service boundary MA-150 itself respects).

## 5. Testing Strategy

- Unit: form validation (future-date expiry, positive-quantity, required reason), the two distinct floor-check error messages.
- Integration: mocked against MA-150's DTOs (§7 of MA-151).
- E2E: the three MA-151 §10 scenarios, run against mocks per this repo's standard `npm run dev` default, **and once more manually against the real backend** (`VITE_USE_MOCKS=false`) before declaring this done — the established local-dev verification discipline from MA-39 found two real bugs (a proxy-routing gap, a field-name mismatch) that no mocked test could have caught, specifically because the mock agreed with the frontend's own (wrong) assumptions. Don't skip this step.

## 6. Acceptance Check

- `npx tsc -b`, `npx vitest run`, `npx playwright test` all pass.
- A manual walkthrough against the real local-dev backend (after `services/tasks/MA/MA-48/impl-plan/IMPLEMENTATION-PLAN.md` is complete): log in as an Ops admin, view the inventory list, drill into a product, adjust it, receive stock, confirm the audit trail shows both actions — before declaring this done.
