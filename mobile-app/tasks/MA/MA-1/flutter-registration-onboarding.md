# Flutter Registration Onboarding

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) |
| **Related JIRA Task** | SDD: MA-1 - Flutter Registration Onboarding (to be created) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-20 |
| **Stakeholders** | Product, Mobile engineering, QA |

---

## 2. Problem Statement

New customers cannot order until they have a verified account, serviceable delivery address,
and wallet. The Flutter app must guide users through registration with clear validation,
loading/error states, and the ability to resume if interrupted.

## 3. Scope

**In scope:**

- Onboarding routes: `/signup`, `/otp`, `/profile`, `/address`, `/slot`, `/consent`, `/success`
- Mobile + OTP primary flow; Google/Apple optional entry points
- Map picker, address autocomplete, manual fallback
- Serviceability and slot selection UI
- Consent checkboxes and WebView for legal docs
- Secure token storage and onboarding state persistence
- Analytics events per AC-10

**Out of scope:**

- Login flow (MA-21)
- Admin user management (MA-39)
- Referral code, guest checkout, i18n content

## 4. Functional Requirements

### Screen flow

```
Welcome → Sign Up (Mobile) → OTP Verify → [Optional Social Link]
  → Name → Address (Map/Manual) → Serviceability result
  → Delivery Slot → Consent → Submit → Success → Home
```

### FR-1: Mobile entry (`/signup`)

- User sees **Country code** (+91 fixed or picker) and **Mobile number** field (10 digits).
- **Send OTP** button disabled until valid format.
- On tap **Send OTP**: call `POST /auth/otp/send`; show loading spinner on button.
- Success → navigate to `/otp` with `requestId` in route state.
- If API returns `USER_EXISTS` → show inline message "Already registered?" with **Log in** link → `/login`.

### FR-2: OTP verification (`/otp`)

- 6-digit OTP input (pinput), auto-advance between boxes.
- Countdown **Resend OTP in 0:30**; after expiry, **Resend OTP** enabled (max 3 per 15 min).
- **Verify** on 6th digit or explicit button.
- Invalid OTP: shake animation + inline error "Invalid code. Try again."
- Expired: "Code expired. Tap Resend OTP."

### FR-3: Social auth (optional)

- **Continue with Google** on Android/iOS; **Continue with Apple** on iOS only.
- After social token exchange, if mobile not verified → still require OTP step.
- Store tokens via `flutter_secure_storage` on success.

### FR-4: Name (`/profile`)

- **Full name** field, min 2 max 100 chars, Unicode allowed.
- **Continue** disabled until valid; inline error below field.

### FR-5: Address (`/address`)

- Tabs or segments: **Use map** | **Search** | **Enter manually**
- Map: draggable pin; lat/lng displayed; reverse geocode fills fields.
- Search: Google Places autocomplete.
- Manual: House/Flat, Street, Landmark, City, State, **Pincode** (6 digits).
- Location permission rationale dialog before map; manual fallback if denied.
- On pincode/map settle → call serviceability API (FR-6).

### FR-6: Serviceability UI

- Loading: skeleton on address summary card.
- Serviceable: green check "We deliver to your area" → enable **Continue**.
- Not serviceable: message "Sorry, we don't deliver here yet" + **Try another address** + optional **Join waitlist** (if backend supports).
- Error: **Retry** button.

### FR-7: Delivery slot (`/slot`)

- Fetch slots from `GET /delivery/slots?zoneId=`.
- Chip/radio list: e.g. **Morning 6–8 AM**, **Evening 6–8 PM**.
- One selection required.

### FR-8: Consent (`/consent`)

- Required checkboxes: **I agree to Terms & Conditions**, **I agree to Privacy Policy** (links open WebView).
- Optional/required per product: **Send me order updates via push notifications**.
- **Complete registration** disabled until mandatory boxes checked.
- On submit → `POST /users/register` with full payload.

### FR-9: Success (`/success`)

- Message: "Welcome to Milkful!" + "Your Milkful Wallet is ready" (if wallet in response).
- Wallet pending/failed: warning banner with **Retry** (calls wallet status endpoint).
- **Start ordering** → Home with auth session active.

### FR-10: Onboarding persistence

- Save step + draft data to `shared_preferences` / Hive on each Continue.
- On app relaunch mid-flow → resume last incomplete step.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | Screen transitions < 300ms; map load < 2s on 4G |
| Accessibility | TalkBack/VoiceOver labels on all inputs; contrast WCAG AA |
| Security | Tokens only in secure storage; no PII in logs |
| Reliability | Offline on submit → queue retry with user message |

## 6. Technical Design

### Architecture

- **State:** `flutter_bloc` or `riverpod` — `RegistrationBloc` + `AuthBloc`
- **Routing:** `go_router` with guarded routes post-auth
- **HTTP:** `dio` with interceptors for JWT and `X-Request-Id`

### UI component map

| Component | Source | Pattern | Notes |
|-----------|--------|---------|-------|
| Phone input | `intl_phone_field` or custom | +91 prefix | Semantics: "Mobile number" |
| OTP boxes | `pinput` | 6 cells | Key: `otp-input` |
| Primary CTA | Material `FilledButton` | Full width | Labels: Send OTP, Verify, Continue, Complete registration |
| Map view | `google_maps_flutter` | Full screen with pin | |
| Slot chips | Material `ChoiceChip` | Single select | |
| Legal links | `webview_flutter` | In-app | |
| Error banner | Custom `Banner` | Red surface | |

### Responsive behavior (mobile only)

| Breakpoint | Behavior |
|------------|----------|
| Phone (< 600dp) | Single column, full-width CTAs |
| Tablet (≥ 600dp) | Centered max-width 480dp column |

## 7. Data Considerations

Local draft model:

```dart
class RegistrationDraft {
  String? mobile;
  String? requestId;
  String? name;
  AddressDraft? address;
  String? slotId;
  bool termsAccepted;
  bool privacyAccepted;
  bool pushConsent;
}
```

## 8. Integration Considerations

| API | When |
|-----|------|
| `POST /auth/otp/send` | Send OTP |
| `POST /auth/otp/verify` | Verify OTP → tokens |
| `POST /auth/social` | Social sign-in |
| `GET /serviceability/check` | After address |
| `GET /delivery/slots` | Slot screen |
| `POST /users/register` | Final submit |

Errors mapped to user-friendly strings; 429 → "Too many attempts. Wait and try again."

## 9. Edge Cases and Failure Modes

| Case | Behavior |
|------|----------|
| App killed mid-flow | Resume from saved step |
| OTP resend limit hit | Disable resend; show support link |
| Map permission denied | Switch to manual entry |
| Register succeeds, wallet fails | Success screen with retry banner (AC-9) |
| Network loss on submit | Snackbar + retry; preserve form |

## 10. Testing Strategy

### Widget tests

- Phone validation (valid/invalid 10-digit)
- OTP resend timer countdown
- Consent gating on submit button

### Integration test scenario: Happy path OTP registration

**Given:** Fresh install, no session, staging API available  
**Steps:**

1. Tap **Get started** on Welcome (`find.text('Get started')`)
2. Enter `9876543210` in mobile field (`find.bySemanticsLabel('Mobile number')`)
3. Tap **Send OTP** (`find.text('Send OTP')`)
4. Enter OTP `123456` in pinput (`find.byKey(Key('otp-input'))`)
5. Enter name `Priya Sharma` → **Continue**
6. Select map pin in Bangalore serviceable area → **Continue**
7. Assert: "We deliver to your area" visible
8. Select **Morning 6–8 AM** slot → **Continue**
9. Check T&C and Privacy → **Complete registration**
10. Assert: "Welcome to Milkful!" and Home tab visible

**Outcome:** User authenticated; wallet confirmation shown.

### Negative scenarios

- Invalid OTP → error text visible
- Non-serviceable pincode → blocked from Continue
- Unchecked consent → submit disabled

## 11. Risks and Trade-offs

- **Assumption:** 6-digit OTP (align with Identity Auth spec).
- **Assumption:** Wallet failure shows success with banner (async retry) — pending product sign-off on flagged item.

## 12. Open Questions

| # | Question | Default assumed |
|---|----------|-----------------|
| Q1 | Push consent required? | Optional |
| Q2 | Waitlist for non-serviceable? | Out of phase 1 unless Inventory adds endpoint |

## 13. Approval / Alignment Notes

Pending product approval on decomposition G1, G3. Engineering review after Step 5 PR.
