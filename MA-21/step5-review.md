# SDD Step 5 — Review Checklist

**Story:** MA-21 User Login
**Specs reviewed:** 3 (1 mobile, 2 services)
**Date:** 2026-07-28

---

## Part 1: Individual Specification Quality

| # | Check | flutter-login-flow | identity-auth-login | user-account-type-profile |
|---|-------|:---:|:---:|:---:|
| 1 | Solves User Story problem | ✅ | ✅ | ✅ |
| 2 | All required sections present | ✅ | ✅ | ✅ |
| 3 | Functional requirements unambiguous | ✅ | ✅ | ✅ |
| 4 | NFRs with measurable targets | ✅ | ✅ | ✅ |
| 5 | Acceptance criteria testable | ✅ | ✅ | ✅ |
| 6 | Edge cases documented | ✅ | ✅ | ✅ |
| 7 | Testing strategy sufficient | ✅ | ✅ | ✅ |
| 8 | Scope boundaries clear | ✅ | ✅ | ✅ |
| 9 | Assumptions/risks explicit | ⚠️ Q2 | ✅ | ✅ |
| 10 | Hand-off ready without verbal explanation | ✅ | ✅ | ✅ |

**Notes on ⚠️:**

- **Q2 (Flutter):** Exact UI placement of the Log out action is provisional (no Account/Settings
  screen exists yet). This is a genuine open item, not a spec-quality gap — the logout mechanism
  itself (FR-5) is fully specified regardless of where the trigger lives visually. Acceptable for
  draft PR; flagged for design/product follow-up.

---

## Part 2: Cross-Specification Coherence

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Consistent terminology | ✅ | `accountType`, `refreshToken`, `requestId` aligned across all 3 specs |
| 2 | No conflicts between specs | ✅ | Login OTP endpoints distinct from MA-1's registration endpoints; logout is new; no overlapping ownership |
| 3 | Data models align | ✅ | `otp_requests.purpose` (Identity Auth) and `users.account_type` (User Service) are independent additive changes — no collision |
| 4 | Inter-spec dependencies documented | ✅ | step2-context diagram + each spec's §8/§13 name the dependency explicitly (Flutter depends on both service specs; service specs are independent of each other) |
| 5 | No uncovered required behavior | ✅ | All AC-1..AC-9 from step1-analysis mapped across the three specs |
| 6 | Combined specs satisfy User Story | ✅ | End-to-end login → session → role-aware landing → logout flow complete |
| 7 | No overlapping responsibilities | ✅ | Identity Auth owns OTP/session; User Service owns account-type/profile; Flutter owns UI/state — clean boundaries |
| 8 | NFRs consistent | ✅ | Latency targets compatible (login verify < 500ms backend, < 1s round trip from Flutter's perspective) |
| 9 | Testing forms coherent plan | ✅ | Mobile widget/integration tests + service unit/integration tests cover the full path, including the negative "unregistered number" and "logout with revoked token" cases on both sides of the boundary |
| 10 | Implementation can begin | ✅ | No blocking open questions remain — both Step 3 conflicts (OTP length, account-type existence) were resolved in chat before drafting |

---

## Approval gate result

**Status: PASS**

All specs pass quality checks with no blocking items. One provisional UI-placement detail
(logout entry point) is documented as an open question, consistent with how MA-1 handled its own
flagged items (G1, G3) — informational for reviewers, not blocking.

**Recommended actions (live mode):**

1. Open PR: `spec: MA-21 - user login (mobile + identity auth + user profile)`
2. Transition Jira Tasks → **Spec: In Review**
3. Transition MA-21 → **SDD: In Review**
4. Design/product note: reconcile the MA-21 mockup's 5-digit OTP visual with the implemented
   6-digit standard (kept for consistency with MA-1); confirm final Log out UI placement once an
   Account/Settings story exists.

---

## PR body template

```markdown
Specification set for [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21).

## Specs included

- mobile-app/tasks/MA/MA-21/flutter-login-flow.md
- services/tasks/MA/MA-21/identity-auth-login.md
- services/tasks/MA/MA-21/user-account-type-profile.md

## Depends on

- MA-1 specs (shared entry screen, shared Cognito pool/OTP infrastructure, `AuthBloc` base)

## Open items for reviewers

- Design asset (MA-21 mockup) shows 5-digit OTP; spec implements 6-digit for backend consistency
  with MA-1 — design to update the asset, not engineering to match it
- Log out UI placement is provisional pending an Account/Settings screen story
```
