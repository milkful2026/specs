### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for **MA-48 — Inventory & Procurement Control · Admin / Inventory (Admin UI)**:

---

* **✓ Inventory Service — Admin Receive, Batch Detail & Stock List** — `services` (MA-95) · spec path `services/tasks/MA/MA-95/{KEY}.md`
  Three new endpoints, all behind the existing admin authorizer (Ops role, D4): `POST /inventory/receive` (goods receipt — new `stock_batches` row with a real expiry date, same single-transaction audit/lock pattern MA-119's adjustment already uses, publishes `StockChanged` as a third producer; D2); `GET /inventory/{productId}/batches` (batch-detail read, additive to MA-118's deliberately-aggregate-only product endpoint); `GET /inventory` (paginated list/summary across products with `stockState`, the full answer to D3's "reorder alerts = list view"). **Zero new tables** — every endpoint reads/writes schema MA-118/MA-119 already define. **Explicitly depends on MA-118 and MA-119 actually being implemented first** — this spec does not re-specify their content (per the resolved decomposition decision), only references them; implementation planning must size all of it as one continuous effort, not three independently-sequenced small tickets. One engineer / one sprint for this spec's own 3 endpoints, **on top of** whatever MA-118+MA-119 themselves take to implement.

* **✓ Portal-UI — Admin Inventory screens** — `portal-ui` (MA-20/Admin-UI) · spec path `portal-ui/tasks/MA/MA-20/{KEY}.md`
  New "Inventory" section under the existing MA-47/MA-128 console and RBAC (Ops, matching D4 — same role-gating mechanism as MA-39's Customer Accounts, `RequireRole roles={['Ops', 'SuperAdmin']}`). Product/stock list with low-stock/out-of-stock indicators (consumes the new `GET /inventory` list endpoint); per-product detail showing on-hand/reserved/available plus a batch table (consumes `GET /inventory/{productId}` + the new `/batches` endpoint); an adjustment dialog (reason required, consumes MA-119's `PATCH /inventory` once implemented); a goods-receipt dialog (quantity + expiry date, consumes the new `POST /inventory/receive`); an audit-trail view per product. Reuses MA-128/MA-141's established dialog/table/RBAC patterns — no new infra, same Vite + React + TS + MUI stack. One engineer / one sprint, **blocked on** the Inventory Service spec above actually shipping (nothing to call otherwise — same sequencing note MA-39's specs carried for their own cross-service dependencies).

---

* **⚠ MA-118 / MA-119 — explicitly not re-spec'd, referenced as a prerequisite**
  Per the resolved decomposition decision: these are separate, already-`SDD: Approved` Tasks under MA-95, not rewritten or duplicated here. **This is the single biggest risk to this story's own estimate** — if implementation planning treats MA-48 as "3 endpoints + a UI," it will badly undercount the actual work, which is "implement two already-designed-but-unbuilt specs (concurrency-safe reserve/commit/release, a TTL sweep, an audit log), then add 3 endpoints and a UI on top." Flagging prominently so the reviewer sizes this correctly, not assumes it away.

* **⚠ Catalog Service (MA-94) — explicitly excluded, verification-only**
  No code change. Its `StockChanged` consumer already exists, already tested (against a fake event) — the only new obligation is live verification once MA-118 ships a real producer, which belongs in the Inventory Service spec's own testing strategy (an integration/acceptance check), not a separate Catalog-side spec.

---

#### Notes for the reviewer

- **Two specs, with a load-bearing dependency on two others that already exist.** Unlike MA-39 (three self-contained specs, one decomposition), MA-48's real complexity is almost entirely in MA-118/MA-119, which this decomposition deliberately does not touch — please confirm you're comfortable treating "implement MA-118 + MA-119" as in-scope prerequisite work for this story's implementation plan, even though it's tracked under MA-95's Tasks, not MA-48's.
- **Zero-new-tables finding carries through to the decomposition** — the Inventory Service spec above is unusually light on schema for a backend spec, which is correct, not a gap: it's entirely riding on MA-118/MA-119's already-approved data model.
- **Role gate (D4, Ops) is settled**, unlike MA-39 where the exact role split was left as an open question — recorded here as a precedent for consistency, not re-litigated.
- **Accounting integration** (named in MA-48's own Jira "Key Dependencies") is **not** included in either spec — nothing in the codebase or in MA-118/MA-119 defines an accounting system to integrate with; flagged in Step 1 as likely aspirational, carried forward as excluded rather than silently dropped.

---

**To approve as-is (2 specs, MA-118/MA-119 referenced not re-spec'd):** transition MA-48 → `SDD: Drafting`.
**To modify:** post `SDD-DECOMPOSITION-FEEDBACK`, then transition → `SDD: Drafting`.
**To reject:** transition → `SDD: Building Context` and post `SDD-FEEDBACK`.
