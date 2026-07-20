# Services — SDD Context

**GitHub Repo:** [`milkful2026/services`](https://github.com/milkful2026/services) (backend microservices monorepo — code not yet implemented)

**Context Docs** (paths relative to `milkful2026/milkful-app`):

- `docs/design/milkful-well-architected.md`
- `docs/design/milkful-hld.drawio`
- `docs/design/milkful-lld.drawio`
- `docs/design/milkful-messaging.drawio`
- `docs/jira/attachments/nsmb-app-feature-spec.txt`

## Description

AWS cloud-native backend for Milkful. **13 microservices** with database-per-service,
EventBridge event bus, API Gateway BFF, Cognito auth, hybrid **Lambda + ECS Fargate** compute.

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
