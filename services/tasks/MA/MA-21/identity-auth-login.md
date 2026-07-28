# Identity & Auth — Login APIs

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) |
| **Related JIRA Task** | SDD: MA-21 - Identity & Auth Login APIs |
| **Backend Story** | [MA-92](https://milkfuldairyindia.atlassian.net/browse/MA-92) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-28 |

---

## 2. Problem Statement

Existing customers need to re-authenticate with their already-verified mobile number and receive
a fresh JWT session, without going through MA-1's registration/Cognito-user-creation path. This
service owns the login-specific OTP lifecycle and per-device session revocation on logout.

## 3. Scope

**In scope:** Login OTP send/verify for existing, verified Cognito users; JWT access + refresh
issuance via `InitiateAuth`; per-device logout (single refresh-token revocation).

**Out of scope:** New-user OTP/registration (MA-1, existing `/auth/otp/send` + `/auth/otp/verify`
— unchanged by this spec), social login (MA-1, unchanged), password/biometric/forgot-password
(excluded from MA-21 scope per Step 1), profile/account-type data (User Service — see
`user-account-type-profile.md`).

## 4. Functional Requirements

### FR-1: Send login OTP

`POST /auth/login/otp/send`

Request:

```json
{ "mobile": "+919876543210" }
```

- Validate E.164 +91, 10-digit Indian mobile (same validator as MA-1).
- Look up Cognito user by phone; if **no user exists** or `phone_number_verified=false` →
  `404 USER_NOT_FOUND` with `{ "redirect": "signup" }` — mirrors MA-1's `409 USER_EXISTS` /
  `redirect: "login"` symmetry in the opposite direction.
- If found and verified: generate 6-digit OTP, store hash + `requestId` in DynamoDB (TTL 5 min) —
  reuses the same `otp_requests` table as MA-1, distinguished by a `purpose: "LOGIN"` field.
- Publish SMS via Notification/SNS (`OtpRequested` event, `template: "login"`).
- Rate limit: 3 requests / 15 min / mobile, **tracked under a separate Redis key prefix**
  (`login:otp:{mobile}`) from MA-1's registration counter (`register:otp:{mobile}`) — a user
  mid-registration and a user attempting login on the same number must not exhaust each other's
  attempt budget.
- Response: `{ "requestId": "uuid", "expiresIn": 300, "resendAfter": 30 }`

### FR-2: Verify login OTP

`POST /auth/login/otp/verify`

Request:

```json
{ "mobile": "+919876543210", "otp": "123456", "requestId": "uuid" }
```

- Max 3 failed attempts per `requestId`; then invalidate (same policy as MA-1).
- On success: `InitiateAuth` against the existing Cognito user (no `AdminCreateUser` /
  `AdminConfirmSignUp` — those are MA-1-only, new-user operations).
- Issue Cognito tokens (access, refresh, id).
- Response: `{ "accessToken", "refreshToken", "expiresIn" }` — no `isNewUser` field (always
  `false` in this path by construction; field omitted rather than hardcoded to avoid confusing
  clients into branching on it).

### FR-3: Logout

`POST /auth/logout`
**Authorization:** Bearer JWT (Cognito access token).

Request:

```json
{ "refreshToken": "..." }
```

- Call Cognito `RevokeToken` for the supplied refresh token **only** — this revokes just the
  calling device's session, consistent with the "concurrent sessions allowed" product decision;
  it must not call `AdminUserGlobalSignOut`, which would revoke every device.
- Response: `204 No Content`, idempotent on an already-revoked token (still `204`, not an error).

### FR-4: Token refresh

Reuses MA-1's existing `POST /auth/token/refresh` — no changes required; both login-issued and
registration-issued refresh tokens are ordinary Cognito refresh tokens and refresh identically.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | login OTP verify p95 < 500ms; logout p95 < 300ms |
| Security | OTP hashed (bcrypt), same as MA-1; login attempt counter isolated from registration counter |
| Reliability | SMS failure → retry 2x with backoff (same as MA-1); logout must not fail closed — a `RevokeToken` error on an already-invalid token is not surfaced as a client error |

## 6. Technical Design

- **Compute:** AWS Lambda behind API Gateway (same stack as MA-1's Identity Auth).
- **Identity:** existing Amazon Cognito User Pool — no new pool or app client required.
- **OTP store:** existing DynamoDB `otp_requests` table, add `purpose` attribute
  (`"REGISTER" | "LOGIN"`) — additive schema change, no migration of existing rows required
  (absence of `purpose` on old rows is treated as `"REGISTER"`).
- **Rate limits:** ElastiCache Redis, new key prefix `login:otp:{mobile}` alongside MA-1's
  `register:otp:{mobile}`.

### API Gateway

- `/auth/login/otp/send`, `/auth/login/otp/verify` — **no authorizer** (pre-auth), same pattern
  as MA-1's registration OTP endpoints.
- `/auth/logout` — **Cognito authorizer required** (must be an authenticated request).

## 7. Data Considerations

**DynamoDB `otp_requests` (extended, not new):**

| Field | Type | Notes |
|-------|------|-------|
| requestId | S (PK) | UUID — unchanged |
| mobile | S | GSI — unchanged |
| otpHash | S | bcrypt — unchanged |
| attempts | N | max 3 — unchanged |
| ttl | N | epoch expiry — unchanged |
| purpose | S | **new** — `"REGISTER" \| "LOGIN"`; defaults to `"REGISTER"` when absent (back-compat with MA-1 rows written before this field existed) |

No new tables. No changes to the Cognito user pool schema (that's `user-account-type-profile.md`'s
concern, and it does not touch Cognito — see that spec).

## 8. Integration Considerations

| System | Contract |
|--------|----------|
| Cognito | `InitiateAuth` (existing-user login), `RevokeToken` (per-device logout) |
| Notification | EventBridge `OtpRequested` { mobile, otp, template: "login" } — same event shape as MA-1, differentiated by `template` |
| User Service | Not called by this spec — Flutter calls `GET /users/me` directly after receiving tokens (see `flutter-login-flow.md` FR-2) |

Errors: `400` validation, `401` invalid OTP, `404` user not found (login-specific — MA-1 uses
`409` for the inverse case), `429` rate limit.

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| Mobile registered but never completed OTP verification (partial MA-1 signup) | Treated as `404 USER_NOT_FOUND` (same as unregistered) — `phone_number_verified=false` is the gate, not mere Cognito user existence |
| Duplicate send while a valid login OTP is outstanding | Return same `requestId`, don't resend SMS until `resendAfter` (same as MA-1) |
| Cognito throttling | Exponential backoff, `503` to client (same as MA-1) |
| Logout called with an already-expired/revoked refresh token | `204` (idempotent — see FR-3) |
| Logout called without a body / malformed refresh token | `400` validation error — this is a genuine client error, unlike the idempotent-revoke case above |

## 10. Testing Strategy

- **Unit:** login vs. registration OTP-purpose branching, rate-limit key isolation, `RevokeToken`
  called with single-token scope (not global sign-out)
- **Integration:** Cognito test pool with a pre-seeded verified user (login path) and an
  unverified/absent user (404 path); mocked SNS
- **Negative:** expired OTP, brute-force lockout, logout with invalid token (must still be `204`),
  login attempt against an unregistered number

## 11. Risks and Trade-offs

- Reusing the `otp_requests` table (vs. a separate table) keeps infra simple but couples the two
  purposes in one schema — acceptable given both share the identical TTL/attempt/hash shape.
- `RevokeToken`-based per-device logout (vs. `AdminUserGlobalSignOut`) is the correct choice for
  the "concurrent sessions allowed" decision, but means a compromised-device scenario requiring
  "log out everywhere" is **not** covered by this spec — flagged as a future capability if
  product ever needs it (not needed for MA-21 as scoped).

## 12. Open Questions

| # | Question | Default assumed |
|---|----------|-----------------|
| Q1 | Should `login_otp_sent` volume feed the same CloudWatch alarm as registration, or a separate one? | Separate metric names (`login_otp_sent` vs. `otp_sent`), shared alarm threshold (>5% failure rate) unless traffic patterns diverge later |

## 13. Approval Notes

Depends on MA-1's Identity & Auth Registration APIs spec (shared Cognito pool, shared OTP table
shape). Must deploy before `flutter-login-flow.md` can be implemented end to end.
