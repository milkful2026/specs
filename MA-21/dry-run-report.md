# SDD Dry-Run Report — MA-21

**Mode:** dry-run (local outputs only; Jira/Git writes skipped — `acli` is not installed/authenticated
in this environment, and MA-21's Jira status is plain `To Do`, since the custom `SDD: *` workflow
statuses from the skill are not yet configured on the MA project. Same constraints as the MA-1 pilot.)
**Story:** MA-21 User Login
**Date:** 2026-07-28

---

## Outputs written

| Step | File |
|------|------|
| 1 | `MA-21/step1-analysis.md` |
| 2 | `MA-21/step2-context.md` |
| 3 | `MA-21/step3-decomposition.md` |
| 4 | `mobile-app/tasks/MA/MA-21/flutter-login-flow.md` |
| 4 | `services/tasks/MA/MA-21/identity-auth-login.md` |
| 4 | `services/tasks/MA/MA-21/user-account-type-profile.md` |
| 5 | `MA-21/step5-review.md` |

## Decisions resolved in chat (not silently assumed)

| Decision | Resolution |
|----------|------------|
| Password / biometric / forgot-password scope | Out of scope — OTP-only, matches the actual Jira ticket text over the broader NSMB source row |
| Multi-device session policy | Concurrent sessions allowed; logout revokes only the calling device's refresh token |
| Entry screen ownership | Reused from MA-1 unchanged; MA-21 builds only the downstream `/login` destination MA-1 already links to |
| OTP digit count (MA-1 says 6, MA-21 mockup shows 5) | Kept at 6 for backend consistency with MA-1; mockup flagged as needing a design update |
| B2C/B2B account-type field (doesn't exist yet) | Added in MA-21 as a User Service schema extension + `GET /users/me`, defaulting every account to B2C |

## Skipped actions (would run in live mode)

```
[SKIPPED] acli jira workitem comment create --key MA-21 --body-file step1-analysis.adf.json
[SKIPPED] acli jira workitem transition --key MA-21 --status "SDD: Building Context"

[SKIPPED] acli jira workitem comment create --key MA-21 --body-file step2-context.adf.json
[SKIPPED] acli jira workitem transition --key MA-21 --status "SDD: Awaiting Decomposition"

[SKIPPED] acli jira workitem comment create --key MA-21 --body-file step3-decomposition.adf.json

[SKIPPED] acli jira workitem create --summary "SDD: MA-21 - Flutter Login Flow" → DRY-6
[SKIPPED] acli jira workitem create --summary "SDD: MA-21 - Identity & Auth Login APIs" → DRY-7
[SKIPPED] acli jira workitem create --summary "SDD: MA-21 - User Service Account Type & Profile Lookup" → DRY-8

[SKIPPED] acli jira workitem link (×3) --link-type "specifies"

[SKIPPED] git checkout -b spec/MA-21
[SKIPPED] git add mobile-app/tasks/MA/MA-21/*.md services/tasks/MA/MA-21/*.md
[SKIPPED] git commit -m "spec(MA-21): initial drafts - user login flow"
[SKIPPED] git push -u origin spec/MA-21

[SKIPPED] gh pr create --title "spec: MA-21 - user login flow" --head spec/MA-21

[SKIPPED] acli jira workitem transition --key MA-21 --status "SDD: In Review"
[SKIPPED] acli jira workitem transition (×3 tasks) --status "Spec: In Review"
```

---

## Next steps to go live

1. Set up `acli` authenticated against `milkfuldairyindia.atlassian.net` (currently unavailable
   in this environment — reads were done via direct Jira REST API calls with the token already
   configured in `.claude/settings.local.json`).
2. Configure the `SDD: *` / `Spec: *` custom workflow statuses on the MA Jira project — neither
   MA-1 nor MA-21 currently has these; both stories sit at the default `To Do` status.
3. Push these local `d:/milkful/specs` changes to the `milkful2026/specs` remote on branch
   `spec/MA-21` once `git`/`gh` write access is confirmed for that repo.
4. Run `/spec-driven-designer MA-21` live (or post Steps 1–3 as Jira comments manually from these
   generated files) once `acli` is available.
5. Product/design follow-up: reconcile the OTP digit-count mismatch between MA-1's spec and the
   MA-21 mockup; confirm Log out UI placement.

---

## Extend to other stories

Per the specs repo's story map (`README.md`), MA-22 Product Listing (mobile-app + MA-94, MA-95)
is next in the backlog after MA-21.
