# SDD Step 5 — Review Checklist

**Story:** MA-48 — Inventory & Procurement Control · Admin / Inventory (Admin UI)
**Specs reviewed (branch `spec/MA-48`):**
- `services/tasks/MA/MA-48/MA-150.md` — Inventory Service: Admin Receive, Batch Detail & Stock List
- `portal-ui/tasks/MA/MA-48/MA-151.md` — Admin Inventory Management

---

## Part 1 — Individual specification quality

### MA-150 — Inventory Service: Admin Receive, Batch Detail & Stock List

- [x] Solves the problem stated in MA-48 (goods receipt, batch visibility, stock list, audit-log read — the gaps MA-118/MA-119 don't cover)
- [x] All 13 sections present and complete
- [x] Functional requirements specific and unambiguous (4 endpoints, exact request/response shapes, validation rules, idempotency posture explicitly stated — including the deliberate non-idempotency of `receive()`)
- [x] NFRs defined with measurable targets (p95s, 100%-audit-coverage bar inherited from MA-119)
- [x] Acceptance criteria testable (§10 — unit, integration, contract, explicit live-verification requirement for Catalog's consumer, negative scenarios)
- [x] Edge cases and failure modes documented (§9 — 8 cases incl. concurrent-write races, zero-batches-but-known-product, non-idempotent-by-design repeats)
- [x] Testing strategy sufficient (offline pattern matching existing `inventory` service precedent, plus a flagged live-verification step for the Catalog integration)
- [x] Scope boundaries clearly stated (§3 — MA-118/MA-119's write-side explicitly not redefined, only their missing audit-read path added)
- [x] Assumptions and risks explicit (§11 — non-idempotent `receive()`, no product-name search, inherited authorizer-ARN gap)
- [x] Hand-off ready without verbal explanation

### MA-151 — Admin Inventory Management

- [x] Solves the problem (full admin visibility and control over stock, matching MA-48's "admin oversight" ask)
- [x] All 13 sections present; UI-specific coverage included (component map inherited from shipped MA-128/MA-141 patterns, all UI states, exact selectors, a11y inherited)
- [x] Functional requirements specific and unambiguous (exact dialogs, two-distinct-error-message requirement for the two floor-check failure modes, FIFO-ordered batch table)
- [x] NFRs defined with measurable targets (load time, server-side filtering from day one with explicit rationale vs. MA-128's original client-side choice)
- [x] Acceptance criteria testable (§10 — three Playwright scenarios with concrete selectors)
- [x] Edge cases and failure modes documented (§9 — 6 cases incl. the two-distinct-floor-check-messages requirement, concurrent-edit non-optimistic UI)
- [x] Testing strategy sufficient (unit + integration against MA-150 DTOs + E2E, matching the established convention)
- [x] Scope boundaries clearly stated (§3 — backend, reservation UI, Catalog admin, notification pipeline all explicitly out)
- [x] Assumptions and risks explicit (§11 — no product-name display, server-side-filtering choice, two-dialogs-not-one design call)
- [x] Hand-off ready without verbal explanation

---

## Part 2 — Cross-specification coherence

- [x] **Consistent terminology and definitions** — `onHand`/`reserved`/`available`/`stockState`, `StockChanged`, `/v1/inventory*` endpoint style, `goods_receipt` reason-prefix convention — used identically across both specs.
- [x] **No conflicts or contradictions** — MA-151's DTOs (§7) match MA-150's endpoint definitions (§4) field-for-field, including the audit-log shape added during drafting (see finding below).
- [x] **Data models align without collision** — both specs explicitly declare zero new tables, riding entirely on MA-118/MA-119's existing schema; no competing data-ownership claims.
- [x] **Inter-spec dependencies identified** — MA-151 → MA-150 (HTTP, all 5 endpoints including the aggregate `GET /inventory/{productId}` MA-118 itself owns) + MA-119 (`PATCH /inventory`, once implemented); both specs → MA-118/MA-119 as a shared hard prerequisite, stated identically in both (not just one).
- [x] **No required behavior silently uncovered** — every element of MA-48's Jira description maps to an owner: manual adjustment → MA-119 (write) + MA-151 FR-4 (UI); batch/expiry → MA-150 FR-2 + MA-151 FR-3; reorder alerts → MA-150 FR-3 + MA-151 FR-2; wastage/spoilage → MA-119's reason field + MA-151 FR-4; stock reconciliation → the same adjustment path; goods receipt → MA-150 FR-1 + MA-151 FR-5; audit trail → MA-150 FR-4 (new, added during drafting) + MA-151 FR-3.
- [x] **Combined specs fully satisfy the User Story** — an Ops admin can see what needs attention, correct drift, receive new stock with real batch/expiry identity, and see a full audit trail — all without any new tables, riding entirely on already-approved schema.
- [x] **No overlapping responsibilities causing ambiguity** — MA-150 owns all backend logic and the `StockChanged`/audit contracts (single-homed); MA-151 owns only presentation. MA-118/MA-119's own scope is referenced, never redefined, by either spec.
- [x] **NFRs consistent** — the "server-side, not client-side, filtering from day one" framing in MA-151 is justified by citing MA-150's own `GET /inventory` filter support directly, not asserted independently; the audit/observability bar (100% coverage, structured logs) is stated the same way in both.
- [x] **Testing strategies form a coherent overall test plan** — MA-150's flagged live-Catalog-verification step and MA-151's E2E goods-receipt scenario are two ends of the same acceptance gate (a receipt flows through to a visible `StockChanged`-driven state change), not duplicated effort.
- [x] **Implementation planning can begin without major ambiguity** — both specs state the same hard prerequisite (MA-118+MA-119) identically, so there's no risk of one being read as independently shippable. The open items (product-name search/display, exact role split) are enumerated per spec §12 and are implementation-review calls, not blockers.

---

## Review finding (found and fixed during this drafting pass)

| # | File(s) | Finding | Resolution |
|---|---------|---------|------------|
| 1 | MA-150, MA-151 | Neither spec defined a way to actually *read* the audit log — MA-119 explicitly states it builds no read API ("that's the admin console's responsibility"), and the original MA-150 draft (3 endpoints: receive/batches/list) didn't pick that responsibility up, leaving MA-151's FR-3 audit-trail view with nothing to call. Caught while drafting MA-151, before either spec was finalized. | Added MA-150 FR-4 (`GET /inventory/{productId}/audit-log`), updated MA-150's endpoint count (3→4) consistently throughout (§1, §3, §5, §6, §9, §10), and updated MA-151 §3/§4/§6/§12/§13 to reference it directly instead of leaving it as an open question. |

No other discrepancies found between the two specs' contracts, terminology, or scope boundaries.

## Verdict

**PASS** — all individual-quality and cross-specification coherence checks are satisfied; the one finding from this drafting pass (a genuine missing capability, not just a naming mismatch) was resolved in both specs before this review concluded, not carried forward as a gap.

### Decision records / follow-up actions (carried, not blocking)

1. **Role-gate exact split** — both specs propose Ops + SuperAdmin uniformly (D4 settled Ops as a floor; whether SuperAdmin should also always be included, or whether any action should be SuperAdmin-only, is not re-litigated here) — same open-question class MA-39 carried, not a new one.
2. **Product-name search/display** — MA-150 §11/§12 and MA-151 §11/§12 both flag that Inventory doesn't own product names and this spec doesn't solve cross-referencing against Catalog; the UI shows raw `productId` for v1. A real, acknowledged usability gap, not a silent omission.
3. **`receive()`'s deliberate non-idempotency** (MA-150 §11 Risk 1) — a considered design choice (no natural retry-correlation key, repeated calls represent repeated real deliveries), flagged for architect confirmation rather than asserted as obviously correct.
4. **MA-118/MA-119 implementation sizing** — the single biggest risk to this story's own estimate, stated identically and prominently in both specs' own opening sections (not buried) and in the Step 3 decomposition proposal: this is "two unbuilt approved specs + 4 endpoints + a UI," not "4 endpoints + a UI."
