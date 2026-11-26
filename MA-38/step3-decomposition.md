### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for MA-38, in build order:

* ✓ **Pricing — per-product GST and per-line tax breakdown** (`services`) — Pricing uses Catalog's existing `hsnCode`/`taxRate` instead of the flat 5%. It splits tax into CGST/SGST or IGST from `deliveryState` vs the seller state, and taxes the delivery fee as a service line (configurable SAC and rate). It returns a per-line breakdown alongside the unchanged aggregate fields. Includes seed HSN and rate values for local-dev products.
* ⚠ **Order — bill snapshot and address capture** (`services`) — At order creation (subscription and checkout paths), store per-line price, discount, taxable value, tax and HSN, plus the delivery fee and its tax, place of supply, and a billing-address snapshot. Return a `bill` object on `GET /orders/{id}` and add an internal "CONFIRMED orders for date D, with breakdown" read for the invoice job. Includes the small User-service change so its internal address endpoint returns the full default address.
  * Concern: this spans two services (Order plus a small User change). I've kept them together because the User change is too small for its own spec, but it could be split out.
* ⚠ **Invoice service — daily generation, numbering, PDF and download API** (`services`, new 14th service) — A Lambda run by EventBridge Scheduler after the last slot. It invoices every CONFIRMED order for the day, allocates a gapless per-financial-year number (`MF/26-27/000123`), renders the PDF in the reference layout to S3, records the invoice immutably, and publishes `InvoiceGenerated`. An owner-scoped `GET /orders/{orderId}/invoice` returns a short-lived pre-signed URL.
  * Concern: size. Generation plus numbering plus PDF plus API may exceed one sprint. Alternative: split into (a) generation, numbering and records and (b) PDF rendering and the download API.
  * Unsure: this adds a 14th service, so the HLD table needs an update. The alternative is a module inside Order (fewer moving parts, but it puts PDF and S3 on Order's hot service).
* ✓ **Mobile — Bill Details and Download Invoice on Order Details** (`mobile-app`) — `OrderSummary` gains an optional `bill`. `OrderDetailScreen` adds the **Bill Details** card (Item Total, Delivery Fee, Taxes & Fees, Grand Total) and a **Download Invoice** row that fetches the PDF and opens the share sheet. It covers every state (loading, not yet issued, error, hidden for failed or cancelled orders) and old orders with no breakdown. Adds `path_provider` and `share_plus`.

Not proposed as specs: Catalog and portal-ui (HSN and tax fields already exist and are admin-editable, from MA-156/MA-157), and email/SMS sending (deferred to MA-103 per D4).

Confident specs are ready to proceed. Flagged specs need input before drafting.

**To approve:** Transition to `SDD: Drafting` (no comment required).
**To modify:** Post `SDD-DECOMPOSITION-FEEDBACK` then transition to `SDD: Drafting`.
**To reject:** Transition to `SDD: Building Context` and post `SDD-FEEDBACK`.
