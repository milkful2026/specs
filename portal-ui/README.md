# Portal UI — SDD Context

**GitHub Repo:** [`milkful2026/portal-ui`](https://github.com/milkful2026/portal-ui) (React admin console — code not yet implemented)

**Context Docs** (paths relative to `milkful2026/milkful-app`):

- `docs/jira/attachments/nsmb-app-feature-spec.txt` (Admin section, rows 20–31)
- `docs/design/milkful-well-architected.md`
- `scripts/link-admin-backend-jira.py`

## Description

React **admin / back-office** web application for Milkful operations staff.
Covers user management, catalog, orders, subscriptions, delivery routes, offers,
CRM/support, RBAC, reporting, and system configuration.

**Jira Epic:** [MA-20 Admin UI](https://milkfuldairyindia.atlassian.net/browse/MA-20)

**Jira Component tag:** `portal-ui`

## SDD conventions (React)

- E2E / acceptance tests as **Playwright** scenarios (Given / Steps / Outcome / Selectors).
- Selector priority: `getByRole` > `getByText` > `getByLabel` > `getByTestId` — never CSS classes.
- Section 6 must include **UI Component Map** and **Responsive Behavior** tables.
- WCAG AA: keyboard navigation, ARIA labels, focus management.

**Note:** MA-1 (User Registration) is consumer mobile-only; admin portal spec is out of scope except
for downstream read-only user visibility (covered under MA-39).
