# Implementation Plan — MA-27: Transaction History — Wallet / Payments (Flutter)

## 1. Overview

| Field | Value |
|-------|-------|
| **Story** | [MA-27](https://milkfuldairyindia.atlassian.net/browse/MA-27) — Transaction History · Wallet / Payments (Flutter) |
| **Date** | 2026-10-02 |
| **Specs implemented** | [MA-148](https://milkfuldairyindia.atlassian.net/browse/MA-148) — Wallet Service: Transaction Type Filter (`services`) · [MA-149](https://milkfuldairyindia.atlassian.net/browse/MA-149) — Flutter Transaction History (`mobile-app`) |
| **Spec source** | `origin/main` after [specs#31](https://github.com/milkful2026/specs/pull/31), **including** the review revision `64adfc3`: the refund ref is `refund:{orderId}:{refundId}`, and the amount sign comes only from the `+ `/`− ` prefix over `formatPaise(abs)` |
| **Repos touched** | `milkful2026/services` (wallet), `milkful2026/milkful-app` |
| **Code branches** | `services`: `feat/MA-27-wallet-type-filter` · `milkful-app`: `feat/MA-27-transaction-history` (both from `origin/main`) |

**What this delivers:**
- Wallet's `GET /wallet/me/transactions` accepts an optional `types` filter.
- The app's `/wallet/transactions` placeholder becomes a real passbook: the balance with ADD
  MONEY, month-grouped entries with signed amounts and closing balances, a type filter, order
  chips, and order-linked rows that open the order.

**Codebase reality found during analysis (Step 2):**

1. **Wallet listing** (`wallet_service.list_transactions` → `repo.list_ledger_entries(wallet_id,
   limit, before_id)`) is keyset on `id` with a `limit + 1` probe. Adding `type IN (...)` to
   that query keeps paging correct; no other layer changes.
2. **Wallet's error envelope** spreads `details` into `data` (seen in MA-142), so the `400`
   body is `data: {errorCode: "VALIDATION_ERROR", message, field: "types", invalid: [...]}`.
3. **App:** `WalletRepository` (abstract + `DioWalletRepository`) and `FakeWalletRepository`
   exist; there's no transactions method. `/wallet/transactions` is built in `app_router.dart`
   (`WalletTransactionsPlaceholder`); no test references the placeholder. `/wallet` is gated by
   `AppConfig.walletEnabled` (→ `WalletComingSoon`).
4. **Reusable from MA-26:**
   - `formatPaise` and `istNow` (`lib/core/utils`);
   - `OrderRepository` / `OrderSource` (`lib/features/orders`);
   - the `StatusChip` tone colours (`orders/presentation/widgets/status_chip.dart:toneColors`);
   - the paging/generation/refresh-completer bloc pattern (`MyOrdersBloc`);
   - the GoRouter widget-test harness.
5. **Don't run `dart format`.** The app repo isn't formatter-clean (it reflows unrelated
   files). Match the surrounding style by hand.
6. **No CI in `milkful-app`.** The gate is local `flutter analyze` (no new issues) and
   `flutter test`. **`services` CI** runs per-service pytest (wallet included).

## 2. Prerequisites

| Prerequisite | Status | Action |
|--------------|--------|--------|
| Wallet test venv (`services/wallet/.venv`) | Already satisfied | — |
| `AppConfig.walletBaseUrl`, `AppConfig.orderBaseUrl` | Already satisfied | — |
| `OrderRepository` registered in `main.dart` | Already satisfied (MA-26) | — |
| New packages (either repo) | None | — |
| Migration | None (MA-148 §7) | — |
| **Deploy order** | **Not done** | Merge and deploy MA-148 **before** releasing MA-149's filter. Without it the old Wallet ignores `types`, and the filter would show unfiltered data (MA-149 §8) |

## 3. Implementation Order

1. **MA-148 (Wallet type filter)** first. MA-149's filter relies on it at runtime, and it's
   small and independent.
2. **MA-149 (Flutter Transaction History)** second. Everything except the filter works against
   today's API, so it can be built in parallel; the integration check needs step 1.

Two PRs (one per repo). The services PR merges first.

## 4. Per-Spec Implementation Steps

### MA-148: Wallet Service — Transaction Type Filter

**Files to modify:**
- `wallet/src/domain/exceptions.py`: add `InvalidTransactionTypeError(WalletError)` with
  `error_code = "VALIDATION_ERROR"` and `http_status = 400`.
- `wallet/src/domain/wallet_service.py`:
  - add module-level `_parse_types(raw: str | None) -> frozenset[LedgerType] | None`.
    `None` → `None`. Otherwise split on `,` and strip each part. An empty part, a value not in
    `LedgerType` (case-sensitive), or more than 7 distinct values raise
    `InvalidTransactionTypeError("Unknown transaction type", {"field": "types", "invalid":
    [...]})`. Duplicates collapse.
  - `list_transactions(user_id, limit, cursor, types: str | None = None)`: parse first, before
    any DB read, and pass to the repository.
- `wallet/src/adapters/wallet_repository.py`: `list_ledger_entries(wallet_id, limit, before_id,
  types: frozenset[LedgerType] | None = None)`. When `types` is set, add
  `ledger_entries_table.c.type.in_([t.value for t in types])`. Ordering and keyset are
  unchanged.
- `wallet/src/adapters/interfaces.py`: port signature updated (docstring notes the filter).
- `wallet/src/handlers/wallet_handlers.py`: `get_wallet_transactions` gains `types: str | None =
  Query(default=None)` and passes it through.
- `wallet/README.md`:
  - the endpoint table's `/wallet/me/transactions` row mentions `types`;
  - a short **"Ledger refs"** note: `order:{orderId}` for order debits, and
    `refund:{orderId}:{refundId}` reserved for order refunds (MA-148 FR-3; no writer yet).

**Implementation steps:**
1. Exception + `_parse_types` with unit tests.
2. Repository filter with tests.
3. Service and handler wiring with HTTP tests.
4. README.
5. `pytest` and `ruff check`.

**Tests to write:**
- **Unit (`tests/unit/domain/test_wallet_service.py`):**
  - `_parse_types`: each valid type, spaces trimmed, duplicates collapsed; `""`,
    `"RECHARGE,,X"`, `"recharge"` and `"BOGUS"` raise with `details["invalid"]` listing the bad
    values;
  - `list_transactions` without `types` returns the same as before (existing tests stay green);
  - with `types="RECHARGE"`: seed 3 recharges, 5 order debits and the opening entry → only the
    3 recharges, newest first; `limit=2` → 2 entries + a cursor, then 1 + `next_cursor None`;
  - `types="ORDER_DEBIT,RECHARGE"` → 8 entries;
  - an absent type → an empty page.
- **HTTP (`tests/integration/test_wallet_http.py`):**
  - `?types=RECHARGE` → only `RECHARGE` items;
  - `?types=BOGUS` → `400`, `data.errorCode == "VALIDATION_ERROR"`, `data.field == "types"`;
  - no param → the body is unchanged from the existing `test_transactions_paged`;
  - `?types=ORDER_DEBIT&limit=1`, then the returned cursor → stays within order debits.

**Acceptance check:** in `services/wallet`, `./.venv/Scripts/python -m pytest -q` passes, and
`./.venv/Scripts/python -m ruff check src tests` is clean.

### MA-149: Flutter Transaction History

**Files to create:**
- `lib/features/wallet/models/ledger_entry.dart`:
  - `LedgerType` value class: `wire` string; constants `opening`, `recharge`, `orderDebit`,
    `refund`, `cashback`, `referralCredit`, `adjustment`; `isUnknown`.
  - `LedgerEntry`: `id`, `type`, `amountPaise`, `balanceAfterPaise`, `ref`, `description`,
    `createdAt`; `fromJson`.
  - `String? get orderId`: `order:{id}` → `id`; `refund:{id}:{refundId}` or `refund:{id}` →
    `id`; an empty id or any other ref → null.
  - `LedgerPage(items, nextCursor)` with `fromJson`.
- `lib/features/wallet/domain/ledger_copy.dart` (pure Dart):
  - `enum TransactionFilter { all, topUps, orderPayments, refundsCredits }` with `label`
    ("All transactions" / "Top-ups" / "Order payments" / "Refunds & credits"), `chipLabel`,
    `types` (`null`, `[RECHARGE]`, `[ORDER_DEBIT]`, `[REFUND, CASHBACK, REFERRAL_CREDIT,
    ADJUSTMENT]`) and `emptyText`.
  - `String ledgerTitle(LedgerEntry)` per the FR-4 table (a refund with an `orderId` → "Refund
    for Order").
  - `String ledgerChipLabel(LedgerEntry, OrderSource? source)`: for an `ORDER_DEBIT`,
    Subscription / One-time order / Order (when `source` is null); otherwise the per-type chip;
    unknown → title-cased raw type.
  - `LedgerIcon ledgerIcon(LedgerEntry)` (an enum mapped to `IconData` in the widget).
  - `String formatSignedAmount(int paise)`: `+ ₹45` / `− ₹367` (U+2212) / `₹0`, always over
    `formatPaise(paise.abs())`.
  - `String formatLedgerTimestamp(DateTime instant)`: IST, `EEE, d'<ordinal>' MMM yy,
    hh:mm:ss a`, e.g. `Thu, 6th Aug 26, 07:29:15 AM`.
  - `String ordinal(int day)`: st/nd/rd/th, with 11–13 → th.
  - `String formatMonthHeader(DateTime month, DateTime todayIst)`: "August", or "August 2025"
    when the year differs.
- `lib/features/wallet/bloc/transaction_history_event.dart`: `HistoryOpened`,
  `HistoryRefreshed(completer)`, `FilterChanged(filter)`, `NextPageRequested`, `RetryBalance`,
  `RetryLedger`, and the internal `OrderSourcesResolved(Map<String, OrderSource?>)` that the bloc
  adds itself.
- `lib/features/wallet/bloc/transaction_history_state.dart`:
  - `LoadStatus { loading, loaded, failed }` for the balance, and `LedgerStatus { loading,
    loaded, failed, walletNotReady }`;
  - `WalletView? wallet`, `List<LedgerEntry> entries`, `nextCursor`, `filter`,
    `Map<String, OrderSource?> orderSources` (a key present with null = lookup failed),
    `PagingStatus`, `refreshFailedCount`, `today`;
  - a derived `groupedByMonth` (list of `(month, entries)`, IST, newest first).
- `lib/features/wallet/bloc/transaction_history_bloc.dart`:
  `TransactionHistoryBloc(WalletRepository, OrderRepository, {Clock clock})`.
  - **Opened / Refreshed:** balance (`getWallet`) and the first page
    (`listTransactions(limit: 50, types: filter.types)`) run in parallel and independently. An
    `ApiException` with `statusCode == 404` / `errorCode == 'WALLET_NOT_FOUND'` on the ledger →
    `walletNotReady`.
  - **Refreshed:** keeps the data on failure, bumps `refreshFailedCount`, completes the
    completer. Like every first-page (re)load, it bumps the generation, so a page still in
    flight is discarded (MA-149).
  - **FilterChanged:** a no-op if unchanged. Otherwise clear the entries and cursor, bump the
    generation, set ledger `loading`, and load the first page with the new types. The balance
    isn't reloaded.
  - **NextPageRequested** (`droppable()`): ignored when there's no cursor or the ledger isn't
    loaded; a stale generation is discarded, and a stale result (success or failure) resets
    `PagingStatus.loading` → `idle`. Otherwise a refresh that fails while a page is in flight
    keeps the old state and leaves the spinner stuck. A current failure →
    `PagingStatus.failed`.
  - **Order sources:** after each page, `getById` for unseen `orderId`s in parallel; failures
    cache `null`. The lookups run **unawaited**, and their results come back through
    `OrderSourcesResolved`, which merges them into `orderSources`. If the `droppable()` paging
    handler awaited them, load-more requests during the lookups would be silently dropped.
  - **RetryBalance / RetryLedger:** reload just that part.
- `lib/features/wallet/presentation/transaction_history_screen.dart`:
  - `TransactionHistoryScreen({Clock? clock})` creates the bloc with `context.read<WalletRepository>()`
    and `context.read<OrderRepository>()`.
  - `Scaffold`: `AppBar(title: 'Transaction History', actions: [filter IconButton(key
    'txn.filter', tooltip 'Filter transactions')])`. The filter is hidden when
    `walletNotReady`; there's no search icon and no bottom bar.
  - Body: `RefreshIndicator` → `CustomScrollView` with `_BalanceCard` (key `txn.balance`), the
    active-filter `InputChip` with delete, month headers, `_LedgerRow`s and the paging footer
    (key `txn.loadMoreRetry` on failure). Pagination uses a `NotificationListener`
    (`extentAfter < 300`).
  - `_FilterSheet`: `showModalBottomSheet` with the title "Show" and four `RadioListTile`s;
    selecting one pops and dispatches `FilterChanged`.
  - `_LedgerRow` (key `txn.row.{id}`):
    - icon with a check badge;
    - title, timestamp, signed amount (credit in the primary colour);
    - chip (styled with `toneColors`: neutral for most types; primary for Top-up; the order
      chips neutral);
    - "Closing balance: ₹X.XX" (`formatPaise(balanceAfterPaise, alwaysDecimals: true)`);
    - an `InkWell` → `context.push('/orders/$orderId')` only when `orderId != null`;
    - one `Semantics` label per FR-5 NFR.
  - The states per MA-149 FR-9, with the exact copy, including the filtered empty texts and
    "Show all transactions".

**Files to modify:**
- `lib/features/wallet/data/wallet_repository.dart`: add to the interface `Future<LedgerPage>
  listTransactions({String? cursor, int limit = 50, List<String>? types})`. In
  `DioWalletRepository`, use `GET ${AppConfig.walletBaseUrl}/wallet/me/transactions` with
  query `limit`, `cursor?` and `types` (joined with `,`) only when non-null and non-empty.
- `test/fakes/fake_wallet_repository.dart`: implement `listTransactions` with pages keyed by
  `'${types?.join(',')}|$cursor'`, `listTransactionsException` (first page) and
  `pageException` (later pages), an optional `Completer` gate, and a `listTransactionsCalls`
  log of `(cursor, types)`.
- `test/fakes/fake_order_repository.dart`: add an optional `getGate` `Completer` that holds
  `getById` open, so a test can race order lookups against paging.
- `lib/core/router/app_router.dart`: `/wallet/transactions` builds `AppConfig.walletEnabled ?
  const TransactionHistoryScreen() : const WalletComingSoon()`; the placeholder import is
  removed.
- **Delete** `lib/features/wallet/presentation/wallet_transactions_placeholder.dart`.

**Implementation steps:**
1. Model + `ledger_copy.dart` with unit tests.
2. Repository method + fake.
3. Bloc with bloc tests.
4. Screen + router swap; delete the placeholder.
5. Widget and router tests.
6. `flutter analyze`; `flutter test`.

**Tests to write:**
- **Unit (`test/features/wallet/domain/ledger_copy_test.dart`):**
  - every row of the FR-4 table, plus an unknown type;
  - `ledgerTitle` for `refund:ord_1:rf_1` → "Refund for Order", and for `manual-credit` →
    "Refund";
  - `formatSignedAmount(-36700)` == `− ₹367`, `(4500)` == `+ ₹45`, `(0)` == `₹0`, with no "-₹"
    anywhere;
  - ordinals 1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31;
  - a timestamp at `2026-08-06T01:59:15Z` → `Thu, 6th Aug 26, 07:29:15 AM`, plus a UTC-evening
    entry → the next IST day;
  - month headers for the same and a different year;
  - each `TransactionFilter.types`.
- **Model (`test/features/wallet/models/ledger_entry_test.dart`):** `fromJson` (signed amount,
  unknown type); `orderId` for `order:ord_1`, `refund:ord_1:rf_1`, `refund:ord_1` → `ord_1`, and
  for `refund::rf_1`, `razorpay_payment:pay_1`, `opening:wal_1`, `manual-credit` → null.
- **Bloc (`test/features/wallet/bloc/transaction_history_bloc_test.dart`, fixed clock):**
  - opened → both loaded;
  - ledger 404 → `walletNotReady` with the balance still loaded;
  - ledger 500 → ledger failed with the balance loaded; `RetryLedger` → loaded;
  - balance failed with the ledger loaded; `RetryBalance` → loaded;
  - `FilterChanged(topUps)` → the fake saw `types: ['RECHARGE']` and `cursor: null`, the entries
    were replaced, and the balance wasn't re-fetched;
  - paging appends; a duplicate request is dropped (gate);
  - a filter change during a gated page → the stale page is ignored;
  - a refresh that fails while a page is gated → once the page lands, `PagingStatus` is `idle`
    (not stuck `loading`), the entries are unchanged, and a new `NextPageRequested` fetches it;
  - order lookups held open (a `getById` gate on the fake order repository) don't block the
    next `NextPageRequested`; the sources merge once the gate opens;
  - one `getById` per distinct order across a debit and a refund of the same order, and across
    a refresh; `getById` throws → source cached null;
  - a refresh failure keeps the entries and bumps the counter.
- **Widget (`test/features/wallet/presentation/transaction_history_screen_test.dart`, GoRouter
  harness with stubs for `/wallet` and `/orders/:id`; a tall viewport):**
  - mock-like data → "Transaction History", "Current Balance", "₹6621.46", "August", "Paid for
    Order", "− ₹367", "+ ₹45", "Closing balance: ₹6621.46", "Subscription"; no `Icons.search`;
    no text containing "-₹";
  - filter: tap `txn.filter` → "Show" → "Top-ups" → the fake got `types=[RECHARGE]`; the chip
    "Top-ups" with a delete icon; delete → back to All;
  - filtered empty → "No top-ups yet" + "Show all transactions" resets;
  - wallet not ready → "Your wallet is being set up." + "Back to Wallet" → `/wallet`; no filter
    icon;
  - ledger failure → "Couldn't load your transactions." and **no** "No transactions yet";
  - tap an order-debit row → `/orders/ord_1`; tap the refund row `refund:ord_1:rf_1` →
    `/orders/ord_1`; tapping a top-up row pushes nothing;
  - ADD MONEY → `/wallet`; ADD MONEY disabled when the wallet status is `CREATING`.
- **Router (`test/core/router/app_router_test.dart`):** `/wallet/transactions` builds
  `WalletComingSoon` when the wallet is disabled (MA-149). `AppConfig.walletEnabled` is the
  compile-time `bool.fromEnvironment('WALLET_ENABLED')` and is off in a plain `flutter test`,
  so this is the case the test run can assert. The enabled branch (`TransactionHistoryScreen`) is covered
  by the widget tests, which build the screen directly.

**Acceptance check:** `flutter analyze` adds no issues beyond the existing info-level notes;
`flutter test` is all green.

## 5. Cross-Cutting Steps

1. Wallet README (MA-148) documents `types` and the ledger ref conventions.
2. App: the router swap and the placeholder removal. Nothing else in `main.dart` changes (both
   repositories are already provided).
3. Final full runs: `services/wallet` pytest + ruff; app `flutter analyze` + `flutter test`.

## 6. Test Strategy

| Level | Location | Covers |
|-------|----------|--------|
| Wallet unit | `services/wallet/tests/unit/domain/test_wallet_service.py` | parsing, the filtered keyset, compatibility |
| Wallet HTTP | `services/wallet/tests/integration/test_wallet_http.py` | the param, the 400 envelope, cursor continuation |
| App unit | `test/features/wallet/domain/`, `test/features/wallet/models/` | copy, formats, ordinals, IST, `orderId` |
| App bloc | `test/features/wallet/bloc/` | independence, filter reset, paging races, order cache |
| App widget/router | `test/features/wallet/presentation/`, `test/core/router/` | labels, states, navigation |

**Commands:**

```
# services
cd services/wallet && ./.venv/Scripts/python -m pytest -q && ./.venv/Scripts/python -m ruff check src tests
# app
cd milkful-app && flutter analyze && flutter test
```

**Coverage:** every branch of `_parse_types`, `ledger_copy.dart` and `LedgerEntry.orderId`, via
the truth tables above. There's no numeric gate in either repo.

## 7. Commit Strategy

- `services` (`feat/MA-27-wallet-type-filter`): one commit, `feat(MA-27): wallet — transaction
  type filter (MA-148)`; review fixes as follow-ups. PR title: `feat(MA-27): wallet transaction
  type filter`.
- `milkful-app` (`feat/MA-27-transaction-history`): one commit, `[MA-27] [App] feat: Transaction
  History (MA-149)`; review fixes as `[MA-27] [App] fix(wallet): … (PR #N review)`. PR title:
  `[MA-27] [App] feat: Transaction History`.

## 8. Risks and Blockers

| Risk | Mitigation / recovery |
|------|-----------------------|
| The app's filter is released before MA-148 is deployed | The services PR merges first, and the app PR description repeats the deploy-order note |
| `IN` filter performance on large ledgers | Within one wallet's rows; revisit with a `(wallet_id, type, id)` index if wallets exceed about 10k entries (MA-148 §7) |
| Clock-dependent tests | The bloc takes a `Clock`; tests pin UTC instants |
| Accidental `dart format` reflow | Don't run it (§1 item 5); check `git diff --stat` before committing |
| Off-screen widgets in tests | Use a tall test viewport (`tester.view.physicalSize`), as in MA-146's tests |
