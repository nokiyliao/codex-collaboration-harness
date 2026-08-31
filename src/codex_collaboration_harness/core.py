# SPDX-License-Identifier: MIT
"""Deterministic reference core for a bounded collaboration cycle.

The module deliberately models identities and state transitions, not providers,
networks, persistence engines, or domain-specific work.  Every public record is
immutable and every generated identity is derived from canonical public data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from functools import wraps
from hashlib import sha256
from threading import RLock
from typing import Any, Protocol


class EffectState(str, Enum):
    """Whether an executor effect is safe to terminalize."""

    NONE = "none"
    SETTLED = "settled"
    UNSETTLED = "unsettled"


class ContinuationState(str, Enum):
    """Durable ordering for a destination-bound continuation."""

    PREPARED = "prepared"
    COMMITTED = "committed"
    ACKNOWLEDGED = "acknowledged"


class TerminalStatus(str, Enum):
    """Terminal task outcome, independent from callback delivery."""

    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"


class MissionNextAction(str, Enum):
    """Where control returns after a terminal child cycle."""

    ROUTE_SELECTION = "route_selection"
    MISSION_COMPLETE = "mission_complete"


class FailureCode(str, Enum):
    """Typed fail-closed outcomes exposed by the reference harness."""

    STALE_IDENTITY = "STALE_IDENTITY"
    DUPLICATE_OR_REPLAY = "DUPLICATE_OR_REPLAY"
    UNSETTLED_EFFECT = "UNSETTLED_EFFECT"
    LEASE_CONFLICT = "LEASE_CONFLICT"
    CAS_MISMATCH = "CAS_MISMATCH"
    CALLBACK_TARGET_MISMATCH = "CALLBACK_TARGET_MISMATCH"
    CONVERGENCE_NOT_PROVEN = "CONVERGENCE_NOT_PROVEN"
    REPLAY_IDENTITY_CONFLICT = "REPLAY_IDENTITY_CONFLICT"
    EXECUTOR_ERROR = "EXECUTOR_ERROR"
    MISSION_COMPLETE = "MISSION_COMPLETE"
    NO_ROUTE = "NO_ROUTE"


class HarnessViolation(RuntimeError):
    """A deterministic rejection with a stable machine-readable code."""

    def __init__(self, code: FailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


def _atomic(method: Any) -> Any:
    """Run one store operation under its single re-entrant state lock."""

    @wraps(method)
    def locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _canonical(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of canonical, compact UTF-8 JSON."""

    encoded = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{canonical_sha256(value)}"


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Destination:
    """Exact coordinator and thread that must receive the continuation."""

    coordinator_id: str
    thread_id: str

    def __post_init__(self) -> None:
        _require_text("coordinator_id", self.coordinator_id)
        _require_text("thread_id", self.thread_id)


@dataclass(frozen=True, slots=True)
class ExitPredicate:
    key: str
    satisfied: bool = False

    def __post_init__(self) -> None:
        _require_text("predicate key", self.key)


@dataclass(frozen=True, slots=True)
class Route:
    """One bounded route for exactly one mission predicate."""

    route_id: str
    predicate_key: str
    executor_id: str
    scope: tuple[str, ...]
    expected_delta: str
    abandon_if: str
    rank: int = 0

    def __post_init__(self) -> None:
        for name in (
            "route_id",
            "predicate_key",
            "executor_id",
            "expected_delta",
            "abandon_if",
        ):
            _require_text(name, getattr(self, name))
        if not self.scope:
            raise ValueError("scope must contain at least one item")
        if self.scope != tuple(sorted(set(self.scope))):
            raise ValueError("scope must be sorted and contain unique items")
        if self.rank < 0:
            raise ValueError("rank must be non-negative")


@dataclass(frozen=True, slots=True)
class Mission:
    """The parent-owned ordered predicates and candidate routes."""

    mission_id: str
    revision: int
    mode: str
    predicates: tuple[ExitPredicate, ...]
    routes: tuple[Route, ...]
    destination: Destination

    def __post_init__(self) -> None:
        _require_text("mission_id", self.mission_id)
        _require_text("mode", self.mode)
        if self.revision < 1:
            raise ValueError("revision must be at least 1")
        if not self.predicates:
            raise ValueError("mission must contain at least one predicate")
        predicate_keys = tuple(item.key for item in self.predicates)
        if len(predicate_keys) != len(set(predicate_keys)):
            raise ValueError("predicate keys must be unique")
        route_ids = tuple(item.route_id for item in self.routes)
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("route ids must be unique")
        unknown = {item.predicate_key for item in self.routes} - set(predicate_keys)
        if unknown:
            raise ValueError(f"routes reference unknown predicates: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class TaskPacket:
    """Content-addressed decision and bounded dispatch packet."""

    mission_id: str
    mission_revision: int
    mission_mode: str
    predicate_key: str
    route_id: str
    executor_id: str
    scope: tuple[str, ...]
    scope_versions: tuple[tuple[str, int], ...]
    expected_delta: str
    abandon_if: str
    destination: Destination
    packet_id: str = field(init=False)

    def __post_init__(self) -> None:
        payload = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "packet_id"
        }
        object.__setattr__(self, "packet_id", _stable_id("packet", payload))


@dataclass(frozen=True, slots=True)
class Lease:
    """Exclusive scope ownership acquired through compare-and-swap."""

    lease_id: str
    packet_id: str
    scope: tuple[str, ...]
    scope_versions: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Executor-supplied result bound to the admitted packet and lease."""

    executor_id: str
    packet_id: str
    lease_id: str
    effect_id: str
    effect_state: EffectState
    output_digest: str
    predicate_satisfied: bool

    def __post_init__(self) -> None:
        for name in (
            "executor_id",
            "packet_id",
            "lease_id",
            "effect_id",
            "output_digest",
        ):
            _require_text(name, getattr(self, name))
        if self.effect_state is EffectState.NONE:
            raise ValueError(
                "executor results must declare settled or unsettled effect state"
            )


@dataclass(frozen=True, slots=True)
class EffectReconciliation:
    """Settlement proof for the already-recorded effect of one attempt."""

    packet_id: str
    lease_id: str
    effect_id: str
    effect_state: EffectState
    settlement_proof_digest: str

    def __post_init__(self) -> None:
        for name in (
            "packet_id",
            "lease_id",
            "effect_id",
            "settlement_proof_digest",
        ):
            _require_text(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    """A begun attempt that needs explicit effect reconciliation."""

    failure_id: str
    packet_id: str
    lease_id: str
    failure_code: FailureCode
    detail_digest: str
    observed_effect_id: str | None


@dataclass(frozen=True, slots=True)
class FailureReconciliation:
    """Explicit proof that a failed attempt had no effect or a settled effect."""

    packet_id: str
    lease_id: str
    failure_code: FailureCode
    effect_state: EffectState
    effect_id: str | None
    proof_digest: str
    output_digest: str

    def __post_init__(self) -> None:
        for name in ("packet_id", "lease_id", "proof_digest", "output_digest"):
            _require_text(name, getattr(self, name))
        if self.effect_state not in (EffectState.NONE, EffectState.SETTLED):
            raise ValueError("failure reconciliation must prove NONE or SETTLED")
        if self.effect_state is EffectState.SETTLED and not self.effect_id:
            raise ValueError("a settled failure reconciliation requires effect_id")
        if self.effect_state is EffectState.NONE and self.effect_id is not None:
            raise ValueError("a no-effect reconciliation cannot carry effect_id")


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    """Store-authored terminal identity after effect reconciliation."""

    receipt_id: str
    mission_id: str
    mission_revision: int
    packet_id: str
    lease_id: str
    executor_id: str
    status: TerminalStatus
    effect_id: str | None
    effect_state: EffectState
    output_digest: str
    settlement_proof_digest: str | None
    predicate_satisfied: bool
    failure_code: FailureCode | None


@dataclass(frozen=True, slots=True)
class Continuation:
    """Destination-bound callback state derived from one terminal receipt."""

    continuation_id: str
    receipt_id: str
    destination: Destination
    state: ContinuationState


@dataclass(frozen=True, slots=True)
class ResumeProof:
    """Proof that the exact destination was resumed."""

    continuation_id: str
    destination: Destination
    resume_token: str


@dataclass(frozen=True, slots=True)
class ConvergenceProof:
    """Proof that the exact completed turn appeared at the destination."""

    continuation_id: str
    receipt_id: str
    destination: Destination
    completed_turn_id: str
    completed: bool


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """Three identities sequenced atomically after convergence."""

    acknowledgement_id: str
    packet_id: str
    receipt_id: str
    continuation_id: str
    callback_ack_id: str
    receipt_ack_id: str
    continuation_ack_id: str


@dataclass(frozen=True, slots=True)
class MissionVerification:
    """Parent mission readback after acknowledgement."""

    verification_id: str
    mission_id: str
    mission_revision: int
    predicate_key: str
    predicate_satisfied: bool
    next_predicate_key: str | None
    next_action: MissionNextAction
    acknowledgement_id: str


@dataclass(frozen=True, slots=True)
class MissionReadback:
    """Parent-owned current-state evidence for exactly one mission predicate."""

    mission_id: str
    mission_revision: int
    predicate_key: str
    satisfied: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "predicate_key", "evidence_digest"):
            _require_text(name, getattr(self, name))
        if self.mission_revision < 1:
            raise ValueError("mission_revision must be at least 1")


@dataclass(frozen=True, slots=True)
class CycleResult:
    """Complete evidence chain for one successful bounded cycle."""

    packet: TaskPacket
    lease: Lease
    receipt: TerminalReceipt
    continuation: Continuation
    resume_proof: ResumeProof
    convergence_proof: ConvergenceProof
    acknowledgement: Acknowledgement
    verification: MissionVerification


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """An acknowledged replay is deliberately empty."""

    packet_id: str
    effects: tuple[str, ...] = ()
    continuations: tuple[str, ...] = ()
    acknowledgements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoreSnapshot:
    mission_count: int
    active_lease_count: int
    execution_attempt_count: int
    effect_count: int
    terminal_receipt_count: int
    continuation_count: int
    acknowledgement_count: int
    verification_count: int


class Executor(Protocol):
    """One-shot work implementation selected by a route."""

    executor_id: str

    def execute(self, packet: TaskPacket, lease: Lease) -> ExecutionResult:
        """Perform one bounded attempt and return its exact identities."""


class ContinuationTransport(Protocol):
    """Guided continuation transport; it never owns mission verification."""

    def resume(self, continuation: Continuation) -> ResumeProof:
        """Resume the exact destination before a new turn is started."""

    def start_turn(
        self,
        continuation: Continuation,
        resume_proof: ResumeProof,
        receipt: TerminalReceipt,
    ) -> ConvergenceProof:
        """Start and prove the exact completed destination turn."""


class InMemoryStore:
    """Deterministic reference store with lease, CAS, replay, and ACK rules."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._missions: dict[str, Mission] = {}
        self._scope_versions: dict[str, int] = {}
        self._active_leases: dict[str, Lease] = {}
        self._leases_by_packet: dict[str, Lease] = {}
        self._packets: dict[str, TaskPacket] = {}
        self._execution_started: set[str] = set()
        self._attempts: dict[str, ExecutionResult] = {}
        self._execution_failures: dict[str, ExecutionFailure] = {}
        self._effect_owner: dict[str, str] = {}
        self._receipts: dict[str, TerminalReceipt] = {}
        self._receipt_by_packet: dict[str, TerminalReceipt] = {}
        self._continuations: dict[str, Continuation] = {}
        self._continuation_by_receipt: dict[str, str] = {}
        self._acknowledgements: dict[str, Acknowledgement] = {}
        self._ack_by_packet: dict[str, Acknowledgement] = {}
        self._verifications: dict[str, MissionVerification] = {}
        self._verified_predicates: set[tuple[str, int, str]] = set()

    @_atomic
    def register_mission(self, mission: Mission) -> None:
        current = self._missions.get(mission.mission_id)
        if current is None:
            self._missions[mission.mission_id] = mission
            return
        if mission == current:
            return
        if mission.revision <= current.revision:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                f"mission {mission.mission_id!r} is not newer than revision {current.revision}",
            )
        self._missions[mission.mission_id] = mission

    @_atomic
    def scope_snapshot(self, scope: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
        return tuple((item, self._scope_versions.get(item, 0)) for item in scope)

    @_atomic
    def first_false(self, mission: Mission) -> ExitPredicate | None:
        for predicate in mission.predicates:
            verified = (mission.mission_id, mission.revision, predicate.key)
            if not predicate.satisfied and verified not in self._verified_predicates:
                return predicate
        return None

    def _validate_packet(self, packet: TaskPacket) -> Mission:
        mission = self._missions.get(packet.mission_id)
        if mission is None or mission.revision != packet.mission_revision:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                f"packet {packet.packet_id} does not match the authoritative mission revision",
            )
        predicate = self.first_false(mission)
        if predicate is None or predicate.key != packet.predicate_key:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "packet no longer targets the first false predicate",
            )
        route = next(
            (item for item in mission.routes if item.route_id == packet.route_id), None
        )
        expected = None
        if route is not None:
            expected = (
                route.predicate_key,
                route.executor_id,
                route.scope,
                route.expected_delta,
                route.abandon_if,
            )
        actual = (
            packet.predicate_key,
            packet.executor_id,
            packet.scope,
            packet.expected_delta,
            packet.abandon_if,
        )
        if (
            packet.mission_mode != mission.mode
            or packet.destination != mission.destination
            or expected != actual
        ):
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "packet fields do not match the authoritative route",
            )
        return mission

    @_atomic
    def claim(self, packet: TaskPacket) -> Lease:
        self._validate_packet(packet)
        if packet.packet_id in self._leases_by_packet:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"packet {packet.packet_id} was already claimed",
            )
        requested = set(packet.scope)
        for lease in self._active_leases.values():
            overlap = sorted(requested.intersection(lease.scope))
            if overlap:
                raise HarnessViolation(
                    FailureCode.LEASE_CONFLICT,
                    f"scope already leased: {overlap}",
                )
        current_versions = self.scope_snapshot(packet.scope)
        if current_versions != packet.scope_versions:
            raise HarnessViolation(
                FailureCode.CAS_MISMATCH,
                f"scope version changed from {packet.scope_versions} to {current_versions}",
            )
        claimed_versions = tuple(
            (item, version + 1) for item, version in current_versions
        )
        for item, version in claimed_versions:
            self._scope_versions[item] = version
        lease_id = _stable_id(
            "lease",
            {
                "packet_id": packet.packet_id,
                "scope_versions": claimed_versions,
            },
        )
        lease = Lease(lease_id, packet.packet_id, packet.scope, claimed_versions)
        self._packets[packet.packet_id] = packet
        self._active_leases[lease_id] = lease
        self._leases_by_packet[packet.packet_id] = lease
        return lease

    def _validate_active_claim(
        self, packet: TaskPacket, lease: Lease, *, current_mission_required: bool = True
    ) -> None:
        if current_mission_required:
            self._validate_packet(packet)
        stored = self._active_leases.get(lease.lease_id)
        if (
            stored != lease
            or self._packets.get(packet.packet_id) != packet
            or self._leases_by_packet.get(packet.packet_id) != lease
            or lease.packet_id != packet.packet_id
        ):
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "execution does not hold the active lease for this packet",
            )

    @_atomic
    def begin_execution(self, packet: TaskPacket, lease: Lease) -> None:
        if (
            packet.packet_id in self._execution_started
            or packet.packet_id in self._receipt_by_packet
        ):
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"packet {packet.packet_id} already has an execution attempt",
            )
        self._validate_active_claim(packet, lease)
        self._execution_started.add(packet.packet_id)

    def _persist_terminal(
        self,
        packet: TaskPacket,
        lease: Lease,
        *,
        status: TerminalStatus,
        effect_id: str | None,
        effect_state: EffectState,
        output_digest: str,
        settlement_proof_digest: str | None,
        predicate_satisfied: bool,
        failure_code: FailureCode | None,
    ) -> TerminalReceipt:
        if packet.packet_id in self._receipt_by_packet:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"packet {packet.packet_id} already has a terminal receipt",
            )
        self._validate_active_claim(packet, lease, current_mission_required=False)
        receipt_payload = {
            "mission_id": packet.mission_id,
            "mission_revision": packet.mission_revision,
            "packet_id": packet.packet_id,
            "lease_id": lease.lease_id,
            "executor_id": packet.executor_id,
            "status": status,
            "effect_id": effect_id,
            "effect_state": effect_state,
            "output_digest": output_digest,
            "settlement_proof_digest": settlement_proof_digest,
            "predicate_satisfied": predicate_satisfied,
            "failure_code": failure_code,
        }
        receipt = TerminalReceipt(
            receipt_id=_stable_id("receipt", receipt_payload), **receipt_payload
        )
        self._receipts[receipt.receipt_id] = receipt
        self._receipt_by_packet[packet.packet_id] = receipt
        self._active_leases.pop(lease.lease_id)
        return receipt

    @_atomic
    def terminalize_pre_execution(
        self,
        packet: TaskPacket,
        lease: Lease,
        code: FailureCode,
        detail: str,
    ) -> TerminalReceipt:
        """Persist a typed blocker without inventing an executor result."""

        if packet.packet_id in self._execution_started:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "execution already started; rejection is no longer pre-execution",
            )
        self._validate_active_claim(packet, lease, current_mission_required=False)
        return self._persist_terminal(
            packet,
            lease,
            status=TerminalStatus.BLOCKED,
            effect_id=None,
            effect_state=EffectState.NONE,
            output_digest=canonical_sha256(
                {"failure_code": code, "detail": detail, "phase": "pre_execution"}
            ),
            settlement_proof_digest=None,
            predicate_satisfied=False,
            failure_code=code,
        )

    @_atomic
    def record_execution_failure(
        self,
        packet: TaskPacket,
        lease: Lease,
        code: FailureCode,
        detail: str,
        *,
        observed_effect_id: str | None = None,
    ) -> ExecutionFailure:
        """Record effect uncertainty without guessing that no effect occurred."""

        self._validate_active_claim(packet, lease, current_mission_required=False)
        if packet.packet_id not in self._execution_started:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY, "executor attempt was never started"
            )
        if (
            packet.packet_id in self._execution_failures
            or packet.packet_id in self._receipt_by_packet
        ):
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "execution failure was already recorded or terminalized",
            )
        detail_digest = canonical_sha256(
            {
                "failure_code": code,
                "detail": detail,
                "observed_effect_id": observed_effect_id,
            }
        )
        payload = {
            "packet_id": packet.packet_id,
            "lease_id": lease.lease_id,
            "failure_code": code,
            "detail_digest": detail_digest,
            "observed_effect_id": observed_effect_id,
        }
        failure = ExecutionFailure(
            failure_id=_stable_id("execution_failure", payload), **payload
        )
        self._execution_failures[packet.packet_id] = failure
        if (
            observed_effect_id is not None
            and observed_effect_id not in self._effect_owner
        ):
            self._effect_owner[observed_effect_id] = packet.packet_id
        return failure

    @_atomic
    def failure_for_packet(self, packet_id: str) -> ExecutionFailure | None:
        return self._execution_failures.get(packet_id)

    @_atomic
    def reconcile_failure(
        self,
        packet: TaskPacket,
        lease: Lease,
        reconciliation: FailureReconciliation,
    ) -> TerminalReceipt:
        """Terminalize one failed attempt only from explicit effect proof."""

        failure = self._execution_failures.get(packet.packet_id)
        if failure is None or packet.packet_id in self._receipt_by_packet:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "packet has no unresolved execution failure",
            )
        self._validate_active_claim(packet, lease, current_mission_required=False)
        if (
            reconciliation.packet_id != packet.packet_id
            or reconciliation.lease_id != lease.lease_id
            or reconciliation.failure_code is not failure.failure_code
        ):
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "failure reconciliation does not bind the recorded failure",
            )
        if reconciliation.effect_state is EffectState.SETTLED:
            if (
                failure.observed_effect_id is not None
                and reconciliation.effect_id != failure.observed_effect_id
            ):
                raise HarnessViolation(
                    FailureCode.STALE_IDENTITY,
                    "settled effect differs from the executor-observed effect",
                )
            owner = self._effect_owner.get(reconciliation.effect_id or "")
            if owner is not None and owner != packet.packet_id:
                raise HarnessViolation(
                    FailureCode.DUPLICATE_OR_REPLAY,
                    f"effect is already owned by packet {owner}",
                )
            self._effect_owner[reconciliation.effect_id or ""] = packet.packet_id
        elif (
            failure.observed_effect_id is not None
            and self._effect_owner.get(failure.observed_effect_id) == packet.packet_id
        ):
            self._effect_owner.pop(failure.observed_effect_id)
        return self._persist_terminal(
            packet,
            lease,
            status=TerminalStatus.FAILED,
            effect_id=reconciliation.effect_id,
            effect_state=reconciliation.effect_state,
            output_digest=reconciliation.output_digest,
            settlement_proof_digest=reconciliation.proof_digest,
            predicate_satisfied=False,
            failure_code=failure.failure_code,
        )

    @_atomic
    def record_execution(
        self, packet: TaskPacket, lease: Lease, result: ExecutionResult
    ) -> TerminalReceipt:
        self._validate_active_claim(packet, lease, current_mission_required=False)
        if packet.packet_id not in self._execution_started:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY, "executor attempt was never started"
            )
        if packet.packet_id in self._attempts:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"packet {packet.packet_id} already returned a result",
            )
        if (
            result.executor_id != packet.executor_id
            or result.packet_id != packet.packet_id
            or result.lease_id != lease.lease_id
        ):
            self.record_execution_failure(
                packet,
                lease,
                FailureCode.STALE_IDENTITY,
                "executor result identity does not match packet, executor, and lease",
                observed_effect_id=result.effect_id,
            )
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "executor result identity does not match packet, executor, and lease",
            )
        owner = self._effect_owner.get(result.effect_id)
        if owner is not None:
            self.record_execution_failure(
                packet,
                lease,
                FailureCode.DUPLICATE_OR_REPLAY,
                f"effect {result.effect_id!r} is already owned by packet {owner}",
                observed_effect_id=result.effect_id,
            )
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"effect {result.effect_id!r} is already owned by packet {owner}",
            )
        self._attempts[packet.packet_id] = result
        self._effect_owner[result.effect_id] = packet.packet_id
        if result.effect_state is not EffectState.SETTLED:
            raise HarnessViolation(
                FailureCode.UNSETTLED_EFFECT,
                f"effect {result.effect_id!r} has no settlement proof",
            )
        return self._persist_terminal(
            packet,
            lease,
            status=TerminalStatus.SUCCEEDED,
            effect_id=result.effect_id,
            effect_state=result.effect_state,
            output_digest=result.output_digest,
            settlement_proof_digest=result.output_digest,
            predicate_satisfied=result.predicate_satisfied,
            failure_code=None,
        )

    @_atomic
    def reconcile_effect(
        self,
        packet: TaskPacket,
        lease: Lease,
        reconciliation: EffectReconciliation,
    ) -> TerminalReceipt:
        """Settle the recorded attempt without invoking its executor again."""

        result = self._attempts.get(packet.packet_id)
        if result is None or result.effect_state is not EffectState.UNSETTLED:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "packet has no unsettled recorded effect to reconcile",
            )
        self._validate_active_claim(packet, lease, current_mission_required=False)
        if (
            reconciliation.packet_id != packet.packet_id
            or reconciliation.lease_id != lease.lease_id
            or reconciliation.effect_id != result.effect_id
        ):
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "reconciliation does not match the recorded attempt and effect",
            )
        if reconciliation.effect_state is not EffectState.SETTLED:
            raise HarnessViolation(
                FailureCode.UNSETTLED_EFFECT,
                f"effect {result.effect_id!r} remains unsettled",
            )
        settled = replace(result, effect_state=EffectState.SETTLED)
        self._attempts[packet.packet_id] = settled
        return self._persist_terminal(
            packet,
            lease,
            status=TerminalStatus.SUCCEEDED,
            effect_id=settled.effect_id,
            effect_state=settled.effect_state,
            output_digest=settled.output_digest,
            settlement_proof_digest=reconciliation.settlement_proof_digest,
            predicate_satisfied=settled.predicate_satisfied,
            failure_code=None,
        )

    @_atomic
    def terminal_receipt_for_packet(self, packet_id: str) -> TerminalReceipt | None:
        return self._receipt_by_packet.get(packet_id)

    @_atomic
    def prepare_continuation(self, receipt: TerminalReceipt) -> Continuation:
        if self._receipts.get(receipt.receipt_id) != receipt:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY, "terminal receipt is not authoritative"
            )
        existing_id = self._continuation_by_receipt.get(receipt.receipt_id)
        if existing_id is not None:
            existing = self._continuations[existing_id]
            if existing.state is ContinuationState.PREPARED:
                return existing
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                f"receipt {receipt.receipt_id} already has a committed continuation",
            )
        packet = self._packets[receipt.packet_id]
        continuation_id = _stable_id(
            "continuation",
            {"receipt_id": receipt.receipt_id, "destination": packet.destination},
        )
        continuation = Continuation(
            continuation_id,
            receipt.receipt_id,
            packet.destination,
            ContinuationState.PREPARED,
        )
        self._continuations[continuation_id] = continuation
        self._continuation_by_receipt[receipt.receipt_id] = continuation_id
        return continuation

    @_atomic
    def continuation_for_receipt(self, receipt_id: str) -> Continuation | None:
        continuation_id = self._continuation_by_receipt.get(receipt_id)
        if continuation_id is None:
            return None
        return self._continuations[continuation_id]

    @_atomic
    def validate_prepared_continuation(
        self, continuation: Continuation, receipt: TerminalReceipt
    ) -> None:
        current = self._continuations.get(continuation.continuation_id)
        if (
            current != continuation
            or current.state is not ContinuationState.PREPARED
            or continuation.receipt_id != receipt.receipt_id
            or self._receipts.get(receipt.receipt_id) != receipt
        ):
            raise HarnessViolation(
                FailureCode.REPLAY_IDENTITY_CONFLICT,
                "continuation, receipt, or prepared state identity changed",
            )

    @_atomic
    def validate_resume(
        self, continuation: Continuation, proof: ResumeProof
    ) -> Continuation:
        current = self._continuations.get(continuation.continuation_id)
        if current != continuation or current.state is not ContinuationState.PREPARED:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "continuation is not the current prepared identity",
            )
        if (
            proof.continuation_id != continuation.continuation_id
            or proof.destination != continuation.destination
        ):
            raise HarnessViolation(
                FailureCode.CALLBACK_TARGET_MISMATCH,
                "resume proof does not bind the requested destination",
            )
        _require_text("resume_token", proof.resume_token)
        return continuation

    @_atomic
    def acknowledge_after_convergence(
        self,
        continuation: Continuation,
        receipt: TerminalReceipt,
        proof: ConvergenceProof,
    ) -> tuple[Continuation, Acknowledgement]:
        current = self._continuations.get(continuation.continuation_id)
        if current != continuation or current.state is not ContinuationState.PREPARED:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "continuation is not in the prepared state",
            )
        if (
            continuation.receipt_id != receipt.receipt_id
            or proof.continuation_id != continuation.continuation_id
            or proof.receipt_id != receipt.receipt_id
            or proof.destination != continuation.destination
        ):
            raise HarnessViolation(
                FailureCode.CALLBACK_TARGET_MISMATCH,
                "completed turn proof does not bind receipt and destination",
            )
        if not proof.completed or not proof.completed_turn_id.strip():
            raise HarnessViolation(
                FailureCode.CONVERGENCE_NOT_PROVEN,
                "destination has no exact completed turn proof",
            )
        committed = replace(continuation, state=ContinuationState.COMMITTED)
        self._continuations[continuation.continuation_id] = committed
        ack_base = {
            "packet_id": receipt.packet_id,
            "receipt_id": receipt.receipt_id,
            "continuation_id": continuation.continuation_id,
            "completed_turn_id": proof.completed_turn_id,
        }
        ack = Acknowledgement(
            acknowledgement_id=_stable_id("ack", ack_base),
            packet_id=receipt.packet_id,
            receipt_id=receipt.receipt_id,
            continuation_id=continuation.continuation_id,
            callback_ack_id=_stable_id("callback_ack", ack_base),
            receipt_ack_id=_stable_id("receipt_ack", ack_base),
            continuation_ack_id=_stable_id("continuation_ack", ack_base),
        )
        acknowledged = replace(committed, state=ContinuationState.ACKNOWLEDGED)
        self._continuations[continuation.continuation_id] = acknowledged
        self._acknowledgements[ack.acknowledgement_id] = ack
        self._ack_by_packet[receipt.packet_id] = ack
        return acknowledged, ack

    @_atomic
    def verify_mission(
        self, ack: Acknowledgement, readback: MissionReadback
    ) -> MissionVerification:
        if self._acknowledgements.get(ack.acknowledgement_id) != ack:
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY, "acknowledgement is not authoritative"
            )
        if ack.acknowledgement_id in self._verifications:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "acknowledgement has already returned to mission verification",
            )
        packet = self._packets[ack.packet_id]
        mission = self._missions[packet.mission_id]
        if (
            mission.revision != packet.mission_revision
            or readback.mission_id != packet.mission_id
            or readback.mission_revision != packet.mission_revision
            or readback.predicate_key != packet.predicate_key
        ):
            raise HarnessViolation(
                FailureCode.STALE_IDENTITY,
                "parent readback does not bind the current mission revision and predicate",
            )
        if readback.satisfied:
            self._verified_predicates.add(
                (mission.mission_id, mission.revision, packet.predicate_key)
            )
        next_predicate = self.first_false(mission)
        next_action = (
            MissionNextAction.MISSION_COMPLETE
            if next_predicate is None
            else MissionNextAction.ROUTE_SELECTION
        )
        payload = {
            "mission_id": mission.mission_id,
            "mission_revision": mission.revision,
            "predicate_key": packet.predicate_key,
            "predicate_satisfied": readback.satisfied,
            "next_predicate_key": None
            if next_predicate is None
            else next_predicate.key,
            "next_action": next_action,
            "acknowledgement_id": ack.acknowledgement_id,
            "readback_evidence_digest": readback.evidence_digest,
        }
        identity_payload = dict(payload)
        identity_payload.pop("readback_evidence_digest")
        verification = MissionVerification(
            verification_id=_stable_id("verification", payload), **identity_payload
        )
        self._verifications[ack.acknowledgement_id] = verification
        return verification

    @_atomic
    def replay_acknowledged(self, continuation: Continuation) -> ReplayResult:
        current = self._continuations.get(continuation.continuation_id)
        if current != continuation:
            raise HarnessViolation(
                FailureCode.REPLAY_IDENTITY_CONFLICT,
                "replay changed continuation payload or target identity",
            )
        if continuation.state is not ContinuationState.ACKNOWLEDGED:
            raise HarnessViolation(
                FailureCode.DUPLICATE_OR_REPLAY,
                "only an acknowledged continuation has an empty replay",
            )
        receipt = self._receipts[continuation.receipt_id]
        if receipt.packet_id not in self._ack_by_packet:
            raise HarnessViolation(
                FailureCode.REPLAY_IDENTITY_CONFLICT,
                "acknowledged continuation is not bound to an acknowledgement",
            )
        return ReplayResult(packet_id=receipt.packet_id)

    @_atomic
    def snapshot(self) -> StoreSnapshot:
        return StoreSnapshot(
            mission_count=len(self._missions),
            active_lease_count=len(self._active_leases),
            execution_attempt_count=len(self._execution_started),
            effect_count=len(self._effect_owner),
            terminal_receipt_count=len(self._receipts),
            continuation_count=len(self._continuations),
            acknowledgement_count=len(self._acknowledgements),
            verification_count=len(self._verifications),
        )


class CollaborationHarness:
    """Small orchestrator that keeps every graph edge explicit and testable."""

    def __init__(self, store: InMemoryStore | None = None) -> None:
        self.store = store if store is not None else InMemoryStore()

    def plan(self, mission: Mission) -> TaskPacket:
        self.store.register_mission(mission)
        predicate = self.store.first_false(mission)
        if predicate is None:
            raise HarnessViolation(
                FailureCode.MISSION_COMPLETE,
                f"mission {mission.mission_id!r} is complete",
            )
        routes = sorted(
            (item for item in mission.routes if item.predicate_key == predicate.key),
            key=lambda item: (item.rank, item.route_id),
        )
        if not routes:
            raise HarnessViolation(
                FailureCode.NO_ROUTE,
                f"no route exists for first false predicate {predicate.key!r}",
            )
        route = routes[0]
        return TaskPacket(
            mission_id=mission.mission_id,
            mission_revision=mission.revision,
            mission_mode=mission.mode,
            predicate_key=predicate.key,
            route_id=route.route_id,
            executor_id=route.executor_id,
            scope=route.scope,
            scope_versions=self.store.scope_snapshot(route.scope),
            expected_delta=route.expected_delta,
            abandon_if=route.abandon_if,
            destination=mission.destination,
        )

    def claim(self, packet: TaskPacket) -> Lease:
        return self.store.claim(packet)

    def execute(
        self, packet: TaskPacket, lease: Lease, executor: Executor
    ) -> TerminalReceipt:
        if executor.executor_id != packet.executor_id:
            return self.store.terminalize_pre_execution(
                packet,
                lease,
                FailureCode.STALE_IDENTITY,
                "selected executor does not match the bounded route",
            )
        try:
            self.store.begin_execution(packet, lease)
        except HarnessViolation as error:
            if error.code is FailureCode.STALE_IDENTITY:
                return self.store.terminalize_pre_execution(
                    packet, lease, error.code, error.detail
                )
            raise
        try:
            result = executor.execute(packet, lease)
        except Exception as error:
            self.store.record_execution_failure(
                packet,
                lease,
                FailureCode.EXECUTOR_ERROR,
                f"{type(error).__name__}: {error}",
            )
            raise HarnessViolation(
                FailureCode.EXECUTOR_ERROR,
                "executor failed; explicit effect reconciliation is required",
            ) from error
        return self.store.record_execution(packet, lease, result)

    def reconcile_effect(
        self,
        packet: TaskPacket,
        lease: Lease,
        reconciliation: EffectReconciliation,
    ) -> TerminalReceipt:
        return self.store.reconcile_effect(packet, lease, reconciliation)

    def reconcile_failure(
        self,
        packet: TaskPacket,
        lease: Lease,
        reconciliation: FailureReconciliation,
    ) -> TerminalReceipt:
        return self.store.reconcile_failure(packet, lease, reconciliation)

    def continue_and_ack(
        self, receipt: TerminalReceipt, transport: ContinuationTransport
    ) -> tuple[Continuation, ResumeProof, ConvergenceProof, Acknowledgement]:
        continuation = self.store.prepare_continuation(receipt)
        return self.continue_existing(continuation, receipt, transport)

    def continue_existing(
        self,
        continuation: Continuation,
        receipt: TerminalReceipt,
        transport: ContinuationTransport,
    ) -> tuple[Continuation, ResumeProof, ConvergenceProof, Acknowledgement]:
        """Retry transport over the same prepared identity, never a new callback."""

        self.store.validate_prepared_continuation(continuation, receipt)
        resume_proof = transport.resume(continuation)
        prepared = self.store.validate_resume(continuation, resume_proof)
        convergence_proof = transport.start_turn(prepared, resume_proof, receipt)
        acknowledged, acknowledgement = self.store.acknowledge_after_convergence(
            prepared, receipt, convergence_proof
        )
        return acknowledged, resume_proof, convergence_proof, acknowledgement

    def verify_mission(
        self, acknowledgement: Acknowledgement, readback: MissionReadback
    ) -> MissionVerification:
        return self.store.verify_mission(acknowledgement, readback)

    def run(
        self,
        mission: Mission,
        executor: Executor,
        transport: ContinuationTransport,
        readback: MissionReadback,
    ) -> CycleResult:
        packet = self.plan(mission)
        lease = self.claim(packet)
        receipt = self.execute(packet, lease, executor)
        continuation, resume_proof, convergence_proof, acknowledgement = (
            self.continue_and_ack(receipt, transport)
        )
        verification = self.verify_mission(acknowledgement, readback)
        return CycleResult(
            packet=packet,
            lease=lease,
            receipt=receipt,
            continuation=continuation,
            resume_proof=resume_proof,
            convergence_proof=convergence_proof,
            acknowledgement=acknowledgement,
            verification=verification,
        )
