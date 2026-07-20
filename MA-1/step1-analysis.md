# SDD Step 1 — User Story Analysis

**Story:** [MA-1 User Registration](https://milkfuldairyindia.atlassian.net/browse/MA-1)  
**Epic:** MA-18 (Flutter Mobile App)  
**Status at analysis:** Backlog (assumed)  
**Source:** `docs/jira/MA-001-user-registration-story.md`, NSMB feature spec row 1.0

---

## Business intent

New Milkful customers must register with a **verified mobile number**, complete profile and
delivery setup, accept legal consents, and receive a **ready-to-use wallet** before first order.

## Actors

| Actor | Role |
|-------|------|
| New customer | Primary — completes registration on Flutter app |
| Identity & Auth service | OTP send/verify, social token exchange, JWT issuance |
| User service | Persists profile, addresses, preferences, consents |
| Inventory service | Pincode/geo serviceability validation |
| Wallet service | Auto-creates ledger account on registration |
| Notification service | SMS OTP delivery (via SNS) |

## Functional summary

1. Mobile + OTP registration (primary); optional Google/Apple social sign-up.
2. Profile: full name (required).
3. Delivery address: map picker, autocomplete, manual entry; lat/lng to backend.
4. Pincode serviceability check before proceeding.
5. Preferred delivery slot selection from zone-specific slots.
6. Multiple addresses supported; first address required; default flag.
7. T&C + Privacy Policy consent (required); push notification consent (product TBD).
8. Wallet auto-provision on successful registration.
9. Session tokens stored securely; onboarding resumable if app killed.

## Acceptance criteria coverage

| AC | Summary | Spec boundary |
|----|---------|---------------|
| AC-1 | Mobile OTP flow | Flutter UI + Identity Auth API |
| AC-2 | Social sign-up | Flutter + Identity Auth API |
| AC-3 | Name capture | Flutter + User API |
| AC-4 | Map/address picker | Flutter + User API |
| AC-5 | Serviceability | Flutter + Inventory API |
| AC-6 | Delivery slot | Flutter + User API (+ config from Inventory zones) |
| AC-7 | Multi-address model | User API schema |
| AC-8 | Legal consent | Flutter + User API audit fields |
| AC-9 | Wallet auto-create | Wallet API + User registration saga |
| AC-10 | Completion & session | Flutter auth state + Identity Auth |

## Out of scope (Phase 1)

- Referral code at sign-up
- Guest checkout
- Multi-language onboarding (i18n scaffold only)
- Admin UI for registration (MA-39 is separate)

## Gaps / ambiguities (for Step 3)

| # | Item | Impact |
|---|------|--------|
| G1 | Social sign-up without mobile — merge policy undefined | ⚠ Identity Auth spec |
| G2 | Waitlist for non-serviceable pincodes — supported or not? | ⚠ Inventory spec |
| G3 | Push notification consent required vs optional | ⚠ Flutter spec |
| G4 | OTP length (4 vs 6 digits) | ⚠ Identity Auth spec |
| G5 | Single registration API vs step-wise endpoints | ⚠ User + Auth specs |

## Prior SDD comments

None found (fresh start).

## Impacted areas

- `mobile-app` — full onboarding flow (7+ screens)
- `services` — Identity Auth, User, Inventory, Wallet, Notification
- `portal-ui` — none for MA-1 (read-only user list is MA-39)

---

*Posted as Step 1 output. Next: Step 2 Build Technical Context.*
