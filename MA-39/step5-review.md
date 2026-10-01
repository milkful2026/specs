# SDD Step 5 — Review Checklist

**Story:** MA-39 — Enable / Disable User Account · Admin / User Management (Admin UI)
**Specs reviewed (branch `spec/MA-39`):**
- `services/tasks/MA/MA-39/MA-139.md` — User Service: Customer Account Status
- `services/tasks/MA/MA-39/MA-140.md` — Subscription Service: Admin-Triggered Pause Consumer
- `portal-ui/tasks/MA/MA-39/MA-141.md` — Customer Account Management

---

## Part 1 — Individual specification quality

### MA-139 — User Service: Customer Account Status

- [x] Solves the problem stated in MA-39 (status lifecycle, admin CRUD, login block, audit trail)
- [x] All 13 sections present and complete
- [x] Functional requirements specific and unambiguous (exact endpoints, state-transition rules, idempotency semantics)
- [x] NFRs defined with measurable targets (p95s, named CloudWatch metric/alarm)
- [x] Acceptance criteria testable (§10 — unit, integration, contract, E2E, explicit negative scenarios)
- [x] Edge cases and failure modes documented (§9 — 7 cases incl. idempotent repeat-action, invalid transition, concurrent sweep-vs-manual-reactivate race)
- [x] Testing strategy sufficient (offline moto/SQLite pattern matching existing `user`/`identity-auth` precedent)
- [x] Scope boundaries clearly stated (§3 — Wallet and Subscription behavior explicitly out, KYC/B2B filtering explicitly out)
- [x] Assumptions and risks explicit (§11 — ordering rationale, no optimistic locking, new scheduled job, denormalized actor id)
- [x] Hand-off ready without verbal explanation

### MA-140 — Subscription Service: Admin-Triggered Pause Consumer

- [x] Solves the problem (reliable, idempotent pause of a deactivated/suspended customer's subscriptions, reusing existing domain logic)
- [x] All 13 sections present and complete
- [x] Functional requirements specific (exact consumer behavior, new internal entrypoint distinct from the customer-facing one, idempotency argument)
- [x] NFRs defined with measurable targets (5-minute freshness target, DLQ depth alarm)
- [x] Acceptance criteria testable (§10 — unit, integration, contract, E2E, explicit negative scenarios)
- [x] Edge cases and failure modes documented (§9 — 6 cases incl. zero-subscriptions, redelivery, concurrent Daily Run, filtered-out reactivation events)
- [x] Testing strategy sufficient (offline moto pattern, shared contract fixture with MA-139)
- [x] Scope boundaries clearly stated (§3 — explicitly one-directional, no auto-resume, no schema change, no Wallet interaction)
- [x] Assumptions and risks explicit (§11 — one-directional-by-design, new queue justified, reason-persistence trade-off)
- [x] Hand-off ready without verbal explanation

### MA-141 — Customer Account Management

- [x] Solves the problem (find, view, and act on customer accounts from the admin console)
- [x] All 13 sections present; UI-specific coverage included (component map inherited from shipped MA-128 patterns, all UI states, exact selectors, a11y inherited)
- [x] Functional requirements specific and unambiguous (exact dialogs, state-aware action menu, bulk summary behavior)
- [x] NFRs defined with measurable targets (load time, inherited a11y/security posture)
- [x] Acceptance criteria testable (§10 — three Playwright scenarios with concrete selectors)
- [x] Edge cases and failure modes documented (§9 — 6 cases incl. the explicit naming-collision guard against MA-47's Admin Users screen)
- [x] Testing strategy sufficient (unit + integration against MA-139 DTOs + E2E, matching MA-128's established convention)
- [x] Scope boundaries clearly stated (§3 — backend, Subscription behavior, Admin Users screens, audit viewer all explicitly out)
- [x] Assumptions and risks explicit (§11 — role gate unconfirmed, client-side-filter scale risk, new bulk-UI risk)
- [x] Hand-off ready without verbal explanation

---

## Part 2 — Cross-specification coherence

- [x] **Consistent terminology and definitions** — `Active`/`Suspended`/`Deactivated`, `user.status.changed`, `userId`/`previousStatus`/`newStatus`/`reason`/`effectiveFrom`/`actorAdminId`, `/v1/admin/customers*` endpoint style — used identically across all three specs.
- [x] **No conflicts or contradictions** — MA-141's DTOs (§7) match MA-139's endpoint definitions (§4) field-for-field. MA-140's consumed-event shape (§4 FR-1, §8) is byte-for-byte the same contract MA-139 publishes (§8) — neither spec redefines it independently. *Corrected post-review:* this check originally missed that MA-141's Deactivate workflow (§6) documented handling a `409 INVALID_STATUS_TRANSITION` response, while MA-139 FR-4 defines Deactivate as always idempotent/200 and never returning 409 — a real cross-spec response-contract mismatch, not present in the request DTOs this check actually verified. Fixed in both specs (MA-141 §6 now correctly attributes the 409 case to Suspend, MA-139's FR-4/FR-3 wording was tightened alongside it) — re-verified field-for-field and response-code-for-response-code after the fix, this checklist item now holds for both.
- [x] **Data models align without collision** — `users`/`user_status_history` (MA-139, User Service's Aurora) and `subscriptions` (MA-140, Subscription Service's own Aurora, unchanged schema) are fully separate per the database-per-service guardrail; MA-140 never reads MA-139's tables directly, only the event payload.
- [x] **Inter-spec dependencies identified** — MA-141 → MA-139 (HTTP, all 6 endpoints, §8 of both); MA-139 → MA-140 (event only, §8 of both, one-way, fire-and-forget). Every cross-reference names the sibling spec and section.
- [x] **No required behavior silently uncovered** — every AC from MA-39's Step 1 maps to exactly one owner: list/search/filter → MA-141 FR-2 + MA-139 FR-1; status change + audit → MA-139 FR-3/4/5/§7; login block → MA-139 FR-3/4 (Cognito calls) + a checklist item against Identity & Auth (MA-139 §8, §12 Q1); subscription pause → MA-140 FR-1/FR-2; bulk + per-row independence → MA-139 FR-6 + MA-141 FR-5; self-lockout safety (AC-8, admin accounts are never a target) → structurally true by construction, since these endpoints operate on `users` (customers), never `admin_user` (staff) — a distinct table in a distinct service context (MA-129's `admin_user` lives in Identity & Auth, not User Service).
- [x] **Combined specs fully satisfy the User Story** — an admin can find a customer, suspend/deactivate/reactivate them (singly or in bulk) with a reason, the customer is immediately blocked from new logins and (for the two blocking states) their subscriptions stop generating orders within a bounded delay, and every action is durably auditable — while order history and wallet balance are never touched by any of the three specs.
- [x] **No overlapping responsibilities causing ambiguity** — User Service owns the status model, the login-block mechanism, and the event contract (single-homed, not duplicated); Subscription Service owns only the pause reaction; Portal-UI owns only presentation and the one place a human makes a decision. The event contract lives only in MA-139 and is referenced, not redefined, by MA-140.
- [x] **NFRs consistent** — the "short eventually-consistent delay is an accepted trade-off" framing (D7) is stated the same way in MA-139 (implicitly, via the async outbox) and MA-140 (explicitly, §5); the audit/observability story (structured logs + correlation ID + a named CloudWatch metric per spec) is uniform across all three.
- [x] **Testing strategies form a coherent overall test plan** — MA-139 and MA-140 share a contract fixture for `user.status.changed`; MA-141 and MA-139 share the DTO shapes in MA-141 §7; the E2E scenario in MA-139 §10 (login blocked after deactivation) and the E2E scenario in MA-140 §10 (subscriptions paused after deactivation) are two independent acceptance gates for the same underlying action, not duplicated effort.
- [x] **Implementation planning can begin without major ambiguity** — sequencing is explicit (MA-139 first and independently shippable; MA-140 depends on MA-139's event; MA-141 depends on MA-139's API — MA-140 and MA-141 can be built in parallel once MA-139's contract is stable). The open items (role-gate exact split, sweep schedule time, client- vs server-side search, reason-persistence-on-subscription) are enumerated per spec §12 and are implementation-review calls, not blockers.

---

## Review finding (found and fixed during this pass)

| # | File | Finding | Resolution |
|---|------|---------|------------|
| 1 | MA-139 §4 FR-1 | `lastStatusChangeAt` was listed as a returned field with no clear source column — `users.status_effective_from` is only a `DATE`, losing the time-of-day precision a "last changed" display implies, and doesn't get updated the same way on every transition type as cleanly as the history table does | Clarified: `lastStatusChangeAt` is explicitly sourced from the most recent `user_status_history.created_at` (`timestamptz`), not from `status_effective_from`; `NULL` for an account with no history yet |

No other discrepancies found between the three specs' contracts, terminology, or scope boundaries.

## Review round 2 — post-implementation `/code-review` findings (2026-10-01)

A `/code-review` run against the merged specs (after User/Subscription Service implementation had begun) found four further issues the round-1 review above missed — all resolved on `spec/MA-39-revision`:

| # | File | Finding | Resolution |
|---|------|---------|------------|
| 2 | MA-140 §4 FR-1/FR-2 | The candidate-set query (FR-1) only included `ACTIVE` subscriptions and not-yet-started `PAUSED` ones, and FR-2's own write-time guard skipped *every* already-`PAUSED` subscription — together, a customer's already-in-effect temporary pause was never reached by the admin override §9 itself claimed would happen, so it would silently auto-resume on its original schedule even while the account stayed deactivated. | FR-1 widened to every non-`STOPPED` subscription; FR-2's skip condition narrowed to only `PAUSED` subscriptions with `pause_until` already `None` (a true repeat), so a `PAUSED` subscription with a real `pause_until` is now correctly overridden. Workflow diagram, edge-case table, and testing strategy (§6/§9/§10) updated to match, including a new testing requirement that at least one test exercise this through the consumer's own entrypoint, not only the inner method directly — which is how the original gap passed review. |
| 3 | MA-139 §4 FR-5 | Reactivate had no idempotency guarantee, unlike FR-3/FR-4 (added in round 1) — a repeat reactivate call on an already-`Active` account would write a duplicate `Active`→`Active` history row and re-publish the event. | FR-5 given the same idempotent-200, still-calls-Cognito treatment as FR-3/FR-4. |
| 4 | MA-139 §4 FR-3 | A cross-reference for "what `until` means" pointed at §9 (Edge Cases), but the actual definition lives in FR-7. | Corrected to point at FR-7. |
| 5 | MA-39/step5-review.md | This file's own decision-record item 4 still listed the sweep schedule as an open question after MA-139 FR-7/§12 had already resolved it (00:05 IST). | Corrected (struck through, see item 4 below). |

## Verdict

**PASS** — all individual-quality and cross-specification coherence checks are satisfied; all findings from both review rounds are resolved on `spec/MA-39-revision` without changing scope or the cross-service contract.

### Decision records / follow-up actions (carried, not blocking)

1. **Role-gate confirmation needed** — MA-139 §12 Q3 and MA-141 §12 Q1 both flag the same open question (should Deactivate require SuperAdmin specifically, or is Ops sufficient for all three actions uniformly) — both specs currently propose the same uniform Ops+SuperAdmin default; needs an architect/product confirmation before or during implementation, not blocking spec approval.
2. **Identity & Auth checklist item** — MA-139 §8/§12 Q1: confirm `UserDisabledException` maps to a clean client error in the existing login handlers; a small implementation-time spike, not a spec.
3. **List scale / pagination approach** — MA-141 §12 Q2: recommend server-side search from day one (MA-139's list endpoint already supports it), unlike MA-128's client-side-first precedent, given the larger expected customer-account volume; flagged for architect confirmation.
4. ~~Sweep schedule time~~ — resolved: MA-139 FR-7/§12 Q2 now specifies 00:05 IST, ahead of the Subscription Daily Run's own cut-off window.
5. **Reason persistence on the subscription row** — MA-140 §12 Q1: this spec recommends not persisting it there (rely on User Service's own history as the source of "why"), flagged for confirmation since it's the one place MA-140 makes a call not explicitly directed by the approved decomposition.
