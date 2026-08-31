# SPDX-License-Identifier: MIT
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

from codex_collaboration_harness import (
    CollaborationHarness,
    Continuation,
    ContinuationState,
    ConvergenceProof,
    Destination,
    EffectReconciliation,
    EffectState,
    ExecutionResult,
    ExitPredicate,
    FailureCode,
    FailureReconciliation,
    HarnessViolation,
    InMemoryStore,
    Mission,
    MissionNextAction,
    MissionReadback,
    ResumeProof,
    Route,
    StoreSnapshot,
    TerminalStatus,
    canonical_sha256,
)

EXECUTOR_ID = "executor.synthetic"
DESTINATION = Destination("coordinator.public", "thread.synthetic")


def make_route(
    predicate_key: str = "result_materialized",
    *,
    route_id: str = "route.preferred",
    executor_id: str = EXECUTOR_ID,
    scope: tuple[str, ...] = ("artifact:synthetic-result",),
    rank: int = 1,
) -> Route:
    return Route(
        route_id=route_id,
        predicate_key=predicate_key,
        executor_id=executor_id,
        scope=scope,
        expected_delta="a public result exists",
        abandon_if="the route needs a private dependency",
        rank=rank,
    )


def make_mission(
    *,
    mission_id: str = "mission.synthetic",
    revision: int = 1,
    scope: tuple[str, ...] = ("artifact:synthetic-result",),
    destination: Destination = DESTINATION,
) -> Mission:
    return Mission(
        mission_id=mission_id,
        revision=revision,
        mode="delivery",
        predicates=(
            ExitPredicate("inputs_ready", True),
            ExitPredicate("result_materialized", False),
        ),
        routes=(
            make_route(
                route_id="route.fallback",
                executor_id="executor.never-selected",
                scope=scope,
                rank=2,
            ),
            make_route(scope=scope),
        ),
        destination=destination,
    )


def make_readback(
    mission: Mission,
    *,
    satisfied: bool = True,
    predicate_key: str = "result_materialized",
) -> MissionReadback:
    return MissionReadback(
        mission_id=mission.mission_id,
        mission_revision=mission.revision,
        predicate_key=predicate_key,
        satisfied=satisfied,
        evidence_digest=canonical_sha256(
            {
                "mission_id": mission.mission_id,
                "mission_revision": mission.revision,
                "predicate_key": predicate_key,
                "satisfied": satisfied,
                "owner": "parent",
            }
        ),
    )


class RecordingExecutor:
    def __init__(
        self,
        *,
        effect_id: str = "effect.synthetic.1",
        effect_state: EffectState = EffectState.SETTLED,
        predicate_satisfied: bool = True,
        executor_id: str = EXECUTOR_ID,
    ) -> None:
        self.executor_id = executor_id
        self.effect_id = effect_id
        self.effect_state = effect_state
        self.predicate_satisfied = predicate_satisfied
        self.calls = 0

    def execute(self, packet, lease) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            executor_id=self.executor_id,
            packet_id=packet.packet_id,
            lease_id=lease.lease_id,
            effect_id=self.effect_id,
            effect_state=self.effect_state,
            output_digest=canonical_sha256(
                {"packet_id": packet.packet_id, "value": "synthetic-output"}
            ),
            predicate_satisfied=self.predicate_satisfied,
        )


class RaisingExecutor:
    executor_id = EXECUTOR_ID

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, packet, lease):
        self.calls += 1
        raise RuntimeError("synthetic provider failure")


class MismatchedResultExecutor(RecordingExecutor):
    def execute(self, packet, lease) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            executor_id=self.executor_id,
            packet_id="packet_changed_identity",
            lease_id=lease.lease_id,
            effect_id=self.effect_id,
            effect_state=EffectState.SETTLED,
            output_digest=canonical_sha256({"value": "untrusted-result"}),
            predicate_satisfied=True,
        )


class BarrierStore(InMemoryStore):
    """Release two claim callers together before the store lock boundary."""

    def __init__(self, barrier: Barrier) -> None:
        super().__init__()
        self.barrier = barrier

    def claim(self, packet):
        self.barrier.wait(timeout=5)
        return super().claim(packet)


class DeterministicTransport:
    def __init__(
        self,
        *,
        proof_destination: Destination | None = None,
        completed: bool = True,
    ) -> None:
        self.proof_destination = proof_destination
        self.completed = completed
        self.resume_calls = 0
        self.start_turn_calls = 0

    def resume(self, continuation: Continuation) -> ResumeProof:
        self.resume_calls += 1
        return ResumeProof(
            continuation_id=continuation.continuation_id,
            destination=continuation.destination,
            resume_token=canonical_sha256(
                {"step": "resume", "continuation_id": continuation.continuation_id}
            ),
        )

    def start_turn(self, continuation, resume_proof, receipt) -> ConvergenceProof:
        self.start_turn_calls += 1
        return ConvergenceProof(
            continuation_id=continuation.continuation_id,
            receipt_id=receipt.receipt_id,
            destination=self.proof_destination or continuation.destination,
            completed_turn_id=canonical_sha256(
                {
                    "step": "turn",
                    "resume_token": resume_proof.resume_token,
                    "receipt_id": receipt.receipt_id,
                }
            ),
            completed=self.completed,
        )


class HarnessTestCase(unittest.TestCase):
    def assert_code(self, expected: FailureCode, operation) -> HarnessViolation:
        with self.assertRaises(HarnessViolation) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def terminalize(self, harness: CollaborationHarness):
        packet = harness.plan(make_mission())
        lease = harness.claim(packet)
        receipt = harness.execute(packet, lease, RecordingExecutor())
        return packet, lease, receipt


class HappyPathTests(HarnessTestCase):
    def test_complete_cycle(self) -> None:
        harness = CollaborationHarness()
        executor = RecordingExecutor()
        transport = DeterministicTransport()
        mission = make_mission()

        result = harness.run(mission, executor, transport, make_readback(mission))

        self.assertEqual(result.packet.predicate_key, "result_materialized")
        self.assertEqual(result.packet.route_id, "route.preferred")
        self.assertEqual(result.receipt.status, TerminalStatus.SUCCEEDED)
        self.assertEqual(result.receipt.effect_state, EffectState.SETTLED)
        self.assertEqual(result.continuation.state, ContinuationState.ACKNOWLEDGED)
        self.assertEqual(result.convergence_proof.destination, DESTINATION)
        self.assertTrue(result.verification.predicate_satisfied)
        self.assertEqual(
            result.verification.next_action, MissionNextAction.MISSION_COMPLETE
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(transport.resume_calls, 1)
        self.assertEqual(transport.start_turn_calls, 1)
        self.assertEqual(
            harness.store.snapshot(),
            StoreSnapshot(1, 0, 1, 1, 1, 1, 1, 1),
        )

        second_mission = make_mission()
        second = CollaborationHarness().run(
            second_mission,
            RecordingExecutor(),
            DeterministicTransport(),
            make_readback(second_mission),
        )
        self.assertEqual(result.packet.packet_id, second.packet.packet_id)
        self.assertEqual(result.receipt.receipt_id, second.receipt.receipt_id)
        self.assertEqual(
            result.verification.verification_id, second.verification.verification_id
        )


class VerificationContractTests(HarnessTestCase):
    def test_first_false_predicate_wins_over_later_higher_rank_route(self) -> None:
        mission = Mission(
            "mission.order",
            1,
            "delivery",
            (
                ExitPredicate("ready", True),
                ExitPredicate("first_false", False),
                ExitPredicate("later_false", False),
            ),
            (
                make_route("later_false", route_id="route.later", rank=0),
                make_route("first_false", route_id="route.first", rank=9),
            ),
            DESTINATION,
        )
        packet = CollaborationHarness().plan(mission)
        self.assertEqual(packet.predicate_key, "first_false")
        self.assertEqual(packet.route_id, "route.first")

    def test_overlapping_active_lease_is_rejected(self) -> None:
        harness = CollaborationHarness()
        first = harness.plan(make_mission(mission_id="mission.first"))
        second = harness.plan(make_mission(mission_id="mission.second"))
        harness.claim(first)
        self.assert_code(FailureCode.LEASE_CONFLICT, lambda: harness.claim(second))

    def test_pre_execution_rejection_is_typed_terminal_and_releases_lease(self) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission())
        lease = harness.claim(packet)
        wrong = RecordingExecutor(executor_id="executor.wrong")

        receipt = harness.execute(packet, lease, wrong)

        self.assertEqual(wrong.calls, 0)
        self.assertEqual(receipt.status, TerminalStatus.BLOCKED)
        self.assertEqual(receipt.failure_code, FailureCode.STALE_IDENTITY)
        self.assertEqual(receipt.effect_state, EffectState.NONE)
        self.assertFalse(receipt.predicate_satisfied)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assertEqual(harness.store.snapshot().terminal_receipt_count, 1)

    def test_unsettled_effect_never_reexecutes_and_reconciles_same_attempt(
        self,
    ) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission())
        lease = harness.claim(packet)
        executor = RecordingExecutor(effect_state=EffectState.UNSETTLED)

        self.assert_code(
            FailureCode.UNSETTLED_EFFECT,
            lambda: harness.execute(packet, lease, executor),
        )
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, executor),
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)
        self.assertEqual(harness.store.snapshot().terminal_receipt_count, 0)

        receipt = harness.reconcile_effect(
            packet,
            lease,
            EffectReconciliation(
                packet.packet_id,
                lease.lease_id,
                executor.effect_id,
                EffectState.SETTLED,
                canonical_sha256({"effect_id": executor.effect_id, "settled": True}),
            ),
        )
        self.assertEqual(receipt.status, TerminalStatus.SUCCEEDED)
        self.assertEqual(receipt.effect_id, executor.effect_id)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(harness.store.snapshot().effect_count, 1)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.reconcile_effect(
                packet,
                lease,
                EffectReconciliation(
                    packet.packet_id,
                    lease.lease_id,
                    executor.effect_id,
                    EffectState.SETTLED,
                    "proof",
                ),
            ),
        )

    def test_callback_target_mismatch_has_no_ack_and_no_task_lease(self) -> None:
        harness = CollaborationHarness()
        _, _, receipt = self.terminalize(harness)
        wrong = Destination("coordinator.public", "thread.other")

        self.assert_code(
            FailureCode.CALLBACK_TARGET_MISMATCH,
            lambda: harness.continue_and_ack(
                receipt, DeterministicTransport(proof_destination=wrong)
            ),
        )
        snapshot = harness.store.snapshot()
        self.assertEqual(snapshot.active_lease_count, 0)
        self.assertEqual(snapshot.continuation_count, 1)
        self.assertEqual(snapshot.acknowledgement_count, 0)

    def test_callback_retry_reuses_same_prepared_continuation(self) -> None:
        harness = CollaborationHarness()
        _, _, receipt = self.terminalize(harness)
        wrong = Destination("coordinator.public", "thread.other")
        self.assert_code(
            FailureCode.CALLBACK_TARGET_MISMATCH,
            lambda: harness.continue_and_ack(
                receipt, DeterministicTransport(proof_destination=wrong)
            ),
        )
        prepared = harness.store.continuation_for_receipt(receipt.receipt_id)
        self.assertIsNotNone(prepared)
        self.assertEqual(prepared.state, ContinuationState.PREPARED)

        acknowledged, _, _, _ = harness.continue_existing(
            prepared, receipt, DeterministicTransport()
        )
        self.assertEqual(acknowledged.continuation_id, prepared.continuation_id)
        self.assertEqual(acknowledged.state, ContinuationState.ACKNOWLEDGED)
        self.assertEqual(harness.store.snapshot().continuation_count, 1)

    def test_identical_acknowledged_replay_is_empty(self) -> None:
        harness = CollaborationHarness()
        mission = make_mission()
        result = harness.run(
            mission,
            RecordingExecutor(),
            DeterministicTransport(),
            make_readback(mission),
        )
        before = harness.store.snapshot()
        replay = harness.store.replay_acknowledged(result.continuation)
        self.assertEqual(
            (replay.effects, replay.continuations, replay.acknowledgements),
            ((), (), ()),
        )
        self.assertEqual(harness.store.snapshot(), before)

    def test_changed_replay_identity_is_conflict(self) -> None:
        harness = CollaborationHarness()
        mission = make_mission()
        result = harness.run(
            mission,
            RecordingExecutor(),
            DeterministicTransport(),
            make_readback(mission),
        )
        changed = replace(
            result.continuation,
            destination=Destination("coordinator.public", "thread.changed"),
        )
        self.assert_code(
            FailureCode.REPLAY_IDENTITY_CONFLICT,
            lambda: harness.store.replay_acknowledged(changed),
        )

    def test_acknowledgement_count_is_exactly_one(self) -> None:
        harness = CollaborationHarness()
        mission = make_mission()
        result = harness.run(
            mission,
            RecordingExecutor(),
            DeterministicTransport(),
            make_readback(mission),
        )
        ack = result.acknowledgement
        self.assertEqual(harness.store.snapshot().acknowledgement_count, 1)
        self.assertEqual(
            len({ack.callback_ack_id, ack.receipt_ack_id, ack.continuation_ack_id}), 3
        )
        harness.store.replay_acknowledged(result.continuation)
        self.assertEqual(harness.store.snapshot().acknowledgement_count, 1)

    def test_terminal_outcome_returns_to_parent_mission_verification(self) -> None:
        mission = Mission(
            "mission.return",
            1,
            "delivery",
            (
                ExitPredicate("ready", True),
                ExitPredicate("current", False),
                ExitPredicate("next", False),
            ),
            (make_route("current", route_id="route.current"),),
            DESTINATION,
        )
        result = CollaborationHarness().run(
            mission,
            RecordingExecutor(),
            DeterministicTransport(),
            make_readback(mission, predicate_key="current"),
        )
        self.assertEqual(result.verification.predicate_key, "current")
        self.assertEqual(result.verification.next_predicate_key, "next")
        self.assertEqual(
            result.verification.next_action, MissionNextAction.ROUTE_SELECTION
        )


class ParentReadbackAndFailureRecoveryTests(HarnessTestCase):
    def test_false_parent_readback_cannot_complete_worker_claim(self) -> None:
        mission = make_mission()
        result = CollaborationHarness().run(
            mission,
            RecordingExecutor(predicate_satisfied=True),
            DeterministicTransport(),
            make_readback(mission, satisfied=False),
        )
        self.assertTrue(result.receipt.predicate_satisfied)
        self.assertFalse(result.verification.predicate_satisfied)
        self.assertEqual(
            result.verification.next_action, MissionNextAction.ROUTE_SELECTION
        )
        self.assertEqual(result.verification.next_predicate_key, "result_materialized")

    def test_true_parent_readback_completes_despite_false_worker_claim(self) -> None:
        mission = make_mission()
        result = CollaborationHarness().run(
            mission,
            RecordingExecutor(predicate_satisfied=False),
            DeterministicTransport(),
            make_readback(mission, satisfied=True),
        )
        self.assertFalse(result.receipt.predicate_satisfied)
        self.assertTrue(result.verification.predicate_satisfied)
        self.assertEqual(
            result.verification.next_action, MissionNextAction.MISSION_COMPLETE
        )

    def test_mismatched_parent_readback_is_rejected(self) -> None:
        harness = CollaborationHarness()
        _, _, receipt = self.terminalize(harness)
        _, _, _, acknowledgement = harness.continue_and_ack(
            receipt, DeterministicTransport()
        )
        wrong = MissionReadback(
            "mission.other",
            1,
            "result_materialized",
            True,
            canonical_sha256({"owner": "parent", "wrong": True}),
        )
        self.assert_code(
            FailureCode.STALE_IDENTITY,
            lambda: harness.verify_mission(acknowledgement, wrong),
        )
        self.assertEqual(harness.store.snapshot().verification_count, 0)

    def test_executor_exception_requires_explicit_no_effect_reconciliation(
        self,
    ) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission())
        lease = harness.claim(packet)
        executor = RaisingExecutor()

        self.assert_code(
            FailureCode.EXECUTOR_ERROR,
            lambda: harness.execute(packet, lease, executor),
        )
        failure = harness.store.failure_for_packet(packet.packet_id)
        self.assertIsNotNone(failure)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)
        self.assertEqual(harness.store.snapshot().terminal_receipt_count, 0)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, executor),
        )
        self.assertEqual(executor.calls, 1)

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
                output_digest=canonical_sha256({"terminal": "executor_failed"}),
            ),
        )
        self.assertEqual(receipt.status, TerminalStatus.FAILED)
        self.assertEqual(receipt.effect_state, EffectState.NONE)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)

    def test_mismatched_result_reconciles_observed_effect_without_rerun(self) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission())
        lease = harness.claim(packet)
        executor = MismatchedResultExecutor(effect_id="effect.mismatch.1")

        self.assert_code(
            FailureCode.STALE_IDENTITY,
            lambda: harness.execute(packet, lease, executor),
        )
        failure = harness.store.failure_for_packet(packet.packet_id)
        self.assertEqual(failure.observed_effect_id, executor.effect_id)
        self.assertEqual(executor.calls, 1)
        self.assert_code(
            FailureCode.DUPLICATE_OR_REPLAY,
            lambda: harness.execute(packet, lease, executor),
        )
        self.assertEqual(executor.calls, 1)

        receipt = harness.reconcile_failure(
            packet,
            lease,
            FailureReconciliation(
                packet_id=packet.packet_id,
                lease_id=lease.lease_id,
                failure_code=FailureCode.STALE_IDENTITY,
                effect_state=EffectState.SETTLED,
                effect_id=executor.effect_id,
                proof_digest=canonical_sha256(
                    {"effect_id": executor.effect_id, "settled": True}
                ),
                output_digest=canonical_sha256({"terminal": "identity_mismatch"}),
            ),
        )
        self.assertEqual(receipt.effect_state, EffectState.SETTLED)
        self.assertEqual(receipt.effect_id, executor.effect_id)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assertEqual(harness.store.snapshot().effect_count, 1)

    def test_revision_drift_closes_exact_pre_execution_lease(self) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission(revision=1))
        lease = harness.claim(packet)
        harness.store.register_mission(make_mission(revision=2))
        executor = RecordingExecutor()

        receipt = harness.execute(packet, lease, executor)

        self.assertEqual(executor.calls, 0)
        self.assertEqual(receipt.status, TerminalStatus.BLOCKED)
        self.assertEqual(receipt.failure_code, FailureCode.STALE_IDENTITY)
        self.assertEqual(receipt.effect_state, EffectState.NONE)
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)


class IdentityAndOwnershipTests(HarnessTestCase):
    def test_concurrent_overlapping_claim_has_one_winner(self) -> None:
        barrier = Barrier(3)
        harness = CollaborationHarness(BarrierStore(barrier))
        first = harness.plan(make_mission(mission_id="mission.concurrent.first"))
        second = harness.plan(make_mission(mission_id="mission.concurrent.second"))

        def attempt(packet):
            try:
                return ("lease", harness.claim(packet))
            except HarnessViolation as error:
                return ("error", error.code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, first), pool.submit(attempt, second)]
            barrier.wait(timeout=5)
            outcomes = [future.result(timeout=5) for future in futures]

        self.assertEqual(sum(kind == "lease" for kind, _ in outcomes), 1)
        self.assertEqual(
            [value for kind, value in outcomes if kind == "error"],
            [FailureCode.LEASE_CONFLICT],
        )
        self.assertEqual(harness.store.snapshot().active_lease_count, 1)

    def test_stale_mission_identity_is_rejected_before_claim(self) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission(revision=1))
        harness.store.register_mission(make_mission(revision=2))
        self.assert_code(FailureCode.STALE_IDENTITY, lambda: harness.claim(packet))
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)

    def test_duplicate_dispatch_is_rejected(self) -> None:
        harness = CollaborationHarness()
        packet = harness.plan(make_mission())
        harness.claim(packet)
        self.assert_code(FailureCode.DUPLICATE_OR_REPLAY, lambda: harness.claim(packet))

    def test_stale_cas_snapshot_is_rejected_after_prior_terminalization(self) -> None:
        harness = CollaborationHarness()
        first = harness.plan(make_mission(mission_id="mission.cas.first"))
        stale = harness.plan(make_mission(mission_id="mission.cas.second"))
        lease = harness.claim(first)
        harness.execute(first, lease, RecordingExecutor())
        self.assertEqual(harness.store.snapshot().active_lease_count, 0)
        self.assert_code(FailureCode.CAS_MISMATCH, lambda: harness.claim(stale))

    def test_missing_convergence_proof_never_acknowledges(self) -> None:
        harness = CollaborationHarness()
        _, _, receipt = self.terminalize(harness)
        self.assert_code(
            FailureCode.CONVERGENCE_NOT_PROVEN,
            lambda: harness.continue_and_ack(
                receipt, DeterministicTransport(completed=False)
            ),
        )
        self.assertEqual(harness.store.snapshot().acknowledgement_count, 0)


if __name__ == "__main__":
    unittest.main()
