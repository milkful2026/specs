# Implementation Plan — MA-123: Flutter Cart Review Screen

## 1. Overview

**Story:** [MA-23](https://milkfuldairyindia.atlassian.net/browse/MA-23) — Add to Cart (Flutter)
**Task/Spec:** [MA-123](https://milkfuldairyindia.atlassian.net/browse/MA-123) — Flutter Cart Review Screen
**Date:** 2026-08-31
**Author:** Claude Code (session), implementing the merged MA-123 spec

**Specs implemented:**

| Spec | Area | Backend story |
|------|------|----------------|
| Flutter Cart Review Screen (MA-123) | `mobile-app` | — |

**Relationship to the existing MA-23 plan:** `mobile-app/tasks/MA/MA-23/impl-plan/IMPLEMENTATION-PLAN.md`
already implemented MA-120 (the product-configuration/add-to-cart screen) against fakes, since Cart Service
and Pricing & Offer Service didn't exist yet at that time. **Both now exist and are running** (`services/cart`,
`services/pricing-offer` — confirmed by directory listing and by exercising both locally, see §2). This is a
separate file, not an edit to that plan, following the same one-file-per-spec convention the specs
themselves use (`MA-120.md` / `MA-123.md`) — the original plan documents work that's already shipped and
should stay an accurate historical record.

**What this delivers:** a new `/cart` screen — line items with live product data, quantity edit, removal,
and the real server-computed price breakdown — plus wiring the Home screen's dormant cart icon to it. No
backend changes.

## 2. Prerequisites

Confirmed by reading each target repo directly and by running the actual services, not assumed from the
spec's own claims:

| Repo/Service | Status |
|---|---|
| `milkful-app` (Flutter) | MA-120 already shipped — `ProductConfigBloc`/`ProductConfigScreen`/`CartRepository.addItem`/`Quote` model all exist and are reusable as-is. |
| `services/cart` (MA-96) | **Real, running.** `GET /cart`, `POST /cart/items`, `PUT /cart`, `DELETE /cart/items/{id}` all exist (`services/cart/src/handlers/`, `run_local.py`'s `ROUTES` table). Verified live: `GET /cart` returns `{items, cartVersion, quote}`; empty cart returns `200` with `items: [], cartVersion: 0, quote: null` (never `404`). |
| `services/catalog` (MA-94) | Real, running — `GET /products/{id}` already used by MA-120's stale-stock re-fetch; reused here unchanged for per-line-item product data. |
| `services/pricing-offer` (MA-101) | Real, running — not called directly by this plan; Cart Service's own `GET /cart` already calls it server-side to build the aggregate `quote` (`services/cart/src/domain/cart_service.py`'s `get_cart`). |
| Local dev environment | All four services above running locally (`docker compose` for identity-auth/user/inventory/catalog; `pricing-offer` and `cart` run natively per `services/local-dev/README.md` — ports 8000-8005 all live during this session). |

**What this means for scope:** unlike MA-120's plan, there are **no missing-service blockers** here. Every
piece of this plan can be built and integration-tested against the real local backend, not just fakes.

## 3. Implementation Order

1. **`lib/features/cart/models` additions (§4A)** — `CartLineItem`, `CartView`; `Quote` is reused unchanged
   from MA-120. Independent, no dependencies.
2. **`lib/features/cart/data/cart_repository.dart` additions (§4B)** — `getCart`/`updateItem`/`removeItem`
   added to the existing `CartRepository`/`DioCartRepository`. Depends on #1.
3. **`test/fakes/fake_cart_repository.dart` extension (§4B)** — alongside #2.
4. **`lib/features/cart/bloc/cart_bloc.dart` (§4C)** — depends on #2/#3 and `CatalogRepository.getProduct`
   (existing, MA-120 §6, unchanged).
5. **`lib/features/cart/presentation/cart_screen.dart` (§4D)** — depends on #4.
6. **Router + Home FAB wiring (§4E)** — depends on #5 existing to navigate to.

## 4. Per-Spec Implementation Steps

### §4A: Cart models

**Files to create:**
- `lib/features/cart/models/cart_line_item.dart` — `CartLineItem` (`id`, `productId`, `quantity`,
  `Frequency frequency`, `DateTime? startDate`, `DateTime addedAt`), `fromJson`/`toJson` matching
  `serialize_line_item` (`services/cart/src/handlers/dto.py`) field names exactly (`id`, `productId`,
  `quantity`, `frequency`, `startDate`, `addedAt`). `toJson` is needed because `PUT /cart` sends the full
  item list back (§4B).
- `lib/features/cart/models/cart_view.dart` — `CartView` (`List<CartLineItem> items`, `int cartVersion`,
  `Quote? quote`), matching `serialize_cart_view`. Reuses the existing `Quote` model
  (`lib/features/cart/models/quote.dart`) unchanged — its shape already matches `serialize_quote` exactly
  (confirmed field-for-field against `dto.py`).

**Implementation steps:**
1. `CartLineItem` first (no dependencies).
2. `CartView` (depends on `CartLineItem` and the existing `Quote`).

**Tests to write:**
- Unit: `CartLineItem.fromJson`/`toJson` round-trip, including `startDate: null` (one-time items).
- Unit: `CartView.fromJson` with a non-empty item list + quote, and with `items: [], quote: null`
  (empty-cart shape).

**Acceptance check:** `flutter test test/features/cart/models/` passes.

---

### §4B: `CartRepository` additions

**Files to modify:**
- `lib/features/cart/data/cart_repository.dart` — add three methods to the existing abstract
  `CartRepository` and `DioCartRepository`:
  ```dart
  Future<CartView> getCart();
  Future<CartView> updateItem({required List<CartLineItem> items, required int ifVersion});
  Future<void> removeItem({required String id});
  ```
  - `getCart()`: `await _client.request('GET', '${AppConfig.cartBaseUrl}/cart')`, parsed via
    `CartView.fromJson`.
  - `updateItem(...)`: `await _client.request('PUT', '${AppConfig.cartBaseUrl}/cart', body: {'items':
    items.map((i) => i.toJson()).toList(), 'ifVersion': ifVersion})`, parsed via `CartView.fromJson`
    (matches `dto.py`'s `ReplaceCartRequestDto`/`serialize_cart` exactly — note `PUT`'s response has no
    `quote` field, per `serialize_cart`'s own comment; `CartView.fromJson` must treat a missing `quote` key
    the same as an explicit `null`).
  - `removeItem(...)`: `await _client.request('DELETE', '${AppConfig.cartBaseUrl}/cart/items/$id')` —
    return value discarded (`204 No Content`, same pattern as `AuthRepository.logout`'s existing
    body-less-response handling).
- `test/fakes/fake_cart_repository.dart` — add matching fakes: `getCart` returns a configurable
  `CartView`/throws a configurable exception; `updateItem`/`removeItem` record their call args (mirroring
  the existing `FakeAddItemRequest` recording pattern) and throw a configurable exception, defaulting to
  success.

**Implementation steps:**
1. Add the three methods to the abstract class.
2. Implement each on `DioCartRepository`.
3. Extend the fake to match.

**Tests to write:**
- Unit: `DioCartRepository.getCart` against a mocked `ApiClient` — correct URL, response parsed into
  `CartView`.
- Unit: `DioCartRepository.updateItem` — request body shape (`items` serialized via `toJson`, `ifVersion`
  present), response parsed with `quote: null` when the key is absent.
- Unit: `DioCartRepository.removeItem` — correct URL (`id` interpolated), no body sent.

**Acceptance check:** `flutter test test/features/cart/data/` passes.

---

### §4C: `CartBloc`

**Files to create:**
- `lib/features/cart/bloc/cart_event.dart` — `CartStarted`, `QuantityChanged(lineItemId, newQuantity)`,
  `ItemRemoveRequested(lineItemId)`, `ItemRemoveConfirmed(lineItemId)`.
- `lib/features/cart/bloc/cart_state.dart` — phase-based, mirroring `ProductConfigState`'s shape:
  `CartLoadStatus` (loading/loaded/error), `List<CartLineItemView> items` (each pairing a `CartLineItem`
  with its resolved `Product?` — `null` while that specific product lookup is still in flight or failed,
  per spec FR-2's per-row degradation), `int cartVersion`, `Quote? quote`, and a per-action
  `writeInFlight`/`pendingRemovalId` flag set for the optimistic-UI revert path (spec FR-6).
- `lib/features/cart/bloc/cart_bloc.dart`.

**Implementation steps:**
1. `CartStarted`: calls `CartRepository.getCart()`; for each returned line item, fires a parallel
   `CatalogRepository.getProduct(productId)` (`Future.wait`, not sequential — spec FR-2's performance
   requirement) and pairs the results; a per-item `getProduct` failure sets that row's `Product?` to `null`
   rather than failing the whole load.
2. `QuantityChanged`: updates the target line item's quantity in local state immediately (optimistic),
   starts/resets a 500ms `Timer` (owned by the **screen**, matching `ProductConfigScreen`'s existing
   debounce-in-the-widget pattern from MA-120 §4E step 3 — not the bloc), which then dispatches an internal
   write. On the write: calls `CartRepository.updateItem` with the **full** current item list (spec FR-4 —
   `PUT /cart` is a replace, not a patch) and `cartVersion`; on success, replaces `items`/`cartVersion`
   from the response, then immediately calls `getCart()` again to refresh `quote` (spec FR-4 — `PUT`'s own
   response never carries a quote); on a `409 ApiException`, silently calls `getCart()` and re-applies the
   same target quantity against the fresh state (spec FR-6) rather than surfacing an error; any other
   `ApiException` reverts the optimistic quantity change and surfaces `e.message` via the bloc's error
   state (consumed by the screen as a SnackBar).
3. `ItemRemoveRequested`: sets `pendingRemovalId` — the screen listens for this to show the confirmation
   dialog (FR-5); the dialog itself is UI-only, no bloc event for "cancelled".
4. `ItemRemoveConfirmed`: removes the item optimistically from local state, calls
   `CartRepository.removeItem`; on success, if the resulting list is now empty, transition straight to the
   empty-cart state without an extra `getCart()` round-trip (spec FR-5) — otherwise call `getCart()` to
   refresh `quote`. Same `409`-silent-retry and other-error-revert handling as step 2.

**Tests to write:**
- Unit (`bloc_test`): `CartStarted` — happy path (items + products resolved); a `getProduct` failure for
  one item still resolves the bloc to `loaded` with that row's product `null`; a `getCart` failure resolves
  to an error state.
- Unit: `QuantityChanged` → `updateItem` called with the full item list and correct `cartVersion` after the
  debounce fires (use `bloc_test`'s fake-async / `Future.delayed` handling, matching how
  `ProductConfigBloc`'s own restartable-quote tests already handle timing).
- Unit: a `409` on `updateItem` triggers a silent `getCart` refetch and re-applied quantity, with no error
  state emitted.
- Unit: removing the last item transitions directly to the empty-cart state without an intermediate
  `getCart` call (assert `FakeCartRepository.getCart` call count).

**Acceptance check:** `flutter test test/features/cart/bloc/cart_bloc_test.dart` passes.

---

### §4D: `CartScreen`

**Files to create:**
- `lib/features/cart/presentation/cart_screen.dart` — per MA-123 spec §4 structure: empty state
  (`Key('cart-empty-state')`, `Key('cart-browse-products-cta')` routing to `/catalog`), line-item list
  (quantity stepper `Key('cart-item-quantity-decrease-{id}')`/`increase`/`value`, remove button
  `Key('cart-item-remove-{id}')` with a confirmation `AlertDialog`), sticky bottom summary bar (Subtotal/
  Tax/Delivery/Discount-if-present/Total rows from `state.quote`, plus `monthlyEstimate` when non-null),
  and the disabled `Key('cart-checkout-cta')` placeholder button (spec FR-7).
- Follows the same `Card`-based layout and `FilledButton` conventions already established in
  `product_config_screen.dart`; the 500ms debounce `Timer` for quantity changes lives here, in the
  `StatefulWidget`, per §4C step 2.

**Implementation steps:** per MA-123 spec §4 FR-1–FR-8.

**Tests to write:** the five widget scenarios already enumerated in MA-123 spec §10, built against
`FakeCartRepository` and the existing `FakeCatalogRepository`.

**Acceptance check:** `flutter test test/features/cart/presentation/cart_screen_test.dart` passes; manual
walkthrough against the real local Cart + Catalog services (both running, §2) — per MA-123 spec §10's
acceptance check, fake-only verification is not sufficient here since the real backend already exists.

---

### §4E: Router + Home FAB wiring

**Files to modify:**
- `lib/core/router/app_router.dart` — add `GoRoute(path: '/cart', builder: (context, state) => const
  CartScreen())` alongside the existing `/catalog` and `/product/:productId` entries. No `extra:` payload.
- `lib/features/home/presentation/home_screen.dart` — line 171, `onPressed: null` →
  `onPressed: () => context.push('/cart')` on the existing `Key('cart-fab')` `FloatingActionButton`. Remove
  the now-inaccurate "No cart feature/backend yet" comment above it (lines 169-170).

**Tests to write:**
- Widget: tapping `Key('cart-fab')` in `home_screen_test.dart` navigates to `/cart` (extends the existing
  test file — check first whether it currently asserts `onPressed == null` and update that expectation).
- Router: `/cart` renders `CartScreen` (extends `app_router_test.dart`).

**Acceptance check:** `flutter test test/features/home/ test/core/router/` passes.

## 5. Cross-Cutting Steps

- Regression-run the full `flutter test` suite after §4E's `home_screen.dart` change — it's a modification
  to an existing, already-tested file.
- Manual end-to-end walkthrough against the real local stack (§2): add an item via the existing MA-120
  screen, open `/cart` via the Home FAB, edit quantity, remove an item down to empty, confirm the summary
  bar always matches what `GET /cart` actually returns.
- `flutter analyze` clean across all new/modified files.

## 6. Test Strategy

Same fake-first approach as MA-120, **plus** a real manual integration pass — unlike MA-120's plan, this
one's backend dependency (Cart Service) is fully implemented and running, so "all tests pass against fakes"
is necessary but not sufficient; the manual walkthrough in §5 is a required acceptance step, not optional
follow-up.

**Coverage threshold:** same as MA-120/MA-1/MA-21 — no numeric threshold, "all tests pass" is the gate.

## 7. Commit Strategy

One commit per lettered step in §4, in order:

1. `feat(mobile): CartLineItem, CartView models (MA-123)`
2. `feat(mobile): CartRepository.getCart/updateItem/removeItem + fakes (MA-123)`
3. `feat(mobile): CartBloc (MA-123)`
4. `feat(mobile): CartScreen (MA-123)`
5. `feat(mobile): wire /cart route and Home cart FAB (MA-123)`

Each references `MA-123`.

## 8. Risks and Blockers

- **None backend-side** — unlike MA-120's plan, both dependencies (`services/cart`, `services/catalog`)
  are real and running; this plan has no "blocked until X exists" caveats.
- **`PUT /cart` full-replace semantics (§4B/§4C)** — sending the whole item list on every quantity change
  is a real, accepted trade-off from the spec (§11), not an implementation shortcut; if Cart Service later
  adds a per-item `PATCH`, this is the one place that would change.
- **N parallel `getProduct` calls (§4C step 1)** — same accepted-for-now scaling limit the spec's §11
  already flags; not a blocker for this plan, revisit only if real cart sizes prove it wrong.
