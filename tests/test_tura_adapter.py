# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from importlib.resources import files

from codex_collaboration_harness import (
    CollaborationHarness,
    Destination,
    EffectState,
    ExecutionFailure,
    ExecutionResult,
    ExitPredicate,
    FailureCode,
    FailureReconciliation,
    HarnessViolation,
    Mission,
    Route,
    TerminalStatus,
    canonical_sha256,
)
from codex_collaboration_harness.adapters.tura import (
    TURA_PROTOCOL_VERSION,
    TuraAdapter,
    TuraDispatchRequest,
    TuraExecutionFailureError,
    TuraRejectedError,
    TuraTerminalEnvelope,
    TuraTerminalKind,
    TuraTypedRejection,
    build_tura_dispatch_request,
    decode_tura_terminal_envelope,
    encode_tura_dispatch_request,
)

EXECUTOR_ID = "executor.tura.public"


def claimed_harness():
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
    return harness, packet, harness.claim(packet)


def claimed_packet():
    _, packet, lease = claimed_harness()
    return packet, lease


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
    def test_tura_dispatch_golden_vector_matches_request_identity(self) -> None:
        golden = json.loads(
            files("codex_collaboration_harness")
            .joinpath("protocol", "golden", "tura_dispatch_request_v1.json")
            .read_text(encoding="utf-8")
        )
        request = TuraDispatchRequest(
            packet_id=golden["packet_id"],
            mission_id=golden["mission_id"],
            mission_revision=golden["mission_revision"],
            mission_mode=golden["mission_mode"],
            predicate_key=golden["predicate_key"],
            route_id=golden["route_id"],
            executor_id=golden["executor_id"],
            scope=tuple(golden["scope"]),
            expected_scope_versions=tuple(
                tuple(item) for item in golden["expected_scope_versions"]
            ),
            claimed_scope_versions=tuple(
                tuple(item) for item in golden["claimed_scope_versions"]
            ),
            expected_delta=golden["expected_delta"],
            abandon_if=golden["abandon_if"],
            recovery_budget=golden["recovery_budget"],
            destination=Destination(**golden["destination"]),
            lease_id=golden["lease_id"],
        )

        self.assertEqual(request.request_id, golden["request_id"])
        self.assertEqual(encode_tura_dispatch_request(request), golden)

    def test_tura_wire_golden_vectors_round_trip(self) -> None:
        golden_root = files("codex_collaboration_harness").joinpath(
            "protocol", "golden"
        )
        result_wire = json.loads(
            golden_root.joinpath("tura_result_v1.json").read_text(encoding="utf-8")
        )
        failure_wire = json.loads(
            golden_root.joinpath("tura_failure_v1.json").read_text(encoding="utf-8")
        )

        for wire in (result_wire, failure_wire):
            with self.subTest(kind=wire["kind"]):
                decoded = decode_tura_terminal_envelope(wire)
                json_round_trip = json.loads(json.dumps(asdict(decoded)))
                self.assertEqual(json_round_trip, wire)
                self.assertEqual(
                    decode_tura_terminal_envelope(json_round_trip), decoded
                )
                self.assertEqual(decoded.protocol_version, TURA_PROTOCOL_VERSION)

        self.assertIs(
            decode_tura_terminal_envelope(result_wire).effect_state,
            EffectState.SETTLED,
        )
        self.assertIs(
            decode_tura_terminal_envelope(failure_wire).failure_code,
            FailureCode.EXECUTOR_ERROR,
        )

    def test_adapter_decodes_json_wire_at_single_boundary(self) -> None:
        packet, lease = claimed_packet()

        def wire_result(request):
            return {
                "protocol_version": TURA_PROTOCOL_VERSION,
                "request_id": request.request_id,
                "packet_id": request.packet_id,
                "lease_id": request.lease_id,
                "executor_id": request.executor_id,
                "kind": "result",
                "effect_state": "settled",
                "effect_id": "effect.tura.wire.1",
                "output_digest": canonical_sha256({"wire": "result"}),
                "predicate_satisfied": True,
                "failure_code": None,
                "failure_detail_digest": None,
            }

        outcome = TuraAdapter(FakeTuraClient(wire_result), EXECUTOR_ID).dispatch(
            packet, lease
        )

        self.assertIsInstance(outcome, ExecutionResult)
        self.assertIs(outcome.effect_state, EffectState.SETTLED)
        self.assertIs(outcome.predicate_satisfied, True)

    def test_noncanonical_tura_runtime_values_are_rejected(self) -> None:
        packet, lease = claimed_packet()
        request = build_tura_dispatch_request(packet, lease)
        fields = {
            "protocol_version": TURA_PROTOCOL_VERSION,
            "request_id": request.request_id,
            "packet_id": request.packet_id,
            "lease_id": request.lease_id,
            "executor_id": request.executor_id,
            "effect_id": "effect.tura.invalid",
            "output_digest": canonical_sha256({"invalid": True}),
        }

        with self.assertRaises(TypeError):
            TuraTerminalEnvelope(
                **fields,
                kind="result",
                effect_state=EffectState.SETTLED,
                predicate_satisfied=True,
            )
        with self.assertRaises(TypeError):
            TuraTerminalEnvelope(
                **fields,
                kind=TuraTerminalKind.RESULT,
                effect_state=EffectState.SETTLED,
                predicate_satisfied="false",
            )
        with self.assertRaises(TypeError):
            decode_tura_terminal_envelope(
                {
                    **fields,
                    "kind": "result",
                    "effect_state": "settled",
                    "predicate_satisfied": "false",
                    "failure_code": None,
                    "failure_detail_digest": None,
                }
            )

    def test_tura_failure_cannot_emit_mission_complete(self) -> None:
        packet, lease = claimed_packet()

        def invalid_failure(request):
            return {
                "protocol_version": TURA_PROTOCOL_VERSION,
                "request_id": request.request_id,
                "packet_id": request.packet_id,
                "lease_id": request.lease_id,
                "executor_id": request.executor_id,
                "kind": "failure",
                "effect_state": "none",
                "effect_id": None,
                "output_digest": canonical_sha256({"terminal": "invalid"}),
                "predicate_satisfied": False,
                "failure_code": "MISSION_COMPLETE",
                "failure_detail_digest": canonical_sha256(
                    {"failure": "invalid commander outcome"}
                ),
            }

        outcome = TuraAdapter(FakeTuraClient(invalid_failure), EXECUTOR_ID).dispatch(
            packet, lease
        )

        self.assertIsInstance(outcome, TuraTypedRejection)
        self.assertEqual(outcome.code, FailureCode.INVALID_FAILURE_CODE)
        self.assertEqual(outcome.mismatched_fields, ("failure_code",))

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
        self.assertEqual(request.recovery_budget, packet.recovery_budget)
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
        self.assertEqual(outcome.observed_effect_id, "effect.tura.synthetic.1")
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


class TuraCoreCompositionTests(unittest.TestCase):
    def assert_code(self, expected: FailureCode, operation) -> HarnessViolation:
        with self.assertRaises(HarnessViolation) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_settled_failure_identity_survives_core_boundary_without_rerun(
        self,
    ) -> None:
        harness, packet, lease = claimed_harness()
        detail_digest = canonical_sha256({"failure": "cas conflict"})

        def settled_failure(request):
            return TuraTerminalEnvelope(
                request_id=request.request_id,
                packet_id=request.packet_id,
                lease_id=request.lease_id,
                executor_id=request.executor_id,
                kind=TuraTerminalKind.FAILURE,
                effect_state=EffectState.SETTLED,
                effect_id="effect.tura.real.7",
                output_digest=canonical_sha256({"terminal": "failed"}),
                predicate_satisfied=False,
                failure_code=FailureCode.CAS_MISMATCH,
                failure_detail_digest=detail_digest,
            )

        client = FakeTuraClient(settled_failure)
        adapter = TuraAdapter(client, EXECUTOR_ID)

        self.assert_code(
            FailureCode.CAS_MISMATCH,
            lambda: harness.execute(packet, lease, adapter),
        )
        failure = harness.store.failure_for_packet(packet.packet_id)
        self.assertEqual(failure.failure_code, FailureCode.CAS_MISMATCH)
        self.assertEqual(failure.detail_digest, detail_digest)
        self.assertEqual(failure.observed_effect_id, "effect.tura.real.7")
        self.assertEqual(harness.store.snapshot().effect_count, 1)
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)
        self.assertEqual(harness.store.snapshot().terminal_receipt_count, 0)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, adapter),
        )
        self.assertEqual(len(client.requests), 1)

        receipt = harness.reconcile_failure(
            packet,
            lease,
            FailureReconciliation(
                packet_id=packet.packet_id,
                lease_id=lease.lease_id,
                failure_code=FailureCode.CAS_MISMATCH,
                effect_state=EffectState.SETTLED,
                effect_id="effect.tura.real.7",
                proof_digest=canonical_sha256(
                    {"effect_id": "effect.tura.real.7", "settled": True}
                ),
                output_digest=canonical_sha256({"terminal": "reconciled"}),
            ),
        )
        self.assertEqual(receipt.status, TerminalStatus.FAILED)
        self.assertEqual(receipt.failure_code, FailureCode.CAS_MISMATCH)
        self.assertEqual(receipt.effect_id, "effect.tura.real.7")
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assertEqual(harness.store.snapshot().effect_count, 1)

    def test_typed_rejection_preserves_observed_effect_for_reconciliation(
        self,
    ) -> None:
        harness, packet, lease = claimed_harness()

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

        client = FakeTuraClient(wrong_identity)
        adapter = TuraAdapter(client, EXECUTOR_ID)
        expected_detail_digest = canonical_sha256(
            {"kind": "terminal_identity_mismatch", "fields": ("packet_id",)}
        )

        self.assert_code(
            FailureCode.STALE_IDENTITY,
            lambda: harness.execute(packet, lease, adapter),
        )
        failure = harness.store.failure_for_packet(packet.packet_id)
        self.assertEqual(failure.failure_code, FailureCode.STALE_IDENTITY)
        self.assertEqual(failure.detail_digest, expected_detail_digest)
        self.assertEqual(
            failure.observed_effect_id,
            "effect.tura.synthetic.1",
        )
        self.assertEqual(harness.store.snapshot().effect_count, 1)
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, adapter),
        )
        self.assertEqual(len(client.requests), 1)

        receipt = harness.reconcile_failure(
            packet,
            lease,
            FailureReconciliation(
                packet_id=packet.packet_id,
                lease_id=lease.lease_id,
                failure_code=FailureCode.STALE_IDENTITY,
                effect_state=EffectState.SETTLED,
                effect_id="effect.tura.synthetic.1",
                proof_digest=canonical_sha256(
                    {"effect_id": "effect.tura.synthetic.1", "settled": True}
                ),
                output_digest=canonical_sha256({"terminal": "reconciled"}),
            ),
        )
        self.assertEqual(receipt.status, TerminalStatus.FAILED)
        self.assertEqual(receipt.effect_id, "effect.tura.synthetic.1")
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)

    def test_none_failure_identity_survives_until_explicit_no_effect_proof(
        self,
    ) -> None:
        harness, packet, lease = claimed_harness()
        detail_digest = canonical_sha256({"failure": "no effect terminal"})

        def none_failure(request):
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

        client = FakeTuraClient(none_failure)
        adapter = TuraAdapter(client, EXECUTOR_ID)
        self.assert_code(
            FailureCode.EXECUTOR_ERROR,
            lambda: harness.execute(packet, lease, adapter),
        )
        failure = harness.store.failure_for_packet(packet.packet_id)
        self.assertEqual(failure.detail_digest, detail_digest)
        self.assertIsNone(failure.observed_effect_id)
        self.assertEqual(harness.store.snapshot().effect_count, 0)
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, adapter),
        )
        self.assertEqual(len(client.requests), 1)

        receipt = harness.reconcile_failure(
            packet,
            lease,
            FailureReconciliation(
                packet_id=packet.packet_id,
                lease_id=lease.lease_id,
                failure_code=FailureCode.EXECUTOR_ERROR,
                effect_state=EffectState.NONE,
                effect_id=None,
                proof_digest=canonical_sha256({"effect": "none", "proved": True}),
                output_digest=canonical_sha256({"terminal": "reconciled"}),
            ),
        )
        self.assertEqual(receipt.effect_state, EffectState.NONE)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assertEqual(harness.store.snapshot().effect_count, 0)


if __name__ == "__main__":
    unittest.main()
