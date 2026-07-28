# SDD Step 1 — User Story Analysis

**Story:** [MA-21 User Login — Authentication (Flutter)](https://milkfuldairyindia.atlassian.net/browse/MA-21)
**Epic:** MA-18 (Flutter Mobile App)
**Status at analysis:** To Do (SDD custom workflow statuses not yet configured on the MA project — proceeding in dry-run mode, consistent with the MA-1 pilot)
**Source:** Jira ticket description, NSMB App Feature Spec row 2.0 (`docs/jira/attachments/nsmb-app-feature-spec.txt`), 2 attached mockups (`image-20260724-175400.png`, `image-20260724-175420.png`)

---

## Business intent

Returning Milkful customers must be able to securely authenticate with their mobile number so
they can access the full milk delivery service — browsing, ordering, subscriptions, wallet — on
Android and iOS. The session must persist ("remember me") so customers aren't forced to
re-authenticate on every app open, while still supporting secure logout and B2C/B2B role
awareness post-login.

## Actors

| Actor | Role |
|-------|------|
| Returning customer | Primary — logs in via mobile + OTP on the Flutter app |
| New customer | Arrives at the same mobile-entry screen; branches to MA-1 registration instead of login |
| Identity & Auth service (MA-92) | OTP send/verify, JWT + refresh token issuance, session/logout |
| User service (MA-93) | Account lookup (existing vs. new), B2C/B2B role/type |

## Functional summary

1. Mobile number entry on the shared "Get Started" screen (same screen as MA-1 registration).
2. OTP send + verify — **5-digit code** (per mockup `image-20260724-175420.png`; this supersedes
   the 4-vs-6-digit ambiguity flagged as G4 during MA-1's analysis).
3. Backend OTP-verify response distinguishes existing account (→ login-complete) from new
   number (→ continues into MA-1 registration) — no separate login entry screen.
4. JWT session issuance with secure token storage; "remember me" = persistent session across
   app restarts.
5. Session timeout / token refresh handling.
6. Multi-device handling — **concurrent sessions allowed** (confirmed with product); a login on
   a new device does not revoke sessions elsewhere.
7. Secure logout (client token clear + server-side refresh-token revocation for that session).
8. Role awareness — B2C vs. B2B account type surfaced to the app immediately after login.
9. Social login buttons (Google/Apple) are visible on the shared entry screen mockup — these
   belong to the already-specced MA-1 Identity & Auth registration/social-link flow; MA-21 does
   not re-spec them, but the login branch must accept an already-linked social identity the same
   way it accepts mobile+OTP (existing-account detection is identity-agnostic).

## Scope decisions (resolved in chat before this analysis was finalized)

| Decision | Resolution |
|----------|------------|
| Password login / biometric (Face ID, fingerprint) / forgot-password | **Out of scope for MA-21.** NSMB source row 2.0 lists these, but the actual MA-21 Jira ticket text only specifies mobile+OTP — treated as the authoritative, trimmed scope. Deferred to a later story. |
| Multi-device session policy | **Concurrent sessions allowed.** No cross-device revocation on new login. |
| Entry screen | **Reused from MA-1**, not rebuilt. MA-21 adds the login branch (existing-user routing), the OTP-verify screen behavior for returning users, post-login landing, session persistence, and logout — it does not duplicate the mobile-number entry UI. |

## Acceptance criteria coverage

| AC | Summary | Spec boundary |
|----|---------|---------------|
| AC-1 | Mobile number entry (reused MA-1 screen) | Flutter UI (no new build — dependency on MA-1) |
| AC-2 | OTP send / 5-digit verify | Flutter UI + Identity Auth API (MA-92) |
| AC-3 | Existing-user detection routes to login, not registration | Identity Auth + User API (MA-92 + MA-93) |
| AC-4 | JWT + refresh token issuance, secure storage, "remember me" persistence | Flutter + Identity Auth |
| AC-5 | Session timeout / silent token refresh | Flutter + Identity Auth |
| AC-6 | Concurrent multi-device sessions | Identity Auth (session model) |
| AC-7 | Secure logout (client + server-side revocation) | Flutter + Identity Auth |
| AC-8 | B2C vs. B2B role awareness post-login | Flutter + User API |
| AC-9 | Already-linked social identity (Google/Apple) can complete login | Identity Auth (reuses MA-1 social token exchange) |

## In scope / out of scope

**In scope:**
- Mobile + OTP login for existing accounts (5-digit OTP)
- Existing-user vs. new-user branching on the shared entry screen
- JWT/refresh-token session issuance, secure storage, persistence ("remember me")
- Session timeout and token refresh
- Concurrent multi-device sessions
- Secure logout with server-side session revocation
- B2C/B2B role awareness surfaced after login
- Social login (Google/Apple) as a login path for accounts already linked via MA-1

**Out of scope (this story):**
- Password-based login (NSMB row 2.0 — deferred)
- Biometric login / Face ID / fingerprint (NSMB row 2.0 — deferred)
- Forgot-password flow (NSMB row 2.0 — deferred; not applicable while OTP-only)
- New-user registration flow (MA-1, already specced)
- Admin/staff login, 2FA, RBAC (separate epic row 28.0 — Admin / Security)
- B2B-specific catalog/pricing behavior post-login (future story)

## Assumptions

- OTP length is 5 digits, per mockup (overrides MA-1's unresolved G4).
- "Remember me" reuses MA-1's established JWT convention (access 15 min / refresh 30 days)
  unless Step 2 architecture context indicates otherwise — flagged for confirmation in Step 2.
- Social login buttons on the entry screen are MA-1-owned UI; MA-21 only needs the backend
  login branch to accept an already-linked identity, not new social-link UI.
- "Existing account" is determined server-side (Identity Auth / User service) from the OTP-verify
  response — Flutter does not pre-check account existence client-side.

## Open questions

None blocking — the three scope-defining ambiguities (password/biometric scope, multi-device
policy, entry-screen ownership) were resolved in chat prior to this analysis. One item carried
into Step 2 for confirmation rather than escalation:

| # | Item | Impact |
|---|------|--------|
| Q1 | Exact JWT access/refresh token lifetimes for "remember me" — reuse MA-1's 15min/30-day convention or does login need a shorter default (not-remembered) vs. longer (remembered) split? | Identity Auth spec — Non-Functional Requirements |

## Prior SDD comments

None found. Two non-SDD comments present: an admin note asking that the story be assigned to a
developer, and the two attached mockup images (reposted as a comment on 2026-07-24).

## Impacted areas

- `mobile-app` — login branch on existing entry screen, OTP-verify (login path), session
  persistence, logout, post-login role-aware landing
- `services` — Identity & Auth (MA-92): OTP verify/login branch, JWT/refresh issuance, session
  revocation; User (MA-93): existing-account lookup, B2C/B2B role exposure
- `portal-ui` — none for MA-21 (admin login/RBAC is epic row 28.0, separate story)

---

*Step 1 output — dry-run (local file; no Jira write). Next: Step 2 Build Technical Context.*
