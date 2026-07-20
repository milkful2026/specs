# Wallet — Auto-Provision on Registration

| Field | Value |
|-------|-------|
| **Related User Story** | [MA-1](https://milkfuldairyindia.atlassian.net/browse/MA-1) |
| **Related JIRA Task** | SDD: MA-1 - Wallet Auto-Provision on Registration |
| **Backend Story** | [MA-100](https://milkfuldairyindia.atlassian.net/browse/MA-100) |
| **Author** | SDD Agent (dry-run) |
| **Date** | 2026-07-20 |

---

## 2. Problem Statement

Every registered customer needs a prepaid wallet for subscriptions and checkout (AC-9).
Wallet must be created automatically without user action, with clear failure handling.

## 3. Scope

**In scope:** Consume `UserRegistered` event, idempotent wallet creation, status query endpoint,
`WalletCreated` event, mobile-visible status.

**Out of scope:** Recharge (MA-33), ledger transactions, admin wallet adjustments (MA-40).

## 4. Functional Requirements

### FR-1: Event consumer

- SQS queue `wallet-user-registered` subscribed to EventBridge rule on `UserRegistered`.
- Idempotency key = `detail.idempotencyKey` (userId); duplicate events no-op.
- Create wallet row: `{ userId, balance: 0, currency: "INR", status: "ACTIVE" }`.
- Publish `WalletCreated` { userId, walletId, balance }.

### FR-2: Wallet status (for mobile retry)

`GET /wallet/me/status`  
**Authorization:** Bearer JWT

Response:

```json
{
  "walletId": "uuid",
  "status": "ACTIVE|CREATING|FAILED",
  "balance": 0,
  "currency": "INR"
}
```

- `CREATING` if event not yet processed (< 30s normal)
- `FAILED` after max retries exhausted — triggers support alert

### FR-3: Failure handling (resolves flagged concern)

**Decision (assumed pending product):** Registration **succeeds**; wallet creation is async.

- User Service returns `walletStatus: "PENDING"`.
- Mobile success screen polls `GET /wallet/me/status` every 2s up to 15s.
- If `FAILED`: show banner "Wallet setup incomplete — Retry" calling `POST /wallet/me/retry` (internal replay by userId).
- AC-9 satisfied: user never sees silent failure; support notified on FAILED.

### FR-4: Admin visibility

- Wallet row queryable by admin MA-40 (future); not part of this spec's implementation.

## 5. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency | Wallet created within 5s of event p95 |
| Reliability | At-least-once delivery; idempotent consumer |
| Audit | Ledger entry for wallet creation (zero balance opening) |

## 6. Technical Design

- **Compute:** ECS Fargate consumer + Lambda for status API
- **Database:** Aurora `wallet` — `wallets`, `ledger_entries`
- **DLQ:** `wallet-user-registered-dlq` with CloudWatch alarm

### Saga position

```
UserRegistered → [Wallet Consumer] → WalletCreated
                      ↓ fail
                   DLQ → manual replay / auto retry (3x)
```

## 7. Data Considerations

```sql
wallets (id, user_id UNIQUE, balance, currency, status, created_at)
ledger_entries (id, wallet_id, type, amount, ref, created_at)
```

Opening ledger entry: type `OPENING`, amount 0.

## 8. Integration Considerations

| System | Role |
|--------|------|
| EventBridge | Trigger |
| User Service | Emits UserRegistered |
| Flutter | Polls status endpoint |
| Notification | Optional welcome push on WalletCreated |

## 9. Edge Cases and Failure Modes

| Case | Handling |
|------|----------|
| Duplicate UserRegistered | Idempotent skip |
| DB insert fail | Retry 3x → DLQ → status FAILED |
| User deleted before event | Log and skip (orphan event) |

## 10. Testing Strategy

- Unit: idempotency, ledger opening entry
- Integration: event → wallet row exists
- Chaos: DLQ replay restores FAILED → ACTIVE

## 11. Risks and Trade-offs

- Async wallet vs sync register response — chosen for decoupling; UX handles PENDING state.
- Product must confirm assumed failure UX in Step 3 flagged item.

## 12. Open Questions

| # | Question | Assumption |
|---|----------|------------|
| Q1 | Block registration if wallet fails? | No — async retry |

## 13. Approval Notes

Completes AC-9 with mobile + User Service coordination.
