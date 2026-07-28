# SDD Step 3 — Decomposition Proposal

**Story:** [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) User Login

---

### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for MA-21:

* ✓ **Flutter Login Flow** — `/login` screen(s) reached from MA-1's existing "Already registered? Log in" link: mobile number carried forward, 6-digit OTP verify (aligned with MA-1's convention — see note), resend, role-aware post-login landing (B2C/B2B), "remember me" session persistence, and a logout trigger. Reuses MA-1's shared mobile-entry screen unchanged — no new entry UI.
* ✓ **Identity & Auth — Login APIs** — `POST /auth/login/otp/send`, `POST /auth/login/otp/verify`, `POST /auth/logout`. Reuses MA-1's OTP infrastructure (hashing, 5-min expiry, 3-attempt lockout) under a distinct rate-limit key so login attempts don't share a counter with registration. Logout revokes only the current device's refresh token (Cognito `RevokeToken`), consistent with the "concurrent sessions allowed" decision.
* ✓ **User Service — Account Type & Profile Lookup** — adds `account_type` (B2C/B2B) to the `users` schema, defaulting all existing and new accounts to `B2C`; adds `GET /users/me` for the app to resolve role after login.

Confident specs are ready to proceed — no flagged/uncertain items remain; both open conflicts
identified in Step 2 (OTP length, account-type existence) were resolved in chat before this
proposal.

**Note carried into drafting (not a blocker):** MA-21's attached mockup shows a 5-digit OTP
entry, but the resolved decision is to keep 6-digit for consistency with MA-1's already-drafted
Identity & Auth spec. The Flutter Login Flow spec will note this as a design-asset inconsistency
for the design team to reconcile (mockup vs. implemented digit count), separate from engineering scope.

**To approve:** Transition MA-21 to **SDD: Drafting** (no comment needed).

**To modify:** Post `SDD-DECOMPOSITION-FEEDBACK` with Accept/Remove/Add/Modify, then transition to **SDD: Drafting**.

---

## Spec file paths (Step 4)

| Spec | Area | Path |
|------|------|------|
| Flutter Login Flow | mobile-app | `mobile-app/tasks/MA/MA-21/flutter-login-flow.md` |
| Identity & Auth — Login APIs | services | `services/tasks/MA/MA-21/identity-auth-login.md` |
| User Service — Account Type & Profile Lookup | services | `services/tasks/MA/MA-21/user-account-type-profile.md` |

## Jira tasks to create (Step 4, once live)

| Summary |
|---------|
| SDD: MA-21 - Flutter Login Flow |
| SDD: MA-21 - Identity & Auth Login APIs |
| SDD: MA-21 - User Service Account Type & Profile Lookup |

---

*Human approval required before Step 4 drafting. This dry-run proceeds with proposal-as-approved, consistent with the MA-1 precedent, since all decomposition-affecting decisions were already confirmed in chat.*
