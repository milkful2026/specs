# User Service — Account Type & Profile Lookup

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-21](https://milkfuldairyindia.atlassian.net/browse/MA-21) |
| **Related JIRA Task** | SDD: MA-21 - User Service Account Type & Profile Lookup |
| **Backend Story** | [MA-93](https://milkfuldairyindia.atlassian.net/browse/MA-93) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-28 |

---

## 2. Problem Statement

After logging in, the app needs to know whether the account is B2C or B2B to render a role-aware
Home screen. No such field exists on the `users` table today — MA-1 shipped registration without
it, since Phase 1 is B2C-only by default. This spec introduces the field (schema-only, no B2B
functionality) and a lookup endpoint the app can call right after login.

## 3. Scope

**In scope:** `account_type` column on `users` (default `B2C` for all existing and new rows),
`GET /users/me` endpoint returning the caller's own profile summary including `accountType`.

**Out of scope:** Any B2B-specific behavior, pricing, or catalog differences (no B2B feature
exists yet — this spec only adds the data point and a way to read it); admin-side account-type
assignment/editing UI (would belong to MA-39 Admin / User Management, not this story);
registration-time account-type selection (MA-1 is unchanged — all registrations continue to
default to `B2C`).

## 4. Functional Requirements

### FR-1: Schema — `account_type`

- Add `account_type` column to the `users` table: `VARCHAR`, `NOT NULL`, `DEFAULT 'B2C'`,
  `CHECK (account_type IN ('B2C', 'B2B'))`.
- Backfill: existing rows (from any MA-1 registrations already in a non-prod environment) get
  `B2C` via the column default — no data migration script needed beyond the `ALTER TABLE`.
- No API currently sets this to `B2B` — until a B2B onboarding path exists, every account is
  `B2C` by construction. The column exists so `GET /users/me` has something real to return, and
  so a future B2B story is a pure additive change (no schema rework).

### FR-2: Profile lookup

`GET /users/me`
**Authorization:** Bearer JWT (Cognito access token); resolves the calling user via `sub` claim.

Response:

```json
{
  "userId": "uuid",
  "name": "Priya Sharma",
  "mobile": "+919876543210",
  "accountType": "B2C",
  "defaultAddressId": "uuid"
}
```

- `404 USER_NOT_FOUND` if the JWT's `sub` has no matching `users` row (should not happen in
  practice post-MA-1, but the endpoint must not 500 on an inconsistent state — surface a clear
  error instead).
- Read-only; no request body.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | `GET /users/me` p95 < 300ms — single indexed read on `cognito_sub` |
| Consistency | Read is eventually consistent with the same Aurora primary used by MA-1's writes — no special consistency requirement beyond MA-1's existing setup |
| Security | Endpoint returns only the caller's own row (scoped by JWT `sub`), never accepts a target user ID |

## 6. Technical Design

- **Compute:** Lambda (same service/runtime as MA-1's User Service).
- **Database:** existing Aurora PostgreSQL `users` cluster — additive column, no new table.

### Schema change

```sql
ALTER TABLE users
  ADD COLUMN account_type VARCHAR NOT NULL DEFAULT 'B2C'
  CHECK (account_type IN ('B2C', 'B2B'));
```

## 7. Data Considerations

- Purely additive migration — no backfill script, no downtime expected (`DEFAULT` handles
  existing rows at the database level for the column add).
- `GET /users/me` does not expose `addresses[]`, `consents[]`, or `preferredSlotId` — kept
  minimal to what MA-21's login flow needs; a fuller profile-read endpoint (if needed later) is
  out of scope here to avoid over-building for an unstated requirement.

## 8. Integration Considerations

| Caller | Purpose |
|--------|---------|
| Flutter app (`flutter-login-flow.md` FR-2) | Resolve `accountType` immediately after login |

No other services call this endpoint as part of MA-21. No EventBridge events are produced or
consumed by this spec.

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| JWT `sub` has no matching `users` row | `404 USER_NOT_FOUND` (not `500`) |
| Column-add migration runs against a table with existing MA-1 rows | Default value satisfies `NOT NULL` for all existing rows automatically; no separate backfill step |
| Future B2B account creation before an assignment API exists | Not possible by design — no write path sets `B2B` yet; this is intentional, not a gap, per Step 1's scope decision |

## 10. Testing Strategy

- **Unit:** `GET /users/me` response shape, 404-on-missing-user branch, JWT `sub` scoping (never
  trusts a client-supplied user ID)
- **Integration:** Aurora test DB with the migration applied; assert existing MA-1-style rows
  read back `accountType: "B2C"` without any manual backfill
- **Migration test:** apply `ALTER TABLE` against a seeded pre-migration `users` table; assert no
  errors and all rows satisfy the `CHECK` constraint post-migration

## 11. Risks and Trade-offs

- Adding a column with no write path for `B2B` yet is a deliberate minimal-scope choice (per
  Step 1) rather than a half-finished feature — it unblocks MA-21's role-aware UI without
  speculative B2B onboarding work that has no story behind it yet.
- `GET /users/me` intentionally returns a narrow shape rather than the full registration payload,
  to avoid the endpoint becoming a de facto "get everything" API before there's a real second
  consumer that needs more.

## 12. Open Questions

None blocking — scope was resolved in chat during Step 1/3 (add the field now, B2B behavior
deferred).

## 13. Approval Notes

Independent of `identity-auth-login.md` (no shared schema); both are required before
`flutter-login-flow.md` can be implemented end to end, since the Flutter spec calls both.
