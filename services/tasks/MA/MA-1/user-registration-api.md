# User Service — Registration API

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) |
| **Related JIRA Task** | SDD: MA-1 - User Service Registration API |
| **Backend Story** | [MA-93](https://milkfuldairyindia.atlassian.net/browse/MA-93) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-20 |

---

## 2. Problem Statement

After OTP verification, the app must persist customer profile, delivery address(es),
preferred slot, and legal consents, then signal downstream services (Wallet) via events.

## 3. Scope

**In scope:** `POST /users/register`, `GET /delivery/slots`, address model, consent audit,
Cognito attribute sync, `UserRegistered` event emission.

**Out of scope:** OTP (Identity Auth), wallet ledger (Wallet Service), zone polygon admin (Inventory admin).

## 4. Functional Requirements

### FR-1: Register user

`POST /users/register`  
**Authorization:** Bearer JWT (Cognito access token); `sub` must match registering user.

Request:

```json
{
  "name": "Priya Sharma",
  "email": "optional@example.com",
  "addresses": [{
    "lines": ["12 MG Road", "Near Metro"],
    "city": "Bangalore",
    "state": "Karnataka",
    "pincode": "560001",
    "lat": 12.9716,
    "lng": 77.5946,
    "landmark": "Metro station",
    "isDefault": true
  }],
  "preferredSlotId": "morning-6-8",
  "consents": [
    { "type": "TERMS", "version": "2026-01", "acceptedAt": "2026-07-20T10:00:00Z" },
    { "type": "PRIVACY", "version": "2026-01", "acceptedAt": "2026-07-20T10:00:00Z" },
    { "type": "PUSH_NOTIFICATIONS", "accepted": true, "acceptedAt": "2026-07-20T10:00:00Z" }
  ]
}
```

Validation:

- `name` 2–100 chars
- At least one address; `pincode` 6 digits
- Mandatory consents: TERMS, PRIVACY
- Re-call Inventory serviceability for default address pincode/lat/lng — reject if not serviceable

Processing:

1. Upsert `users` row keyed by `cognito_sub`
2. Insert `addresses` rows
3. Insert `user_consents` audit rows
4. Update Cognito attributes: `name`, `custom:default_pincode`
5. Publish EventBridge event `UserRegistered`
6. Response 201:

```json
{
  "userId": "uuid",
  "walletId": null,
  "walletStatus": "PENDING",
  "defaultAddressId": "uuid"
}
```

(`walletId` populated if sync path; else client polls or receives push — see Wallet spec)

### FR-2: Delivery slots

`GET /delivery/slots?zoneId={zoneId}`

- Returns slots from zone config (cached from Inventory or local replica).
- Response: `[{ "id": "morning-6-8", "label": "Morning 6–8 AM", "available": true }]`

### FR-3: Multi-address extensibility

- Schema supports N addresses; registration requires exactly 1.
- `isDefault` exactly one true per user.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | Register p95 < 1s |
| Consistency | User row + addresses in single DB transaction |
| Audit | Consents immutable append-only |

## 6. Technical Design

- **Compute:** Lambda (Node.js or Python)
- **Database:** Aurora PostgreSQL `users` cluster
- **Outbox:** Transactional outbox table → EventBridge publisher Lambda

### Schema (simplified)

```sql
users (id, cognito_sub, name, mobile, email, preferred_slot_id, created_at)
addresses (id, user_id, lines, city, state, pincode, lat, lng, is_default)
user_consents (id, user_id, type, version, accepted_at, metadata jsonb)
outbox_events (id, aggregate_id, type, payload, published_at)
```

### Event: `UserRegistered`

```json
{
  "detail-type": "UserRegistered",
  "detail": {
    "userId": "uuid",
    "cognitoSub": "...",
    "mobile": "+919876543210",
    "defaultPincode": "560001",
    "idempotencyKey": "user-uuid"
  }
}
```

## 7. Data Considerations

- Mobile denormalized from Cognito for query; source of truth remains Cognito for auth.
- Addresses store decimal lat/lng (8 dp precision).

## 8. Integration Considerations

| Downstream | Purpose |
|------------|---------|
| Inventory `GET /internal/serviceability/check` | Re-validate before commit |
| Cognito AdminUpdateUserAttributes | Profile sync |
| EventBridge | Wallet, Notification, Reporting |

Duplicate register (same cognito_sub): idempotent 200 with existing userId.

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| Serviceability changes between UI check and register | 422 `NOT_SERVICEABLE` |
| Partial DB failure | Rollback transaction; 500 |
| Event publish fails | Outbox retry; user created, wallet async |

## 10. Testing Strategy

- Unit: validation rules, consent required set
- Integration: Aurora test DB, mocked Inventory
- Idempotency: double POST returns same userId

## 11. Risks and Trade-offs

- Sync vs async wallet ID in response — async chosen for resilience; mobile shows PENDING state.

## 12. Open Questions

None blocking after wallet failure UX default (banner + retry).

## 13. Approval Notes

Central orchestration point for MA-1; coordinates with MA-92, MA-95, MA-100.
