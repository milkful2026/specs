# SDD Step 3 — Decomposition Proposal

**Story:** [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) User Registration

---

### SDD-DECOMPOSITION-PROPOSAL

Proposed specifications for MA-1:

* ✓ **Flutter Registration Onboarding** — 7-screen mobile flow: mobile entry, OTP, optional social link, name, address/map picker, serviceability UI, slot selector, consent, success; secure token storage and onboarding resume.
* ✓ **Identity & Auth — Registration APIs** — Cognito-backed OTP send/verify, social token exchange (Google/Apple), JWT issuance, rate limiting, existing-user redirect to login.
* ✓ **User Service — Registration API** — `POST /users/register` orchestration: profile, addresses, slot, consents; Cognito attribute sync; publishes `UserRegistered` event.
* ✓ **Inventory — Serviceability Check API** — Pincode and lat/lng zone lookup, slot availability metadata, cache layer; non-serviceable response contract for mobile UI.
* ⚠ **Wallet — Auto-Provision on Registration** — Event-driven wallet creation on `UserRegistered`; idempotent; failure handling and mobile confirmation.
  * Concern: Registration should not fail silently if wallet creation fails (AC-9). Need product decision: block registration vs async retry with banner.

Confident specs are ready to proceed. The flagged spec needs input on wallet failure UX before drafting Section 9 edge cases.

**To approve:** Transition MA-1 to **SDD: Drafting** (no comment needed).

**To modify:** Post `SDD-DECOMPOSITION-FEEDBACK` with Accept/Remove/Add/Modify, then transition to **SDD: Drafting**.

---

## Spec file paths (Step 4)

| Spec | Area | Path |
|------|------|------|
| Flutter Registration Onboarding | mobile-app | `mobile-app/tasks/MA/MA-1/flutter-registration-onboarding.md` |
| Identity & Auth — Registration APIs | services | `services/tasks/MA/MA-1/identity-auth-registration.md` |
| User Service — Registration API | services | `services/tasks/MA/MA-1/user-registration-api.md` |
| Inventory — Serviceability Check API | services | `services/tasks/MA/MA-1/inventory-serviceability-api.md` |
| Wallet — Auto-Provision on Registration | services | `services/tasks/MA/MA-1/wallet-auto-provision.md` |

## Jira tasks to create (Step 4)

| Summary |
|---------|
| SDD: MA-1 - Flutter Registration Onboarding |
| SDD: MA-1 - Identity & Auth Registration APIs |
| SDD: MA-1 - User Service Registration API |
| SDD: MA-1 - Inventory Serviceability Check API |
| SDD: MA-1 - Wallet Auto-Provision on Registration |

---

*Human approval required before Step 4 drafting. This dry-run proceeds with proposal-as-approved.*
