# Implementation Plan — MA-35: Order Details — Orders (Flutter)

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-35](https://milkfuldairyindia.atlassian.net/browse/MA-35) — Order Details · Orders (Flutter) |
| **Date** | 2026-10-06 |
| **Specs implemented** | [MA-152](https://milkfuldairyindia.atlassian.net/browse/MA-152) — Flutter Order Detail: Reorder & Support Actions (`mobile-app`) |
| **Spec source** | `origin/main` after [specs#35](https://github.com/milkful2026/specs/pull/35) |
| **Repos touched** | `milkful2026/milkful-app` only (no backend change) |
| **Code branch** | `feat/MA-35-order-detail-actions` (from `origin/main`) |

**What this delivers:**
- Two buttons at the bottom of the existing `OrderDetailScreen` (MA-146), shown only when the
  order has loaded:
  - **Reorder Items** re-adds every line of the order to the cart as one-time items.
  - **Support** opens the device's email app, addressed to the support address, with the
    order's display ID in the subject.

**Codebase reality found during analysis (Step 2):**

1. **Parallel adds collide in Cart Service — deviation from FR-1 (decided in chat on
   2026-10-06).**
   - The problem: `cart_repository.add_item` writes every add as one DynamoDB
     `TransactWriteItems`. That transaction also upserts the cart's shared `META` row
     (`_meta_upsert_transact_item`) and refreshes the sibling item TTLs. When two of these
     transactions touch the same row at the same time, DynamoDB cancels one of them
     (`TransactionConflict`). The cancelled add surfaces as `CartServiceError` → 500, with no
     retry.
   - What would happen: FR-1's `Future.wait` fan-out would make multi-line reorders report
     failures that aren't real ("Added 1 of 3 items").
   - **Decision:** the cubit adds the lines **one at a time, in order**. Everything else in
     FR-1 is unchanged: per-line failure attribution, the three SnackBar outcomes, and
     retry-all. The cost is one round trip per line instead of the slowest one (§5's
     performance NFR is relaxed accordingly). Orders are typically 1–3 lines.
2. **Cart Service rejects `startDate`/`slotId` on a `ONE_TIME` line**
   (`cart_service._validate_item`: "startDate must not be set for a ONE_TIME item"). Reorder
   must pass neither. `CartRepository.addItem` already omits null values from the body.
3. **Adding the same product again creates a second line** (`add_item` always writes a new
   `ITEM#{uuid}`). This confirms the spec's retry-all trade-off (§11) is exactly as described.
4. **`displayOrderId(orderId)`** (`lib/features/orders/domain/order_status_copy.dart`) returns
   `#3F9A2C1B`, with a leading `#`. The spec's subject uses the bare `3F9A2C1B`, so strip the
   `#` (a raw `#` would also start a URL fragment).
5. **`canLaunchUrl('mailto:…')` needs platform declarations that don't exist yet:**
   - Android 11+ package visibility: `android/app/src/main/AndroidManifest.xml`'s `<queries>`
     has only `PROCESS_TEXT`.
   - iOS: `ios/Runner/Info.plist`'s `LSApplicationQueriesSchemes` has only UPI schemes.
   - Without them, `canLaunchUrl` returns false on real devices **even with a mail app
     installed**, and FR-2 would always show the fallback.
6. **`CartRepository` is already provided app-wide** (`main.dart`:
   `RepositoryProvider<CartRepository>`). `OrderDetailScreen` creates its cubit in its own
   `BlocProvider`, so it can `context.read<CartRepository>()` there.
7. **Test files have different names from the spec's §10:**
   - Cubit tests live in `test/features/orders/bloc/detail_cubits_test.dart`.
   - Screen tests live in `test/features/orders/presentation/detail_screens_test.dart`. Its
     GoRouter harness has no `CartRepository` provider and no `/cart` route yet.
8. **`FakeCartRepository.addItemException` fails every call.** It needs a per-product failure
   map (for the partial-failure case) and a gate (for the busy-state assertion).
9. **Don't run `dart format`.** The app repo isn't formatter-clean, so it reflows unrelated
   files. Match the surrounding style by hand.
10. **No CI in `milkful-app`.** The gate is local: `flutter analyze` adds no new issues, and
    `flutter test` is green.

## 2. Prerequisites

| Prerequisite | Status | Action |
|--------------|--------|--------|
| `url_launcher` package | Not done | `flutter pub add url_launcher` (latest stable; records the `^x.y.z` in `pubspec.yaml` + `pubspec.lock`) |
| `url_launcher_platform_interface`, `plugin_platform_interface` (tests) | Not done | `flutter pub add --dev url_launcher_platform_interface plugin_platform_interface`, used for the fake launcher in widget tests |
| Android `mailto` visibility | Not done | Add a second `<intent>` to the existing `<queries>`: `<action android:name="android.intent.action.SENDTO"/>` + `<data android:scheme="mailto"/>` |
| iOS `mailto` query scheme | Not done | Add `<string>mailto</string>` to the existing `LSApplicationQueriesSchemes` array |
| `AppConfig.supportEmail` | Not done | See §4 step 1 |
| `CartRepository` provided app-wide | Already satisfied | — |
| `newHexId()`, `Frequency.oneTime` | Already satisfied | — |
| `/cart` route | Already satisfied | `app_router.dart` |
| Backend | Already satisfied | No change. Uses Cart's existing `POST /cart/items` |

## 3. Implementation Order

There's one spec, built in this order (each step compiles and tests green on its own):

1. **Config, dependency and platform declarations.** Everything after this depends on them.
2. **Cubit: `reorder()` and the result type.** The screen renders from it.
3. **Fake repository additions.** The cubit and widget tests need them.
4. **Screen: the actions row and Support.**
5. **Tests.**

## 4. Per-Spec Implementation Steps

### MA-152: Flutter Order Detail — Reorder & Support Actions

**Files to modify:**

- `pubspec.yaml` / `pubspec.lock` — `url_launcher` (dependency), and
  `url_launcher_platform_interface` + `plugin_platform_interface` (dev dependencies).
- `android/app/src/main/AndroidManifest.xml` — the `SENDTO`/`mailto` intent in `<queries>`.
- `ios/Runner/Info.plist` — `mailto` in `LSApplicationQueriesSchemes`.
- `lib/core/config/app_config.dart` — `supportEmail`.
- `lib/features/orders/bloc/order_detail_cubit.dart`:
  - `OrderDetailLoaded.reordering`;
  - `ReorderResult`;
  - `OrderDetailCubit.reorder()`;
  - a `CartRepository` constructor dependency.
- `lib/features/orders/presentation/order_detail_screen.dart` — pass `CartRepository` to the
  cubit; add the actions row, the Reorder SnackBars and `_openSupport`.
- `test/fakes/fake_cart_repository.dart` — the per-product failures and the gate.
- `test/features/orders/bloc/detail_cubits_test.dart` — the new `OrderDetailCubit` cases, and
  `CartRepository` passed into every existing construction.
- `test/features/orders/presentation/detail_screens_test.dart` — harness additions and the new
  scenarios.

**Files to create:** none.

**Implementation steps:**

1. **`AppConfig.supportEmail`**
   - Make it `static const supportEmail = String.fromEnvironment('SUPPORT_EMAIL', defaultValue:
     'support@milkful.app')`. This is the same `fromEnvironment` pattern as the base URLs, and
     it can be overridden per build.
   - Give it a doc comment that says the value is a **placeholder pending Product/Support
     sign-off (MA-152 Open Questions)**, so it isn't mistaken for a confirmed address.

2. **`OrderDetailLoaded.reordering`**
   - Add a `final bool reordering` field (default `false`) and include it in `props`.
   - Add `copyWith({bool? reordering})`.
   - A pull-to-refresh that lands mid-reorder emits a fresh `OrderDetailLoaded`. In `_fetch`,
     carry the current `reordering` value over, so the button stays disabled until the reorder
     finishes. Do this only when the current state is `OrderDetailLoaded`, and only for that
     emit.

3. **`ReorderResult`** (plain class, in the cubit file)
   - Fields:
     - `int added`;
     - `int total`;
     - `List<String> failedNames` (in order-line order).
   - `String get message`:
     - all succeeded → `"Added {total} item{s} to cart"` (singular when `total == 1`);
     - some failed → `"Added {added} of {total} items to cart. Couldn't add {failedNames joined
       with ', '}."`;
     - none succeeded → `"Couldn't add items to cart. Try again."`
   - `bool get showViewCart => added > 0`.
   - The copy lives here, not in the widget, per the spec's maintainability NFR.

4. **`OrderDetailCubit`**
   - Add `required CartRepository cartRepository` to the constructor (field `_cart`).
   - Add `Future<ReorderResult?> reorder()`:
     - **No-op guard:** return `null` without calling anything unless the state is
       `OrderDetailLoaded` and `reordering == false`. This covers the double tap.
     - Snapshot `order` and `products` from the current state, then emit
       `copyWith(reordering: true)`.
     - **Sequentially** (a plain `for` over `order.items`, awaiting each call; see §1 item 1),
       call `_cart.addItem(productId: line.productId, quantity: line.quantity, frequency:
       Frequency.oneTime, idempotencyKey: newHexId())`. Each line gets a fresh key. Pass no
       `startDate` and no `slotId` (§1 item 2).
     - Catch **any** exception per line (`ApiException` or otherwise). Record the failure as
       `productNameFor(products, line.productId)`, which gives "Item" when the Catalog lookup
       failed, and continue with the next line.
     - A client timeout counts as a failure too, even though a slow Cart Service may still
       commit that add afterwards. The user then sees "Couldn't add {name}" for a line that
       is in the cart, and a second Reorder (fresh keys) adds it again. This is accepted (§8);
       keys are deliberately not reused across taps.
     - **Afterwards:** if not closed and the state is still `OrderDetailLoaded`, emit
       `copyWith(reordering: false)`. Return the `ReorderResult`.
     - If the state changed to not-found or an error during the run (a refresh), still return
       the result, but emit nothing.
   - Reuse `productNameFor` (`lib/features/orders/presentation/widgets/product_thumb.dart`) by
     importing it into the cubit. Don't duplicate the "Item" fallback.

5. **`OrderDetailScreen`**
   - **Cubit creation:** in `BlocProvider.create`, pass `cartRepository:
     context.read<CartRepository>()`.
   - **Placement:** after the Payment Method `DetailCard` (still inside the loaded `ListView`),
     add a padded `Column` with the two full-width buttons and an 8dp gap between them. They
     must be at least 48dp tall.
   - **Reorder button:**
     - `FilledButton(key: Key('orderDetail.reorder'))`, labelled **"Reorder Items"**.
     - `onPressed: reordering ? null : () => _reorder(context)`.
     - While `reordering`, the label is replaced by a small `CircularProgressIndicator`
       (strokeWidth 2, about 18dp).
     - Wrap the button in `Semantics(button: true, enabled: !reordering, label: 'Reorder Items',
       excludeSemantics: reordering, ...)` so a screen reader still hears the name while it's
       busy (§5 accessibility). `excludeSemantics` only while busy: when idle the button's own
       label is announced, and excluding it then (or never) would announce it twice or drop it.
   - **Support button:** `OutlinedButton(key: Key('orderDetail.support'))`, labelled
     **"Support"**, with `onPressed: () => _openSupport(context, order.orderId)`. It's never
     disabled by Reorder.
   - **`_reorder(context)`:**
     - Capture `ScaffoldMessenger.of(context)` and `GoRouter.of(context)` **before** awaiting.
     - `final result = await cubit.reorder()`. If it's `null`, return.
     - Show `SnackBar(content: Text(result.message), action: result.showViewCart ?
       SnackBarAction(label: 'View Cart', onPressed: () => router.push('/cart')) : null)`.
   - **`_openSupport(context, orderId)`:**
     - Build the subject as `'Order ${displayOrderId(orderId).substring(1)}'`, which strips the
       `#` (§1 item 4).
     - Build `Uri(scheme: 'mailto', path: AppConfig.supportEmail, query:
       'subject=${Uri.encodeComponent(subject)}')`. That gives `%20` for spaces, not `+`,
       which some mail clients show literally.
     - Launched = `await canLaunchUrl(uri) && await launchUrl(uri)`, inside a try/catch that
       treats a throw as not launched.
     - If not launched (no mail app, `launchUrl` returned false, or it threw), show the
       SnackBar **"No email app found. Contact us at {AppConfig.supportEmail}."**
     - Check `context.mounted` / use the captured messenger after each await.

6. **`FakeCartRepository`**
   - Add `final Map<String, Object> addItemExceptionsByProduct = {}`. `addItem` throws the
     mapped exception for that `productId`; otherwise it falls back to the existing
     `addItemException`.
   - Add `Completer<void>? addItemGate`, awaited at the top of `addItem` (after logging the
     request), so a test can hold the reorder open.
   - Leave existing fields and behaviour unchanged for current callers.

7. **Widget-test harness** (`detail_screens_test.dart`)
   - Add `RepositoryProvider<CartRepository>.value(value: cart)` (a `FakeCartRepository` per
     test) to the existing `MultiRepositoryProvider`.
   - Add a stub `GoRoute(path: '/cart')` that renders a `Text('CART')` marker.
   - Add `_FakeUrlLauncher extends Fake with MockPlatformInterfaceMixin implements
     UrlLauncherPlatform`:
     - `bool canLaunchResult`;
     - `List<String> launched`;
     - override `canLaunch(url)` → `canLaunchResult`;
     - override `launchUrl(url, options)` → record, then throw `launchError` if set, else
       return `launchResult` (default true), so tests cover a failed and a throwing launch.
   - Install it in `setUp` with `UrlLauncherPlatform.instance = fake`.

**Tests to write:**

- **Cubit** (`detail_cubits_test.dart`, `group('OrderDetailCubit')`; fixture order with 2
  items, `p1` and `p2`):
  - **All succeed:**
    - The result is `added == 2`, `total == 2`, `failedNames` empty, `message` is "Added 2
      items to cart", and `showViewCart` is true.
    - `cart.requests` has two entries, in order-line order. Each has `frequency ==
      Frequency.oneTime`, `startDate == null` and `slotId == null`, and the two idempotency
      keys differ.
  - **Single-line order succeeds:** `message` is "Added 1 item to cart" (singular).
  - **Partial failure:**
    - `addItemExceptionsByProduct['p2'] = ApiException(... 409 ...)`.
    - Expect `added == 1` and `failedNames == ['<p2 name>']`.
    - Expect `message` to be exactly "Added 1 of 2 items to cart. Couldn't add <p2 name>." and
      `showViewCart` to be true.
  - **Unresolved product:** `p2`'s Catalog lookup failed (`products['p2'] == null`) and its add
    fails → `failedNames == ['Item']`, and nothing is thrown.
  - **Non-`ApiException` failure:** `p1` throws `TimeoutException` → counted as a failure; `p2`
    is still attempted.
  - **All fail:** `added == 0`, `message` is "Couldn't add items to cart. Try again.", and
    `showViewCart` is false.
  - **Double call:**
    - With `addItemGate` held, call `reorder()` twice. The second call returns `null`
      immediately, and after the gate opens `cart.requests.length == 2` (not 4).
    - The state goes `reordering: true` → `false`.
  - **Sequential, not parallel:** with the gate held, after one microtask flush
    `cart.requests.length == 1`. This guards the §1 item 1 decision against a regression to
    `Future.wait`.
  - **Refresh mid-reorder:**
    - With the gate held, `refresh()` completes successfully. The state is still `reordering:
      true`.
    - After the gate opens, the state is `reordering: false`.
  - Update the existing cases to pass `cartRepository: FakeCartRepository()`.
- **Widget** (`detail_screens_test.dart`, `group('OrderDetailScreen')`; tall viewport, as the
  existing tests use):
  - **Successful reorder:**
    - Loaded CONFIRMED order with 2 items. Hold the gate and tap `Key('orderDetail.reorder')`.
    - While held, a `CircularProgressIndicator` sits inside the button, its `onPressed` is null,
      and `Key('orderDetail.support')` is still enabled.
    - Release the gate. The SnackBar "Added 2 items to cart" appears; tap "View Cart" → the
      `CART` marker shows.
  - **Partial failure:** the SnackBar reads "Added 1 of 2 items to cart. Couldn't add
    {name}.", and "View Cart" is present.
  - **Full failure:** the SnackBar reads "Couldn't add items to cart. Try again.", and there's
    no "View Cart".
  - **Support with a mail app:** `canLaunchResult = true`, then tap Support. `launched.single`
    starts with `mailto:support@milkful.app?subject=Order%20`, contains the uppercased 8-char
    display ID, and contains no `#` and no full `ord_` ID.
  - **Support with no mail app:** `canLaunchResult = false` → a SnackBar containing
    `support@milkful.app`, and `launched` is empty.
  - **Not in other states:** neither key is found in the loading, not-found or error states.
- **Integration (local-dev, manual):**
  - Open a real CONFIRMED multi-line order and tap Reorder.
  - `GET /cart` shows one `ONE_TIME` line per order line. Tap "View Cart" → the Cart screen
    lists them.

**Acceptance check:**
- `flutter analyze` adds no issues beyond the existing info-level notes.
- `flutter test` is all green.
- `git diff --stat` touches only the files listed above.

## 5. Cross-Cutting Steps

1. `pubspec.yaml`/`pubspec.lock` updated via `flutter pub add`, not hand-edited, so the lock
   file stays consistent.
2. Platform declarations (Android `<queries>`, iOS `LSApplicationQueriesSchemes`) are
   committed in the same commit as the Support button, so the feature is never half-wired.
3. No router change: `/orders/:orderId` and `/cart` already exist. No `main.dart` change:
   `CartRepository` is already provided.
4. Final full run: `flutter analyze` + `flutter test` on the branch.

## 6. Test Strategy

| Level | Location | Covers |
|-------|----------|--------|
| Cubit | `test/features/orders/bloc/detail_cubits_test.dart` | outcomes, copy, one-time body, sequential order, double-tap guard, refresh-mid-reorder |
| Widget | `test/features/orders/presentation/detail_screens_test.dart` | busy state, the three SnackBars, View Cart navigation, `mailto` URL, no-mail-app fallback, per-state visibility |
| Manual (local-dev) | real Cart Service | lines really land in `GET /cart` |

**Commands:**

```
cd milkful-app && flutter pub get && flutter analyze && flutter test
# focused
flutter test test/features/orders
```

**Coverage:** every `ReorderResult.message` branch, plus both `_openSupport` branches. There's
no numeric gate in this repo.

## 7. Commit Strategy

- Branch `feat/MA-35-order-detail-actions`. One commit: `[MA-35] [App] feat: Order Detail
  Reorder & Support (MA-152)`.
- Review fixes go in follow-up commits: `[MA-35] [App] fix(orders): … (PR #N review)`.
- PR title: `[MA-35] [App] feat: Order Detail Reorder & Support`.
- The PR description must state:
  - the §1 item 1 deviation (sequential adds), with the reason;
  - that `supportEmail` is a placeholder.

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| Support address is a placeholder | Shipped as `fromEnvironment` with a labelled default; Product/Support must confirm before release (spec Open Questions) — set via `--dart-define=SUPPORT_EMAIL=…` without a code change |
| Sequential adds feel slow on a long order | Typical orders are 1–3 lines; the in-button spinner shows progress. If it becomes a problem, the fix is server-side (retry on `TransactionConflict`, or a batch-add endpoint), not reintroducing app-side parallelism |
| Retry-all after a partial failure duplicates the lines that already succeeded | Accepted by the spec (§11); duplicates are normal, removable cart lines (§1 item 3) |
| A timed-out add that the Cart Service commits late is reported as failed, and a retry adds it again | Accepted on the same basis: the cart shows the true contents and the duplicate is removable. Reusing per-line idempotency keys across taps would fix it but needs keys held in cubit state; revisit if support sees it |
| `canLaunchUrl` false on a real device despite a mail app | Caused by missing platform declarations; covered by the §2 prerequisites — verify once on an Android 11+ device/emulator with Gmail |
| `UrlLauncherPlatform.instance` fake leaking between tests | Install a fresh fake in each test's `setUp` |
| Accidental `dart format` reflow | Don't run it (§1 item 9); check `git diff --stat` before committing |
