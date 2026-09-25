### SDD Step 5 — Review Checklist (MA-34)

Specs: MA-135 Cart checkout support · MA-136 Order Service cart checkout · MA-137 Flutter Review Cart & Confirm Order

#### Part 1 — Individual quality

| Check | MA-135 | MA-136 | MA-137 |
|-------|:-----:|:-----:|:-----:|
| Solves the story's problem | ✓ | ✓ | ✓ |
| All 13 sections present | ✓ | ✓ | ✓ |
| FRs specific and unambiguous | ✓ | ✓ | ✓ |
| Measurable NFRs | ✓ | ✓ | ✓ |
| Testable acceptance | ✓ | ✓ | ✓ |
| Edge cases / failure modes | ✓ | ✓ | ✓ |
| Testing strategy | ✓ | ✓ | ✓ |
| Scope boundaries | ✓ | ✓ | ✓ |
| Risks/assumptions explicit | ✓ | ✓ | ✓ |
| Hand-off ready | ✓ | ⚠ | ✓ |

MA-136 ⚠: the stale-`IN_PROGRESS` reconciliation sweep is deferred (§11) and must be
tracked as a pre-production follow-up. A stale checkout no longer blocks the customer
(FR-2a). The sweep is needed only to finish paid checkouts whose customer never returns. Both of its Product questions (§12) were
resolved on 2026-09-25.

#### Part 2 — Cross-spec coherence

- [x] Terminology consistent: "Pay now" = one-time lines (`payNowQuote` ↔ `payNowPaise`);
      "per delivery" = subscription lines; `CHECKOUT` order source.
- [x] Contracts line up: MA-135 FR-3/FR-4 ↔ MA-136 FR-3.2/FR-7; MA-135 FR-2 ↔ MA-137 FR-4;
      MA-136 error codes ↔ MA-137 FR-7 table (all 11 codes mapped, plus an unknown-code
      fallback; re-checked after PR #21 review). Cart's remove-items 409 is
      `CART_VERSION_MISMATCH` in both MA-135 and MA-136 (verified in code).
- [x] Resume/takeover: MA-136 FR-2a (busy window, discard pre-debit, adopt post-debit) ↔
      MA-137 FR-8/FR-9 (pending key + body survive logout, cart locked while pending).
- [x] Partial failure: per-line subscription failures (FR-3.3/FR-6) never block the rest,
      matching Product's 2026-09-25 decision; MA-137 FR-10 shows them.
- [x] Subscription minimum balance ₹500: Cart `wallet_minimum_balance = 500` (verified),
      MA-136 `SUBSCRIPTION_MIN_BALANCE_PAISE` = 50000, MA-137 shared constant.
- [x] Cut-off 20:00 IST: Subscription `cutoff_hour_ist = 20` (verified), MA-136 FR-8,
      MA-137 FR-6.
- [x] `slotId` rule (required for subscriptions, forbidden for ONE_TIME) identical in
      MA-135 FR-1, MA-136 FR-3.3, MA-137 FR-3.
- [x] No overlapping ownership: Cart never prices at checkout; Order never mutates cart
      lines except via MA-135 FR-4; app never calls Subscription create for cart lines.
- [x] Every AC in Step 1 has an owner: AC-1/2/3/4 (MA-137 + MA-135), AC-5/6/7/8/9 (MA-136 + MA-137).
- [x] Double-charge protection is layered consistently: app persisted key → `checkouts`
      unique key → `orders.checkout_id` unique → Wallet ledger ref.
- [x] Migration safe for existing data (defaults backfill `source`; NULL-distinct unique).
- [x] Delivery address: MA-135 FR-6 (`GET /users/me` → `defaultAddress`, from the
      onboarding Google Maps / Places data) ↔ MA-137 FR-6; no address → MA-136
      `DELIVERY_ADDRESS_UNKNOWN` ↔ MA-137 dialog.
- [x] Event schema change safe: only consumer (Wallet) acks-and-logs `OrderConfirmed` today (verified).

#### Result

All specs pass, with the MA-136 follow-up noted. Tasks MA-135/136/137 were created and
linked on 2026-09-25; specs are on `spec/MA-34`; PR opened for human review.
