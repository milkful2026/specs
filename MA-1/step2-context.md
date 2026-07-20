# SDD Step 2 — Technical Context

**Story:** MA-1 User Registration  
**Areas loaded:** `mobile-app`, `services` (portal-ui not applicable)

---

## Current state summary

Milkful is in **design / early implementation** phase. Architecture is defined in
`docs/design/milkful-well-architected.md` with AWS Well-Architected patterns: VPC multi-AZ,
Cognito JWT, API Gateway BFF, EventBridge + SQS messaging, database-per-service.

No production Flutter or backend code exists in this repo yet; specs define the target state.

## Impacted systems

| System | Change type | Notes |
|--------|-------------|-------|
| Flutter mobile app | New | Onboarding module, 7-screen flow |
| API Gateway | Extend | New `/auth/*`, `/users/register`, `/serviceability/*` routes |
| Identity & Auth (Lambda + Cognito) | New | OTP, social federation, JWT |
| User Service (Lambda) | New | Registration orchestration, profile, addresses |
| Inventory Service (Fargate) | Extend | Serviceability check endpoint |
| Wallet Service (Fargate) | Extend | Auto-provision on `UserRegistered` event |
| Notification Service (Lambda) | Extend | OTP SMS via SNS |
| EventBridge | New events | `UserRegistered`, `WalletCreated` |

## Dependencies

| Upstream | Downstream | Contract |
|----------|------------|----------|
| Flutter app | API Gateway | HTTPS + Cognito JWT (post-auth) |
| Identity Auth | SNS / SMS provider | OTP delivery |
| Identity Auth | Google/Apple | OAuth idToken validation |
| User Service | Inventory | `GET /serviceability/check` |
| User Service | Wallet | Event `UserRegistered` → wallet create |
| User Service | Cognito | AdminCreateUser / attribute sync |

## Architecture notes

```
Flutter App
    │ HTTPS
    ▼
API Gateway (Cognito authorizer on protected routes)
    ├── POST /auth/otp/send          → Identity Auth Lambda
    ├── POST /auth/otp/verify        → Identity Auth Lambda
    ├── POST /auth/social            → Identity Auth Lambda
    ├── GET  /serviceability/check   → Inventory Fargate (via ALB)
    ├── GET  /delivery/slots         → User Lambda (zone slots from config)
    └── POST /users/register         → User Lambda
                                          │
                                          ├─► Aurora users DB
                                          ├─► Inventory (serviceability re-check)
                                          └─► EventBridge: UserRegistered
                                                    │
                                                    ▼
                                              Wallet Service → Aurora wallet DB
                                              Notification → welcome SMS (optional)
```

- **Stateless services:** JWT carries `sub`, `phone_number`, roles; no server sessions.
- **Registration saga:** User Service owns the transaction; Wallet creation is async via event with idempotency key = `userId`.
- **Maps:** Google Maps SDK in Flutter; geocoding via Google Places API (keys in Secrets Manager).

## Data / integration considerations

| Entity | Owner | Key fields |
|--------|-------|------------|
| `users` | User Service | id, cognito_sub, name, mobile, email?, default_address_id, preferred_slot, consents[] |
| `addresses` | User Service | id, user_id, lat, lng, lines, pincode, is_default |
| `serviceability_zones` | Inventory | pincode_prefix, polygon, active, slot_config |
| `wallets` | Wallet Service | id, user_id, balance, currency, status |

## Constraints and guardrails

- Indian mobile: +91, 10 digits; OTP rate limit 3 sends / 15 min / number.
- PCI: no card data in registration flow.
- PII: mobile, address encrypted at rest (KMS); consent timestamps auditable.
- App Store: Apple Sign-In required if Google offered on iOS.
- JWT: access 15 min, refresh 30 days; stored in `flutter_secure_storage`.

## Security

- Cognito User Pool with phone as username (primary).
- OTP hashed server-side; 5 min expiry; max 3 verify attempts per requestId.
- Social tokens validated against Google/Apple JWKS; never trust client-only claims.
- API Gateway WAF: rate limiting on `/auth/otp/send`.

## Performance expectations

| Endpoint | Target p95 |
|----------|------------|
| OTP send | < 2s (incl. SMS) |
| OTP verify | < 500ms |
| Serviceability check | < 300ms (Redis cache for pincode) |
| Register | < 1s |

## Observability

- Correlation ID: `X-Request-Id` from API Gateway through all services.
- Metrics: `otp_sent`, `otp_verified`, `registration_completed`, `registration_failed`, `serviceability_rejected`.
- CloudWatch alarms on OTP failure rate > 5%, registration error rate > 2%.

## Operational considerations

- Feature flag: `registration.social_enabled` (Google/Apple).
- Staged rollout: internal test numbers whitelist in non-prod.
- DLQ on `UserRegistered` → Wallet queue; manual replay runbook.

## Risk register

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SMS delivery failure | Medium | Retry + alternate provider; show resend UI |
| Wallet creation fails after user created | Low | Saga compensation job; user sees retry banner |
| Non-serviceable false negative | Low | Admin zone management (MA-50); cache invalidation |
| Social account duplicate mobile | Medium | Explicit merge UX (G1 — flagged) |

---

*Posted as Step 2 output. Next: Step 3 Decomposition Proposal.*
