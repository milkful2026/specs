# SDD Step 2 — Technical Context

**Story:** MA-21 User Login
**Areas loaded:** `mobile-app`, `services` (portal-ui not applicable)
**Layer 3 prior specs read:** MA-1 `identity-auth-registration.md` (MA-92), MA-1 `user-registration-api.md` (MA-93), MA-1 `flutter-registration-onboarding.md`

---

## Current state summary

Milkful is in design/early-implementation phase — no production Flutter or backend code exists
yet (`{area}/docs/` built-state folders are empty for both `mobile-app` and `services`). MA-21 is
the second story through the SDD pipeline and is **not greenfield**: it sits directly downstream
of MA-1's already-drafted Identity & Auth (MA-92) and User (MA-93) specs, which explicitly
anticipated login as a follow-on story.

**Key finding from Layer 3:** MA-1's Identity & Auth spec (FR-1, `POST /auth/otp/send`) already
detects existing accounts: if a Cognito user exists with `phone_number_verified=true`, it returns
`409 USER_EXISTS` with `{ "redirect": "login" }` and does **not** issue an OTP. MA-1's Flutter
spec (FR-1) already renders an inline "Already registered? **Log in**" link on that response,
routing to `/login` — a route MA-1 explicitly lists as out of scope and left unbuilt. **MA-21 is
that route.** This confirms and sharpens the Step 1 assumption: the mobile-number *entry* screen
is fully reused, but MA-21 still owns a distinct `/login` screen (and backend endpoints) reached
from it — it is not simply a branch inside MA-1's existing OTP-verify screen.

## Impacted systems

| System | Change type | Notes |
|--------|-------------|-------|
| Flutter mobile app | New | `/login` route(s): mobile re-entry (or carried-forward number) + OTP verify + post-login landing + logout affordance |
| API Gateway | Extend | New `/auth/login/otp/send`, `/auth/login/otp/verify` routes (pre-auth); `/auth/logout` (authorized) |
| Identity & Auth (Lambda + Cognito) | Extend | Login-specific OTP/InitiateAuth path, refresh-token revocation on logout |
| User Service (Lambda) | Extend | `GET /users/me` (or equivalent) to resolve account type (B2C/B2B) for post-login role awareness |
| EventBridge | New event | `UserLoggedIn` (optional, for Reporting/analytics — confirm need in Step 3) |

## Dependencies

| Upstream | Downstream | Contract |
|----------|------------|----------|
| Flutter app (shared entry screen, MA-1) | Flutter `/login` (MA-21) | Navigation on `409 USER_EXISTS` — already built by MA-1 |
| Flutter `/login` | Identity Auth | `POST /auth/login/otp/send`, `POST /auth/login/otp/verify` (new) |
| Identity Auth | Cognito | `InitiateAuth` (CUSTOM_AUTH or USER_AUTH flow for existing user), `RevokeToken` on logout |
| Flutter (post-login) | User Service | Account type (B2C/B2B) lookup for role-aware landing |

## Architecture notes

```
Flutter App — shared "Get Started" screen (MA-1, already built)
    │ mobile number → POST /auth/otp/send
    ▼
Identity Auth (MA-92, already specced)
    │
    ├─ new number → 200, proceed to MA-1 registration OTP flow (unchanged)
    └─ existing, verified number → 409 USER_EXISTS { redirect: "login" }
                │
                ▼
        Flutter navigates to /login  ◄── MA-21 builds from here
                │ mobile number carried forward (or re-entered)
                ▼
        POST /auth/login/otp/send        → Identity Auth (MA-21, new)
                │
                ▼
        OTP verify screen (mockup: 5-digit boxes, "Verify & Proceed")
                │
                ▼
        POST /auth/login/otp/verify      → Identity Auth (MA-21, new)
                │  issues access + refresh JWT (Cognito InitiateAuth)
                ▼
        GET /users/me (or equivalent)    → User Service (MA-93, extend)
                │  { accountType: B2C | B2B, ... }
                ▼
        Flutter: persist session ("remember me"), role-aware home landing
                │
        Logout → POST /auth/logout       → Identity Auth (revoke this refresh token only)
```

- **Stateless services (Well-Architected doc):** no server-side session store; identity travels
  in the JWT. This has a direct design consequence for the "concurrent sessions" decision below.
- **Per-device logout is feasible:** Cognito supports `RevokeToken` on a single refresh token
  (as opposed to `AdminUserGlobalSignOut`, which revokes *all* sessions for the user). Logout
  should call `RevokeToken` for the current device's refresh token only — this is what makes
  "concurrent sessions allowed, no cross-device revocation on new login" architecturally
  consistent with a normal logout still working per-device.

## Data / integration considerations

No new entities. MA-21 reads existing `users` (MA-1/User Service) and Cognito user pool records;
it does not create or modify the `users`, `addresses`, or `user_consents` tables.

| Entity | Owner | Relevant fields for MA-21 |
|--------|-------|----------------------------|
| Cognito user | Identity Auth | `phone_number_verified`, refresh/access tokens |
| `users` | User Service | `id`, `cognito_sub`, account type (**gap** — see below) |

**Gap:** MA-1's `users` schema (`identity-auth-registration.md` / `user-registration-api.md`) has
no `account_type` (B2C/B2B) column or equivalent Cognito custom attribute. AC-8 (role awareness)
cannot be satisfied without one. This must be added — either as a User Service schema change
(new nullable column, backfilled B2C by default) or a Cognito custom attribute (`custom:account_type`).
Flagged for Step 3 as a scope item on the User Service side.

## Constraints and guardrails

- Indian mobile: +91, 10 digits (unchanged from MA-1).
- OTP rate limiting: MA-1 established 3 sends / 15 min / mobile for registration; login should
  follow the same pattern (same abuse-prevention rationale) unless product wants a separate limit.
- JWT: MA-1 assumed access 15 min / refresh 30 days — Step 1 Q1 (remember-me lifetimes) still
  open; **default to reusing MA-1's convention** unless the spec review raises it.
- **OTP length conflict (flag for Step 3):** MA-1's Identity & Auth spec hardcodes a 6-digit OTP
  (`identity-auth-registration.md` FR-2: `"otp": "123456"`) and MA-1's Flutter spec builds a
  6-cell `pinput`. MA-21's attached mockup (`image-20260724-175420.png`, uploaded 2026-07-24,
  four days after MA-1's spec was drafted) shows a **5-digit** OTP entry. Since both stories
  share the same OTP-generation logic in Identity & Auth (MA-92), this is a genuine cross-spec
  inconsistency, not just an MA-21-local detail — resolving it either way has a side effect on
  MA-1. Carried into Step 3 as a flagged item rather than assumed silently.

## Security

- Login OTP endpoints are pre-auth (no API Gateway authorizer), same as MA-1's `/auth/otp/*`.
- Reuse MA-1's OTP hashing (bcrypt), 5-min expiry, max-3-attempt lockout pattern for the new
  login OTP endpoints — no reason to diverge.
- Logout must invalidate the refresh token server-side (`RevokeToken`), not just clear it
  client-side, so a captured refresh token can't be replayed after logout.

## Performance expectations

| Endpoint | Target p95 | Basis |
|----------|------------|-------|
| Login OTP send | < 2s (incl. SMS) | Matches MA-1 registration OTP send |
| Login OTP verify | < 500ms | Matches MA-1 registration OTP verify |
| `GET /users/me` (role lookup) | < 300ms | Simple keyed read |
| Logout | < 300ms | Single `RevokeToken` call |

## Observability

- Reuse MA-1's correlation ID convention (`X-Request-Id` end to end).
- New metrics: `login_otp_sent`, `login_otp_verified`, `login_failed`, `logout_completed`.
- CloudWatch alarm: login OTP failure rate > 5% (mirrors MA-1's registration alarm).

## Operational considerations

- No new feature flag needed (login is not conditionally rolled out the way social registration
  was) — confirm in Step 3 if product wants a staged rollout.
- No DLQ needed unless `UserLoggedIn` analytics event is added (EventBridge, best-effort, non-critical path).

## Risk register

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| OTP length mismatch between MA-1 (6-digit) and MA-21 mockup (5-digit) ships inconsistently | Medium | Resolve explicitly in Step 3 decomposition before drafting either spec further |
| `account_type` field doesn't exist yet — AC-8 blocked | Medium | Add as explicit User Service scope item in MA-21's decomposition, not assumed pre-existing |
| Reusing MA-1's rate-limit counter keyed only by mobile could conflate registration and login attempts | Low | Use a distinct Redis key prefix for login OTP attempts |
| Per-device logout relies on client sending the correct refresh token to `RevokeToken` | Low | Standard Cognito SDK behavior; document in Identity Auth spec's edge cases |

---

*Step 2 output — dry-run (local file; no Jira write). Next: Step 3 Decomposition Proposal.*
