# Native Tura End-State Topology

## Ownership Matrix

| Surface | Sole owner | Tura role |
| --- | --- | --- |
| UI, task/thread, session DB, rollout, writer lock | Official Codex Desktop/App Server | Client only |
| Provider turn, tools, command receipts, interruption recovery | Native Codex task runtime | Execution policy |
| Mission truth and route selection | Parent Global Commander task | Returns terminal delta |
| Task decomposition and fan-out | Parent Global Commander task | Executes one bounded shard |
| DCF/J-Space | Existing read-only context/authority surfaces | Optional consumer |
| Terminal callback | Official `send_message_to_thread` | Trusted direct writer |

## Canonical Flow

1. Commander creates one first-class Native Codex task with `create_thread`.
2. The initial prompt explicitly invokes `$tura-kernel` and binds the parent
   thread plus one callback identity.
3. Native Codex persists the task, executes provider turns and tools, and owns
   restart recovery.
4. Tura applies objective-first route selection to its one bounded shard.
   Commander may create several independent first-class Tura tasks in parallel.
5. The Tura task terminalizes and invokes one
   official `send_message_to_thread` callback to the bound Commander.
6. Successful tool delivery persists the callback independently of the parent
   provider turn. Commander verifies the returned predicate delta on its next
   available turn and continues its mission.

There is no reverse ACK requirement for Tura to terminalize. The Native tool
success response proves delivery; parent turn execution and mission acceptance
are separate facts. Never reuse a completed Tura task as a new dispatch merely
to continue its provider response chain.

## Retired Operational Surfaces

The following must not be installed, started, or treated as current authority:

- Tura Gateway, Router, Runtime, Session DB, scheduler, runtime lease store;
- Tura callback outbox/queue, polling daemon, or bridge-owned mission store;
- standalone or second Codex App Server;
- `CODEX_CLI_PATH` takeover, patched `app.asar`, or patched bundled Codex;
- raw App-tools pipe delivery or direct Codex private DB/rollout writes;
- wrapper tasks whose only purpose is to spawn an `agent_type=tura` child.

Tura-internal Native subagents are not part of the operational baseline. They
may be reconsidered only after the platform canary proves a child receives the
exact bounded packet; do not patch Desktop or add a transport to manufacture
that capability.

Historical source, benchmarks, receipts, and rollback evidence remain archives.
`tura-taskpacket` remains a stateless optional capsule verifier. The existing
Codex multi-model switchboard and model-provider gateway are not Tura lifecycle
surfaces and are outside this retirement set.

## Maintenance Boundary

Desktop updates may replace only official application bytes. Tura behavior is
versioned in this external skill and the collaboration-harness package, so an
App update requires a Native task/callback smoke test rather than a source
rebase or App re-signing operation.

Native task persistence and upstream provider continuation are distinct. A
locally durable turn can still encounter an invalid provider
`previous_response_id`; this does not justify a Tura Session DB, callback retry,
or App patch. Use a fresh first-class task per dispatch and keep callback
delivery evidence separate from the parent's subsequent model turn.
