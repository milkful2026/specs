### SDD Step 1 — Analysis

**Story:** MA-38 — Invoice Generation (GST, Discounts, Offers) · Billing / Invoice (Flutter)
**Status:** SDD: Analyzing
**Sources:** Jira description (NSMB App Feature Spec, epic MA-18/MA-19); attachments `CountryDelight_09-08-2026.pdf` (reference tax invoice) and `image-20261125-170046.png` (Order Details mock with **Bill Details** and **Download Invoice**). Blocked-by links: MA-101 (Pricing & Offer — Impl:Done, scoped-down build), MA-99 (Payment Service — SDD: Pending). No Jira Components set on the ticket — areas inferred below.

---

#### User Story Summary

Every Milkful delivery must produce a **GST-compliant tax invoice**. After each day's deliveries, the platform generates one invoice per order: line items with HSN codes, quantity, MRP, discount, taxable value, CGST/SGST or IGST, delivery fee and invoice total, under a sequential invoice number. In the mobile app, the customer sees a **Bill Details** breakdown on the Order Details screen and can **Download Invoice** as a PDF and share it.

#### User / Actor

- **Primary:** authenticated Milkful customer (Cognito consumer pool) viewing a past or today's order in the Flutter app.
- **System actor:** a daily scheduled job that generates invoices after delivery slots end.
- **Secondary (systems):** Catalog (HSN and GST rate per product), Pricing (tax computation), Order (per-line price and tax snapshot, order source of truth), User (billing and shipping address, place of supply).
- **Downstream (later):** Accounting and Reporting (MA-104) consume invoice data for reconciliation.

#### Goal and Business Outcome

- **Customer goal:** see exactly what was charged for an order, and get a valid tax invoice for it.
- **Business outcome:** GST compliance (a tax invoice or bill of supply for every taxable supply), correct tax on each product (fresh milk at 0%, not the current flat 5%), and a sequential, auditable invoice record that finance can reconcile.

#### Ground truth today (from the repo, not the ticket)

- **Orders store only a grand total.** `orders.amount_paise` holds the total. `order_items` holds `product_id` and `quantity` but **no unit price, discount, tax or delivery fee**, so neither the Bill Details card nor an invoice can be built from existing order data.
- **Orders have no address snapshot.** There is no billing or shipping address or delivery state on an order, so Place of Supply and Bill To / Ship To have no reliable source.
- **Pricing (MA-101) is a scoped-down build.** It applies a flat `PRICING_DEFAULT_TAX_RATE_PERCENT` (5%) and a flat ₹20 delivery fee, and has **no CGST/SGST/IGST split** and **no Offers system** (`discountAmount` and `appliedOfferId` are always null). Its README explicitly defers the tax split to MA-38.
- **Catalog has no `hsnCode` or `gstRatePercent`.** The full MA-122 spec designed these fields, but they were not built.
- **No "Delivered" state exists.** Orders stop at `CONFIRMED` (paid). The Delivery Service (MA-102) is not built.
- **No notification channel exists.** There is no Notification Service (MA-103), no email/SES sender and no push in the app, and `users.email` is optional.
- **The mobile screen is ready.** `OrderDetailScreen` (MA-146/MA-152/MA-155) explicitly leaves Download Invoice to MA-38. The app has no PDF, share or file packages yet.
- **Subscriptions are open-ended.** There is no end date or billing period; each delivery is charged to the wallet when its order is created.

#### Functional Intent (what, not how)

1. Each day, after the last delivery slot, generate exactly **one invoice for every order confirmed for that day's delivery** (subscription and one-time checkout orders alike).
2. The invoice follows the reference layout:
   - **Header:** seller name, CIN, registered and GST addresses, GSTIN, FSSAI number, title "TAX INVOICE/BILL OF SUPPLY", invoice number, date, Place of Supply, Bill To and Ship To.
   - **Lines:** SR, item, HSN, qty, MRP, Disc %, taxable amount, CGST/SGST/IGST/Cess rates and amounts, line total, with the **delivery fee as its own line** (service code and rate).
   - **Totals:** item total and invoice value.
   - **Footer:** the reverse-charge declaration and the IT Act e-invoice notice.
3. Each product line carries its real HSN code and GST rate. Intra-state supply splits tax into CGST and SGST; inter-state supply uses IGST.
4. Invoice numbers are sequential, unique per financial year, at most 16 characters, from a single Milkful entity (e.g. `MF/26-27/000123`).
5. Prices, discounts and tax on the invoice are exactly what the order was charged, snapshotted at order time and never recomputed.
6. Order Details shows a **Bill Details** card (Item Total, Delivery Fee, Taxes & Fees, Grand Total) and a **Download Invoice** row that opens the PDF, which the customer can save or share.
7. An invoice is immutable once issued. Re-running the job never creates a duplicate.

#### Initial Acceptance Criteria → spec-boundary mapping

| # | Acceptance criterion (draft, observable) | Likely spec owner |
|---|------------------------------------------|-------------------|
| AC-1 | A product's HSN code and GST rate are stored in Catalog; milk (HSN 0401) is 0%, and a quote for it shows no tax. | Catalog + Pricing |
| AC-2 | A quote returns per-line taxable value and tax, plus the CGST/SGST vs IGST split based on the delivery state. | Pricing |
| AC-3 | A newly created order stores, per line: unit price (MRP), discount, taxable value, tax rate, tax amounts and HSN. It also stores the delivery fee and its tax, and a snapshot of the delivery address. | Order |
| AC-4 | After the daily job runs, every CONFIRMED order with today's delivery date has exactly one invoice; a second run creates none. | Invoice (new) |
| AC-5 | Invoice numbers are sequential with no gaps or duplicates within a financial year, and at most 16 characters. | Invoice (new) |
| AC-6 | The invoice PDF matches the reference layout, and its line totals equal the order's charged total to the paisa. | Invoice (new) |
| AC-7 | `GET` on the order's invoice returns the PDF (or a short-lived download link) only to the order's owner; any other user gets 404. | Invoice (new) |
| AC-8 | Order Details shows Bill Details for orders with a breakdown. Download Invoice opens or shares the PDF when the invoice exists. Before then it reads "Invoice available after delivery", and for cancelled or failed orders it is hidden. | Mobile |
| AC-9 | Orders created before this change (no breakdown) show the existing screen with no Bill Details and no Download Invoice, with no crash or ₹0 rows. | Mobile + Order |

#### In Scope (proposed)

- Per-product `hsnCode` and `gstRatePercent` in Catalog (data and API), with seed values.
- Pricing: per-line tax from the product's rate, CGST/SGST vs IGST split, and delivery fee taxed as a service line.
- Order: per-line price and tax snapshot, plus delivery address and state snapshot, at order creation (both subscription and checkout paths).
- A new invoice capability: daily generation job, sequential numbering, PDF rendering and storage, customer-facing read API.
- Mobile: Bill Details card, Download Invoice row, PDF open and share, and every UI state.

#### Out of Scope (proposed)

- **Sending invoices by email, SMS, WhatsApp or push (D4).** Invoices are in-app only until the Notification Service (MA-103) exists.
- **Period or monthly statements (D2).** Superseded by the daily per-order invoice.
- **The Offers engine itself** (MA-101 full build / MA-45 admin). The invoice has Disc % and offer columns and fills them from the order snapshot; they show 0 until offers exist.
- **Accounting-system integration.** MA-38 only emits an `InvoiceGenerated` event and keeps queryable invoice records; the feed to an accounting system or Reporting (MA-104) is a follow-up.
- **Credit notes and invoice cancellation.** A customer can only cancel before the cut-off, which is before invoicing, so no credit note is needed in v1.
- **Backfill of invoices for historical orders** (they lack the price and tax snapshot).
- **Admin invoice viewer or regeneration in portal-ui.**
- **Delivery-confirmed invoicing.** This waits for the Delivery Service (MA-102).

#### Assumptions

- A1. Milkful is one legal entity with one GSTIN. Seller details (name, CIN, GSTIN, FSSAI number, registered and GST addresses) are configuration, and **finance supplies the real values before go-live**.
- A2. The delivery fee is invoiced as a service line, SAC 996813 at 18% (configurable). **Finance must confirm the code and rate.**
- A3. Place of Supply is the state of the delivery address snapshotted on the order. It is compared with the seller's GST state to choose CGST+SGST or IGST.
- A4. Wallet-paid orders show the payment as "Paid via Milkful Wallet". Wallet use is a payment method, not a discount, so it does not reduce the taxable value.
- A5. Amounts are stored in paise (integer), rounded half-up per line, and line totals must sum exactly to the order's `amount_paise`.
- A6. An invoice is generated only for `CONFIRMED` orders. `CANCELLED`, `PAYMENT_FAILED`, `FAILED` and `NEEDS_ATTENTION` orders get none.
- A7. Displayed prices are tax-inclusive (MRP), and taxable value is derived by back-calculating tax, as in the reference invoice.

#### Resolved decisions (human, this session — not open questions)

- **D1 (Q1).** Every confirmed order gets its own GST invoice; it is what Download Invoice opens.
- **D2 (Q2).** Invoices are generated **after each day's delivery, every day**. There is no subscription-period or monthly statement, and subscriptions keep no end date.
- **D3 (Q3).** The trigger is a **daily scheduled job after the last delivery slot**, which invoices every `CONFIRMED` order with today's delivery date. When MA-102 ships, it switches to `DELIVERED` orders.
- **D4 (Q4).** Delivery is **in-app only for now**: download and share from Order Details. Outbound sending is deferred to MA-103.
- **D5 (Q5).** Tax data **lives in Catalog and flows through Pricing**. Order snapshots per-line price and tax at order time, following the full MA-122 design.
- **D6 (Q6).** **One entity, one invoice per order.** Products and the delivery fee are lines on the same invoice; numbering is sequential per financial year, ≤16 characters.

#### Items to settle in Step 2–3 (proposed resolutions — none blocks decomposition)

- **Owning service for invoices.** No Invoice/Billing service exists among the 13. Two options: a new `invoice` service (Lambda job plus S3 for PDFs plus Aurora `invoices`), or a module in Order. Proposal: a new service, because invoices have their own lifecycle, numbering and storage.
- **PDF rendering and storage.** Proposal: render server-side when the invoice is generated, store it in a private S3 bucket, and serve it through a short-lived pre-signed URL, so the app only downloads and opens a file.
- **Gapless numbering under concurrency.** This needs a per-financial-year counter with a transactional allocate-and-insert.
- **Address snapshot source.** At order creation, Order needs the delivery address from User (an existing internal lookup or a new one).

#### Impacted areas (Jira Components: `services`, `mobile-app`)

Spec layout follows the repo convention, with nothing new invented:

```
MA-38/step*.md                                 ← SDD workflow notes (this file, context, decomposition, review)
services/tasks/MA/MA-38/{SPEC-KEY}.md          ← Catalog, Pricing, Order, Invoice service specs
mobile-app/tasks/MA/MA-38/{SPEC-KEY}.md        ← Bill Details + Download Invoice spec
{area}/tasks/MA/MA-38/impl-plan/               ← implementation plan beside its specs (after approval)
```


- **`services`:** Catalog (tax fields), Pricing (per-line tax and split), Order (breakdown and address snapshot), and a new Invoice service (job, numbering, PDF, API, `InvoiceGenerated` event).
- **`mobile-app`:** Order Details Bill Details card, Download Invoice row, PDF open and share.
- **`portal-ui`:** only if HSN and GST rate must be editable in the Admin Catalog screens (MA-157). Otherwise seed data. To confirm in Step 2.

---

*Next: Step 2 — Build Technical Context: well-architected guardrails, HLD/LLD and messaging map (where an Invoice service fits, the `InvoiceGenerated` event), the MA-122 full design for tax fields, MA-132/MA-136 order-creation paths for the snapshot, and Admin Catalog (MA-157) for editing HSN and GST rate.*
