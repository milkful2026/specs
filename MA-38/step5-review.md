### SDD Step 5 — Review Checklist

**Story:** MA-38 — Invoice Generation (GST, Discounts, Offers)
**Specs reviewed:**
- [MA-158](https://milkfuldairyindia.atlassian.net/browse/MA-158) — Pricing: per-product GST and per-line breakdown
- [MA-159](https://milkfuldairyindia.atlassian.net/browse/MA-159) — Order: bill snapshot and billing address (+ User)
- [MA-160](https://milkfuldairyindia.atlassian.net/browse/MA-160) — Invoice Service (new): generation, numbering, PDF, API
- [MA-161](https://milkfuldairyindia.atlassian.net/browse/MA-161) — Mobile: Bill Details and Download Invoice

#### Part 1 — Individual specification quality

| Check | MA-158 | MA-159 | MA-160 | MA-161 |
|---|---|---|---|---|
| Solves the problem stated in the User Story | ✅ | ✅ | ✅ | ✅ |
| All 13 sections present and complete | ✅ | ✅ | ✅ | ✅ |
| Functional requirements specific and unambiguous | ✅ | ✅ | ✅ | ✅ |
| NFRs defined with measurable targets | ✅ | ✅ (p95 300 ms) | ✅ (10k/10 min, p95 150 ms) | ✅ |
| Acceptance criteria testable | ✅ | ✅ | ✅ (AC-4 to AC-7 mapped) | ✅ (AC-8, AC-9) |
| Edge cases and failure modes documented | ✅ | ✅ | ✅ | ✅ |
| Testing strategy sufficient | ✅ | ✅ | ✅ (incl. concurrency test) | ✅ (widget scenarios + integration) |
| Scope boundaries clearly stated | ✅ | ✅ | ✅ | ✅ |
| Assumptions and risks explicit | ✅ | ✅ | ✅ | ✅ |
| Hand-off ready without verbal explanation | ✅ | ✅ | ✅ | ✅ |

#### Part 2 — Cross-specification coherence

- [x] **Consistent terminology.** "Taxes & Fees" = product-line GST only (the delivery fee's GST sits inside the fee). The same in MA-158 FR-5, MA-159 FR-6 and MA-161 FR-2.
- [x] **No conflicts.** Prices are tax-exclusive and the delivery fee is GST-inclusive, everywhere. This corrects Step 1 A7, noted in MA-158 §13.
- [x] **Data models align.**
  - MA-158's `lines`/`deliveryFeeLine` field names are stored by MA-159 FR-5.
  - They are re-exposed in MA-159 FR-7 and consumed by MA-160 FR-2 unchanged.
  - Paise integers throughout.
- [x] **Inter-spec dependencies identified.** MA-158 → MA-159 → MA-160 → MA-161 (Bill Details needs only MA-159). Each spec degrades safely if its upstream is missing:
  - MA-159 has a no-snapshot fallback.
  - MA-160 skips orders as `NO_BREAKDOWN`.
  - MA-161 shows "Invoice available after delivery".
- [x] **No required behaviour uncovered.** The ticket's asks map as follows:
  - **GST invoice per order:** MA-160.
  - **HSN:** MA-158 and MA-160.
  - **CGST/SGST/IGST:** MA-158.
  - **Discounts and offers:** columns present and populated from the snapshot; 0 until an offers engine exists (out of scope, documented).
  - **Wallet used:** "Paid via Milkful Wallet" on the PDF.
  - **Sequential numbering:** MA-160 FR-3.
  - **PDF download and share:** MA-160 FR-4/FR-5 and MA-161.
  - **Accounting feed:** `InvoiceGenerated` plus the invoice tables.
  - **Billing summary on Order Details:** MA-161.
  - **Daily cron:** MA-160 FR-1.
- [x] **Combined specs satisfy the User Story** as resolved in D1–D6.
- [x] **No overlapping responsibilities.** Pricing computes, Order snapshots, Invoice issues and renders, Mobile displays.
- [x] **NFRs consistent.** PII (billing address) is held only by Order and Invoice, never logged, and not in events.
- [x] **Test strategies form a coherent plan.** Unit tests per service, a contract snapshot (MA-158), the local-dev end-to-end chain (create order → run invoices → app download).
- [x] **Implementation planning can begin.** Open questions are Finance values only (seller details, fee SAC/rate and inclusivity, production HSN/rates); all are config-driven and none block the build.

**Fix applied during review:** MA-160 FR-2's per-line invariant now states the delivery-fee form explicitly (`… == grossPaise`).

**Result: all four specs pass.** Opening the PR.
