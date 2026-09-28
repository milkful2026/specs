## SDD Step 2 — Technical Context

**Story:** MA-39 · **Status:** SDD: Building Context
**Context layers used:** L1 `app/docs/design/milkful-well-architected.md` + `milkful-messaging.drawio`; L3 prior specs — MA-129 (Admin Identity, RBAC & Session Security), MA-21 `identity-auth-login.md` + `user-account-type-profile.md` (which explicitly names MA-39 as the future owner of admin-side account-type editing), MA-127/MA-130-adjacent Wallet spec (via `wallet/src/domain`), MA-131 Subscription spec (via `subscription/src/domain`); L4 source — `services/user/src`, `services/identity-auth/src`, `services/subscription/src/domain/subscription_service.py`, `services/wallet/src/domain/*`.

---

### Current State Summary

**User Service (`services/user`):** `domain/models.py` has no account-lifecycle field at all — `UserProfile` and `RegistrationResult` carry `account_type` (B2C/B2B, MA-21) and `wallet_status`, nothing else. Handlers are customer self-service only (`register_handler`, `get_me_handler`, `delivery_slots_handler`) — **no admin-facing route exists in this service today.** `CognitoAttributePort` (`cognito_attribute_adapter.py`) is User Service's own narrow adapter to the **consumer** Cognito pool, currently exposing `sync_profile_attributes` and `get_mobile_by_sub` only.

**Identity & Auth (`services/identity-auth`):** Consumer login (`login_otp_send_handler.py` / `login_otp_verify_handler.py`, MA-21) is OTP-based, calls Cognito directly (`find_verified_sub_by_phone`, `InitiateAuth`-equivalent `issue_tokens`), and has **zero dependency on User Service** — it never checks any account-status field, because none exists yet. Separately, the **Admin** side (MA-47/MA-129) already has a complete, proven pattern for exactly this kind of action: `POST /v1/admin/users/{id}/deactivate` sets `status=Deactivated` and calls `AdminUserGlobalSignOut` to revoke refresh tokens immediately, emitting `admin.user.deactivated`. MA-39 is this same shape, applied to the **consumer** pool instead of the admin pool.

**Subscription Service (`services/subscription`):** Already has everything MA-39's "pause active subscriptions" requirement needs, built for MA-131: `SubscriptionStatus.PAUSED`, `pause_from`/`pause_until` (both nullable — an **open-ended pause with `until=None` is already a supported shape**), and the Daily Run's `is_due` computation already excludes any subscription inside its pause window regardless of the coarse `status` field (see `subscription_service.py`'s own module docstring). The catch: `pause(subscription_id, user_id, ...)` calls `_get_owned(subscription_id, user_id)` — **it is hard-coded to the owning customer**; there is no admin/system-initiated pause path today.

**Wallet Service (`services/wallet`):** No "auto-debit halt" flag exists, and **none is needed** — wallet debits happen only via `debit_for_order`, which Order Service calls when an order is created. If Subscription's Daily Run stops generating orders for a paused subscription (which it already does, per the `is_due` behavior above), there is nothing left that would auto-debit the wallet. **This means Wallet Service needs no code change for MA-39** — a scope reduction from the Step 1 assumption (D5: full cross-area) worth flagging back before Step 3 locks the decomposition.

### Impacted Systems

| System | Change |
|--------|--------|
| **`portal-ui`** | New Customer Accounts screens (list/search/filter-by-status, detail, bulk action) under existing RBAC; a new permission (e.g. `customers:manage`) added to the fixed 5-role set from MA-47/MA-128. |
| **User Service (MA-93)** | **Owns the new capability.** Add `status` (Active/Suspended/Deactivated), `status_reason`, `status_effective_from`, `suspended_until`, plus a status-history table, to `users`. New admin-only endpoints: list/search/filter, get-detail-with-history, `POST /v1/admin/customers/{id}/suspend` \| `/deactivate` \| `/reactivate`, bulk variant. Extend `CognitoAttributePort` with `disable_user`/`enable_user` (consumer pool `AdminDisableUser`/`AdminEnableUser`) — mirrors MA-129's admin-pool pattern exactly. Publishes a new `user.status.changed` event (payload includes previous/new status, reason, actor). |
| **Identity & Auth (MA-92)** | **Likely no functional change** — Cognito's own `AdminDisableUser` makes `InitiateAuth` fail natively with `UserDisabledException` for a disabled consumer, so login is blocked for free once User Service calls it. The only possible change is translating that Cognito exception into a clean, non-5xx client error in `login_otp_send_handler.py`/`login_otp_verify_handler.py` if it doesn't already map cleanly — **needs a Step 3 spike**, not assumed as a full spec-owning service the way MA-129 was for MA-47. |
| **Subscription Service (MA-98)** | Add an internal/admin-triggered pause path — either a new `admin_pause(subscription_id, reason)` domain method bypassing the `user_id` ownership check, or (preferred, decoupled) a new EventBridge consumer that reacts to `user.status.changed` and calls the **existing** `pause(..., until=None)` internally. Reuses existing status/date fields; **no schema change**. |
| **Wallet Service (MA-100)** | **No change** (see Current State Summary) — removed from the cross-area build scope, kept only as "verify this assumption holds" in Step 3/testing. |
| **`mobile-app`** | Login error message/screen for a blocked account (`UserDisabledException` mapped to a clear "account deactivated, contact support" message) — small, if Identity & Auth needs the mapping above. |

### Dependencies

- **Cognito consumer pool `AdminDisableUser`/`AdminEnableUser`** — same API family MA-129 already uses on the admin pool; no new AWS permission *pattern*, just a new IAM action on User Service's existing Cognito adapter role (least-privilege addition, not a new trust boundary).
- **EventBridge `milkful-events`** — a new event, `user.status.changed`, not present in the current messaging topology (`milkful-messaging.drawio` §7.1 lists `UserRegistered` as User Service's only published event today). New rule needed if Subscription consumes it via event rather than a direct call (see Architecture Notes).
- **MA-47/MA-128 admin RBAC + audit emission** — MA-39 reuses this wholesale; no new console, no new auth mechanism for admins themselves.
- **Blocking:** none of Identity & Auth, Subscription, or Wallet need to ship *before* User Service's core (status model + admin CRUD + Cognito disable/enable) — that core alone gets AC-1/2/3/6/7/8 (list, change status, login block, bulk, audit, admin-safety) working end to end. The Subscription-pause integration is the one piece with a real cross-service dependency.

### Architecture Notes

**Two ways to wire Subscription's pause, to settle in Step 3:**

```
Option A — Direct admin path (sync, simple)
  portal-ui → User Service: POST /admin/customers/{id}/deactivate
                → Cognito AdminDisableUser (consumer pool)
                → users.status = Deactivated (+ reason, history row)
                → User Service calls Subscription Service's admin-pause
                  endpoint synchronously (new, ownership-check bypassed)
                → emits user.status.changed (fire-and-forget, for
                  audit/MA-50 and any other future consumer)

Option B — Event-driven (decoupled, matches well-architected §1 "Integration")
  portal-ui → User Service: POST /admin/customers/{id}/deactivate
                → Cognito AdminDisableUser
                → users.status = Deactivated (+ reason, history row,
                  transactional outbox)
                → outbox publishes user.status.changed → EventBridge
                    → new rule → subscription-events-q (new queue+DLQ)
                        → Subscription Service consumes, calls its own
                          existing pause(..., until=None) internally
```

Recommend **Option B** — it's what the well-architected doc mandates as the default integration style (§1 "Integration: Event-driven... cross-service data flows via events or APIs only", database-per-service with no direct cross-service writes), and it matches the outbox pattern User Service already uses for `UserRegistered` (`registration_service.py`). Option A is faster to build but makes User Service a synchronous caller into Subscription's write path — exactly the coupling the platform's own guardrails steer away from. **Trade-off to flag for Step 3 sign-off:** Option B means a deactivation takes a short, eventually-consistent window before the subscription is actually paused (the gap between the outbox publish and the consumer processing it) — acceptable given D4 already accepts an equivalent window for session/token expiry, but worth stating explicitly rather than assuming.

**Login-block enforcement is "free" once `AdminDisableUser` is called** — this is the same trick MA-129 uses for admin deactivation, just on the other Cognito pool. No new identity-auth ↔ user-service coupling is needed for the login path itself, which keeps AC-3 cheap and avoids adding a synchronous per-login status check (which would have been the "obvious" but heavier alternative — a call from Identity & Auth to User Service on every OTP send/verify).

### Data / Integration Considerations

**User Service — extends `users` (Aurora, MA-93's own database):**
```sql
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'
  CHECK (status IN ('Active', 'Suspended', 'Deactivated'));
ALTER TABLE users ADD COLUMN status_reason TEXT;
ALTER TABLE users ADD COLUMN status_effective_from DATE;
ALTER TABLE users ADD COLUMN suspended_until DATE;  -- NULL unless status = Suspended

CREATE TABLE user_status_history (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  previous_status TEXT, new_status TEXT NOT NULL,
  reason TEXT, effective_from DATE, actor_admin_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
- A background sweep (mirrors Subscription's own Daily Run pattern, not new infrastructure) flips `Suspended` rows past their `suspended_until` back to `Active` — consistent with D1 ("Suspension... lifts automatically").
- Bulk action is per-row: same single-row status-change path invoked N times inside one handler, each independently emitting its own `user.status.changed` and history row — **no new bulk-specific schema**, matches AC-6's "one failure doesn't roll back others" requirement naturally (no shared transaction across rows).

**Event contract (`user.status.changed`):**
```json
{ "eventId", "eventType": "user.status.changed", "eventVersion": "1.0",
  "source": "user", "timestamp", "correlationId",
  "payload": { "userId", "previousStatus", "newStatus", "reason",
               "effectiveFrom", "actorAdminId" } }
```

### Constraints and Guardrails (from L1)

- **Database-per-service** — `users` status lives only in User Service's Aurora; Subscription never reads it directly, only reacts to the event (Option B).
- **Zero-trust** — new admin endpoints sit behind the existing admin authorizer (MA-129), requiring the new `customers:manage` permission on the caller's role claim, checked server-side.
- **Transactional outbox** (mandated, already User Service's own precedent from `UserRegistered`) — `user.status.changed` written in the same DB transaction as the status change, not published inline.
- **Idempotent consumers + DLQ** — Subscription's new consumer must be idempotent (same event redelivered must not double-pause) and have a DLQ, consistent with every other consumer in the messaging topology.
- **Least privilege** — User Service's IAM role gains only `cognito-idp:AdminDisableUser`/`AdminEnableUser` scoped to the consumer pool ARN, nothing broader.
- **Audit** — every status change is both an `admin.*`-family-equivalent domain event (for MA-50, consistent with MA-129's precedent) and a durable `user_status_history` row (belt-and-suspenders: MA-50's audit pipeline doesn't exist yet, so the history table is User Service's own fallback source of truth in the meantime).

### Risk Register

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | Event-driven pause (Option B) means a brief window where a deactivated account's subscription is still technically ACTIVE. | Med | Acceptable per D4's own precedent (session TTL window); Subscription's `is_due` already checks the pause window at run time, so worst case is the *next* daily-run cycle, not an immediate mis-charge — confirm this timing is inside the daily cut-off window in Step 3. |
| R2 | `AdminDisableUser` on the consumer pool blocks login, but any **already-issued** access token for that user keeps working until its own TTL, per D4 — a deactivated customer could still hit other authenticated endpoints briefly. | Med | Same accepted trade-off as MA-129's admin-side equivalent; no new mitigation invented here, consistent with the decision already made. |
| R3 | Subscription's `pause()` is currently hard-owned to `user_id`; wiring an admin/system path risks accidentally exposing a bypass of the ownership check to other callers. | Med | New consumer/method must be a distinct, narrowly-scoped internal entrypoint (event consumer or `/internal/*` route, not a parameter added to the existing customer-facing `pause()` that could be misused). |
| R4 | Wallet Service assumption ("no change needed") is inferred from current code, not from a Wallet spec author's confirmation. | Low | Flag explicitly in Step 3 decomposition proposal for the human approver to confirm or override before Wallet is dropped from scope. |
| R5 | Bulk action against a large selection with no shared transaction could partially succeed with no way to distinguish "processing" from "done" mid-flight. | Low | Per-row synchronous response (small N expected — admin console, not a data pipeline); explicitly out of scope: async/background bulk jobs for very large selections. |

### Operational Considerations

- **Observability:** CloudWatch metric on `user.status.changed` volume by `newStatus`; alarm on an unusual spike in `Deactivated` (possible bulk-action misuse or automation gone wrong) — mirrors MA-129's `admin.login.failed` alarm precedent.
- **Backward compatibility:** `status` defaults to `Active` for all existing rows — purely additive migration, same shape as MA-21's `account_type` column add.
- **Rollout:** Subscription's consumer can be dark-launched (deployed, not yet subscribed to the EventBridge rule) so User Service's core can ship and be verified independently first, then the Subscription integration follows — matches this Step 2's own recommendation to decouple the two.

---

### Decisions (human, this session)

- **D6.** Wallet Service is **dropped from build scope** — confirmed, per this section's finding: pausing the subscription already stops the orders that would trigger a debit, so there is nothing for Wallet to change. Kept only as a test assertion (balance/auto-debit unaffected), not a spec.
- **D7.** Subscription pause is wired **event-driven (Option B)** — User Service emits `user.status.changed`; Subscription Service consumes it and calls its own existing `pause(..., until=None)` internally. Accepted trade-off: a short eventually-consistent delay before the pause takes effect, consistent with D4's existing token-TTL precedent.

---

*Next: Step 3 — Decomposition proposal (halt for human approval).*
