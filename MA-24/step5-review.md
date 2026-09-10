# SDD Step 5 — Review Checklist

**Story:** MA-24 — Payment Gateway Integration · Wallet / Recharge
**Specs reviewed (branch `spec/MA-24`):**
- `mobile-app/tasks/MA/MA-24/MA-125.md` — Flutter Wallet & Recharge Screen
- `services/tasks/MA/MA-99/MA-126.md` — Payment Service: Razorpay Wallet-Recharge Slice
- `services/tasks/MA/MA-100/MA-127.md` — Wallet Service: Recharge Crediting & Passbook Slice

---

## Part 1 — Individual specification quality

### MA-125 — Flutter Wallet & Recharge Screen

- [x] Solves the problem stated in MA-24 (the Wallet screen from the ticket mock; funds the wallet via Razorpay)
- [x] All 13 sections present and complete; mobile-specific coverage included (widget hierarchy, all UI states, exact visible labels, `Key(...)` selectors, a11y ≥48dp, offline, JWT)
- [x] Functional requirements specific and unambiguous (exact endpoints, `Key`s, labels, validation messages, state machine)
- [x] NFRs defined with measurable targets (interactive <400ms, ≥48dp, WCAG AA contrast, per-state Keys)
- [x] Acceptance criteria testable (AC-1..AC-9 in §1/§4; nine widget scenarios in §10)
- [x] Edge cases and failure modes documented (§9 — 12 cases incl. app-kill, confirm/webhook race, empty key id)
- [x] Testing strategy sufficient (bloc unit + widget scenarios + real-backend acceptance, deferred to sibling services per MA-120/MA-123 precedent)
- [x] Scope boundaries clearly stated (§3 — cart checkout, MA-27 screen, saved-cards UI, web all explicitly out)
- [x] Assumptions and risks explicit (§11)
- [x] Hand-off ready without verbal explanation

### MA-126 — Payment Service: Razorpay Wallet-Recharge Slice

- [x] Solves the problem (server-side Razorpay order + authoritative webhook confirmation + idempotent recharge lifecycle + `PaymentConfirmed`)
- [x] All 13 sections present; backend coverage complete (owning service, Fargate, Aurora `payments`, event contracts, 3-layer idempotency, retries/DLQ, SigV4/webhook-HMAC auth, correlation IDs, CloudWatch/X-Ray, PCI-DSS SAQ-A)
- [x] Functional requirements specific (exact endpoints, status transitions `CREATED→CONFIRMING→CONFIRMED/FAILED`, HMAC formulae, reconciliation sweep cadence/thresholds)
- [x] NFRs defined with measurable targets (p95s, named metrics + alarm thresholds)
- [x] Acceptance criteria testable (§10 — domain unit, integration against Razorpay test mode, contract schema)
- [x] Edge cases and failure modes documented (§9 — 12 cases incl. webhook-before-confirm, duplicate webhook, amount mismatch, orphan webhook, late-capture-after-fail)
- [x] Testing strategy sufficient (unit + Localstack integration + shared contract schema + end-to-end acceptance + security sign-off)
- [x] Scope boundaries clearly stated (§3 — `purpose=WALLET_RECHARGE` only; ORDER path, refunds, split-tender, saved-card CRUD all out)
- [x] Assumptions and risks explicit (§11)
- [x] Hand-off ready without verbal explanation

### MA-127 — Wallet Service: Recharge Crediting & Passbook Slice

- [x] Solves the problem (idempotent ledger credit from `PaymentConfirmed`, balance/limits/passbook read APIs, `WalletCredited`)
- [x] All 13 sections present; backend coverage complete (Fargate, Aurora `wallet` ledger, `wallet-events-q` consumer, outbox, DB-per-service, idempotency via `ref` UNIQUE, DLQ, JWT + SigV4, correlation IDs, observability)
- [x] Functional requirements specific (the `credit_recharge` transaction pseudo-code, ledger schema, keyset pagination, discriminator routing)
- [x] NFRs defined with measurable targets (p95s, the balance invariant, named metrics/alarms)
- [x] Acceptance criteria testable (§10 — domain unit incl. duplicate/no-wallet/out-of-limits, integration incl. redrive-once-credit, migration test)
- [x] Edge cases and failure modes documented (§9 — 11 cases incl. recharge-before-provision, dual consumers, stale cursor, currency mismatch)
- [x] Testing strategy sufficient (unit + test-container integration + migration test + shared contract schema + end-to-end acceptance)
- [x] Scope boundaries clearly stated (§3 — extends MA-1; debits, refunds, auto-recharge, alerts, admin, the MA-27 screen all out)
- [x] Assumptions and risks explicit (§11 — schema migration, stored-balance invariant, shared queue, RetryableError trade-off)
- [x] Hand-off ready without verbal explanation

---

## Part 2 — Cross-specification coherence

- [x] **Consistent terminology and definitions** — `purpose = WALLET_RECHARGE`, integer **paise** for all money, `ref = "razorpay_payment:{id}"`, `PaymentConfirmed` / `PaymentFailed` / `WalletCredited`, `/wallet/me/*` endpoint style, `CONFIRMING` state — all used identically across the three specs.
- [x] **No conflicts or contradictions** — MA-125's `RechargeOrder` / `PaymentView` / `WalletView` model fields match MA-126's `POST /payments` + `GET /payments/{id}` responses and MA-127's `GET /wallet/me` response verbatim. MA-126's `PaymentConfirmed.detail` (§8.1) is exactly what MA-127's consumer (FR-4) expects.
- [x] **Data models align without collision** — `payments` cluster (MA-126) and `wallet` / `ledger_entries` cluster (MA-127) are separate per the database-per-service guardrail; no shared tables, no cross-DB reads (Payment reads Wallet limits via an API, not the DB).
- [x] **Inter-spec dependencies identified** — MA-125 → MA-126 (HTTP: create/confirm/get) + MA-127 (HTTP: `GET /wallet/me`, and `/transactions` via MA-27); MA-126 → MA-127 (`PaymentConfirmed` event + `GET /wallet/internal/limits`). Every cross-reference names the sibling spec and section.
- [x] **No required behavior silently uncovered** — every element of the MA-24 mock maps to exactly one owner: balance display → MA-127 FR-1 + MA-125 FR-2; Quick/custom amount + validation → MA-125 FR-3 + MA-126 FR-1 (enforce) + MA-127 FR-6 (own the bounds); payment method → MA-125 FR-4; gateway → MA-126 FR-1–3 + MA-125 FR-5–6; crediting → MA-127 FR-4; passbook data → MA-127 FR-2; passbook navigation → MA-125 FR-9; pending-UPI → MA-126 FR-3/FR-5 + MA-125 FR-6–7.
- [x] **Combined specs fully satisfy the User Story** — a customer can see their balance, top up (quick or custom) via Razorpay UPI/card, get an honest success/failure/pending result, never be double-charged or double-credited, and reach the passbook. The reconciliation reference (`payments.id` + `razorpay_payment_id`) is persisted for finance.
- [x] **No overlapping responsibilities causing ambiguity** — Payment owns the gateway + the cross-service event contract (§8, deliberately single-homed); Wallet owns the ledger + balance + limit values; Mobile owns the UI + the Razorpay SDK wrapper. The event-contract section lives only in MA-126 and is referenced (not duplicated) by MA-127.
- [x] **NFRs consistent** — the 3-layer idempotency story (client key → Razorpay `order_id` → `payment_id`/ledger `ref`) is told the same way in all three; latency budgets compose to the stated <5s end-to-end; security posture (PCI-DSS SAQ-A, no PAN in app or Payment Service, Secrets Manager with rotation, Cognito JWT for user calls, SigV4/mTLS + webhook-HMAC for the rest) is uniform.
- [x] **Testing strategies form a coherent overall test plan** — a shared `services/shared/events/*.schema.json` is validated by both backend specs' contract tests; the same end-to-end path (`POST /payments` → Razorpay test → webhook → `PaymentConfirmed` → Wallet consumer → `GET /wallet/me` reflects the credit) is the acceptance gate recited in MA-126 §10 and MA-127 §10; MA-125's real-backend manual pass depends on that stack.
- [x] **Implementation planning can begin without major ambiguity** — sequencing is explicit (backend services first, or mobile in parallel behind `FakeWalletRepository` + `--dart-define=WALLET_ENABLED`); the only open items (local-dev ports 8006/8007, brand-green contrast token, reconciliation scheduler mechanism, dedicated-queue-vs-shared) are enumerated per spec §12 and are implementation-review calls, not blockers.

---

## Review round 2 — external `/code-review` on PR #16 (2026-09-11)

Ten correctness findings were raised on the PR and addressed by revising the specs on `spec/MA-24`:

| # | File | Finding | Resolution |
|---|------|---------|------------|
| 1 | MA-126 §FR-1 | "return the stored create-response verbatim" contradicted the gateway-outage retry (row with no `razorpay_order_id`) | FR-1 idempotency now branches: order present → verbatim; order absent → resume `orders.create` once. |
| 2 | MA-127 §7 | migration ran `ALTER COLUMN ref SET NOT NULL` before the opening-`ref` backfill → abort on MA-1 rows | Backfill `UPDATE` reordered **before** `SET NOT NULL` / `ADD UNIQUE`. |
| 3 | MA-125 §FR-6/§6 | client `confirmRecharge` dropped `razorpayOrderId`, which MA-126 FR-2 requires (409 `ORDER_MISMATCH`) | `razorpayOrderId` added to `RechargeGatewaySucceeded`, `confirmRecharge(...)`, and the tests. |
| 4 | MA-125 §FR-6 | pending-poll had no `getPayment()` = `FAILED` branch → failed payment shown as "updating shortly" | Added a `FAILED` → failure-state (FR-8) branch; §9 + tests updated. |
| 5 | MA-125 §6/§FR-3 | `idempotencyKey` not cleared after a pending-timeout → new amount charged at the old amount | Key persisted per attempt and reused; amount controls disabled while an attempt is unresolved; key cleared only on a terminal outcome. |
| 6 | MA-125 §FR-2/§7 | memory-only idempotency key → app-kill-after-pay allowed a second charge | New `wallet.pendingRecharge` `shared_preferences` record; `WalletStarted` resumes the *same* payment (FR-6a). |
| 7 | MA-126 §FR-5/§9 | 30-min reconciliation force-FAILED a still-open UPI collect; a late capture went to manual review | Sweep no longer force-fails while Razorpay shows the order payable (6-h hard cap); `TIMEOUT` is provisional and a late `captured` auto-recovers to `CONFIRMED` (`LATE_CAPTURE_RECOVERED`). |
| 8 | MA-126 §FR-1 | idempotency dedupe ignored `amountPaise`/`purpose` → reused key + new amount returned the wrong order | Body-mismatch on a reused key → 409 `IDEMPOTENCY_KEY_REUSED`. |
| 9 | MA-127 §FR-1/§FR-7 | `/wallet/me/status` "alias" returning the new `balancePaise` body would break MA-1's rupee consumer | `/wallet/me/status` explicitly keeps MA-1's original `{…, balance (rupees), currency}` body; `GET /wallet/me` is a new endpoint; MA-1 screen migration is out of scope. |
| 10 | MA-125 §FR-6/§FR-7 | success inferred from a `getWallet()` balance delta → false-positive on a concurrent same-value credit | Success is decided **only** by `getPayment(paymentId)` = `CONFIRMED`; `getWallet()` is display-only. |

## Verdict

**PASS (with round-2 revisions applied)** — all individual-quality and cross-specification coherence checks are satisfied; the ten correctness findings from the PR #16 `/code-review` were resolved on `spec/MA-24` (table above) without changing the specs' scope or the cross-service contract.

### Decision records / follow-up actions (carried, not blocking)

1. **Architect ack required** to update `milkful-well-architected.md` §7.1 (add `WalletCredited` / `WalletDebited` to Wallet's published events) and to add the recharge `PaymentConfirmed → wallet-events-q` path to `milkful-messaging.drawio`. Raised as an acceptance item in MA-126 §8.5 / §13 and MA-127 §13. The specs adopt the fuller vocabulary regardless.
2. **`GET /wallet/me/status` (MA-1)** kept returning MA-1's **original** body (`balance` in whole rupees) for backward-compat — it is *not* re-pointed at the new `balancePaise` FR-1 shape. Migrating MA-1's registration screen onto `GET /wallet/me` is a separate MA-1 follow-up. (MA-127 FR-1 / §12.)
3. **`MA-33` (NR : Wallet Recharge)** overlaps MA-24; recommend closing as duplicate or repurposing for deferred extras (recharge offers/cashback, low-balance auto-recharge). Flagged on MA-24's decomposition comment.
4. **Backend unimplemented** — MA-126 + MA-127 are first scaffolds; MA-125 ships behind a flag. Implementation-plan step to own the sequencing.
