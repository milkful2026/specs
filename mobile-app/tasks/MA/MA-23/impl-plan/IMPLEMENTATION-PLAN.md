# Implementation Plan — MA-23: Flutter Product Configuration & Add-to-Cart Screen

## 1. Overview

**Story:** [MA-23](https://milkfuldairyindia.atlassian.net/browse/MA-23) — Flutter Product
Configuration & Add-to-Cart Screen
**Date:** 2026-08-21
**Author:** Claude Code (session), implementing the merged MA-120 spec

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Flutter Product Configuration & Add-to-Cart Screen (MA-120) | `mobile-app` | — |

**Deliberately not implemented by this plan:** MA-96/MA-121 (Cart Service) and MA-101/MA-122
(Pricing & Offer Service) are separate backend stories with their own specs (both merged, both
reviewed) but **zero implementation** — confirmed by listing `services/`, which contains only
`catalog/`, `identity-auth/`, `inventory/`, `user/`. This plan builds the mobile screen fully
against fakes and writes the `Dio`-backed repository implementations to the merged contracts, but
real end-to-end integration is blocked until those two services exist. See §2/§8.

**What this delivers:** the tap-through from `catalog_screen.dart`'s product cards into a new
configuration screen (frequency, start date, quantity, live price estimate, wallet-balance gate,
confirm), backed by new `CartRepository`/`PricingRepository` abstractions — fully testable today,
real-backend-integrable once MA-96/MA-101 land.

**Path note:** single-area story (`mobile-app` only) — this plan lives at
`mobile-app/tasks/MA/MA-23/impl-plan/`, alongside the spec it implements, rather than at the specs
repo root the way MA-1/MA-21's plans do — those were multi-area (`mobile-app` + `services`) stories
where the root was the only neutral location; MA-23 has no such ambiguity.

## 2. Prerequisites

Confirmed by reading each target repo directly, not assumed from the specs' own claims (two of
which — MA-120 FR-7 and MA-121 FR-6 — turned out to assert an integration as settled that isn't):

| Repo/Service | Status |
|---|---|
| `milkful-app` (Flutter) | Real, substantially built — registration, login, and catalog browse/search are implemented and merged. **Not** scaffold-only (unlike what MA-1's own plan described as its starting point). |
| `services/catalog` (MA-94) | Real, running code — `GET /products`, `GET /products/{id}` (`services/catalog/src/handlers/products_handler.py:21`), `GET /categories`, `GET /search` all exist today. **Missing:** the `availableQuantity` field MA-120 §7 calls for — `serialize_product` (`services/catalog/src/handlers/dto.py:16`) doesn't emit it yet. |
| `services/user` (MA-93/MA-107) | Real — `GET /users/me` exists (`services/user/src/handlers/dto.py:102`, `serialize_user_profile`), returns `userId/name/mobile/accountType/defaultAddressId` only. **Missing:** any way to resolve the default address's `state` — see §2.1, a gap this plan surfaces that neither MA-120 nor MA-121's own review passes caught. |
| `services/cart` (MA-96) | **Does not exist.** Spec merged (PR #8, reviewed) but no directory under `services/`. |
| `services/pricing-offer` (MA-101) | **Does not exist.** Spec merged (PR #9, reviewed) but no directory under `services/`. |
| `services/wallet` (MA-100) | **Does not exist at all — not even a spec.** MA-120 FR-7 and MA-121 FR-6 both describe it as "already shipped"; it isn't. Confirmed via `services/` directory listing (only `catalog/`, `identity-auth/`, `inventory/`, `user/`). |

**What this means for scope:** everything in §4 below is buildable and testable today against
fakes. The wallet-balance gate (FR-7) specifically **cannot** be built against a real balance read
at all — there is no service to call. It's implemented against a fake balance source with a clearly
isolated seam (see §4D), so swapping in a real `WalletRepository` later is a small, contained change
once MA-100 exists — not a rewrite.

### 2.1 New gap found: mobile has no way to resolve the customer's delivery-address state

MA-120's FR-5 (as corrected in the PR #7 review) says the quote request's delivery-address state is
"sourced from the address captured during onboarding, `address_screen.dart`'s `state-field`." That
turns out not to be true of the actual code: `address_screen.dart` submits an `AddressDraft`
(carrying `state`) into `RegistrationBloc` and never retains it anywhere retrievable afterward — no
field on `UserProfile` (`lib/features/auth/models/user_profile.dart`), `AuthBloc`, or any local
storage holds the customer's address `state` post-registration. `GET /users/me`'s response
(`services/user/src/handlers/dto.py:102`) returns `defaultAddressId` only, not the address body,
even though the backend's own `UserProfile` domain object already carries the full `Address` list
(`services/user/src/domain/models.py`) — the data exists server-side, it's just never serialized
out.

**Resolution (small, additive, same category as this SDD chain's other flagged contract
additions):** `serialize_user_profile` gains a `defaultAddressState` field, resolved by matching
`default_address_id` against `profile.addresses` (`None` if no default address is set — mirrors the
`DELIVERY_ADDRESS_REQUIRED` case MA-121 §9 already anticipates for Cart Service's own resolution
path). The mobile `UserProfile` model gains the matching nullable field. This must land before
`ProductConfigBloc` can call `PricingRepository.quote(...)` with a real state value instead of a
placeholder — see §4A/§4D.

## 3. Implementation Order

1. **`services/user`: `defaultAddressState` addition (§4A)** — independent, small; unblocks FR-5's
   real state value. Can happen in parallel with everything below.
2. **`lib/core/network/api_client.dart`: per-call headers support (§4B)** — independent; needed by
   FR-8's Idempotency-Key header.
3. **`lib/features/catalog`: `getProduct` + `Product.availableQuantity` (§4C)** — independent;
   needed by the screen's stale-stock re-fetch (MA-120 §9) and quantity stepper max (FR-4).
4. **`lib/features/cart`: models, repositories, fakes (§4D)** — depends on #2 (headers) for
   `CartRepository`'s Idempotency-Key; otherwise independent of #1/#3.
5. **`lib/features/cart`: `ProductConfigBloc` (§4E)** — depends on #3 and #4.
6. **`lib/features/cart`: `ProductConfigScreen` (§4F)** — depends on #5.
7. **`_ProductCard.onTap` + `/product/:productId` route (§4G)** — depends on #6 existing to
   navigate to.

## 4. Per-Spec Implementation Steps

### §4A: `services/user` — `defaultAddressState`

**Files to modify:**
- `services/user/src/handlers/dto.py` — `serialize_user_profile` resolves and adds
  `defaultAddressState`.

**Implementation steps:**
1. In `serialize_user_profile`, find the `Address` in `profile.addresses` whose id matches
   `profile.default_address_id`; add `"defaultAddressState": match.state if match else None` to the
   returned dict.
2. No domain/model change needed — `Address.state` already exists
   (`services/user/src/domain/models.py:10`).

**Tests to write:**
- Unit: `serialize_user_profile` with a matching default address (returns its `state`), with no
  default address set (returns `None`), with a `default_address_id` that doesn't match any address
  in the list (defensive — returns `None`, doesn't raise).
- Regression: existing `GET /users/me` integration test still passes with the new field present.

**Acceptance check:** `pytest services/user/tests/` passes.

**Mobile-side companion change:**
- `lib/features/auth/models/user_profile.dart` — add `final String? defaultAddressState;`,
  `json['defaultAddressState'] as String?` in `fromJson`, add to `props`.
- `test/features/auth/models/user_profile_test.dart` — update fixtures.

---

### §4B: `ApiClient` — per-call headers

**Files to modify:**
- `lib/core/network/api_client.dart` — `request()` and `_requestRaw()` gain an optional
  `Map<String, String>? headers` parameter, merged into `Options(method: method, headers: headers)`
  — additive to (not replacing) the interceptor's own `X-Request-Id`/`Authorization` injection.

**Implementation steps:**
1. Add the parameter, thread it through `_requestRaw` → `Options`.
2. Extract `_newRequestId()`'s random-hex-string generation into a small reusable
   `lib/core/utils/id_generator.dart` (`String newHexId({int bytes = 16})`), used both by
   `ApiClient`'s own request-ID generation and by `CartRepository`'s Idempotency-Key (§4D) — avoids
   adding the `uuid` package as a new dependency for something this codebase already hand-rolls one
   way.

**Tests to write:**
- Unit: a request with `headers` supplied sends them alongside the interceptor-injected ones (no
  existing `api_client_test.dart` today — this is the first direct unit test of `ApiClient`; keep it
  narrow, just the new parameter's behavior, not a full retest of the interceptor).

**Acceptance check:** `flutter test test/core/` passes.

---

### §4C: Catalog — `getProduct` + `availableQuantity`

**Files to modify:**
- `lib/features/catalog/data/catalog_repository.dart` — `CatalogRepository` gains
  `Future<Product> getProduct(String productId)`; `DioCatalogRepository` implements it via
  `GET {catalogBaseUrl}/products/{id}` (endpoint already exists server-side, confirmed §2 — no
  backend change needed for this method itself).
- `lib/features/catalog/models/product.dart` — add `final int? availableQuantity;`, parsed from
  `json['availableQuantity'] as int?` (nullable — the field doesn't exist on the wire yet, see §2;
  `null` is the expected, common case until Catalog Service's own small addition lands).
- `test/fakes/fake_catalog_repository.dart` — add `getProduct`.

**Implementation steps:**
1. Add the field and parsing to `Product`/`Product.fromJson` — purely additive, no existing call
   site touches `availableQuantity`.
2. Add `getProduct` to the abstract class and `DioCatalogRepository`.
3. Add a matching fake implementation (returns a seeded product or throws `ApiException` for a
   configurable test scenario, matching this codebase's existing fake conventions).

**Tests to write:**
- Unit: `Product.fromJson` with and without `availableQuantity` present (both must parse cleanly).
- Unit: `DioCatalogRepository.getProduct` against a mocked `ApiClient` response.

**Acceptance check:** `flutter test test/features/catalog/` passes.

**Flagged, not blocking:** Catalog Service's own `availableQuantity` addition (`services/catalog`)
is a separate, small PR to that service — until it lands, every `Product` this app sees has
`availableQuantity == null`, and the quantity stepper (§4F) uses its documented fallback cap of 20
(MA-120 §7). This doesn't block anything in this plan; it degrades gracefully by design.

---

### §4D: `lib/features/cart` — models, repositories, fakes

**Files to create:**
- `lib/features/cart/models/frequency.dart` — `enum Frequency { oneTime, daily, alternateDays }`
  with `ONE_TIME`/`DAILY`/`ALTERNATE_DAYS` wire (de)serialization, mirroring `StockState`'s
  from-json-with-safe-fallback pattern in `product.dart`.
- `lib/features/cart/models/quote.dart` — `Quote` (`basePrice, taxAmount, taxRate, deliveryFee,
  netPayable, monthlyEstimate` (nullable, subscription-only), `appliedOfferId`/`discountAmount`
  (both nullable)) — mirrors MA-101/MA-122 FR-1's response shape as merged (including its PR #9
  fix: `monthlyEstimate` is tax/delivery/discount-inclusive, not unit-price-only).
- `lib/features/cart/data/pricing_repository.dart` — abstract `PricingRepository`:
  ```dart
  Future<Quote> quote({
    required String productId,
    required int quantity,
    required Frequency frequency,
    required String? deliveryState, // null until §4A/§2.1 lands or the read fails
    String? offerCode, // MA-101/MA-122 PR #9's added field; always null from this screen —
                        // no offer-code UX exists anywhere in this app (MA-120 §3 out of scope)
  });
  ```
  `DioPricingRepository` posts to `{pricingBaseUrl}/pricing/quote`. If `deliveryState` is `null`,
  it throws a distinct client-side `ApiException(errorCode: 'DELIVERY_STATE_UNKNOWN', ...)` rather
  than silently omitting the field — Pricing can't compute tax without it (MA-101 FR-2), so failing
  fast client-side surfaces the real cause instead of a confusing backend validation error.
- `lib/features/cart/data/cart_repository.dart` — abstract `CartRepository`:
  ```dart
  Future<void> addItem({
    required String productId,
    required int quantity,
    required Frequency frequency,
    DateTime? startDate,
  });
  ```
  `DioCartRepository` posts to `{cartBaseUrl}/cart/items` with an `Idempotency-Key` header — one
  `newHexId()` (§4B) generated when the confirm attempt starts and reused across any retry of that
  same attempt (MA-121 FR-8's contract), not regenerated per HTTP call.
- `test/fakes/fake_pricing_repository.dart`, `test/fakes/fake_cart_repository.dart` — configurable
  success/failure fakes, matching `fake_catalog_repository.dart`'s existing shape.
- `lib/core/config/app_config.dart` — add `cartBaseUrl` (`CART_BASE_URL`, default
  `http://localhost:8004`) and `pricingBaseUrl` (`PRICING_BASE_URL`, default
  `http://localhost:8005`) — port numbers are provisional (next free slots after the existing
  8000-8003 range); confirm against `services/local-dev/README.md` once those two services are
  actually scaffolded, since this plan can't see a port assignment for services that don't exist
  yet.

**Wallet balance — isolated seam, no real backend:**
- `lib/features/cart/data/wallet_balance_repository.dart` — abstract
  `WalletBalanceRepository { Future<int> getBalance(); }`, with only a
  `FakeWalletBalanceRepository` (test/fakes) provided — **no `Dio` implementation**, since
  `services/wallet` doesn't exist (§2). `ProductConfigBloc` (§4E) depends on the abstraction only;
  wiring a real implementation is a follow-up change scoped entirely to this one file plus DI
  registration, once MA-100 exists.

**Implementation steps:**
1. `Frequency` enum + wire mapping first — everything else depends on it.
2. `Quote` model.
3. `PricingRepository` (abstract + Dio + fake) — includes the `DELIVERY_STATE_UNKNOWN` fail-fast.
4. `CartRepository` (abstract + Dio + fake) — includes Idempotency-Key generation/reuse.
5. `WalletBalanceRepository` (abstract + fake only).
6. `AppConfig` additions.

**Tests to write:**
- Unit: `Frequency` wire (de)serialization, including an unrecognized-value fallback if one is
  warranted (mirrors `StockState`'s pattern — decide based on whether an unknown frequency is a
  realistic wire scenario; if not, an assertion/throw is more honest than a silent fallback here).
- Unit: `DioPricingRepository.quote` — request shape (all fields, including `offerCode: null`)
  against a mocked `ApiClient`; `DELIVERY_STATE_UNKNOWN` thrown when `deliveryState` is null without
  a network call being attempted.
- Unit: `DioCartRepository.addItem` — `Idempotency-Key` header present and stable across two calls
  built from the same generated key.

**Acceptance check:** `flutter test test/features/cart/` passes (fakes only — no real backend
exists to integration-test against, see §2).

---

### §4E: `ProductConfigBloc`

**Files to create:**
- `lib/features/cart/bloc/product_config_event.dart` — `ProductConfigStarted`,
  `FrequencyChanged`, `StartDateChanged`, `QuantityChanged`, `AddToCartRequested`.
- `lib/features/cart/bloc/product_config_state.dart` — phase-based, mirroring
  `RegistrationState`'s shape (`product`, `selection` (frequency/date/quantity), `quote`
  (idle/loading/loaded/error), `walletCheck` (idle/loading/sufficient/insufficient/error),
  `confirm` (idle/loading/success/error)).
- `lib/features/cart/bloc/product_config_bloc.dart`.

**Implementation steps:**
1. `ProductConfigStarted`: seeds state from the `Product` passed via route `extra:` (MA-120 §6),
   then kicks off the stale-stock re-fetch (`CatalogRepository.getProduct`, §4C) and the wallet
   balance read (`WalletBalanceRepository`, §4D) in parallel — neither blocks initial render.
2. `FrequencyChanged`/`QuantityChanged`/`StartDateChanged`: update selection, then re-issue a quote
   request. Register these three (or a shared internal `_QuoteRequested` they all funnel into) with
   **`transformer: restartable()`** from `bloc_concurrency` — this is `CatalogBloc`'s own established
   pattern (`lib/features/catalog/bloc/catalog_bloc.dart:14-26`) for exactly this problem (a rapid
   sequence of user-driven events where only the latest matters): it cancels any in-flight quote
   handler when a newer one starts, which solves both FR-5's debounce-adjacent need and the
   out-of-order-response risk the PR #7 review flagged, without a hand-rolled sequence number.
3. Debounce (300ms) belongs in the **screen's** `Timer`, not the bloc — matches
   `catalog_page.dart`'s `_onSearchChanged` pattern (`Timer` in the `StatefulWidget`, dispatching the
   bloc event after the delay) rather than the bloc debouncing its own input.
4. `AddToCartRequested`: gates on `walletCheck == sufficient` for subscription frequencies only
   (FR-7), then calls `CartRepository.addItem`.

**Tests to write:**
- Unit (`bloc_test`): each event's state transitions; `restartable()` behavior — a `QuantityChanged`
  fired while a prior quote is in flight cancels the prior handler (assert only the latest quote
  result lands in state); wallet gate blocks `AddToCartRequested` for subscription frequencies with
  insufficient balance but not for one-time; add success/failure paths.

**Acceptance check:** `flutter test test/features/cart/bloc/` passes.

---

### §4F: `ProductConfigScreen`

**Files to create:**
- `lib/features/cart/presentation/product_config_screen.dart` — per MA-120 §4 structure (frequency
  cards, calendar, quantity stepper, price estimate, sticky bottom bar), following the `Card`-based
  layout already established in `welcome_screen.dart`/`address_screen.dart`. `FilledButton` gets its
  `StadiumBorder` for free from the app-wide theme (`lib/core/theme/app_theme.dart:17-21`) — no
  per-widget styling needed.
- Calendar (FR-3): use Flutter SDK's built-in `CalendarDatePicker` (or a small hand-rolled month
  grid if its default chrome doesn't match the mockup closely enough) — **no new package** for this;
  `pubspec.yaml` has no calendar dependency today and this doesn't need one.

**Implementation steps:** per MA-120 §4 FR-2–FR-9, using the debounced-`Timer` pattern from §4E
step 3 for quantity/frequency changes.

**Tests to write:** the five widget scenarios already enumerated in MA-120 §10, built against
`FakeCartRepository`/`FakePricingRepository`/`FakeWalletBalanceRepository`.

**Acceptance check:** `flutter test test/features/cart/presentation/` passes; manual walkthrough on
an emulator against fakes (no real backend to test against yet, §2).

---

### §4G: Catalog card wiring + routing

**Files to modify:**
- `lib/features/catalog/presentation/catalog_screen.dart` — `_ProductCard` gains
  `required VoidCallback onTap`, wraps the card body in a tap handler. Per the PR #7 review's
  correction: this is a **new** field, not an already-declared one — the current constructor is
  `const _ProductCard({required this.product});` with no tap handling anywhere on the card, only the
  inner "Add" `FilledButton`'s empty `onPressed: () {}`. Use `InkWell`/`GestureDetector` on the outer
  `Container`, keeping the inner Add button's own tap target working independently (don't let the
  card's `onTap` also fire when Add is tapped).
- `lib/core/router/app_router.dart` — add
  `GoRoute(path: '/product/:productId', builder: (context, state) { final product = state.extra as
  Product?; if (product == null) return const HomeScreen(); ... })` — null-checked per the PR #7
  review's correction (this is the first route in the app to actually consume `state.extra`; no
  existing builder does, so there's no established null-handling precedent to copy — redirecting
  to `/home` rather than crashing is the safe default for a missing/deep-linked `extra`).

**Tests to write:**
- Widget: tapping a product card in `catalog_screen_test.dart` navigates with the right `Product`.
- Router: `/product/:productId` with `extra` present renders the screen; with `extra` missing
  redirects to `/home` (extends `app_router_test.dart`).

**Acceptance check:** `flutter test test/features/catalog/ test/core/router/` passes.

## 5. Cross-Cutting Steps

- Regression-run the full `flutter test` suite after §4G's `catalog_screen.dart` change — it's a
  modification to an existing, already-tested file, not just an extension.
- Confirm `AppConfig`'s two new base URLs (§4D) don't collide with whatever ports Cart Service and
  Pricing & Offer Service's own (not-yet-written) implementation plans eventually pick — this plan
  can't fully close that loop since neither service is scaffolded yet; flag it explicitly when those
  services' own plans are written (§8).
- `flutter analyze` clean across all new/modified files.

## 6. Test Strategy

Same fake-first approach already established for `catalog`/`onboarding` — every new repository gets
a hand-written fake in `test/fakes/`, every bloc is tested via `bloc_test`, every screen via widget
tests against the fakes. No integration test suite is possible for the `Dio` implementations
(`DioCartRepository`, `DioPricingRepository`) until Cart Service and Pricing & Offer Service exist —
those are written and unit-tested (request shape, header presence) against a mocked `ApiClient` only,
same as `DioCatalogRepository`'s own existing test pattern.

**Coverage threshold:** same as MA-1/MA-21 — no numeric threshold, "all tests pass" is the gate.

## 7. Commit Strategy

One commit per lettered step in §4, in order:

1. `feat(user): expose defaultAddressState on GET /users/me (MA-23)`
2. `feat(mobile): per-call headers on ApiClient (MA-23)`
3. `feat(mobile): CatalogRepository.getProduct, Product.availableQuantity (MA-23)`
4. `feat(mobile): CartRepository, PricingRepository, WalletBalanceRepository + fakes (MA-23)`
5. `feat(mobile): ProductConfigBloc (MA-23)`
6. `feat(mobile): ProductConfigScreen (MA-23)`
7. `feat(mobile): wire _ProductCard.onTap, /product/:productId route (MA-23)`

Each references `MA-23` and, once a Jira Task exists for this implementation pass, that Task's key.

## 8. Risks and Blockers

- **Real end-to-end verification is blocked on two backend stories that don't exist yet**
  (`services/cart`, `services/pricing-offer`) — this plan produces a fully fake-tested screen, not a
  working live purchase flow. Don't let "the mobile work is done" read as "MA-23 is done end to end."
- **Wallet Service (MA-100) doesn't exist at all** — FR-7's gate is real code against a fake balance
  source; there is no real balance to check against until that service is built (which, per §2, has
  no spec yet either — this is likely the actual next blocker for the broader cart/checkout effort,
  not just this screen).
- **§2.1's `defaultAddressState` addition is a small but real dependency on `services/user`** — if
  it's deprioritized, `PricingRepository.quote` calls fail closed with `DELIVERY_STATE_UNKNOWN`
  (§4D) rather than silently sending a wrong/missing state — a deliberate choice so a skipped
  prerequisite produces a loud, debuggable failure instead of a wrong tax computation. §4A is small
  enough to implement as part of this same plan, but it does touch a second repo (`services`), so
  flag it clearly if that's out of bounds for whoever picks this plan up.
- **Port numbers for `cartBaseUrl`/`pricingBaseUrl` (§4D) are provisional** — neither service exists
  to confirm against; revisit once their own implementation plans are written.
