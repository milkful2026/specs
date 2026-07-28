# SDD Run Report — MA-21

**Mode:** live, with one deliberate exception (see below).
**Story:** MA-21 User Login
**Date:** 2026-07-28

This story started as a dry-run (see git history on this file for the original dry-run version)
because `acli` was not installed and MA-21's Jira project had no custom `SDD:*` workflow
statuses. Both gaps were investigated further; `acli` turned out to be installable, so this run
went live for everything except status transitions, per an explicit decision to not block on the
missing workflow statuses.

## What actually ran

| Action | Result |
|--------|--------|
| Install & authenticate `acli` (was missing) | Installed via `winget install Atlassian.AtlassianCLI`; authenticated with the existing `JIRA_EMAIL`/`JIRA_API_TOKEN` |
| Install & authenticate `gh` (was missing) | Installed via `winget install GitHub.cli`; authenticated with the existing `GH_TOKEN` |
| Build `tools/md_to_adf.py` | Was flagged "not yet built" by the skill; written and used for all comment postings below |
| Post Step 1 analysis as a Jira comment on MA-21 | ✅ Done |
| Post Step 2 context as a Jira comment on MA-21 | ✅ Done |
| Post Step 3 `SDD-DECOMPOSITION-PROPOSAL` as a Jira comment on MA-21 | ✅ Done |
| Create Jira Tasks for the 3 approved specs | ✅ MA-105 (Flutter Login Flow), MA-106 (Identity & Auth Login APIs), MA-107 (User Service Account Type & Profile Lookup) |
| Link each Task to MA-21 | ✅ Done, using **`Relates`** instead of `specifies` — this Jira instance has no `specifies` link type configured (`acli jira workitem link type` only lists Blocks, Cloners, Duplicate, Relates) |
| Commit spec files + `tools/md_to_adf.py` on `spec/MA-21` | ✅ Commit `593793a` |
| Push `spec/MA-21` and open the PR | ✅ [github.com/milkful2026/specs/pull/1](https://github.com/milkful2026/specs/pull/1) |
| Update each Task description with spec file URL + PR URL | ✅ Done |
| Post the Step 5 review checklist as a comment on each Task | ✅ Done on MA-105, MA-106, MA-107 |
| Transition MA-21 → `SDD: Building Context` → `SDD: Awaiting Decomposition` → `SDD: In Review` | ❌ **Skipped by decision** — confirmed via a failed test transition that the MA project's Jira workflow has no `SDD:*`/`Spec:*` statuses (`acli jira workitem transition --key MA-21 --status "SDD: Analyzing"` → "No allowed transitions found for given status"). Configuring these requires a human in Jira's workflow editor; MA-21 and its 3 Tasks remain at the default `To Do` status. |
| Transition MA-105/106/107 → `Spec: In Review` | ❌ Skipped for the same reason |

## Decisions resolved in chat (not silently assumed)

| Decision | Resolution |
|----------|------------|
| Password / biometric / forgot-password scope | Out of scope — OTP-only, matches the actual Jira ticket text over the broader NSMB source row |
| Multi-device session policy | Concurrent sessions allowed; logout revokes only the calling device's refresh token |
| Entry screen ownership | Reused from MA-1 unchanged; MA-21 builds only the downstream `/login` destination MA-1 already links to |
| OTP digit count (MA-1 says 6, MA-21 mockup shows 5) | Kept at 6 for backend consistency with MA-1; mockup flagged as needing a design update |
| B2C/B2B account-type field (doesn't exist yet) | Added in MA-21 as a User Service schema extension + `GET /users/me`, defaulting every account to B2C |
| Go live without configured `SDD:*` statuses | Yes — go live on comments/Tasks/git/PR; skip only status transitions |

## Remaining gaps for a fully live SDD workflow

1. **Custom `SDD:*` / `Spec:*` workflow statuses** are not configured on the MA Jira project.
   Both MA-1 and MA-21 (and their Tasks) sit at the default `To Do` status regardless of actual
   progress. A Jira admin needs to add these statuses to the project's workflow scheme before
   status transitions can run for any future story.
2. **No `specifies` / `is specified by` link type** exists on this Jira instance. Used `Relates`
   for MA-21's Task↔Story links; the same substitution will be needed for every future story
   until a custom link type is added (Jira admin action, not something `acli` can create).

## Live artifacts created this run

- Jira comments: 3 on [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) (Step 1, Step 2, Step 3), 1 each on MA-105/MA-106/MA-107 (Step 5 checklist)
- Jira Tasks: [MA-105](https://milkfuldairyindia.atlassian.net/browse/MA-105), [MA-106](https://milkfuldairyindia.atlassian.net/browse/MA-106), [MA-107](https://milkfuldairyindia.atlassian.net/browse/MA-107)
- Git: branch `spec/MA-21`, commit `593793a`
- PR: [milkful2026/specs#1](https://github.com/milkful2026/specs/pull/1)

## Next steps

1. Human reviews and merges [PR #1](https://github.com/milkful2026/specs/pull/1).
2. A Jira admin adds the `SDD:*`/`Spec:*` statuses and a `specifies` link type to the MA project.
3. Once merged and statuses exist, manually (or via a future agent run) transition MA-21 →
   `SDD: In Review` and MA-105/106/107 → `Spec: In Review` to bring Jira state in line with
   actual progress.
4. Per the specs repo's story map, MA-22 Product Listing (mobile-app + MA-94, MA-95) is next.
