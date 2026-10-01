# Implementation Plan — MA-26: Order History — Account / Orders (Flutter)

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-26](https://milkfuldairyindia.atlassian.net/browse/MA-26) — Order History · Account / Orders (Flutter) |
| **Date** | 2026-10-01 |
| **Specs implemented** | [MA-145](https://milkfuldairyindia.atlassian.net/browse/MA-145) — Flutter My Orders List · [MA-146](https://milkfuldairyindia.atlassian.net/browse/MA-146) — Flutter Order Detail (Basic) · [MA-147](https://milkfuldairyindia.atlassian.net/browse/MA-147) — Flutter Profile Screen and My Orders Entry Point |
| **Spec source** | `origin/main` after [specs#27](https://github.com/milkful2026/specs/pull/27), **including** the review revision `bf17770`. That revision covers: future-dated PAUSED subscriptions still scheduled; Catalog `price` is rupees → estimates in paise; `NEEDS_ATTENTION` + `CUTOFF_PASSED` is known-not-charged; no empty states on failed sources; the scheduled view checks Order Service before saying "now an order" |
| **Repos touched** | `milkful2026/milkful-app` only (no backend change) |
| **Code branch** | `feat/MA-26-order-history`, cut from `origin/main` |

**What this delivers:**
- The Profile tab (a stub today) opens a minimal **Profile** screen, whose **My Orders** row opens a new **My Orders** screen.
- My Orders shows **Today's Delivery**, an **Upcoming** tab (real orders plus each subscription's next delivery, shown as *Scheduled* with a marked estimate) and a paged **Past Orders** tab.
- Any entry opens a read-only **Order Details** screen, or a **Scheduled delivery** view.
- Statuses never claim "Delivered", and "You weren't charged" only appears where the backend has proven it.

**Codebase reality found during analysis (Step 2):**

1. **No shared money formatter.** `cart_screen.dart` has a private `_rupees(int paise)` (always two decimals). MA-145 needs "no decimals when whole" and MA-146 needs "always two decimals", so this plan adds `lib/core/utils/money.dart`. `cart_screen.dart` is left as is (no drive-by refactor).
2. **IST is computed inline** (`cart_screen.dart:624`, `DateTime.now().toUtc().add(5:30)`). The orders feature puts `istToday()` in a pure helper and injects a clock into its blocs for tests.
3. **`SubscriptionRepository` has no `get(id)`**, only `list()`, and `list()` unwraps `data['subscriptions']`. MA-146 FR-8 needs `GET /subscriptions/{id}`, so this plan adds `get(String id)` to the interface, the Dio implementation and `FakeSubscriptionRepository`.
4. **Screens own their blocs.** Routes are plain `const XScreen()`. Each screen (e.g. `SubscriptionsScreen`) creates its `BlocProvider` from the app-wide repositories in `main.dart`'s `MultiRepositoryProvider`. The new screens follow the same pattern, and the new `OrderRepository` is registered in `main.dart`.
5. **Four bottom bars, all hand-rolled:** `_HomeBottomNav` (`home_screen.dart:945`), `_SubscriptionsBottomNav` (`subscriptions_screen.dart:~522`), the Wallet screen's bar (`wallet_screen.dart:~895`), and the new Profile bar. No existing test asserts the Profile no-op, so no test has to be *removed*, only added. `WalletComingSoon` (shown when `WALLET_ENABLED` is off) has no bottom bar, so it needs no change.
6. **No CI in `milkful-app`.** The gate is local `flutter analyze` (no new errors or warnings) and `flutter test` (all green).
7. **`SubscriptionView.nextDeliveryDate` is a `DateTime?`** parsed from `YYYY-MM-DD`. The orders feature compares **date parts only** (a `DateOnly`-style year/month/day comparison), never instants.

## 2. Prerequisites

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `AppConfig.orderBaseUrl`, `AppConfig.subscriptionBaseUrl` | Already satisfied (`app_config.dart`) | — |
| `flutter_bloc`, `bloc_concurrency`, `go_router`, `equatable`, `intl` | Already satisfied (`pubspec.yaml`) | — |
| `bloc_test`, `mocktail`/fakes in dev deps | Already satisfied (existing bloc tests use `bloc_test` and `test/fakes/*`) | — |
| New packages | None | — |
| Backend endpoints (`GET /orders/me`, `GET /orders/{id}`, `GET /subscriptions`, `GET /subscriptions/{id}`, `GET /products/{id}`) | Already satisfied (MA-132/136/138 on `services` main; MA-131; MA-115) | — |
| `SubscriptionRepository.get(id)` | **Not done** | Add in MA-146 step 1 (interface + Dio + fake) |
| Shared money / IST helpers | **Not done** | Add in MA-145 step 1 |

## 3. Implementation Order

1. **MA-145 (My Orders list)** first. It creates the `orders` feature, the models, `OrderRepository` (including `getById`, used by MA-146), the pure helpers (`order_buckets`, `order_status_copy` with `isKnownNotCharged`, `money`, IST) and the `/orders` route. The other two specs depend on all of these.
2. **MA-146 (Order Detail)** second. It reuses MA-145's models, repository and status copy; adds failure-reason copy, the two detail routes (which MA-145's rows push to) and `SubscriptionRepository.get`.
3. **MA-147 (Profile + tab wiring)** last. It only needs `/orders` to exist. It's kept last so the shared bottom-bar edits land in one place, after the feature is navigable end to end.

All three ship in **one code PR** (one feature branch, one commit per spec). MA-147 FR-8 notes it depends on MA-145's route; one PR removes that ordering risk.

## 4. Per-Spec Implementation Steps

### MA-145: Flutter My Orders List

**Files to create:**
- `lib/core/utils/money.dart` — `formatPaise(int paise, {bool alwaysDecimals = false})` → `₹65` / `₹65.50` (or always `₹65.00`); `rupeesToPaise(double rupees)` → `(rupees * 100).round()`.
- `lib/core/utils/ist_clock.dart` — `typedef Clock = DateTime Function();`; `DateTime istNow(Clock clock)` (UTC + 5:30); `DateTime istToday(Clock clock)` (date-only `DateTime(y, m, d)`); `bool isSameDate(DateTime a, DateTime b)`.
- `lib/features/orders/models/order_summary.dart` — `OrderItem(productId, quantity)`; `OrderSource { subscription, checkout }` (unknown → checkout); `OrderStatus` value class with `wire` (raw string) and known constants CREATED/CONFIRMED/PAYMENT_FAILED/FAILED/NEEDS_ATTENTION/CANCELLED plus `isUnknown`. `OrderSummary` has `orderId, source, checkoutId, items, subscriptionId, amountPaise, deliveryDate (date-only), status, failureReason, createdAt, confirmedAt` and a defensive `fromJson` (missing `items` → `[]`; `deliveryDate` parsed from the leading `YYYY-MM-DD`).
- `lib/features/orders/models/orders_page.dart` — `OrdersPage(items, nextCursor)` with `fromJson`.
- `lib/features/orders/models/order_entry.dart` — sealed `OrderEntry` with `date`; `OrderedEntry(OrderSummary)`; `ScheduledEntry(subscriptionId, productId, quantity, date)` (also passed as `extra` to MA-146's route).
- `lib/features/orders/data/order_repository.dart` — `abstract class OrderRepository { Future<OrdersPage> listMine({String? cursor, int limit = 50}); Future<OrderSummary> getById(String orderId); }` and `DioOrderRepository(ApiClient)`:
  - `listMine` → `GET ${AppConfig.orderBaseUrl}/orders/me` with query `limit`, `cursor`;
  - `getById` → `GET …/orders/{id}`.
  - Errors surface as `ApiException`, unchanged.
- `lib/features/orders/domain/order_status_copy.dart` — `StatusChipSpec(label, tone, icon)` with `tone` ∈ {neutral, error, warning, primary}; `statusChip(OrderStatus)` per MA-145 FR-6 (unknown → title-cased raw value, neutral, no icon); `scheduledChip`; `bool isKnownNotCharged(OrderSummary)` = `CANCELLED` or `PAYMENT_FAILED`, or (`NEEDS_ATTENTION` and `failureReason == 'CUTOFF_PASSED'`); `bool isAmountStruck(OrderSummary)` = `isKnownNotCharged` **or** `FAILED` (MA-145 FR-8: a legacy `FAILED` order is struck through and left out of totals even though its charge isn't known, so it is not "known not charged"). MA-146 adds reason copy to this file.
- `lib/features/orders/domain/order_buckets.dart` — pure functions:
  - `Buckets bucketOrders(List<OrderSummary>, DateTime today)` → `today`, `upcoming`, `past`;
  - `List<ScheduledEntry> scheduledEntries(List<SubscriptionView>, List<OrderSummary> orders, DateTime today)`: status ≠ STOPPED, `nextDeliveryDate` non-null and after today, no order with the same (subscriptionId, date);
  - `List<DayGroup> groupByDate(List<OrderEntry>, {required bool ascending})`, where orders come before scheduled entries within a day;
  - `DayTotal dayTotal(List<OrderEntry>, Map<String, Product?> products)` → `paise`, `hasEstimate`. It excludes `isAmountStruck` (CANCELLED, PAYMENT_FAILED, FAILED, NEEDS_ATTENTION/CUTOFF_PASSED), estimates scheduled entries as `rupeesToPaise(price) * quantity`, and skips unknown prices;
  - `int? estimatePaise(ScheduledEntry, Product?)`.
- `lib/features/orders/bloc/my_orders_event.dart` — `MyOrdersOpened`, `MyOrdersRefreshed` (carries a `Completer` for `RefreshIndicator`), `PastPageRequested`, `RetryFailedSources`.
- `lib/features/orders/bloc/my_orders_state.dart` — `SourceStatus { loading, loaded, failed }`; `PagingStatus { idle, loading, failed }`. State holds `ordersStatus, subscriptionsStatus, orders (all loaded pages, deduped by orderId), nextCursor, subscriptions, products (Map<String, Product?>, where null = lookup failed), pagingStatus, refreshFailed (for the SnackBar)`, with `copyWith`, plus derived getters that call `order_buckets` with the injected today.
- `lib/features/orders/bloc/my_orders_bloc.dart` — `MyOrdersBloc(OrderRepository, SubscriptionRepository, CatalogRepository, {Clock clock})`:
  - **Opened / Refreshed:** `Future.wait` of `listMine(limit: 50)` and `subscriptionRepo.list()`, each wrapped so one failure doesn't fail the other; set the per-source statuses. Then `_resolveProducts()` fetches unseen product IDs with parallel `getProduct` calls; a failure caches `null`; emit as results arrive.
  - **Refreshed failure:** keep the previous data, set `refreshFailed`, and complete the `Completer`.
  - **PastPageRequested:** `droppable()` transformer; no-op when `nextCursor == null`. Append, dedupe and resolve the new products. On failure, `pagingStatus = failed` and existing items are kept.
  - **Refresh discards a stale page:** keep a `generation` counter bumped on each Opened/Refreshed, and ignore page results from an older generation.
  - **RetryFailedSources:** re-runs only the sources whose status is `failed`.
- `lib/features/orders/presentation/my_orders_screen.dart` — `MyOrdersScreen` creates `BlocProvider(create: MyOrdersBloc(context.read…)..add(MyOrdersOpened()))`. Layout: `Scaffold` with `AppBar(title: 'My Orders')` (automatic back arrow, no actions); `RefreshIndicator` over a `NestedScrollView` (or `CustomScrollView`) holding the Today section, then a `TabBar` (Upcoming/Past Orders) and a `TabBarView`. The Past tab's scroll listener dispatches `PastPageRequested` within 300 px of the end.
- `lib/features/orders/presentation/widgets/today_section.dart` — header (truck icon, "Today's Delivery", "N Items"/"1 Item" pill), item cards, the "Order total ₹X" header for multi-item orders (amounts struck through when `isAmountStruck`), and the empty/failed text per the MA-145 FR-5/FR-11 empty-state rule.
- `lib/features/orders/presentation/widgets/day_group_card.dart` — date label (see `formatGroupDate` below), total label ("₹X Total" / "≈ ₹X Total"), one `EntryRow` per entry.
- `lib/features/orders/presentation/widgets/entry_row.dart` — thumbnails (≤ 2 plus a "+N" bubble), summary text rules, the order's amount (struck through when `isAmountStruck`), a chip only if the status is not CONFIRMED (scheduled entries always show one), chevron (`Semantics(label: 'Open order')`). Tapping pushes `/orders/{id}` or `/orders/scheduled/{subscriptionId}` with `extra: entry`.
- `lib/features/orders/presentation/widgets/status_chip.dart` — renders a `StatusChipSpec` using `Theme.of(context).colorScheme` tokens (neutral = `surfaceContainerHighest`, error = `errorContainer`, warning = a `tertiaryContainer`-based amber, primary = `primaryContainer`); semantics `"Status: {label}"`.
- `lib/features/orders/presentation/widgets/product_thumb.dart` — `Image.network` with a placeholder and error builder.
- `lib/features/orders/presentation/order_formatting.dart` — `formatGroupDate(DateTime date, DateTime today, {required bool upcoming})`: "Tomorrow, 24 Oct" / "Yesterday, 22 Oct" / "Sat, 26 Oct", plus " 2025" when the year differs, via `intl` `DateFormat`.

**Files to modify:**
- `lib/main.dart` — construct `DioOrderRepository(apiClient)` and add `RepositoryProvider<OrderRepository>.value(value: orderRepository)` to `MultiRepositoryProvider`.
- `lib/core/router/app_router.dart` — add `GoRoute(path: '/orders', builder: (_, __) => const MyOrdersScreen())`. MA-146 adds the child routes in the correct order.

**Implementation steps:**
1. Add `money.dart` and `ist_clock.dart` with their unit tests.
2. Add the models with their `fromJson` tests (every field; unknown status/source; missing `items`; `deliveryDate` with and without a time suffix).
3. Add `order_repository.dart`, then register it in `main.dart`.
4. Add `order_status_copy.dart` (chips, `isKnownNotCharged`) and `order_buckets.dart`, with full unit tests (see Tests).
5. Add the bloc (events, state, bloc) with bloc tests.
6. Build the screen and widgets; add the `/orders` route.
7. Widget tests (see Tests). Run `flutter analyze` and `flutter test`.

**Tests to write** (`test/features/orders/…`, plus `test/core/utils/…`):
- **Unit — `money_test.dart`:** `formatPaise(6500)` → `₹65`; `formatPaise(6550)` → `₹65.50`; `alwaysDecimals` → `₹65.00`; `rupeesToPaise(32.5)` → `3250`; `rupeesToPaise(37.485)` → `3749`.
- **Unit — `ist_clock_test.dart`:** 18:29:59 UTC → same IST date; 18:30:00 UTC → next IST date.
- **Unit — `order_buckets_test.dart`:**
  - buckets across today, past and future for every status;
  - `scheduledEntries`: ACTIVE with a future date → entry; PAUSED with a future date → entry; STOPPED → none; null date → none; date == today → none; an order already for (sub, date) → none;
  - `dayTotal`: excludes CANCELLED, PAYMENT_FAILED, FAILED and NEEDS_ATTENTION/CUTOFF_PASSED; includes NEEDS_ATTENTION/SWEEP_EXHAUSTED; estimate `32.49 × 1` → `3249`; `37.485 × 2` → `7498` (unit rounded first: 3749 × 2); mixed day `6500 + estimate` → paise sum, `hasEstimate: true`; unknown price → skipped.
- **Unit — `order_status_copy_test.dart`:** every row of FR-6; `isKnownNotCharged` and `isAmountStruck` truth tables (they differ only on FAILED: not known-not-charged, but struck).
- **Bloc — `my_orders_bloc_test.dart`** (fakes: new `FakeOrderRepository` in `test/fakes/`, plus the existing `FakeSubscriptionRepository` and `FakeCatalogRepository`; fixed clock):
  - opened → loading → loaded with the correct derived buckets;
  - orders fail, subscriptions load → `ordersStatus: failed`; `RetryFailedSources` calls only `listMine`;
  - both fail → both failed; retry → loaded;
  - product cache: two refreshes → one `getProduct` per distinct ID (assert `requestedProductIds`);
  - `PastPageRequested` appends and updates the cursor; a second request while in flight is dropped; a page failure keeps the items and sets `pagingStatus: failed`;
  - refresh during an in-flight page → the page result is ignored;
  - refresh failure keeps the data and sets `refreshFailed`.
- **Widget — `my_orders_screen_test.dart`** (fakes + a `GoRouter` harness with stub routes for `/orders/:id`, `/orders/scheduled/:id` and `/catalog`; fixed clock):
  - today: 1 CONFIRMED 2-item order + 1 CANCELLED single-item → "Today's Delivery", "3 Items", "Order total" once, "Order Placed", "Cancelled";
  - a FAILED order in an Upcoming/Past group → "Failed" chip, amount rendered with `TextDecoration.lineThrough`, and not in the group's "₹X Total";
  - upcoming merge: "Tomorrow, …", "(Subscription)", "Scheduled", "≈ ₹… Total";
  - no "Delivered" text anywhere for a past CONFIRMED order;
  - taps push the right locations;
  - empty states with all sources loaded, and "Browse products" → `/catalog`;
  - orders failed → banner + "Couldn't load today's deliveries." / "Couldn't load past orders." and **no** "No deliveries today" / "No past orders yet";
  - pagination: scrolling Past to the end calls `listMine(cursor: …)`, then shows the appended group;
  - keys from MA-145 §10 are present.

**Acceptance check:** `flutter analyze` shows no new errors or warnings; `flutter test test/features/orders test/core/utils` all pass. Manual check on local-dev: `/orders` renders against a real Order Service.

### MA-146: Flutter Order Detail (Basic)

**Files to create:**
- `lib/features/orders/bloc/order_detail_cubit.dart` — `OrderDetailCubit(OrderRepository, CatalogRepository, {required String orderId})`:
  - `load()` / `refresh()`;
  - states `OrderDetailLoading`, `OrderDetailLoaded(order, products)`, `OrderDetailNotFound` (an `ApiException` with `statusCode == 404` or `errorCode == 'ORDER_NOT_FOUND'`), `OrderDetailError`;
  - product lookups are parallel; a failure → `null`, never an error.
- `lib/features/orders/bloc/scheduled_delivery_cubit.dart` — `ScheduledDeliveryCubit(SubscriptionRepository, OrderRepository, CatalogRepository, {required String subscriptionId, ScheduledEntry? initial, Clock clock})`:
  - `load()`: with `initial`, emit loaded without a network call (a product lookup only). Otherwise `subscriptionRepo.get(id)` → build the entry (same rule as `scheduledEntries`: not STOPPED, date after today); if it's not scheduled → `ScheduledDeliveryGone`.
  - `refresh()`: fetch the subscription. If the fetched date ≠ the shown date, look in the first page of `orderRepo.listMine()` for `subscriptionId` + `deliveryDate == shown date` → `change: becameOrder(orderId)`; otherwise (including a lookup failure) → `change: dateChanged`. If gone → `ScheduledDeliveryGone`.
  - The first load never does the orders lookup.
  - States: `ScheduledDeliveryLoading`, `ScheduledDeliveryLoaded(entry, product, change)`, `ScheduledDeliveryGone`, `ScheduledDeliveryError`.
  - **Errors (MA-146 §8 "Error → Retry"):** any failure of `subscriptionRepo.get` in `load()` or `refresh()` (network, 5xx, 404) → `ScheduledDeliveryError`. A product lookup failure is never an error (null product, "Price confirmed the evening before"), and a failed orders lookup in `refresh()` is `dateChanged`, not an error.
- `lib/features/orders/presentation/order_detail_screen.dart` — `OrderDetailScreen(orderId)` (own `BlocProvider`), with `RefreshIndicator` and sections per FR-2..FR-7 using the shared cards.
- `lib/features/orders/presentation/scheduled_delivery_screen.dart` — `ScheduledDeliveryScreen(subscriptionId, entry)`. A `BlocListener` shows the SnackBars:
  - "This delivery is now an order." with a **View order** action → `context.pushReplacement('/orders/{orderId}')`;
  - "Your next delivery has changed.";
  - **Manage subscription** → `context.go('/subscriptions')`.
  - `ScheduledDeliveryError` → "Couldn't load this delivery." + a **Retry** button that calls `load()`.
- `lib/features/orders/presentation/widgets/detail_cards.dart` — `DetailHeaderCard` (display ID, long-press → `Clipboard.setData(full id)` + "Order ID copied"; placed-on in IST; status banner; reason text), `ItemsCard`, `BillCard` (Grand Total / Estimated Total, strike-through and captions per FR-5, "—" for 0), `DeliveryInfoCard`, `PaymentMethodCard` ("Milkful Wallet").

**Files to modify:**
- `lib/features/orders/domain/order_status_copy.dart` — add `bannerSpec(OrderStatus)` (FR-3 banner texts); `String reasonText(String? failureReason)` per the FR-3 table with a generic default; `bool showsNotChargedCopy(OrderSummary)` (delegates to `isKnownNotCharged` + reason); `String? billCaption(OrderSummary)` → "Not charged" / "Charge under review" / null per FR-5; `String displayOrderId(String id)` (strip `ord_`, first 8 characters, uppercased, `#` prefix).
- `lib/features/subscriptions/data/subscription_repository.dart` — add `Future<SubscriptionView> get(String id)` to `SubscriptionRepository`; `DioSubscriptionRepository.get` → `GET ${AppConfig.subscriptionBaseUrl}/subscriptions/{id}` → `SubscriptionView.fromJson(data)` (same parsing as `list`).
- `test/fakes/fake_subscription_repository.dart` — implement `get(id)` (look up in `subscriptions`; a missing ID throws `ApiException(errorCode: 'SUBSCRIPTION_NOT_FOUND', statusCode: 404)`; optional `getException`; record `getCalls`).
- `lib/core/router/app_router.dart` — add, **in this order**, before `/orders/:orderId`:
  - `GoRoute('/orders/scheduled/:subscriptionId', builder: ScheduledDeliveryScreen(subscriptionId, entry: state.extra is ScheduledEntry ? … : null))`;
  - `GoRoute('/orders/:orderId', builder: OrderDetailScreen(orderId))`.
  - Top-level routes are used, matching the file's flat style.

**Implementation steps:**
1. `SubscriptionRepository.get` + the Dio implementation + the fake, with a repository unit test if the repo has one for `list` (else covered by the cubit tests).
2. Extend `order_status_copy.dart` with unit tests.
3. `OrderDetailCubit` + tests; `OrderDetailScreen` + cards.
4. `ScheduledDeliveryCubit` + tests; `ScheduledDeliveryScreen`.
5. Add the routes in the correct order; router test.
6. Widget tests; `flutter analyze`; `flutter test`.

**Tests to write:**
- **Unit — `order_status_copy_test.dart` (extended):**
  - every reason → its text; unknown/null → the generic text;
  - "You weren't charged" only for CUTOFF_PASSED;
  - `billCaption` truth table (CANCELLED/PAYMENT_FAILED → "Not charged"; NEEDS_ATTENTION + CUTOFF_PASSED → "Not charged"; NEEDS_ATTENTION + SWEEP_EXHAUSTED/null → "Charge under review"; FAILED → null; CONFIRMED → null);
  - `displayOrderId('ord_3f9a2c1b…')` → `#3F9A2C1B`; with no prefix → first 8 characters.
- **Cubit — `order_detail_cubit_test.dart`:** loaded + products; 404 → notFound; 500 → error → `load()` again → loaded; product failure → loaded with a null product.
- **Cubit — `scheduled_delivery_cubit_test.dart`:**
  - `initial` given → loaded, zero `get` calls;
  - no `initial` → `get` called → loaded, no `listMine` call;
  - STOPPED / null date → gone; PAUSED with a future date → loaded;
  - refresh with a new date + a matching order on page 1 → `becameOrder(orderId)`;
  - a new date with no match → `dateChanged`; `listMine` throws → `dateChanged`;
  - no `initial` and `get` throws (`getException`, and a missing ID → 404) → error; `load()` again after clearing the exception → loaded;
  - `refresh()` when `get` throws → error;
  - product lookup throws → loaded with a null product (not an error).
- **Widget — `order_detail_screen_test.dart`:** the MA-146 §10 scenarios:
  - confirmed checkout order: labels present; "Delivered", "Download Invoice", "Reorder Items" and "Leave Feedback" absent;
  - cancelled at the cut-off;
  - NEEDS_ATTENTION + SWEEP_EXHAUSTED and NEEDS_ATTENTION + CUTOFF_PASSED (the copy rules both ways);
  - pre-pricing ₹0 → "—";
  - 404 → "Order not found"; "Back to My Orders" pops;
  - long-press copy (mock the `SystemChannels.platform` clipboard handler).
- **Widget — `scheduled_delivery_screen_test.dart`:**
  - "SCHEDULED DELIVERY", "Scheduled", "Estimated Total", "≈ ₹…", the caption, and "Manage subscription" → `/subscriptions`;
  - `becameOrder` → SnackBar "This delivery is now an order." + "View order" → replaces with `/orders/{id}`;
  - `dateChanged` → "Your next delivery has changed.";
  - deep link with `get` failing → "Couldn't load this delivery." + "Retry"; tapping Retry with the fake now succeeding → the loaded view.
- **Router — extend `test/core/router/app_router_test.dart`:** `/orders/scheduled/sub_1` builds `ScheduledDeliveryScreen`, not `OrderDetailScreen('scheduled')`; `/orders/ord_1` builds `OrderDetailScreen`.

**Acceptance check:** `flutter test test/features/orders test/core/router` passes; `flutter analyze` is clean. Manual check: open a real order from My Orders; its total matches the wallet debit in Wallet.

### MA-147: Flutter Profile Screen and My Orders Entry Point

**Files to create:**
- `lib/features/profile/bloc/profile_header_cubit.dart` — `ProfileHeaderCubit(ProfileRepository)`: `load()`; states `loading / loaded(UserProfile) / error`.
- `lib/features/profile/presentation/profile_screen.dart` — `ProfileScreen` (own `BlocProvider`; `AppBar(title: 'Profile', automaticallyImplyLeading: false)`), containing:
  - the header card: an initials avatar (a person icon when the name is empty), the name (or "Milkful customer"), and the mobile formatted by `formatIndianMobile`; on error, "Couldn't load your profile" + **Retry**;
  - the hero **My Subscription** row with a "Manage >" pill → `context.go('/subscriptions')`;
  - a **My Orders** row → `context.push('/orders')`;
  - a **FINANCIALS** label and a **Transactions** row → `context.push('/wallet/transactions')`;
  - `_ProfileBottomNav` (`currentIndex: 3`; Home → `go('/home')`, Schedule → `go('/subscriptions')`, Wallet → `go('/wallet')`, Profile → no-op).
- `lib/features/profile/presentation/mobile_format.dart` — `formatIndianMobile(String?)`: 10 digits, or `+91`/`91` + 10 digits → `+91 98765 43210`; anything else → as stored; empty → null (hidden).

**Files to modify:**
- `lib/core/router/app_router.dart` — `GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen())`.
- `lib/features/home/presentation/home_screen.dart` — `_HomeBottomNav.onTap`: `if (index == 3) context.go('/profile');` and remove the "Profile remains a stub" comment.
- `lib/features/subscriptions/presentation/subscriptions_screen.dart` — `_SubscriptionsBottomNav.onTap`: index 3 → `context.go('/profile')`; remove the stub comment.
- `lib/features/wallet/presentation/wallet_screen.dart` — the Wallet bar's `onTap`: index 3 → `context.go('/profile')`.
- *(Optional, per MA-147 §5)* A shared `AppBottomNav` widget is **not** introduced in this PR. It would touch three features' layouts and tests for no user-visible gain; left for a later refactor.

**Implementation steps:**
1. `formatIndianMobile` + unit tests.
2. `ProfileHeaderCubit` + tests.
3. `ProfileScreen` + the `/profile` route.
4. Wire index 3 on the three existing bars.
5. Widget tests for Profile, plus one "Profile tab navigates" test added to each of `home_screen_test.dart`, `subscriptions_screen_test.dart` and `wallet_screen_test.dart`.
6. `flutter analyze`; `flutter test` (the whole suite, since shared screens changed).

**Tests to write:**
- **Unit — `mobile_format_test.dart`:** `9876543210`, `+919876543210` and `919876543210` → `+91 98765 43210`; `12345` → `12345`; `''` / null → null.
- **Cubit — `profile_header_cubit_test.dart`:** loaded; error; `load()` after error → loaded.
- **Widget — `profile_screen_test.dart`:**
  - renders the name, "+91 98765 43210", "My Subscription", "Manage", "My Orders", "FINANCIALS" and "Transactions";
  - no "Refer & Earn", "Offer Zone" or "Account & Preferences";
  - each row navigates (GoRouter harness);
  - a `getMe` failure → error + Retry, and "My Orders" still navigates;
  - its own bar: Profile selected; Home/Schedule/Wallet → the right locations.
- **Widget — existing screens:** on the Home, Subscriptions and Wallet screens, tapping the bottom-bar item labelled "Profile" navigates to `/profile` (GoRouter harness with a stub `/profile`).

**Acceptance check:** full `flutter test` green; `flutter analyze` clean. Manual check: Home → Profile tab → My Orders → back → Profile.

## 5. Cross-Cutting Steps

1. `main.dart`: `OrderRepository` registered once (MA-145). No other providers are needed (`SubscriptionRepository`, `CatalogRepository` and `ProfileRepository` already exist).
2. `app_router.dart` final order: `/orders`, `/orders/scheduled/:subscriptionId`, `/orders/:orderId`, `/profile` (the relative order of scheduled vs `:orderId` is what matters).
3. Theme: widgets use `Theme.of(context).colorScheme` / `textTheme` only; no hex literals (`app_theme.dart` defines the palette).
4. Run the full suite and the analyzer once at the end.

## 6. Test Strategy

| Level | Location | Covers |
|-------|----------|--------|
| Unit (pure Dart) | `test/core/utils/`, `test/features/orders/domain/`, `test/features/profile/presentation/mobile_format_test.dart` | money, IST, buckets, merge, totals, status/reason copy, formatting |
| Bloc/Cubit | `test/features/orders/bloc/`, `test/features/profile/bloc/` | loading/partial/error/retry, cache, paging, refresh races, scheduled change detection |
| Widget | `test/features/orders/presentation/`, `test/features/profile/presentation/`, existing home/subscriptions/wallet tests | labels, states, navigation, keys |
| Router | `test/core/router/app_router_test.dart` | route order for `/orders/scheduled/...` |

**Commands** (from the `milkful-app` root):

```
flutter analyze
flutter test
flutter test test/features/orders test/features/profile test/core
```

**Coverage:** every pure function in `order_buckets.dart`, `order_status_copy.dart`, `money.dart` and `mobile_format.dart` is covered branch-by-branch (the truth tables above). There's no numeric coverage gate in this repo; the per-requirement tests are the gate. **Lint:** `flutter analyze` must add no errors or warnings (info-level lints consistent with the existing codebase are acceptable).

**Local-dev acceptance** (after the tests, before the PR):
1. With the local stack up, create a checkout order for tomorrow and a subscription.
2. Profile → My Orders: tomorrow's group shows the order; the subscription is "Scheduled" with "≈ … est.".
3. Open both detail views.
4. Trigger the Daily Run and refresh: the scheduled entry becomes a real order with its exact amount.

## 7. Commit Strategy

Branch `feat/MA-26-order-history` (from `origin/main`), with **one commit per spec**, in implementation order:

1. `[MA-26] [App] feat: My Orders list (MA-145)`
2. `[MA-26] [App] feat: basic order detail and scheduled delivery view (MA-146)`
3. `[MA-26] [App] feat: Profile screen and My Orders entry point (MA-147)`

Review fixes go in follow-up commits: `[MA-26] [App] fix(orders): … (PR #N review)`. This is the same format as MA-34 (`[MA-34] [App] …`). One PR against `main`, titled `[MA-26] [App] feat: Order History (My Orders, order detail, Profile entry)`.

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| Open PRs #10 (auth), #11 (product config) and #12 (web maps) touch `app_router.dart`, `main.dart` and `product_config_*` | MA-26 only **adds** routes and a provider, so conflicts are additive. Rebase on `main` after whichever merges first and keep both sides |
| `TabBarView` inside a scroll view with `RefreshIndicator` (layout/gesture conflicts) | Use `NestedScrollView` with the Today section in `headerSliverBuilder` and a pinned `TabBar` (`SliverPersistentHeader`). If the Past tab's pagination listener doesn't fire, attach it to the inner `PrimaryScrollController` of that tab |
| Tests depending on the wall clock | Every bloc/cubit takes a `Clock`; tests pass a fixed UTC instant. No `DateTime.now()` in the domain or bloc code |
| Catalog `price` as a double with float error | `rupeesToPaise` rounds the unit price before multiplying; the tests include `37.485`. No double reaches `dayTotal` or the formatter |
| An `extra` object is lost on web refresh or deep link | The scheduled screen falls back to `get(id)` (MA-146 FR-8); no crash |
| Backend returns a status or reason the app doesn't know | Neutral chip with the raw value; generic reason text (covered by tests) |
| Local-dev data needed for the manual check | Use the existing local-dev scripts (`run_daily_local.py` for the Daily Run). A missing stack doesn't block the PR, since the automated tests are the gate |
