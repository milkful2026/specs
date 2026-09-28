### SDD Step 1 — Analysis

**Story:** MA-39 — Enable / Disable User Account · Admin / User Management (Admin UI)
**Status:** SDD: Analyzing
**Sources:** NSMB App Feature Spec — Admin / Back-Office section (via Jira description); epic MA-20 (Admin-UI). No mock or attachment on the ticket. Blocked-by links: MA-92 (Identity & Auth Service), MA-93 (User Service).

---

#### User Story Summary

A Milkful admin/operations user needs to activate, deactivate (soft-block), suspend or reactivate any **customer/B2B account** from the admin console. Deactivation instantly blocks login, pauses active subscriptions and halts wallet auto-debits, while preserving order history and wallet balance. Every action captures a reason, an effective date and an audit-trail entry. Admins can act in bulk, and can search/filter accounts by status, KYC and risk flags. Optionally, accounts auto-disable on repeated failed payments or fraud signals.

#### User / Actor

- **Primary:** authenticated admin (Cognito admin pool, role-gated — built in MA-47).
- **Affected:** the customer/B2B account holder (Cognito consumer pool).
- **Secondary (systems):** Identity & Auth (login block), User Service (account record), Subscription Service (pause), Wallet Service (halt auto-debit), Audit log (MA-47 emits, MA-50 displays).

#### Goal and Business Outcome

- **Admin goal:** stop a problematic or fraudulent account immediately, and reverse it cleanly, with a defensible record of who did it and why.
- **Business outcome:** operational and financial risk control. A blocked account must not log in, be delivered to, or be debited — while the customer's history and money are preserved.

#### Ground truth today (from the repo, not the ticket)

- **`user` service has no account lifecycle.** `domain/models.py` has only `wallet_status` (`PENDING`); there is no active/suspended/deactivated state, reason, or effective date. Handlers are customer self-service only (`register`, `get_me`, `delivery_slots`).
- **The admin console already exists** (MA-47): portal-ui shell, admin Cognito pool, RBAC (5 fixed roles), admin authorizer, audit-event emission. MA-39 adds a *customer-accounts* screen to it and a role permission for it; it does not create the console.
- **Admin-user deactivate/reactivate already exists for admin accounts** (MA-47). MA-39 is the customer-side counterpart and must not be confused with, or duplicate, that flow.
- **Subscription and Wallet services are scaffolded** (`services/subscription`, `services/wallet`) but the pause and auto-debit-halt behaviours MA-39 requires do not exist yet.

#### Functional Intent (what, not how)

1. List and search customer accounts; filter by status, KYC state and risk flag.
2. Open an account and see its current status and status history.
3. Deactivate / suspend / reactivate a single account, capturing a required reason and an effective date.
4. Deactivation takes effect immediately for new logins; already-issued access tokens expire on their normal TTL (D4).
5. Deactivation pauses active subscriptions and stops wallet auto-debits; history and wallet balance are untouched.
6. Reactivation restores login; paused subscriptions stay paused until explicitly resumed (D2).
7. Bulk enable/disable for a selected set of accounts, with a per-account result.
8. Every action is written to the audit log (who, what, when, why).
9. Suspension carries an end date and lifts automatically; deactivation stays until an admin reactivates (D1).
10. *Deferred (D3):* automatic disable on repeated payment failures or fraud signals.

#### Initial Acceptance Criteria → spec-boundary mapping

| # | Acceptance criterion (draft, observable) | Likely spec owner |
|---|------------------------------------------|-------------------|
| AC-1 | An admin with the right role sees a customer list and can filter by status; other roles get 403 / no nav entry. | Portal-UI + Identity/User |
| AC-2 | Deactivating with a reason and effective date changes the account's status and records who/when/why. | User Service |
| AC-3 | A deactivated customer's next login is refused with a clear message, and any live session stops working when its access token expires (D4). | Identity & Auth |
| AC-4 | Active subscriptions of a deactivated account are paused and no auto-debit runs; wallet balance and order history are unchanged. | Subscription + Wallet |
| AC-5 | Reactivation restores login; paused subscriptions remain paused (D2). A Suspended account returns to Active on its end date. | User + Subscription |
| AC-6 | Bulk action reports per-account success/failure; one failure does not roll back the others. | Portal-UI + User Service |
| AC-7 | Every status change emits an audit event with actor, target, reason, timestamp. | User Service (emits) |
| AC-8 | An admin cannot be locked out by this feature: it only ever targets customer/B2B accounts. | User Service |

#### In Scope (proposed)

- Customer-accounts list/search/filter-by-status and detail screen in portal-ui, under the existing RBAC.
- Status lifecycle on the customer account (data model, transitions, reason, effective date, history).
- Login blocking for non-active accounts and session cut-off.
- Event-driven pause of subscriptions and halt of auto-debit on deactivation.
- Bulk enable/disable.
- Audit event emission for every change.

#### Out of Scope (proposed)

- Admin-account management (done in MA-47).
- Audit-log *viewer* UI (MA-50) — MA-39 only emits.
- KYC capture/verification itself and fraud scoring — MA-39 may *filter by* these if the data exists, but does not build them.
- Customer-facing appeal / notification copy (Notification Service, MA-103).
- Hard delete / GDPR-style erasure.

#### Assumptions

- A1. The `user` service is the system of record for customer account status; Identity & Auth enforces it at login.
- A2. Status changes propagate to Subscription and Wallet through EventBridge events, not synchronous calls.
- A3. The admin-facing API lives behind the existing admin authorizer with a new permission (e.g. `customers:manage`) added to the fixed role set.
- A4. "Instantly blocks login" means new sign-ins are refused at once; already-issued tokens expire on their normal TTL (D4).

#### Resolved decisions (human, this session — not open questions)

- **D1 (Q2).** Two states: **Suspended** (temporary, with an end date) and **Deactivated** (indefinite until an admin reactivates), plus Active.
- **D2 (Q3).** On reactivation, paused subscriptions **stay paused** until the customer or an admin resumes them explicitly.
- **D3 (Q4).** Auto-disable on failed payments / fraud signals is **deferred**; v1 is manual only.
- **D4 (Q5).** New logins are blocked at once; already-issued access tokens **expire on their normal TTL** (no Cognito global sign-out in v1).
- **D5 (Q6).** Decomposition is **full cross-area**: portal-ui + User + Identity & Auth + Subscription + Wallet.

#### Items to settle in Step 2–3 (proposed resolutions — none blocks decomposition)

- **Q1 — B2B and KYC/risk filters.** Nothing in the repo stores KYC state, risk flags or a B2B account type. Proposed: v1 treats every customer account uniformly; the list filters by **status** (and search by name/phone/email) only; KYC and risk-flag filters are deferred until that data exists.

#### Impacted areas (Jira Components)

- **`portal-ui`** — customer-accounts screens, bulk action, RBAC nav entry.
- **`services`** — User Service (status model + admin API + events), Identity & Auth (login/session enforcement), Subscription (pause consumer), Wallet (auto-debit halt consumer).
- No `mobile-app` impact beyond the login error message for a blocked account.

---

*Next: Step 2 — Build Technical Context (well-architected guardrails, HLD/LLD, EventBridge event map for `AccountStatusChanged`, existing User/Identity/Subscription/Wallet specs, Cognito session-revocation constraints).*
