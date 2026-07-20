# Mobile App — SDD Context

**GitHub Repo:** [`milkful2026/milkful-app`](https://github.com/milkful2026/milkful-app) (Flutter consumer app — code not yet implemented)

**Context Docs** (paths relative to `milkful2026/milkful-app`):

- `docs/jira/attachments/nsmb-app-feature-spec.txt`
- `docs/jira/MA-001-user-registration-story.md`
- `docs/design/milkful-well-architected.md`
- `docs/design/milkful-architecture.drawio`

## Description

The Milkful B2C mobile application for Android and iOS. Built with **Flutter**.
Covers onboarding, catalog, cart, checkout, subscriptions, wallet, order tracking,
and account management. Communicates with AWS backend via **API Gateway** (Cognito JWT).

**Jira Epic:** [MA-18 Mobile App](https://milkfuldairyindia.atlassian.net/browse/MA-18)

**Jira Component tag:** `mobile-app`

## SDD conventions (Flutter)

- User interactions written as step-by-step sequences (maps to `integration_test` / widget tests).
- Name visible UI labels exactly (button text, field labels) for test selectors.
- Specify all UI states: loading, empty, error, success.
- Use `Key('…')` / semantic labels where no visible label exists (equivalent to `data-testid`).
- Accessibility: screen reader labels, contrast, touch targets ≥ 48dp.
