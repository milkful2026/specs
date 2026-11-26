### SDD Step 2 — Technical Context

**Story:** MA-38 — Invoice Generation (GST, Discounts, Offers)
**Status:** SDD: Building Context
**Components:** `services`, `mobile-app`
**Layers read:**
- **Layer 1:** `milkful-well-architected.md` (HLD and messaging), area READMEs, the services README.
- **Layer 3:** MA-122 (Pricing full design), MA-132/MA-136 (order creation), MA-146/MA-152/MA-155 (Order Details screen), MA-156/MA-157 (Admin Catalog).
- **Layer 4 (targeted):** Catalog model and migrations, Pricing service, Order's pricing and user clients, the User internal address handler, the Flutter orders feature, `pubspec.yaml`, `local-dev/docker-compose.yml`.

---

#### Corrections to Step 1 ground truth

- **Catalog already stores tax data.** MA-156 (migration `catalog/0003_catalog_admin.sql`) added `hsn_code VARCHAR(16)` and `tax_rate NUMERIC(5,2)` to `products`. They are returned as `hsnCode`/`taxRate` by `GET /products/{id}` and are editable in the admin portal (`ProductFormFields.tsx`, MA-157). **No Catalog or portal-ui change is needed.** What remains is seed data: existing products may have nulls.
- **Pricing ignores that data.** `pricing_service.py` still applies the flat `default_tax_rate_percent` (5%), even though it already fetches each product from Catalog per quote.

#### Current State Summary

| Concern | Today | Gap for MA-38 |
|---|---|---|
| Per-product tax | `hsnCode`/`taxRate` in Catalog, admin-editable | Pricing doesn't use them |
| Quote shape | One aggregated `basePrice`/`taxAmount`/`taxRate`/`deliveryFee`/`netPayable` | No per-line breakdown, no CGST/SGST/IGST split, no tax on delivery fee |
| Order record | `amount_paise` total; `order_items(product_id, quantity)` | No unit price, taxable value, tax or delivery fee per order; no address |
| Address | User `GET /v1/internal/users/address-state` returns **state only** (SigV4) | Invoice needs full Bill To / Ship To |
| Order read API | `GET /orders/me`, `GET /orders/{id}` (owner-scoped) | No bill breakdown, no invoice reference |
| Scheduled work | Order `sweep` daemon thread; Subscription daily run (EventBridge Scheduler → Lambda; `local-dev/run_daily_local.py` locally) | No invoice job |
| File storage | S3 is in the HLD; **moto** (S3 emulator) runs in local-dev compose | No bucket or usage yet |
| Mobile | `OrderDetailScreen`, `OrderSummary.fromJson` (no breakdown), `url_launcher` only | No PDF, file or share packages |

#### Impacted Systems

1. **Pricing & Offer Service** (Fargate, no datastore in its current build): per-line tax from Catalog's `taxRate`, CGST/SGST vs IGST split by `deliveryState` vs the seller state, delivery fee taxed as a service line, and a per-line breakdown in the quote response. The existing aggregate fields stay for backward compatibility.
2. **User Service** (Lambda, Aurora `users`): the internal endpoint also returns the full default address (name, lines, city, pincode, state), or a sibling endpoint does. It stays internal and SigV4-signed.
3. **Order Service** (Fargate, Aurora `orders`):
   - At order creation (subscription path MA-132, checkout path MA-136), snapshot the quote's per-line breakdown and the address.
   - Return a `bill` object on `GET /orders/{id}`.
   - Expose an internal read for the invoice job: CONFIRMED orders for a delivery date, with their breakdown.
4. **Invoice Service — new** (proposed **Lambda + EventBridge Scheduler**, Aurora `invoices`, S3 `milkful-invoices`):
   - Daily job, gapless per-financial-year numbering, immutable invoice records.
   - PDF rendering to S3.
   - Owner-scoped `GET /orders/{orderId}/invoice` returning a short-lived pre-signed URL.
   - Publishes `InvoiceGenerated`.
5. **Mobile app (Flutter):** `OrderSummary` gains an optional `bill`. `OrderDetailScreen` gains a **Bill Details** card and a **Download Invoice** row. New packages for download, open and share.

**Not impacted:** Catalog (fields exist), portal-ui (already edits HSN and rate), Subscription, Wallet, Payment (MA-99 blocks nothing here, since wallet debit already works through Order).

#### Dependencies

```
Pricing per-line tax  ──►  Order bill snapshot (+ User full address)  ──►  Invoice service  ──►  Mobile Download Invoice
                                         └────────────────────────────────────────────────────►  Mobile Bill Details
```

- Order depends on the new Pricing response shape and the new User address fields.
- The Invoice service depends on Order's internal read and stored breakdown. It never reads the `orders` DB.
- Mobile Bill Details depends only on Order; Download Invoice depends on the Invoice service.
- **Data prerequisite:** every active product needs a real `hsnCode` and `taxRate`, set via the admin portal or the `local-dev/_catalog_seed_data.py` seed. Finance supplies the values.

#### Architecture Notes

- **New service vs a module in Order.** A separate service keeps Order's hot path free of PDF rendering and S3, and gives invoices their own lifecycle (numbering, immutability, retention). The HLD's 13-service table has no billing owner; this adds a 14th, which is an HLD doc update. **Decided in Step 3.**
- **Lambda fits.** Like Subscription's daily run, the work is a once-a-day burst plus a low-traffic read API, so scale-to-zero wins. Aurora connection storms aren't a concern at this volume.
- **Pull, not events, for the daily batch.** At the scheduled time, the job asks Order for "CONFIRMED orders for date D". This is simpler than consuming `OrderConfirmed` into a read model, and naturally excludes orders cancelled before the cut-off. A later `DELIVERED`-based trigger (MA-102) would only change this filter.
- **Rendering.** The PDF is rendered server-side once at issue time, using a Python library such as ReportLab or WeasyPrint (choice belongs in the spec). The file is stored and never re-rendered, so the document cannot drift if templates or seller config change later.

#### Data / Integration Considerations

- **Money:** integer paise end to end, with ROUND_HALF_UP per line.
  - Invariant: Σ line totals + delivery-fee line total = `orders.amount_paise`. The invoice job **refuses to issue** if it doesn't hold, and logs and alarms instead.
- **Tax math (tax-inclusive MRP, A7):**
  - Taxable value = round(line gross × 100 / (100 + rate)).
  - Tax = gross − taxable value.
  - Intra-state: CGST = SGST = tax / 2, with the odd paisa going to SGST. Inter-state: IGST = tax.
- **Order snapshot (Order DB):**
  - **`order_items`** gains `unit_price_paise`, `discount_paise`, `taxable_paise`, `tax_rate`, `cgst_paise`, `sgst_paise`, `igst_paise`, `hsn_code`, `product_name`.
  - **`orders`** gains `delivery_fee_paise`, `delivery_fee_tax_paise`, `place_of_supply_state` and `billing_address JSONB`, all nullable so pre-existing orders stay valid (AC-9).
  - **Subscription orders.** Today they keep `product_id`/`quantity` on `orders` itself, not in `order_items`, so the spec must decide whether they also write a single `order_items` row. Proposed: yes, for one uniform breakdown read.
- **Invoice DB (new):**
  - `invoices(id, invoice_no UNIQUE, order_id UNIQUE, user_id, fy, issued_on, totals…, s3_key, created_at)`.
  - `invoice_lines(…)`.
  - `invoice_counters(fy PK, last_no)`, incremented with `UPDATE … RETURNING` in the same transaction as the insert, which makes numbering gapless.
  - `UNIQUE(order_id)` gives idempotency.
- **Event:** `InvoiceGenerated { invoiceId, invoiceNo, orderId, userId, issuedOn, invoiceValuePaise }` via the transactional outbox (the same pattern as order, user and cart). Consumers: Reporting (later) and Notification (later, for email).
- **Retention:** GST records must be kept for 6 years after the end of the financial year. The S3 lifecycle has no expiry before that; KMS encryption at rest.

#### Constraints and Guardrails (Layer 1)

- Database-per-service. Invoice reads Order and User only through their APIs.
- Customer endpoints use a Cognito JWT at API Gateway and are **owner-scoped**: another user's order gets **404**, not 403 (matching `GET /orders/{id}`). Internal endpoints use SigV4.
- Correlation ID on every call and event. CloudWatch metrics and logs, plus X-Ray.
- Idempotency on every write. DLQs on any SQS consumer (none are planned for v1).
- Secrets and seller config (GSTIN and the rest) come from SSM or Secrets Manager. They are never hard-coded and never live in the repo.

#### Mobile-specific context

- Route `/orders/:orderId` → `OrderDetailScreen` (cubit `order_detail_cubit.dart`). Its current card order is header, items, total, delivery date, payment method, then Reorder / Support / Cancel.
- **Bill Details card** (exact labels from the mock): "Bill Details", "Item Total", "Delivery Fee", "Taxes & Fees", "Grand Total". The card appears only when `bill` is present.
- **Download Invoice row:**
  - **States:** label "Download Invoice" with a download icon. Loading shows a spinner in place of the icon and the row disabled. Not yet issued shows "Invoice available after delivery" (disabled). An error shows a SnackBar "Couldn't download invoice. Try again.". The row is hidden for CANCELLED, PAYMENT_FAILED, FAILED and NEEDS_ATTENTION.
  - **Keys:** `Key('order-detail-bill-details')`, `Key('order-detail-download-invoice')`.
  - **Accessibility:** touch target ≥48dp; semantics label "Download invoice PDF".
- **Packages:** add `path_provider` and `share_plus` (save the file, then the share sheet, which on both platforms offers Save to Files or Downloads). Opening via the share sheet avoids storage permissions on Android 10+. Alternative: open the pre-signed URL with the existing `url_launcher`, which needs no new package but gives a weaker UX and the link expires.

#### Risk Register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Products with null `hsnCode`/`taxRate` | Wrong or missing tax; invoice can't be issued | Pricing rejects quoting a product with null tax data (distinct error) once a flag is enabled; seed data plus an admin backfill before enabling |
| R2 | Pricing response change breaks the app's `Quote.fromJson` | Cart/product screens break | Additive fields only; aggregates unchanged |
| R3 | Breakdown doesn't sum to the charged total (rounding) | Non-compliant invoice | Paise math with an explicit residual rule; invariant check before issue |
| R4 | Gaps or duplicates in invoice numbers under concurrent runs | GST non-compliance | Counter row lock in the same transaction; a single scheduled run, plus `UNIQUE(order_id)` |
| R5 | Address changes after order creation | Wrong Bill To | Snapshot at order creation; never read live |
| R6 | Seller details missing or placeholder in prod | Legally invalid invoices | Service fails health or start-up if required seller config is absent in non-local envs |
| R7 | Delivery-fee SAC and rate unconfirmed (A2) | Wrong tax on the fee line | Config-driven; finance sign-off before go-live |
| R8 | A new (14th) service adds ops surface | Cost and maintenance | Lambda (scale-to-zero); reuse shared outbox and logging libraries |

#### Operational Considerations

- **Metrics:** `invoice.generated.count`, `invoice.skipped.count` (by reason: invariant failed, missing tax data), `invoice.job.duration`, `invoice.pdf.bytes`, and the API's 4xx/5xx counts.
- **Alarms:** job didn't run by 12:00 IST; skipped count > 0; DLQ depth (if events are consumed later).
- **Re-runs:** a re-run is safe (idempotent per order). Admin-triggered regeneration is out of scope.
- **Rollout:** ship Pricing, then Order, then Invoice, then mobile. Orders created before Order's release have no breakdown, so the job skips them and logs them as `NO_BREAKDOWN`. Mobile hides Bill Details and Download for them.
