# Changelog

All notable changes to this project will be documented here.

The format follows Keep a Changelog, and the project intends to use Semantic
Versioning after the first public release.

## [Unreleased]

## [0.2.0] - 2026-08-31

### Breaking changes and migration

- `MissionReadback` is replaced by `MissionSnapshotReadback`. Integrations must
  send the complete ordered predicate truth vector plus a monotonic
  `parent_state_sequence`; a partial or stale readback is no longer accepted.
- Direct `TaskPacket` construction now requires `recovery_budget`, and direct
  terminal/verification/callback record construction requires the new
  failure-origin, parent-snapshot, convergence, or delivery-reconciliation
  identities appropriate to that record. Prefer `CollaborationHarness.plan()`
  and the staged harness methods instead of constructing derived records.
- The Tura request wire identity changes because `recovery_budget` and
  `protocol_version=tura-collaboration/v1` are now canonical request fields.
  Consumers must regenerate request identities and validate against the
  packaged v1 schema/golden vectors; persisted v0.1 request identities are not
  replay-compatible with v0.2.
- String lookalikes for Enum values and truthy/falsy non-boolean values are now
  rejected at runtime. Adapters must decode external JSON once at their wire
  boundary and pass canonical Python Enum/bool/int values into the core.

### Fixed

- Enforce canonical Enum, bool, integer, packet, effect, and failure-origin
  types at runtime instead of relying on Python annotations or truthiness.
- Replace permanent predicate latching with complete parent snapshots and a
  monotonic parent-state sequence; stale snapshots cannot overwrite newer
  mission truth.
- Persist callback delivery start/uncertainty and require an exact destination
  absence or convergence proof before retry or acknowledgement.
- Preserve store-classified duplicate-effect failures as reconcilable attempts
  instead of stranding their leases.
- Prevent policy, authority, effect-uncertainty, and other non-local blockers
  from self-labelling as safe local recovery.
- Verify content-addressed task packets before granting a lease.

### Added

- Typed step attempts, blockers, model-generated recovery proposals,
  deterministic recovery admission, duplicate action fingerprints, and
  parent-bounded recovery budgets.
- Parent-authored route dispositions and evidence-only mission supersession
  classification.
- Content-addressed identities for parent snapshots, convergence proofs,
  acknowledgements, terminal receipts, and recovery records.
- Versioned Tura request/terminal JSON schemas and cross-language golden
  request/result/failure vectors packaged in the wheel.
- Networked public Tura component validation for exact branch, trees, ancestry,
  license, and modification notice.
- Pinned GitHub Actions, clean-wheel installation verification, deterministic
  checksums, and tag-triggered build provenance attestation.

### Boundaries

- The package remains an in-memory reference. Durable event logs,
  transactional outbox/inbox, distributed fencing, authenticated transports,
  real effect authority, and installed/runtime acceptance remain integration
  responsibilities.

## [0.1.1] - 2026-08-31

### Fixed

- Preserve a Tura executor's typed failure or rejection code, detail digest,
  and observed effect identity across the adapter-to-core boundary instead of
  flattening the outcome to `EXECUTOR_ERROR`.
- Require explicit effect reconciliation after a structured executor failure
  and reject a second execution attempt before it can reach the Tura client.

### Added

- Generic `ExecutorFailureSignal` support for provider-neutral structured
  executor failures.
- End-to-end Tura composition fixtures for settled-effect and proven-no-effect
  failure paths.

## [0.1.0] - 2026-08-31

### Added

- Original, domain-neutral Python collaboration state machine.
- Ordered mission predicates and first-false selection.
- Bounded task packets with route, expected delta, and abandon condition.
- In-memory lease/CAS ownership reference.
- Typed execution, same-attempt effect reconciliation, terminal receipt,
  destination, convergence, and mission verification records.
- Exact task-lease release at terminal receipt persistence and stable
  continuation identity across callback recovery.
- Deterministic end-to-end and failure-path tests.
- Public architecture, trust-boundary, provenance, security, governance, and
  review documentation.

### Limitations

- No durable/distributed store, production network transport, worker sandbox,
  cryptographic receipt, or production effect authorization.
- Internal benchmark context is not reproducible from this repository and is
  not evidence of this public implementation's performance.
