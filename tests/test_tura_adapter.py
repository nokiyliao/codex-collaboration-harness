# SPDX-License-Identifier: MIT
from __future__ import annotations

import unittest

from codex_collaboration_harness import (
    CollaborationHarness,
    Destination,
    EffectState,
    ExecutionFailure,
    ExecutionResult,
    ExitPredicate,
    FailureCode,
    Mission,
    Route,
    canonical_sha256,
)
from codex_collaboration_harness.adapters.tura import (
    TuraAdapter,
    TuraExecutionFailureError,
    TuraRejectedError,
    TuraTerminalEnvelope,
    TuraTerminalKind,
    TuraTypedRejection,
    build_tura_dispatch_request,
)

EXECUTOR_ID = "executor.tura.public"


def claimed_packet():
    mission = Mission(
        mission_id="mission.tura.synthetic",
        revision=1,
        mode="delivery",
        predicates=(ExitPredicate("artifact_materialized", False),),
        routes=(
            Route(
                route_id="route.tura.synthetic",
                predicate_key="artifact_materialized",
                executor_id=EXECUTOR_ID,
                scope=("artifact:public",),
                expected_delta="a synthetic artifact is materialized",
                abandon_if="external state is required",
            ),
        ),
        destination=Destination("coordinator.public", "thread.public"),
    )
    harness = CollaborationHarness()
    packet = harness.plan(mission)
    return packet, harness.claim(packet)


class FakeTuraClient:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        return self.handler(request)


def result_envelope(request, effect_state: EffectState) -> TuraTerminalEnvelope:
    return TuraTerminalEnvelope(
        request_id=request.request_id,
        packet_id=request.packet_id,
        lease_id=request.lease_id,
        executor_id=request.executor_id,
        kind=TuraTerminalKind.RESULT,
        effect_state=effect_state,
        effect_id="effect.tura.synthetic.1",
        output_digest=canonical_sha256(
            {"request_id": request.request_id, "output": "synthetic"}
        ),
        predicate_satisfied=True,
    )


class TuraAdapterConformanceTests(unittest.TestCase):
    def test_settled_success_maps_bounded_request_and_execution_result(self) -> None:
        packet, lease = claimed_packet()
        client = FakeTuraClient(
            lambda request: result_envelope(request, EffectState.SETTLED)
        )
        adapter = TuraAdapter(client, EXECUTOR_ID)

        outcome = adapter.dispatch(packet, lease)

        self.assertIsInstance(outcome, ExecutionResult)
        self.assertEqual(outcome.packet_id, packet.packet_id)
        self.assertEqual(outcome.lease_id, lease.lease_id)
        self.assertEqual(outcome.effect_state, EffectState.SETTLED)
        request = client.requests[0]
        self.assertEqual(request.mission_id, packet.mission_id)
        self.assertEqual(request.predicate_key, packet.predicate_key)
        self.assertEqual(request.scope, packet.scope)
        self.assertEqual(request.expected_delta, packet.expected_delta)
        self.assertEqual(request.abandon_if, packet.abandon_if)
        self.assertEqual(request.destination, packet.destination)
        self.assertEqual(
            request.request_id,
            build_tura_dispatch_request(packet, lease).request_id,
        )

    def test_unsettled_effect_remains_unsettled_for_core_reconciliation(self) -> None:
        packet, lease = claimed_packet()
        adapter = TuraAdapter(
            FakeTuraClient(
                lambda request: result_envelope(request, EffectState.UNSETTLED)
            ),
            EXECUTOR_ID,
        )

        outcome = adapter.dispatch(packet, lease)

        self.assertIsInstance(outcome, ExecutionResult)
        self.assertEqual(outcome.effect_state, EffectState.UNSETTLED)
        self.assertEqual(outcome.effect_id, "effect.tura.synthetic.1")

    def test_transport_exception_maps_to_deterministic_execution_failure(self) -> None:
        packet, lease = claimed_packet()

        def fail_transport(request):
            raise TimeoutError("synthetic transport unavailable")

        adapter = TuraAdapter(FakeTuraClient(fail_transport), EXECUTOR_ID)

        first = adapter.dispatch(packet, lease)
        second = adapter.dispatch(packet, lease)

        self.assertIsInstance(first, ExecutionFailure)
        self.assertEqual(first.failure_code, FailureCode.EXECUTOR_ERROR)
        self.assertIsNone(first.observed_effect_id)
        self.assertEqual(first.failure_id, second.failure_id)
        with self.assertRaises(TuraExecutionFailureError) as caught:
            adapter.execute(packet, lease)
        self.assertEqual(caught.exception.failure.failure_id, first.failure_id)

    def test_identity_mismatch_is_explicit_typed_rejection(self) -> None:
        packet, lease = claimed_packet()

        def wrong_identity(request):
            envelope = result_envelope(request, EffectState.SETTLED)
            return TuraTerminalEnvelope(
                request_id=envelope.request_id,
                packet_id="packet.changed",
                lease_id=envelope.lease_id,
                executor_id=envelope.executor_id,
                kind=envelope.kind,
                effect_state=envelope.effect_state,
                effect_id=envelope.effect_id,
                output_digest=envelope.output_digest,
                predicate_satisfied=envelope.predicate_satisfied,
            )

        adapter = TuraAdapter(FakeTuraClient(wrong_identity), EXECUTOR_ID)

        outcome = adapter.dispatch(packet, lease)

        self.assertIsInstance(outcome, TuraTypedRejection)
        self.assertEqual(outcome.code, FailureCode.STALE_IDENTITY)
        self.assertEqual(outcome.mismatched_fields, ("packet_id",))
        with self.assertRaises(TuraRejectedError) as caught:
            adapter.execute(packet, lease)
        self.assertEqual(
            caught.exception.rejection.detail_digest, outcome.detail_digest
        )

    def test_terminal_failure_envelope_maps_to_execution_failure(self) -> None:
        packet, lease = claimed_packet()
        detail_digest = canonical_sha256({"failure": "synthetic terminal"})

        def terminal_failure(request):
            return TuraTerminalEnvelope(
                request_id=request.request_id,
                packet_id=request.packet_id,
                lease_id=request.lease_id,
                executor_id=request.executor_id,
                kind=TuraTerminalKind.FAILURE,
                effect_state=EffectState.NONE,
                effect_id=None,
                output_digest=canonical_sha256({"terminal": "failed"}),
                predicate_satisfied=False,
                failure_code=FailureCode.EXECUTOR_ERROR,
                failure_detail_digest=detail_digest,
            )

        outcome = TuraAdapter(FakeTuraClient(terminal_failure), EXECUTOR_ID).dispatch(
            packet, lease
        )

        self.assertIsInstance(outcome, ExecutionFailure)
        self.assertEqual(outcome.detail_digest, detail_digest)
        self.assertEqual(outcome.packet_id, packet.packet_id)
        self.assertIsNone(outcome.observed_effect_id)


if __name__ == "__main__":
    unittest.main()
