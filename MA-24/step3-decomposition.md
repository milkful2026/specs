### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for **MA-24 — Payment Gateway Integration · Wallet / Recharge**:

---

* **✓ Flutter Wallet & Recharge Screen** — `mobile-app` · spec path `mobile-app/tasks/MA/MA-24/{KEY}.md`
  The Wallet tab exactly as mocked: balance card (`Available Balance`, `₹{amount}`), `Top Up` custom-amount sheet, Quick Top Up chips (₹500/₹1000/₹2000), Payment Methods selector (UPI / Card, Card default, remember last-used), `Proceed to Payment` → server creates a Razorpay order → `razorpay_flutter` checkout sheet → success / failure / **pending (async UPI)** handling with a webhook-resolved "processing" state; `Passbook` + `View All Transactions` navigate to MA-27; wire the existing stub bottom-nav Wallet tab to the new `/wallet` route. `WalletBloc` + `WalletRepository` (+ `FakeWalletRepository`), `razorpay_flutter` dependency, Razorpay **key id** via `--dart-define`, retire `StubWalletBalanceRepository` and re-point MA-120's balance gate (whole-rupees → paise). All UI states + `Key(...)` selectors + a11y (≥48dp, semantic labels) per the mobile SDD convention. One engineer / one sprint; can be built and tested against the fake ahead of the backend.

* **✓ Payment Service — Razorpay recharge slice** — `services` (MA-99) · spec path `services/tasks/MA/MA-99/{KEY}.md`
  First scaffold of the Payment Service (in the canonical 13 — no new-service architect gate), scoped to `purpose = WALLET_RECHARGE`. `POST /payments` (server-side Razorpay `orders.create`, `Idempotency-Key`, dedupe on `(userId, idempotencyKey)` + `razorpay_order_id`), `POST /payments/{id}/confirm` (verify the client callback signature → `CONFIRMING`), `POST /payments/webhook` (public, Razorpay webhook-signature + IP allowlist; **authoritative** → `CONFIRMED` / `FAILED`), `GET /payments/{id}`. Reconciliation sweep for `CONFIRMING` payments older than N minutes (poll Razorpay). Aurora `payments` + `payment_events` (immutable audit). Transactional outbox → `PaymentConfirmed` / `PaymentFailed` (carrying the `purpose` discriminator). Razorpay key secret + webhook secret in Secrets Manager (rotation). Fargate. Circuit-breaker + retry/backoff around Razorpay; correlation ID propagation; CloudWatch/X-Ray. One engineer / one sprint.

* **✓ Wallet Service — recharge crediting & passbook slice** — `services` (MA-100) · spec path `services/tasks/MA/MA-100/{KEY}.md`
  Extends the MA-1 `wallet-auto-provision` seed (does **not** redefine wallet creation). `GET /wallet/me` (`balance_paise`, `status`, `rechargeMin/Max`), `GET /wallet/me/transactions` (desc-paged ledger — the contract MA-27 will consume). `wallet-events-q` consumer for recharge `PaymentConfirmed` → idempotent `RECHARGE` `ledger_entries` row + `balance_after_paise` snapshot in a single `SELECT ... FOR UPDATE` transaction (dedupe on `ref = razorpay_payment:{id}`, `INSERT ... ON CONFLICT DO NOTHING`) → publish `WalletCredited`. `ledger_entries` schema extension (signed `amount_paise`, `balance_after_paise`, `ref` UNIQUE, `correlation_id`), `wallets.balance_paise`, min/max recharge rule. Reuse the existing `wallet-events-q` DLQ + add a depth alarm. Fargate. One engineer / one sprint.

---

* **⚠ Cross-service payment/wallet event contract & EventBridge routing**
  The `PaymentConfirmed` schema (with the `purpose` field), the **new EventBridge rule** filtering `purpose = WALLET_RECHARGE` → `wallet-events-q` (this recharge path is not in the current `milkful-messaging.drawio`), the `WalletCredited` schema, plus resolving two naming discrepancies found in Step 2: (a) events — well-architected §7 lists only `WalletLowBalance`, the MA-100 ticket says `WalletDebited`/`WalletCredited`, MA-1 says `WalletCreated` → propose the full set and align the architecture doc; (b) endpoints — MA-100 ticket `GET /wallets/{userId}` vs MA-1 shipped `GET /wallet/me/status` → propose `/wallet/me/*` (JWT-derived, no IDOR).
  * **Concern:** on its own this is close to the "single config/contract change — merge it" line in the sizing guide, but it spans two services *and* edits the authoritative architecture doc, which the guide says to split. **Leaning:** fold it into the **Payment Service** spec (as the event producer) with an explicit "Integration Contracts" section the Wallet spec references — i.e. **3 specs total, not 4**. Flagging so the reviewer can instead ask for it as its own artifact if they want the contract change tracked separately.

---

#### Notes for the reviewer

- **Backend is unimplemented.** Specs 2 and 3 will be fully drafted, but Payment Service and Wallet Service have no code today. The mobile spec (1) follows the MA-120/MA-123 precedent — draft + build against a fake repository now; end-to-end verification waits on MA-99/MA-100. The implementation-plan step will call this out as a sequencing gate (mobile can ship dark behind `--dart-define=WALLET_ENABLED`).
- **Scope confirmed in chat (2026-09-10/11):** MA-24 = *fund the wallet via Razorpay*. The cart→order checkout, the 10 PM cut-off batch, instant-buy inventory locking, the Unified Delivery Object, and subscription first-payment are **downstream consumer behaviour** and belong to MA-25 / MA-97 / MA-98 — not this decomposition. Order Service and Subscription Service are therefore **not** included here despite the earlier "full cross-area" framing (the mock has no order/checkout surface).
- **MA-27 (Transaction History screen)** is a separate story; MA-24 only defines `GET /wallet/me/transactions` and links to it.
- **MA-33 (NR : Wallet Recharge)** overlaps this story's intent. Recommendation: MA-33's recharge-screen scope is absorbed here (per the mock); MA-33 can be closed as duplicate or repurposed for the deferred extras (recharge offers/cashback, low-balance auto-recharge).

---

**To approve as-is (3 specs, contract folded into Payment):** transition MA-24 → `SDD: Drafting`.
**To modify (e.g. break the contract out as a 4th spec, or drop a backend spec):** post `SDD-DECOMPOSITION-FEEDBACK` (Accept / Remove / Add / Modify), then transition → `SDD: Drafting`.
**To reject:** transition → `SDD: Building Context` and post `SDD-FEEDBACK`.
