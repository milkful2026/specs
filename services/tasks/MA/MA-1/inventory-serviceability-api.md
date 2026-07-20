# Inventory — Serviceability Check API

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) |
| **Related JIRA Task** | SDD: MA-1 - Inventory Serviceability Check API |
| **Backend Story** | [MA-95](https://milkfuldairyindia.atlassian.net/browse/MA-95) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-20 |

---

## 2. Problem Statement

Registration must block or warn users in non-delivery areas. The Inventory service owns
serviceable zones (pincodes/polygons) and exposes a fast lookup for mobile and User Service.

## 3. Scope

**In scope:** Public `GET /serviceability/check`, internal variant for User Service,
Redis cache, zone + slot metadata in response.

**Out of scope:** Zone admin UI (MA-50), waitlist storage (phase 2 unless added).

## 4. Functional Requirements

### FR-1: Serviceability check

`GET /serviceability/check?pincode=560001&lat=12.97&lng=77.59`

- At least `pincode` required; `lat`/`lng` refine polygon match when provided.
- Lookup order: Redis cache (key `svc:{pincode}`) → Aurora `serviceability_zones`.
- Match rules: active zone AND (pincode prefix match OR point-in-polygon).

Response 200 serviceable:

```json
{
  "serviceable": true,
  "zoneId": "blr-central",
  "zoneName": "Bangalore Central",
  "slots": [
    { "id": "morning-6-8", "label": "Morning 6–8 AM" },
    { "id": "evening-6-8", "label": "Evening 6–8 PM" }
  ],
  "waitlistAvailable": false
}
```

Response 200 not serviceable:

```json
{
  "serviceable": false,
  "zoneId": null,
  "message": "We don't deliver to this area yet",
  "waitlistAvailable": false
}
```

### FR-2: Internal check

`GET /internal/serviceability/check` — same logic, IAM/mTLS auth for User Service only.

### FR-3: Cache invalidation

- On zone update (admin), publish `ZoneUpdated` → bust Redis keys for affected pincodes.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Performance | p95 < 300ms (cache hit < 50ms) |
| Availability | 99.9% — degraded mode: fail closed (not serviceable) if DB unreachable |

## 6. Technical Design

- **Compute:** ECS Fargate behind internal ALB + API Gateway route
- **Database:** Aurora `inventory` — tables `serviceability_zones`, `zone_pincodes`, `zone_polygons`
- **Cache:** ElastiCache Redis, TTL 15 min

## 7. Data Considerations

**serviceability_zones:** id, name, active, slot_config jsonb, created_at

Pincode index for prefix lookup; PostGIS or precomputed polygon membership for lat/lng.

## 8. Integration Considerations

| Consumer | Usage |
|----------|-------|
| Flutter app | Pre-submit UX feedback |
| User Service | Authoritative re-check on register |
| Admin MA-50 | CRUD zones |

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| Invalid pincode format | 400 |
| Border polygon ambiguity | Prefer polygon over pincode when lat/lng provided |
| DB down | 503; mobile shows Retry; register blocked |

## 10. Testing Strategy

- Unit: pincode prefix, point-in-polygon
- Integration: seeded zones, cache hit/miss
- Negative: inactive zone, malformed pincode

## 11. Risks and Trade-offs

- **G2:** Waitlist not in phase 1 — `waitlistAvailable: false` always until product adds feature.

## 12. Open Questions

| # | Question | Default |
|---|----------|---------|
| Q1 | Waitlist endpoint? | Defer to phase 2 |

## 13. Approval Notes

Shared dependency for MA-1 and future address management stories.
