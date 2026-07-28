# Flutter Login Flow

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) |
| **Related JIRA Task** | SDD: MA-21 - Flutter Login Flow (to be created) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-28 |
| **Stakeholders** | Product, Mobile engineering, QA |

---

## 2. Problem Statement

Returning customers who already completed MA-1 registration must be able to sign back in with
their mobile number, land on a role-aware home screen, stay signed in across app restarts
("remember me"), and sign out securely. Today, MA-1's shared entry screen already detects an
existing account and shows a "Log in" link, but that link has nowhere to go — this spec builds
the destination.

## 3. Scope

**In scope:**

- `/login` route: OTP verification for an already-known mobile number, reached from MA-1's
  "Already registered? Log in" link (mobile number carried forward in route state; no re-typing).
- Standalone re-entry into `/login` (e.g. after logout, or app relaunch with an expired session)
  where the mobile number must be entered again.
- OTP verify screen, resend, error/expiry states.
- Session persistence ("remember me") across app restarts.
- Role-aware post-login landing (B2C vs. B2B).
- Logout trigger and confirmation.
- Session-expiry handling (silent refresh; forced re-login if refresh fails).

**Out of scope:**

- Registration flow (MA-1, already specced).
- Password login, biometric login, forgot-password (excluded from MA-21 per Step 1 scope decision).
- Full Account/Settings screen — MA-21 adds only the minimal logout trigger needed for this
  story; a complete Account screen is a separate future story.
- Admin/staff login (Admin UI epic, separate).

## 4. Functional Requirements

### Screen flow

```
[MA-1 entry screen: 409 USER_EXISTS] → /login (OTP verify, number carried forward)
                                            → Home (role-aware)

[Standalone re-entry, e.g. post-logout] → /login (mobile entry) → OTP verify → Home
```

### FR-1: Login entry — mobile number (`/login`, standalone re-entry only)

- Same field pattern as MA-1's `/signup` mobile entry: **+91** prefix, 10-digit field, **Continue**
  button disabled until valid format.
- Only rendered when `/login` is reached without a carried-forward mobile number (i.e. not via
  MA-1's redirect, where the number is already known).
- On tap **Continue**: call `POST /auth/login/otp/send`; show loading spinner on button.
- If the number is **not** a registered account: inline message "No account found for this
  number." with a **Sign up** link → MA-1's `/signup`.
- On success: navigate to OTP verify step with `requestId` in route state.

### FR-2: OTP verification (`/login/otp`)

- 6-digit OTP input (`pinput`, 6 cells) — consistent with MA-1's Identity Auth spec. **Design
  note:** the mockup attached to MA-21 (`image-20260724-175420.png`) shows a 5-cell OTP layout;
  per product decision this spec keeps 6 digits for backend consistency with MA-1 — flag to the
  design team that the visual asset needs to be reconciled to 6 cells before implementation.
- Screen text per mockup: heading "Verify your number", subtext "We've sent a 5-digit code to
  your mobile number." — **must be updated to reflect 6 digits** when implemented, per the same
  design-reconciliation note above.
- Auto-advance between boxes; **Verify & Proceed** button (label per mockup) enabled on 6th digit
  or tapped explicitly.
- Countdown **Resend Code in 0:30**; after expiry, **Resend Code** enabled (max 3 sends / 15 min,
  same ceiling as MA-1, tracked under a separate login-specific counter — see Identity Auth spec).
- Invalid OTP: shake animation + inline error "Invalid code. Try again."
- Expired: "Code expired. Tap Resend Code."
- Lockout (3 failed attempts): disable input, show "Too many attempts. Request a new code."
  and re-enable **Resend Code**.
- On success: call `POST /auth/login/otp/verify` → receive access + refresh tokens → store via
  `flutter_secure_storage` (same pattern as MA-1) → call `GET /users/me` → navigate to Home.

### FR-3: Session persistence ("remember me")

- No opt-out toggle — every successful login persists the session (access + refresh token) in
  `flutter_secure_storage`, matching MA-1's registration session behavior. App relaunch with a
  valid stored refresh token skips `/login` entirely and goes straight to Home.
- On app start, if an access token is expired but the refresh token is valid: silently call the
  refresh endpoint before rendering Home; on refresh failure, clear stored tokens and route to
  the MA-1 entry screen.

### FR-4: Role-aware landing

- After `GET /users/me` resolves `accountType`, store it in app session state.
- `B2C` → standard consumer Home (catalog, cart, subscriptions).
- `B2B` → Home renders with a **B2B account** indicator; exact B2B home layout differences are
  out of scope for MA-21 (no B2B-specific screens exist yet) — the requirement here is limited
  to correctly reading and storing the flag and rendering the indicator, not gating features.
- If `GET /users/me` fails after a successful token issuance: proceed to Home in a degraded mode
  (default to B2C-equivalent view), retry the lookup on next app foreground.

### FR-5: Logout

- A **Log out** action (minimal entry point — e.g. a menu item or button in the existing
  navigation shell; exact placement to be confirmed with product/design since a full Account
  screen doesn't exist yet in this story's scope).
- Confirmation dialog: "Log out? You'll need to verify your number again to sign back in."
  with **Cancel** / **Log out**.
- On confirm: call `POST /auth/logout` with the current refresh token, clear
  `flutter_secure_storage`, clear in-memory session state, navigate to MA-1's entry screen.
- Logout proceeds locally (clears local tokens, navigates away) even if the server call fails or
  times out — a failed revocation must never trap the user in a logged-in-looking state.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | Screen transitions < 300ms; OTP verify round trip < 1s on 4G |
| Accessibility | TalkBack/VoiceOver labels on mobile field, OTP boxes, and Log out action; contrast WCAG AA; touch targets ≥ 48dp |
| Security | Tokens only in secure storage; no PII or OTP values in logs; logout clears storage even on network failure |
| Reliability | Silent token refresh on app start; on refresh failure, degrade gracefully to the entry screen (no crash, no stuck spinner) |

## 6. Technical Design

### Architecture

- **State:** same `AuthBloc` introduced by MA-1, extended with login-specific events
  (`LoginOtpRequested`, `LoginOtpVerified`, `SessionRefreshed`, `LoggedOut`).
- **Routing:** `go_router`, adds `/login` and `/login/otp` to the existing route guard set;
  guarded routes (Home, etc.) redirect to `/login` (not `/signup`) when no valid session exists
  and a "last known mobile number" hint is present (e.g. post-logout), otherwise to MA-1's
  `/signup` entry screen for a first-time device.
- **HTTP:** reuse MA-1's `dio` client with JWT + `X-Request-Id` interceptors.

### UI component map

| Component | Source | Pattern | Notes |
|-----------|--------|---------|-------|
| Phone input | `intl_phone_field` (MA-1 shared) | +91 prefix | Only shown on standalone `/login` entry |
| OTP boxes | `pinput` (MA-1 shared) | 6 cells | Key: `login-otp-input` |
| Primary CTA | Material `FilledButton` | Full width | Labels: Continue, Verify & Proceed, Resend Code |
| Log out control | Material `TextButton`/menu item | — | Key: `logout-action` |
| Confirmation dialog | Material `AlertDialog` | Cancel/Confirm | — |

### Responsive behavior (mobile only)

| Breakpoint | Behavior |
|------------|----------|
| Phone (< 600dp) | Single column, full-width CTAs (same as MA-1) |
| Tablet (≥ 600dp) | Centered max-width 480dp column (same as MA-1) |

## 7. Data Considerations

Local session model (extends MA-1's token storage, adds role):

```dart
class SessionState {
  String? accessToken;
  String? refreshToken;
  DateTime? accessTokenExpiresAt;
  String? accountType; // "B2C" | "B2B"
}
```

No local persistence of the OTP or mobile number beyond the active login attempt.

## 8. Integration Considerations

| API | When |
|-----|------|
| `POST /auth/login/otp/send` | Standalone `/login` entry, or resend |
| `POST /auth/login/otp/verify` | OTP submission |
| `POST /auth/token/refresh` | Silent refresh on app start (existing MA-1 endpoint, reused) |
| `GET /users/me` | Immediately after successful verify, to resolve `accountType` |
| `POST /auth/logout` | Logout action |

Errors mapped to user-friendly strings; 429 → "Too many attempts. Wait and try again." (same
convention as MA-1).

## 9. Edge Cases and Failure Modes

| Case | Behavior |
|------|----------|
| Mobile number not registered (standalone `/login` entry) | Inline error + **Sign up** link to MA-1 flow |
| OTP invalid / expired / lockout | See FR-2 states |
| App killed mid-OTP-entry | User returns to `/login` mobile entry on relaunch (no draft resume needed — this is a short flow, unlike MA-1's multi-step onboarding) |
| Refresh token expired or revoked (e.g. logged out elsewhere via support action) | Silent refresh fails → clear storage → route to entry screen, no error dialog, just a clean re-auth prompt |
| `GET /users/me` fails after login | Degrade to B2C-equivalent Home per FR-4; retry on next foreground |
| Logout API call fails/times out | Proceed with local logout regardless (FR-5) |
| Network loss on OTP submit | Snackbar + retry; OTP input preserved |

## 10. Testing Strategy

### Widget tests

- Phone validation on standalone `/login` entry (valid/invalid 10-digit)
- OTP resend timer countdown and lockout-after-3-attempts state
- Logout confirmation dialog cancel vs. confirm behavior

### Integration test scenario: Login via MA-1 redirect (happy path)

**Given:** Registered account exists for `9876543210`; fresh app session; staging API available
**Steps:**

1. On MA-1's entry screen, enter `9876543210` in mobile field (`find.bySemanticsLabel('Mobile number')`)
2. Tap **Continue** (`find.text('Continue')`)
3. Assert: "Already registered? Log in" link visible (`find.text('Log in')`)
4. Tap **Log in**
5. Assert: navigated to `/login/otp` with mobile number carried forward (no re-entry field shown)
6. Enter OTP `123456` in pinput (`find.byKey(Key('login-otp-input'))`)
7. Tap **Verify & Proceed** (`find.text('Verify & Proceed')`)
8. Assert: Home screen visible, role indicator matches account's `accountType`

**Outcome:** User authenticated and landed on role-aware Home; session persisted.

### Integration test scenario: Standalone login after logout

**Given:** Previously logged-in user has just logged out
**Steps:**

1. Tap **Log out** (`find.byKey(Key('logout-action'))`)
2. Confirm in dialog (`find.text('Log out')` within `AlertDialog`)
3. Assert: routed to entry screen, no session in storage
4. Navigate to `/login`, enter `9876543210` → **Continue**
5. Enter OTP → **Verify & Proceed**
6. Assert: Home screen visible again

**Outcome:** Full logout → re-login round trip succeeds.

### Negative scenarios

- Unregistered mobile number on standalone `/login` → **Sign up** link shown, no OTP sent
- Invalid OTP → error text visible, attempt counted
- 3 invalid attempts → lockout state, resend re-enabled
- Refresh failure on app start → routed to entry screen without error dialog

## 11. Risks and Trade-offs

- **Design-asset inconsistency:** mockup shows a 5-digit OTP UI while this spec (per product
  decision) implements 6 digits to stay consistent with MA-1's backend. Design must update the
  visual asset; engineering should not build to the mockup's digit count as-is.
- **Logout placement is provisional:** no Account/Settings screen exists yet, so the exact UI
  location of the Log out action is left flexible (menu item vs. button) pending a future
  Account-screen story; the underlying logout mechanism (FR-5) is fixed regardless of placement.
- **B2B home differences deferred:** this spec only surfaces the role flag, not B2B-specific
  functionality — avoids scope creep into an undefined B2B UI.

## 12. Open Questions

| # | Question | Default assumed |
|---|----------|-----------------|
| Q1 | Exact JWT access/refresh lifetimes for "remember me" | Reuse MA-1's 15 min / 30 days (Step 1 Q1, still open for spec review) |
| Q2 | Where does the Log out action live in the nav shell? | Provisional placeholder; finalize with an Account-screen story |

## 13. Approval / Alignment Notes

Depends on MA-1's Flutter Registration Onboarding (entry screen + `AuthBloc` base) and both
services specs below (`identity-auth-login.md`, `user-account-type-profile.md`). Pending product
sign-off on Q1/Q2 above; engineering review after Step 5.
