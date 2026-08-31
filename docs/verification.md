# Verification Contract

## Canonical Command

From an installed editable checkout:

```bash
python3 -m unittest discover -s tests -v
```

Without installing the package:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The supported baseline is Python 3.11 or newer. Runtime code is standard-library
only. Verification must exit zero with no failing tests. Test count and exact
names are reported by the command and should be included in release evidence;
this document does not freeze a count that could silently become stale.

To run only the deterministic complete cycle:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_harness.HappyPathTests.test_complete_cycle -v
```

For the repository-level review contract, run:

```bash
make check
```

`make check` runs the review-readiness scan, evidence-manifest integrity check,
full unit suite, synthetic demo, and import smoke test. Packaging is a separate predicate:
`make build` requires the optional development build dependency and writes
artifacts under `dist/`.

## Current Source Snapshot

On 2026-08-31, the current source tree produced:

- exact complete-cycle selector: `Ran 1 test` and `OK`;
- full suite: `Ran 30 tests` and `OK`;
- review-readiness scan: 41 authored public files, passed;
- evidence-manifest integrity: 1 covered artifact, passed;
- synthetic demo and import smoke check: passed.

This is source-tree evidence, not a release or installed-runtime claim. A release
record must repeat the commands against its exact candidate commit/artifact.

## Public End-to-End Scenario

The deterministic suite exercises this complete in-memory path:

```text
parent mission with ordered predicates
  -> select first false predicate
  -> construct bounded packet
  -> acquire scoped lease/CAS claim
  -> accept typed worker result
  -> create one terminal receipt
  -> target exact parent destination
  -> verify exact convergence
  -> acknowledge once
  -> obtain exact parent-owned MissionReadback
  -> re-evaluate parent mission
```

All identifiers and payloads are synthetic. The run requires no network,
provider account, external agent, secret, private evidence, or installed local
runtime.

## Invariant Matrix

The current v0.1 suite contains 30 tests. Its direct evidence is:

| Test area | Direct observation |
|---|---|
| Complete cycle | First false predicate and lowest-ranked route are selected; one settled effect, terminal receipt, exact destination, three ACK identities, and terminal `MissionVerification` are produced deterministically |
| Predicate order | An earlier false predicate wins even when a later route has a numerically better rank |
| Overlapping ownership | A second mission cannot claim an overlapping active scope |
| Pre-execution rejection | A typed blocked terminal receipt is written and the exact lease is released without an executor call |
| Unsettled reconciliation | One attempt/effect is retained, executor retry is blocked, and settlement terminalizes the same identity with an executor call count of one |
| Callback target | A wrong proof destination creates no ACK or mission verification; the terminal task lease remains released |
| Callback recovery | Retry reuses the same `PREPARED` continuation and reaches `COMMITTED` then `ACKNOWLEDGED` without a duplicate continuation |
| Identical replay | Replay after acknowledgement returns empty effect, continuation, and acknowledgement tuples |
| Changed replay | Reusing an acknowledged packet with a changed identity is a typed conflict |
| ACK cardinality | Callback, receipt, and continuation ACK identities are emitted once under one acknowledgement |
| Mission return | A terminal child outcome returns to parent `MissionVerification` and selects completion or route selection there |
| Parent readback authority | A true worker claim cannot complete a false parent predicate; a true parent readback can complete it despite a false worker claim |
| Readback identity | A readback for another mission revision or predicate is rejected |
| Stale mission | A superseded mission revision is rejected before lease or execution |
| Duplicate dispatch | A second claim for the same packet is rejected |
| Stale CAS | A scope snapshot captured before a prior terminalization is rejected |
| Revision-drift closeout | A claimed packet whose mission revision changes before execution terminalizes the exact prior lease without running the executor |
| Failure reconciliation | Executor exceptions and invalid result identities require explicit `NONE` or `SETTLED` proof before terminalization; the executor is not rerun |
| Concurrent claim | Two synchronized threads competing for one scope produce exactly one lease and one typed conflict |
| Missing convergence | An incomplete destination proof creates no ACK |
| Scanner exclusions | Repo-local virtual-environment variants are excluded as build state |
| Packaging metadata exclusion | Generated `*.egg-info` metadata is excluded while authored `src/` remains scanned |
| Scanner inclusion | Public source remains inside the review-readiness scan boundary |
| Tura adapter success | A bounded task/lease maps deterministically to a Tura request and a settled terminal envelope maps to the core result |
| Tura unsettled effect | The exact effect identity remains unsettled for core reconciliation rather than being retried |
| Tura transport/terminal failure | Transport exceptions and explicit terminal failures become deterministic typed failures |
| Tura identity closure | Packet, lease, request, and executor drift is rejected before becoming a core result |

The implementation has additional structural validation, and future paths may
need new dedicated fixtures. Public evidence is limited to the 30 tests
above and the exact source under review.

## Reproduction Record

A reviewer or release operator should record:

```text
source commit:
python implementation/version:
command:
tests run:
failures/errors/skips:
exit code:
```

Do not label the result "installed runtime verified" unless the installed
artifact identity and the actual adapter behavior were separately read back.

## What Passing Establishes

- the checked source tree imports and runs on the tested interpreter;
- the public in-memory fixtures satisfy the implemented transition contract;
- the tested negative paths fail closed.

## What Passing Does Not Establish

- package publication or installed adoption;
- production durability, distributed concurrency, or crash recovery;
- external worker correctness or isolation;
- authenticated callback delivery;
- permission for external effects;
- benchmark performance or universal productivity improvement.
