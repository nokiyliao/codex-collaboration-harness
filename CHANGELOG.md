# Changelog

All notable changes to this project will be documented here.

The format follows Keep a Changelog, and the project intends to use Semantic
Versioning after the first public release.

## [Unreleased]

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

- No durable/distributed store, network transport, worker sandbox, provider
  adapter, cryptographic receipt, or production effect authorization.
- Internal benchmark context is not reproducible from this repository and is
  not evidence of this public implementation's performance.
