# Changelog

All notable changes to this project will be documented here.

The format follows Keep a Changelog, and the project intends to use Semantic
Versioning after the first public release.

## [Unreleased]

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
