# Services — SDD Context

**GitHub Repo:** [`milkful2026/services`](https://github.com/milkful2026/services)

**Context Docs** (paths relative to `milkful2026/milkful-app` unless noted):

- `docs/design/milkful-well-architected.md`
- `docs/design/milkful-hld.drawio`
- `docs/design/milkful-lld.drawio`
- `docs/design/milkful-messaging.drawio`
- `README.md` (in `milkful2026/services` — coding principles & guardrails)

## Description

AWS cloud-native backend for Milkful. **13 microservices** with database-per-service,
EventBridge domain-event bus, API Gateway BFF, Cognito auth, hybrid **Lambda + ECS Fargate**
compute, SQS per consumer (with DLQ), SNS last-mile fan-out, and Step Functions sagas.

| Service | Jira | Compute | Datastore |
|---------|------|---------|-----------|
| Identity & Auth | MA-92 | Lambda | Cognito |
| User | MA-93 | Lambda | Aurora `users` |
| Catalog | MA-94 | Fargate | Aurora + OpenSearch |
| Inventory | MA-95 | Fargate | Aurora `inventory` |
| Cart | MA-96 | Lambda | DynamoDB |
| Order | MA-97 | Fargate | Aurora `orders` |
| Subscription | MA-98 | Lambda | Aurora `subscriptions` |
| Payment | MA-99 | Fargate | Aurora `payments` |
| Wallet | MA-100 | Fargate | Aurora `wallet` |
| Pricing & Offer | MA-101 | Fargate | Aurora + Redis |
| Delivery | MA-102 | Fargate | Aurora + DynamoDB |
| Notification | MA-103 | Lambda | DynamoDB |
| Reporting | MA-104 | Fargate | OpenSearch + S3 |

**Jira Epic:** [MA-19 Backend Services](https://milkfuldairyindia.atlassian.net/browse/MA-19)

**Jira Component tag:** `services`

## SDD conventions (backend)

- Specs must name owning service(s), compute type (Lambda vs Fargate), and datastore.
- Cross-service data only via **APIs or EventBridge events** — never another service's DB.
- Domain events follow producer/consumer map in `milkful-messaging.drawio`.
- Document idempotency, retries, DLQ behavior for every consumer.
- Auth: Cognito JWT at API Gateway; service-to-service SigV4 / mTLS.
- Observability: correlation ID end-to-end; CloudWatch + X-Ray expectations in NFRs.
- Spec path: `services/tasks/MA/{STORY-KEY}/{SPEC-KEY}.md`
