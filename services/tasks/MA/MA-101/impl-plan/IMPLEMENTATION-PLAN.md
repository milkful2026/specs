# Implementation Plan — MA-101: Pricing & Offer Service (Fargate + Aurora + Redis)

## 1. Overview

**Story:** [MA-101](https://milkfuldairyindia.atlassian.net/browse/MA-101) — Pricing & Offer Service
**Date:** 2026-08-21
**Author:** Claude Code (session), implementing the merged MA-122 spec

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Pricing & Offer Service (Fargate + Aurora + Redis) (MA-122) | `services/pricing-offer` | — |

**What this delivers:** `POST /pricing/quote`, `GET /offers`, `POST /offers/validate` per MA-122's
merged spec (including its own PR #9 review fixes: tax/delivery-inclusive `monthlyEstimate`, the
`offerCode` request field, the BOGO M-unit precedence fix, clarified Redis invalidation, and the new
`active` field on `CatalogUpdated`) — plus the `CatalogUpdated` **producer** side this spec requires
on Catalog Service, which doesn't exist yet either.

**Path note:** single-area story (`services` only, one new service directory
`services/pricing-offer/`) — this plan lives at `services/tasks/MA/MA-101/impl-plan/`, mirroring
MA-23's and MA-96's own impl plans.

## 2. Prerequisites

Confirmed by reading each target service directly:

| Dependency | MA-122's framing | Actual state |
|---|---|---|
| Catalog Service — `hsnCode`/`gstRatePercent` on `Product` | §7: "flagged explicitly as a prerequisite for MA-42, not assumed to already exist" | **Confirmed absent** — `services/catalog/src/domain/models.py`'s `Product` dataclass has no such fields. |
| Catalog Service — `active` field (added by this spec's own PR #9 fix, alongside `CatalogUpdated`) | New field on the event this spec defines | **Confirmed absent** — same file, no `active`/deactivation concept anywhere in Catalog's domain model. |
| Catalog Service — `CatalogUpdated` **publisher** | §6: "a small, additive change... a new `adapters/catalog_updated_publisher.py`... confirmed by inspecting `services/catalog/src` directly, only a consumer (`stock_changed_consumer.py`) exists today, no publisher" | **Confirmed still true** — `services/catalog/src/adapters/` has `stock_changed_consumer.py` and `interfaces.py` only; no publisher of any kind (Catalog has never published an event in its life). |
| Cart Service (MA-96) — the other synchronous caller of this contract | "kept in sync in this same drafting pass" | **Also doesn't exist** — MA-96 has its own impl plan (PR #11) but zero code yet. This service's own contract tests (§10) have no real second party to run against today. |

**New, previously-unflagged gap found:** Catalog Service itself is missing more than its domain
model fields — **it has no `Dockerfile` and no `infra/` CDK directory at all**, unlike Inventory
(which has both, fully realized) or User/Identity-Auth (Lambda CDK stacks). This means Catalog was
never actually made deployable, only runnable locally via `python src/main.py`. Out of scope for
this plan to fix (Catalog's own deployability is Catalog's story, not Pricing's), but it means the
`CatalogUpdated` producer work this plan requires on Catalog's side (§4A below) is being added to a
service with an incomplete deployment story — flagged for whoever picks that piece up.

**Real, working precedent found for every part of this service:**
- `services/catalog/src/main.py` (and `inventory/src/main.py`, which it mirrors) — the
  background-consumer-thread + `uvicorn.run(app, ...)` single-Fargate-task pattern. Pricing's own
  `main.py` runs the same way, with a `CatalogUpdatedConsumer` in place of `StockChangedConsumer`.
- `services/catalog/src/adapters/stock_changed_consumer.py` — the SQS consumer shape (poll, parse,
  apply, delete-on-success, leave-in-queue-for-DLQ on failure) Pricing's own `CatalogUpdatedConsumer`
  follows exactly. Notably, this file's own payload contract already includes an `availableQuantity`
  field that `apply_stock_change(...)` receives and silently discards (confirmed by reading the code)
  — the same "event carries more than the domain model currently stores" situation this plan's own
  `CatalogUpdated` consumer must not repeat for `hsnCode`/`gstRatePercent`/`active`.
- `services/inventory/Dockerfile` + `services/inventory/infra/inventory/inventory_stack.py` — the
  real, complete Fargate CDK/container pattern (Catalog's own copy of this is missing — see above,
  so Inventory is the one to mirror, not Catalog).
- `services/catalog/src/config/env.py` — the `pydantic_settings`/`env_prefix` config pattern; Pricing
  uses `PRICING_` the same way.
- `services/user/src/adapters/inventory_client_adapter.py` — not directly needed here (Pricing calls
  no other service synchronously per its own spec §8), but the same adapter shape applies if a future
  revision needs one.
- `services/local-dev/docker-compose.yml`/`init-databases.sql` — Postgres already runs one shared
  container with one database per service (`milkful_user`, `milkful_inventory`, `milkful_catalog`);
  Redis already runs one shared container, already used by `identity-auth` for rate-limiting (keys
  are caller-namespaced, e.g. `register:otp:{mobile}` — no adapter-level prefix). Pricing adds
  `milkful_offers` to `init-databases.sql` and its own key prefix (`pricing:tax:...`,
  `pricing:offers:...`) to the same Redis container — no new infrastructure, just one more logical
  database and one more key namespace on infra that already exists.

## 3. Implementation Order

1. **Catalog Service: `hsnCode`/`gstRatePercent`/`active` fields + `CatalogUpdated` publisher** — the
   real, shared blocker. Nothing in §4 below can be integration-tested until this lands, but it's a
   small, additive change to an already-shipped service (same category as MA-120 §7's
   `availableQuantity`, still itself unimplemented — three small Catalog additions now queued on the
   same service, worth landing together).
2. **`services/pricing-offer` scaffold** — `src/{handlers,domain,adapters,config}/`, `infra/`,
   `migrations/`, `tests/`, `Dockerfile`, matching Inventory's realized layout.
3. **Aurora schema + migrations** (`offers`, `offer_redemptions`, `product_tax` tables, per MA-122 §6
   as merged).
4. **Domain models + tax/offer-precedence logic** (`domain/tax_service.py`, `domain/offer_service.py`)
   — the bulk of this story's real business logic, buildable and fully unit-testable today with zero
   external dependencies.
5. **`CatalogUpdated` consumer** (`adapters/catalog_updated_consumer.py`) + Aurora `product_tax`
   read-model writer.
6. **Redis cache adapter** (`adapters/redis_cache_adapter.py`) — tax-computation cache with
   event-driven invalidation on `CatalogUpdated`, per this spec's own PR #9 fix (event-driven is
   primary, TTL is a backstop only).
7. **Handlers** (`quote_handler.py`, `offers_handler.py`, `offers_validate_handler.py`).
8. **`local-dev` integration + CDK stack**.

## 4. Per-File Implementation Steps

### §4A: Catalog Service — new fields + `CatalogUpdated` publisher

**Files to modify:**
- `services/catalog/src/domain/models.py` — `Product` gains `hsn_code: str | None`,
  `gst_rate_percent: float | None`, `active: bool = True`.
- `services/catalog/migrations/0003_hsn_gst_active.sql` — additive `ALTER TABLE`, all three columns
  nullable/defaulted (no backfill migration needed for `hsn_code`/`gst_rate_percent` — existing rows
  simply carry `NULL` until an admin sets real values through Catalog's own product create/update
  path, out of this spec's scope per its own §7/§11; `active` defaults `true` for every existing row).
- `services/catalog/src/handlers/dto.py` — no change needed for `GET /products` (these three fields
  are pricing/tax-internal, not part of the public product response contract MA-115/117 define).

**Files to create:**
- `services/catalog/src/adapters/catalog_updated_publisher.py` — the first outbox-style publisher
  Catalog Service has ever had (mirrors `user/src/adapters/outbox_event_publisher.py`'s shape:
  `EventBridge.put_events`, retry+backoff via a new `catalog/src/adapters/retry.py` copy).
- A transactional outbox table (`outbox_events`, matching `user`'s own Postgres outbox schema) and a
  hook into Catalog's own product create/update write path (MA-42/23.0, out of this spec's direct
  control per MA-122 §6 — the hook point is Catalog's, the publisher code is this story's to write).
- `services/catalog/src/handlers/outbox_publisher_handler.py` + `run_local_outbox_publisher.py`,
  matching `user`'s own pair.

**Payload** (per MA-122 FR-6 as merged, including the PR #9 `active` fix):
```json
{
  "eventId": "uuid", "productId": "uuid", "name": "string",
  "priceB2C": 0.0, "priceB2B": 0.0, "hsnCode": "string", "gstRatePercent": 0.0,
  "categoryId": "uuid", "subscriptionEligible": true, "active": true,
  "occurredAt": "2026-08-20T10:00:00Z"
}
```

**Tests to write:** unit tests for the publisher (mirrors `user`'s own outbox publisher test shape);
a migration test asserting existing seeded rows read back `active: true` with no manual backfill.

**Acceptance check:** `pytest services/catalog/tests/` passes (regression + new).

---

### §4B: `services/pricing-offer` scaffold

**Files to create:**
- `src/main.py` — mirrors `catalog/inventory`'s own (background consumer thread +
  `uvicorn.run(app, port=8005)` — port matches the mobile app's own `AppConfig.pricingBaseUrl`
  provisional port from the MA-23 impl plan §4D).
- `src/config/env.py` — `Settings(env_prefix="PRICING_")`: `database_url`, `aws_region`,
  `catalog_updated_queue_url`, `redis_host`, `redis_port`, `redis_use_tls`.
- `src/handlers/app.py`, `src/handlers/health.py`, `src/handlers/dependencies.py`,
  `src/handlers/dto.py` (response envelope helpers) — mirror Catalog's own equivalents file-for-file.
- `Dockerfile` — copies Inventory's exactly (Python 3.11-slim, `pip install -r requirements.txt`,
  `CMD ["python", "main.py"]`), not Catalog's (which doesn't have one to copy).
- `requirements.txt`/`requirements-dev.txt` — adds `redis` (not a dependency of any existing Fargate
  service yet; `identity-auth`, a Lambda service, is the only current `redis` consumer) alongside
  `fastapi`/`uvicorn`/`sqlalchemy`/`psycopg2-binary`/`boto3`, matching Catalog's own requirements
  baseline.

**Tests to write:** none yet (scaffold only) — `tests/conftest.py` copied from Catalog's own
(sqlite-swap-in-for-Aurora fixture pattern) as the base for everything below.

---

### §4C: Aurora schema + migrations

**Files to create:**
- `migrations/0001_offers_schema.sql` — per MA-122 §6 as merged:
  ```sql
  CREATE TABLE offers (
    id UUID PRIMARY KEY, type VARCHAR NOT NULL CHECK (type IN
      ('percentage','flat','bogo','first_order','subscription')),
    value NUMERIC NOT NULL, conditions JSONB NOT NULL DEFAULT '{}',
    valid_from TIMESTAMPTZ, valid_to TIMESTAMPTZ, active BOOLEAN NOT NULL DEFAULT true
  );
  CREATE TABLE offer_redemptions (
    id UUID PRIMARY KEY, offer_id UUID NOT NULL REFERENCES offers(id),
    user_id UUID NOT NULL, redeemed_at TIMESTAMPTZ NOT NULL
  );
  CREATE TABLE product_tax (
    product_id UUID PRIMARY KEY, hsn_code TEXT, gst_rate_percent NUMERIC,
    price_b2c NUMERIC NOT NULL, price_b2b NUMERIC, subscription_eligible BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true, updated_at TIMESTAMPTZ NOT NULL
  );
  ```

**Tests to write:** migration-apply test against sqlite/Aurora-test-fixture, matching Catalog's own
`tests/conftest.py` pattern.

---

### §4D: Domain — tax computation and offer precedence

**Files to create:**
- `src/domain/models.py` — `LineItemQuote`, `Quote` (cart-level), `Offer`, `OfferType` enum.
- `src/domain/exceptions.py` — `ProductPricingUnknownError`, `ProductDiscontinuedError` (this spec's
  PR #9 fix), `UsageLimitReachedError`, and the rest of MA-122 §9's enumerated failure modes.
- `src/domain/tax_service.py` — CGST/SGST-vs-IGST by delivery-state match against the seller's
  registered state (a new, small config value — `PRICING_SELLER_STATE` env var, not hardcoded, per
  services/README.md §7's "config via environment variables" rule).
- `src/domain/offer_service.py` — the precedence rule (largest absolute discount wins; BOGO compared
  by the **sum of all M free/discounted units**, per this spec's own PR #9 fix, not a single unit),
  tie-break by offer ID, and the four offer-type eligibility rules (FR-5).
- `src/domain/pricing_service.py` — orchestrates: resolve tax/HSN from the local `product_tax` read
  model (raising `ProductPricingUnknownError` if never populated, `ProductDiscontinuedError` if
  `active = false`) → apply auto-apply-or-supplied-`offerCode` per FR-4 → assemble the
  tax/delivery-inclusive monthly estimate for subscription frequencies (this spec's own PR #9 fix —
  `net payable per delivery × billing occurrences per month`, never unit price alone).

**Tests to write:** the bulk of this story's real coverage, fully independent of any other
service — tax computation (state-match vs. not), offer-precedence across mixed types including the
corrected BOGO M-unit math, subscription monthly-estimate math for both Daily/Alternate Days,
`ProductDiscontinuedError`/`ProductPricingUnknownError` branches.

---

### §4E: `CatalogUpdated` consumer

**Files to create:**
- `src/adapters/catalog_updated_consumer.py` — mirrors `stock_changed_consumer.py`'s shape exactly
  (poll → parse → apply → delete-on-success, malformed/transient failures left for retry/DLQ).
  Upserts `product_tax` from the event payload, including `active` — **must actually persist every
  field the payload carries**, unlike `stock_changed_consumer.py`'s own precedent of silently
  discarding `availableQuantity` (§2's flagged finding) — this consumer is the one place in this
  codebase that must not repeat that mistake.
- Wired into `main.py`'s background thread, per §4B.

**Tests to write:** consumer unit tests (malformed message left in queue, `active: false` correctly
flips the read-model row, not deleted) matching `test_stock_changed_consumer.py`'s shape.

---

### §4F: Redis cache adapter

**Files to create:**
- `src/adapters/redis_cache_adapter.py` — cache key per `(productId, quantity, frequency,
  deliveryState)` for computed tax; **event-driven invalidation is primary** (a `CatalogUpdated` for
  a product deletes every cached key for that `productId` — the consumer, §4E, calls this on every
  event), a long backstop TTL (24h) is secondary, per this spec's own PR #9 clarification — never
  implemented as TTL-only. Offer list cached with a short, time-only TTL (offers change far less
  urgently than a live price).

**Tests to write:** cache-hit/miss unit tests against a fake Redis client; the invalidation-on-event
path specifically (a cached quote for a product is gone immediately after that product's
`CatalogUpdated` is consumed, not merely eventually via TTL).

---

### §4G: Handlers

**Files to create:**
- `handlers/quote_handler.py` — `POST /pricing/quote`, request `{items: [...], deliveryState,
  offerCode?}` exactly matching MA-96/MA-121's own mirrored contract.
- `handlers/offers_handler.py` — `GET /offers`.
- `handlers/offers_validate_handler.py` — `POST /offers/validate`.

**Tests to write:** handler-level tests (routing, DTO validation, exception→HTTP mapping), matching
Catalog's own handler test shape.

**Acceptance check:** `pytest services/pricing-offer/tests/` — all pass.

---

### §4H: Local-dev integration + CDK

**Files to modify:**
- `services/local-dev/init-databases.sql` — add `CREATE DATABASE milkful_offers;`.
- `services/local-dev/README.md` — add `cd pricing-offer && python src/main.py # :8005` and (if a
  local outbox-drain is needed for `CatalogUpdated`'s own EventBridge→SQS wiring) the matching
  `bootstrap.py` SQS/EventBridge rule, mirroring `StockChanged`'s existing entries.

**Files to create:**
- `services/pricing-offer/infra/app.py`, `infra/cdk.json`, `infra/pricing_offer/pricing_offer_stack.py`
  — mirrors `inventory_stack.py`'s Fargate + ALB + Aurora-cluster-reference shape, plus an
  ElastiCache Redis cluster construct (new — no existing stack has one; Redis is currently only a
  local-dev Docker container, never provisioned via CDK anywhere in this repo yet).

**Acceptance check:** manual round-trip — `POST /pricing/quote` against the local stack once §4A's
Catalog additions have landed and at least one `CatalogUpdated` event has been consumed (seeded via
a manual EventBridge `put-events` call in local-dev, same as `StockChanged`'s own "no real producer
yet, tested against a fake/moto-published event" precedent).

## 5. Cross-Cutting Steps

- Regression-run Catalog Service's full test suite after §4A.
- `ruff check`/`pytest` clean across every new/modified file.
- Confirm `PRICING_SELLER_STATE` (§4D) is documented in this service's own `README.md`'s
  first-commit checklist alongside every other required env var — a genuinely new config value this
  story introduces, not covered by any existing service's precedent.

## 6. Test Strategy

Same layering as every other service: unit (domain — the largest share of this story's real
coverage, fully independent of Cart/Catalog), integration (`CatalogUpdated` → local `product_tax`
round-trip against moto SQS, matching `stock_changed_consumer`'s own test pattern; `POST
/pricing/quote` against a seeded Aurora-test fixture), contract (the shared `POST /pricing/quote`
shape — no second party to run this against yet since Cart Service is still just a plan, MA-96 PR
#11; write the fixture now so it's ready the moment Cart Service exists).

**Coverage threshold:** same as every prior service — no numeric threshold, "all tests pass" is the
gate.

## 7. Commit Strategy

One commit per lettered step in §4, in order:

1. `feat(catalog): hsnCode/gstRatePercent/active fields, CatalogUpdated publisher (MA-101)`
2. `feat(pricing-offer): service scaffold (MA-101)`
3. `feat(pricing-offer): Aurora offers/offer_redemptions/product_tax schema (MA-101)`
4. `feat(pricing-offer): tax computation and offer-precedence domain logic (MA-101)`
5. `feat(pricing-offer): CatalogUpdated consumer (MA-101)`
6. `feat(pricing-offer): Redis cache adapter (MA-101)`
7. `feat(pricing-offer): quote/offers/validate handlers (MA-101)`
8. `feat(pricing-offer): local-dev integration and CDK stack (MA-101)`

## 8. Risks and Blockers

- **Catalog Service's `CatalogUpdated` producer (§4A) is this story's real, shared blocker** — a
  genuine reopening of an already-shipped service (three new `Product` fields plus its first-ever
  event publisher), same category of risk MA-122 §11 itself already called out.
- **Catalog Service has no `Dockerfile`/`infra/` at all** — a real, previously-unflagged gap found
  while grounding this plan. Not this story's to fix, but worth raising since §4A's own work adds
  more to a service that currently can't be deployed the way every other implemented service can.
- **Cart Service (MA-96) — this service's other real caller — is still just a plan** (PR #11, zero
  code). The shared `POST /pricing/quote` contract test (§6) has no second implementation to run
  against yet; write it now, prove it once Cart Service exists.
- **New infrastructure this story introduces that no existing stack has provisioned via CDK yet**:
  an Aurora cluster of its own (`offers`) and, notably, **the first ElastiCache Redis construct
  anywhere in this repo's CDK** — Redis exists today only as a local-dev Docker container, never
  deployed via IaC. Flagged for architect awareness before `infra/` work lands, not assumed
  pre-approved.
- **`PRICING_SELLER_STATE`** (§4D) is a new, real business config value (the seller's own
  registered state, needed for the CGST/SGST-vs-IGST rule) with no existing precedent anywhere in
  this codebase — confirm the actual value with the business/finance owner before this ships to a
  real environment; a placeholder value is fine for local-dev only.
