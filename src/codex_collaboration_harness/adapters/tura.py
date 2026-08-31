# SPDX-License-Identifier: MIT
"""Public, stdlib-only contract for implementing a Tura client adapter.

This module defines an integration boundary only.  It contains no endpoint,
transport, credential, private schema, or Tura implementation code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, TypeAlias

from ..core import (
    Destination,
    EffectState,
    ExecutionFailure,
    ExecutionResult,
    FailureCode,
    Lease,
    TaskPacket,
    canonical_sha256,
)


class TuraTerminalKind(str, Enum):
    """Public terminal-envelope categories understood by the adapter."""

    RESULT = "result"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class TuraDispatchRequest:
    """A flattened, bounded request compiled from a TaskPacket and Lease."""

    packet_id: str
    mission_id: str
    mission_revision: int
    mission_mode: str
    predicate_key: str
    route_id: str
    executor_id: str
    scope: tuple[str, ...]
    expected_scope_versions: tuple[tuple[str, int], ...]
    claimed_scope_versions: tuple[tuple[str, int], ...]
    expected_delta: str
    abandon_if: str
    destination: Destination
    lease_id: str
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        payload = {
            "packet_id": self.packet_id,
            "mission_id": self.mission_id,
            "mission_revision": self.mission_revision,
            "mission_mode": self.mission_mode,
            "predicate_key": self.predicate_key,
            "route_id": self.route_id,
            "executor_id": self.executor_id,
            "scope": self.scope,
            "expected_scope_versions": self.expected_scope_versions,
            "claimed_scope_versions": self.claimed_scope_versions,
            "expected_delta": self.expected_delta,
            "abandon_if": self.abandon_if,
            "destination": self.destination,
            "lease_id": self.lease_id,
        }
        object.__setattr__(
            self, "request_id", f"tura_request_{canonical_sha256(payload)}"
        )


@dataclass(frozen=True, slots=True)
class TuraTerminalEnvelope:
    """Transport-neutral terminal data returned by a third-party Tura client."""

    request_id: str
    packet_id: str
    lease_id: str
    executor_id: str
    kind: TuraTerminalKind
    effect_state: EffectState
    effect_id: str | None
    output_digest: str
    predicate_satisfied: bool
    failure_code: FailureCode | None = None
    failure_detail_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "packet_id",
            "lease_id",
            "executor_id",
            "output_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.kind is TuraTerminalKind.RESULT:
            if self.effect_state is EffectState.NONE or not self.effect_id:
                raise ValueError(
                    "result envelope requires a settled or unsettled effect"
                )
            if self.failure_code is not None or self.failure_detail_digest is not None:
                raise ValueError("result envelope cannot carry failure fields")
        else:
            if self.failure_code is None or not self.failure_detail_digest:
                raise ValueError("failure envelope requires typed failure evidence")
            if self.effect_state is EffectState.NONE and self.effect_id is not None:
                raise ValueError("no-effect failure cannot carry effect_id")
            if self.effect_state is not EffectState.NONE and not self.effect_id:
                raise ValueError("effect-bearing failure requires effect_id")


@dataclass(frozen=True, slots=True)
class TuraTypedRejection:
    """Fail-closed rejection before an envelope can become a core result."""

    code: FailureCode
    mismatched_fields: tuple[str, ...]
    expected_request_id: str
    observed_request_id: str
    detail_digest: str


class TuraClient(Protocol):
    """Contract a third party implements with its chosen Tura transport."""

    def dispatch(self, request: TuraDispatchRequest) -> TuraTerminalEnvelope:
        """Submit one bounded request and return one terminal envelope."""


TuraDispatchOutcome: TypeAlias = ExecutionResult | ExecutionFailure | TuraTypedRejection


class TuraRejectedError(RuntimeError):
    """Executor-facing wrapper for an explicit adapter rejection."""

    def __init__(self, rejection: TuraTypedRejection) -> None:
        self.rejection = rejection
        super().__init__(f"{rejection.code.value}: Tura envelope identity rejected")


class TuraExecutionFailureError(RuntimeError):
    """Executor-facing wrapper retaining the mapped ExecutionFailure."""

    def __init__(self, failure: ExecutionFailure) -> None:
        self.failure = failure
        super().__init__(f"{failure.failure_code.value}: Tura dispatch failed")


def build_tura_dispatch_request(
    packet: TaskPacket, lease: Lease
) -> TuraDispatchRequest:
    """Compile the exact public packet/lease identity into a Tura request."""

    if lease.packet_id != packet.packet_id or lease.scope != packet.scope:
        raise ValueError("lease does not bind the supplied packet and scope")
    claimed = tuple((name, version + 1) for name, version in packet.scope_versions)
    if lease.scope_versions != claimed:
        raise ValueError("lease CAS versions do not follow the packet snapshot")
    return TuraDispatchRequest(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        mission_revision=packet.mission_revision,
        mission_mode=packet.mission_mode,
        predicate_key=packet.predicate_key,
        route_id=packet.route_id,
        executor_id=packet.executor_id,
        scope=packet.scope,
        expected_scope_versions=packet.scope_versions,
        claimed_scope_versions=lease.scope_versions,
        expected_delta=packet.expected_delta,
        abandon_if=packet.abandon_if,
        destination=packet.destination,
        lease_id=lease.lease_id,
    )


def _execution_failure(
    request: TuraDispatchRequest,
    code: FailureCode,
    detail_digest: str,
    observed_effect_id: str | None,
) -> ExecutionFailure:
    payload = {
        "packet_id": request.packet_id,
        "lease_id": request.lease_id,
        "failure_code": code,
        "detail_digest": detail_digest,
        "observed_effect_id": observed_effect_id,
    }
    return ExecutionFailure(
        failure_id=f"execution_failure_{canonical_sha256(payload)}",
        packet_id=request.packet_id,
        lease_id=request.lease_id,
        failure_code=code,
        detail_digest=detail_digest,
        observed_effect_id=observed_effect_id,
    )


class TuraAdapter:
    """Map the public Tura client contract onto collaboration-core records."""

    def __init__(self, client: TuraClient, executor_id: str) -> None:
        if not executor_id.strip():
            raise ValueError("executor_id must be a non-empty string")
        self.client = client
        self.executor_id = executor_id

    def dispatch(self, packet: TaskPacket, lease: Lease) -> TuraDispatchOutcome:
        try:
            request = build_tura_dispatch_request(packet, lease)
        except ValueError as error:
            detail_digest = canonical_sha256(
                {"kind": "request_rejected", "reason": str(error)}
            )
            return TuraTypedRejection(
                code=FailureCode.STALE_IDENTITY,
                mismatched_fields=("packet_or_lease",),
                expected_request_id="unavailable",
                observed_request_id="unavailable",
                detail_digest=detail_digest,
            )
        if request.executor_id != self.executor_id:
            detail_digest = canonical_sha256(
                {
                    "kind": "executor_rejected",
                    "request_executor_id": request.executor_id,
                    "adapter_executor_id": self.executor_id,
                }
            )
            return TuraTypedRejection(
                code=FailureCode.STALE_IDENTITY,
                mismatched_fields=("executor_id",),
                expected_request_id=request.request_id,
                observed_request_id=request.request_id,
                detail_digest=detail_digest,
            )
        try:
            envelope = self.client.dispatch(request)
        except Exception as error:  # noqa: BLE001 - external transport boundary
            detail_digest = canonical_sha256(
                {
                    "kind": "transport_exception",
                    "error_type": type(error).__name__,
                    "message_digest": canonical_sha256(str(error)),
                }
            )
            return _execution_failure(
                request, FailureCode.EXECUTOR_ERROR, detail_digest, None
            )
        if not isinstance(envelope, TuraTerminalEnvelope):
            detail_digest = canonical_sha256(
                {"kind": "invalid_envelope_type", "type": type(envelope).__name__}
            )
            return TuraTypedRejection(
                code=FailureCode.STALE_IDENTITY,
                mismatched_fields=("envelope_type",),
                expected_request_id=request.request_id,
                observed_request_id="unavailable",
                detail_digest=detail_digest,
            )
        expected = {
            "request_id": request.request_id,
            "packet_id": request.packet_id,
            "lease_id": request.lease_id,
            "executor_id": request.executor_id,
        }
        observed = {
            "request_id": envelope.request_id,
            "packet_id": envelope.packet_id,
            "lease_id": envelope.lease_id,
            "executor_id": envelope.executor_id,
        }
        mismatched = tuple(
            name for name in expected if expected[name] != observed[name]
        )
        if mismatched:
            detail_digest = canonical_sha256(
                {"kind": "terminal_identity_mismatch", "fields": mismatched}
            )
            return TuraTypedRejection(
                code=FailureCode.STALE_IDENTITY,
                mismatched_fields=mismatched,
                expected_request_id=request.request_id,
                observed_request_id=envelope.request_id,
                detail_digest=detail_digest,
            )
        if envelope.kind is TuraTerminalKind.FAILURE:
            return _execution_failure(
                request,
                envelope.failure_code or FailureCode.EXECUTOR_ERROR,
                envelope.failure_detail_digest or envelope.output_digest,
                envelope.effect_id,
            )
        return ExecutionResult(
            executor_id=request.executor_id,
            packet_id=request.packet_id,
            lease_id=request.lease_id,
            effect_id=envelope.effect_id or "",
            effect_state=envelope.effect_state,
            output_digest=envelope.output_digest,
            predicate_satisfied=envelope.predicate_satisfied,
        )

    def execute(self, packet: TaskPacket, lease: Lease) -> ExecutionResult:
        """Implement the core Executor protocol while preserving typed outcomes."""

        outcome = self.dispatch(packet, lease)
        if isinstance(outcome, ExecutionResult):
            return outcome
        if isinstance(outcome, ExecutionFailure):
            raise TuraExecutionFailureError(outcome)
        raise TuraRejectedError(outcome)


__all__ = [
    "TuraAdapter",
    "TuraClient",
    "TuraDispatchOutcome",
    "TuraDispatchRequest",
    "TuraExecutionFailureError",
    "TuraRejectedError",
    "TuraTerminalEnvelope",
    "TuraTerminalKind",
    "TuraTypedRejection",
    "build_tura_dispatch_request",
]
