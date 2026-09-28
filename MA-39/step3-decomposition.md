### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for **MA-39 — Enable / Disable User Account · Admin / User Management (Admin UI)**:

---

* **✓ User Service — Customer Account Status** — `services` (MA-93) · spec path `services/tasks/MA/MA-93/{KEY}.md`
  Owns the new capability end to end. Schema: `users.status` (Active/Suspended/Deactivated, default Active), `status_reason`, `status_effective_from`, `suspended_until`, plus a `user_status_history` table (reason/actor/timestamp per change — a durable fallback source of truth until MA-50's audit pipeline exists). New admin-only endpoints (behind the existing admin authorizer + a new `customers:manage` permission): list/search/filter-by-status, get-detail-with-history, `suspend` / `deactivate` / `reactivate` (single + bulk, per-row independent so one failure doesn't roll back others). Extends `CognitoAttributePort` with `disable_user`/`enable_user` (consumer-pool `AdminDisableUser`/`AdminEnableUser` — a first use of these two Cognito Admin APIs in this codebase, not an existing MA-129 pattern; see the corrected note below), expected to block new logins immediately pending the Identity & Auth error-mapping check below. A background sweep (mirrors Subscription's own Daily Run shape) auto-lifts `Suspended` accounts past `suspended_until` back to `Active`. Publishes `user.status.changed` via the existing transactional-outbox pattern (same precedent as `UserRegistered`) — this spec is the event's contract owner; the Subscription spec below references it rather than redefining it. Includes the "Integration Considerations" note that Identity & Auth's `UserDisabledException` handling needs a small implementer check (not a spec) — see notes below. One engineer / one sprint.

* **✓ Subscription Service — Admin-triggered pause consumer** — `services` (MA-98) · spec path `services/tasks/MA/MA-98/{KEY}.md`
  New EventBridge consumer (`subscription-events-q` + DLQ, idempotent) for `user.status.changed`: on `newStatus ∈ {Suspended, Deactivated}`, calls the *existing* `pause(subscription_id, until=None)` internally for every active subscription owned by that user, via a new narrowly-scoped internal entrypoint (not a parameter bolted onto the customer-facing `pause()`, to avoid widening its ownership check). On `newStatus = Active` (reactivation), per D2 (resolved in Step 1) it does **not** auto-resume — paused-by-admin subscriptions stay paused until the customer or an admin resumes them explicitly, so this consumer only acts on the pause direction. No schema change — reuses `SubscriptionStatus.PAUSED` / `pause_from` / `pause_until` as they exist today. One engineer / a few days (small, since the underlying pause mechanism is already built).

* **✓ Portal-UI — Customer Accounts screens** — `portal-ui` (MA-20/Admin-UI) · spec path `portal-ui/tasks/MA/MA-20/{KEY}.md`
  New "Customer Accounts" section under the existing MA-47/MA-128 admin console and RBAC (gated on the new `customers:manage` permission — other roles get no nav entry). List with search (name/phone/email) and status filter; detail view showing current status + history; suspend (reason + end date) / deactivate (reason) / reactivate actions with a confirmation step; bulk select + bulk action with a per-row result summary (matching the User Service API's per-row independence). Reuses MA-128's existing shell, table, and role-gating patterns — no new infra, same Vite + React + TS + MUI stack. One engineer / one sprint.

---

* **⚠ Wallet Service — explicitly excluded**
  Step 2 found Wallet needs no code change: it only debits via `debit_for_order`, which only fires when Subscription generates an order, and a paused subscription never generates one. **Decision (D6, confirmed in chat):** drop Wallet from build scope entirely — not spec'd, not touched. The only trace of this in the delivered work is a test assertion (wallet balance/auto-debit unaffected by a deactivation) inside the Subscription or User Service spec's test plan.

* **⚠ Identity & Auth — folded in, not a separate spec**
  Step 2 found the login-block requirement (AC-3) should be satisfiable "for free" by Cognito's own `AdminDisableUser`/`UserDisabledException` behavior once User Service calls it, *if* the consumer login flow surfaces that exception cleanly. **Correction:** this is *not* an already-proven mechanism — MA-129's admin-deactivation feature, initially cited here as precedent, actually uses a different approach entirely (`services/identity-auth/src/domain/admin_users/user_service.py:299-337`: an Aurora status column checked explicitly at login, plus a best-effort `AdminUserGlobalSignOut`), and never calls `AdminDisableUser`/`AdminEnableUser` at all. So there is no existing precedent in this codebase for `UserDisabledException` surfacing cleanly through the consumer OTP login flow — this is genuinely unverified, not a known-good pattern being reused. **Leaning (revised):** still fold this into the User Service spec's Integration Considerations rather than opening a fourth spec, since the *scope* of the likely change is still small (an exception-mapping catch in `login_otp_send_handler.py`/`login_otp_verify_handler.py`, at most) — but the implementer check must happen early (a spike before or at the start of implementation, not a deferred checklist item), since if `UserDisabledException` doesn't map cleanly, real `services/identity-auth` code changes are needed that this decomposition has not estimated. Flagging so the reviewer can instead ask for a dedicated Identity & Auth spec if they'd rather have it tracked as its own artifact, or ask that the spike happen before Step 3 is re-approved.

---

#### Notes for the reviewer

- **Three specs, not five.** Step 1 assumed full cross-area (portal-ui + User + Identity & Auth + Subscription + Wallet, D5). Step 2's read of the actual code narrowed that to three specs — Wallet dropped entirely (D6, confirmed), Identity & Auth folded into User Service as a checklist item rather than spec'd separately. This is a real scope reduction from what was approved in Step 1, not a reviewer-transparent detail — please confirm you're comfortable with three specs before this proceeds to Drafting.
- **Event-driven pause (D7, confirmed).** Subscription reacts to `user.status.changed` rather than User Service calling it synchronously. Accepted trade-off: a short eventually-consistent delay before a deactivated customer's subscriptions actually pause — same class of window already accepted for session/token expiry (D4).
- **No B2B/KYC filtering in v1** (per Step 1's proposed resolution, not re-litigated here) — the list filters by status and searches by name/phone/email only; nothing in the repo stores KYC state or a B2B flag today.
- **Reactivation does not auto-resume subscriptions** (D2) — this is a one-directional consumer (pause only); resuming stays a distinct, existing, customer/admin-initiated action untouched by this story.

---

**To approve as-is (3 specs, Wallet excluded, Identity & Auth folded into User Service):** transition MA-39 → `SDD: Drafting`.
**To modify (e.g. break Identity & Auth out as its own spec, or reinstate Wallet):** post `SDD-DECOMPOSITION-FEEDBACK` (Accept / Remove / Add / Modify), then transition → `SDD: Drafting`.
**To reject:** transition → `SDD: Building Context` and post `SDD-FEEDBACK`.
