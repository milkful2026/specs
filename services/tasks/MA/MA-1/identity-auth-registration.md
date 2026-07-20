# Identity & Auth — Registration APIs

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) |
| **Related JIRA Task** | SDD: MA-1 - Identity & Auth Registration APIs |
| **Backend Story** | [MA-92](https://milkfuldairyindia.atlassian.net/browse/MA-92) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-20 |

---

## 2. Problem Statement

Registration requires verified mobile identity and optional social federation before
User Service creates the profile. This service owns OTP lifecycle, Cognito user pool
integration, and JWT issuance.

## 3. Scope

**In scope:** OTP send/verify, social token exchange, Cognito user creation for new users,
existing-user detection, rate limiting, JWT access + refresh tokens.

**Out of scope:** Profile/address persistence (User Service), SMS template admin (Notification MA-103).

## 4. Functional Requirements

### FR-1: Send OTP

`POST /auth/otp/send`

Request:

```json
{ "mobile": "+919876543210" }
```

- Validate E.164 +91 and 10-digit Indian mobile.
- If Cognito user exists with `phone_number_verified=true` → `409 USER_EXISTS` with `{ "redirect": "login" }`.
- Generate 6-digit OTP, store hash + `requestId` in DynamoDB (TTL 5 min).
- Publish SMS via Notification/SNS.
- Rate limit: 3 requests / 15 min / mobile (Redis counter).
- Response: `{ "requestId": "uuid", "expiresIn": 300, "resendAfter": 30 }`

### FR-2: Verify OTP

`POST /auth/otp/verify`

Request:

```json
{ "mobile": "+919876543210", "otp": "123456", "requestId": "uuid" }
```

- Max 3 failed attempts per `requestId`; then invalidate.
- On success: create or confirm Cognito user; set `phone_number_verified`.
- Issue Cognito tokens (access, refresh, id).
- Response: `{ "accessToken", "refreshToken", "expiresIn", "isNewUser": true|false }`

### FR-3: Social auth

`POST /auth/social`

Request:

```json
{ "provider": "google|apple", "idToken": "..." }
```

- Validate idToken against provider JWKS.
- Extract email, sub; link or create Cognito federated identity.
- **Flagged (G1):** If mobile not verified, return `{ "requiresMobileVerification": true, "partialToken" }` — mobile OTP still required before full registration complete.

### FR-4: Token refresh

`POST /auth/token/refresh` — standard Cognito refresh flow.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | verify p95 < 500ms |
| Security | OTP hashed (bcrypt); WAF rate limit on send |
| Reliability | SMS failure → retry 2x with backoff; surface error to client |

## 6. Technical Design

- **Compute:** AWS Lambda behind API Gateway
- **Identity:** Amazon Cognito User Pool (phone username attribute)
- **OTP store:** DynamoDB `otp_requests` (requestId PK, mobile GSI)
- **Rate limits:** ElastiCache Redis
- **SMS:** Publish `OtpRequested` event → Notification Service → SNS

### API Gateway

- `/auth/otp/send`, `/auth/otp/verify`, `/auth/social` — **no authorizer** (pre-auth)
- `/auth/token/refresh` — no authorizer

## 7. Data Considerations

**DynamoDB `otp_requests`:**

| Field | Type | Notes |
|-------|------|-------|
| requestId | S (PK) | UUID |
| mobile | S | GSI |
| otpHash | S | bcrypt |
| attempts | N | max 3 |
| ttl | N | epoch expiry |

## 8. Integration Considerations

| System | Contract |
|--------|----------|
| Cognito | AdminCreateUser, AdminConfirmSignUp, InitiateAuth |
| Notification | EventBridge `OtpRequested` { mobile, otp, template } |
| User Service | Consumes Cognito `sub` on register — no direct DB access |

Errors: 400 validation, 401 invalid OTP, 409 user exists, 429 rate limit.

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| Duplicate send while valid OTP | Return same requestId, don't resend SMS until resendAfter |
| Cognito throttling | Exponential backoff, 503 to client |
| Social email already linked to other mobile | 409 with merge instruction code |

## 10. Testing Strategy

- **Unit:** OTP generation, hash verify, rate limit logic
- **Integration:** Cognito test pool, mocked SNS
- **Negative:** expired OTP, brute force lockout, invalid social token

## 11. Risks and Trade-offs

- Cognito SMS vs custom OTP — using custom OTP + SNS for template control.
- Social-without-mobile policy deferred (G1).

## 12. Open Questions

| # | Question |
|---|----------|
| Q1 | 4 vs 6 digit OTP — **default 6** |
| Q2 | Social account merge UX — product decision |

## 13. Approval Notes

Blocks MA-1 mobile OTP and social flows. Must deploy before User registration E2E.
